"""Daily job: fetch the announcement, summarise, write data/<date>.json and data/index.json.

Idempotent: safe to run several times per day (the workflow retries from 02:10 UTC).
  * if arXiv has not announced anything new since the last stored day, it exits quietly;
  * if a day is partly summarised (timeout, API error), the next run fills in the gaps.

Usage
  python -m pipeline.run                    # normal run (network)
  python -m pipeline.run --force            # re-summarise the current day from scratch
  python -m pipeline.run --fixtures tests/fixtures   # offline run on saved pages
  LLM_PROVIDER=mock python -m pipeline.run --fixtures tests/fixtures
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import fetch
from .llm import Client, LLMError

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ARXIV_DAILY_DATA") or ROOT / "data")
MAX_ATTEMPTS = 3


def log(msg: str) -> None:
    print(msg, flush=True)


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(path)


# ------------------------------------------------------------------- fixtures
class FixtureHttp:
    """Serves saved pages: list-<cat>.html and rss.xml from a directory."""

    def __init__(self, folder: Path):
        self.folder = folder

    def get(self, url: str) -> str:
        if "rss.arxiv.org" in url:
            name = "rss.xml"
        else:
            name = "list-" + url.split("/list/")[1].split("/")[0] + ".html"
        p = self.folder / name
        if not p.exists():
            raise fetch.FetchError(f"fixture {name} missing")
        return p.read_text()


# ------------------------------------------------------------------ summaries
def summarise_all(day: dict, cfg: dict, client: Client | None, force: bool) -> None:
    want = cfg.get("summarize", {})
    todo = []
    for p in day["papers"]:
        if not want.get(p["kind"], False):
            continue
        if force:
            p.pop("summary", None); p.pop("summary_error", None); p["summary_attempts"] = 0
        if p.get("summary") or p.get("summary_attempts", 0) >= MAX_ATTEMPTS:
            continue
        todo.append(p)
    cap = int(cfg.get("max_summaries_per_day", 400))
    done_today = sum(1 for p in day["papers"] if p.get("summary"))
    todo = todo[: max(0, cap - done_today)]
    if not todo:
        log("  nothing left to summarise")
        return
    if client is None:
        log(f"  {len(todo)} papers need summaries, but LLM_API_KEY / LLM_MODEL are not set; skipping")
        return
    day["model"] = client.describe()
    day["language"] = client.language
    log(f"  summarising {len(todo)} papers with {client.describe()}")
    lock = threading.Lock()
    finished = 0
    path = DATA / f"{day['date']}.json"

    def work(p):
        return client.summarise(p["title"], p["abstract"], p.get("primary") or ",".join(p.get("listed_in", [])))

    with ThreadPoolExecutor(max_workers=int(cfg.get("concurrency", 4))) as ex:
        futs = {ex.submit(work, p): p for p in todo}
        for fut in as_completed(futs):
            p = futs[fut]
            with lock:
                p["summary_attempts"] = p.get("summary_attempts", 0) + 1
                try:
                    p["summary"] = fut.result()
                    p.pop("summary_error", None)
                except LLMError as e:
                    p["summary_error"] = str(e)[:200]
                finished += 1
                if finished % 25 == 0:          # checkpoint, so a timeout loses little work
                    write_json(path, day)
                    log(f"  {finished}/{len(todo)}")
    ok = sum(1 for p in todo if p.get("summary"))
    log(f"  summaries: {ok} ok, {len(todo) - ok} failed")


# ---------------------------------------------------------------------- index
def counts_of(papers: list[dict], cats: list[str]) -> dict:
    out = {c: {"new": 0, "cross": 0, "replace": 0} for c in cats}
    for p in papers:
        for c in p.get("listed_in", []):
            if c in out:
                out[c][p["kind"]] += 1
    return out


def rebuild_index(cfg: dict) -> dict:
    keep = int(cfg.get("keep_days", 120))
    files = sorted(DATA.glob("20??-??-??.json"))
    if keep > 0 and files:
        cutoff = date.fromisoformat(files[-1].stem) - timedelta(days=keep)
        for f in files:
            if date.fromisoformat(f.stem) < cutoff:
                f.unlink()
                log(f"  pruned {f.name}")
        files = sorted(DATA.glob("20??-??-??.json"))
    days = []
    for f in reversed(files):
        d = json.loads(f.read_text())
        ps = d["papers"]
        days.append({"date": d["date"], "total": len(ps),
                     "new": sum(p["kind"] == "new" for p in ps),
                     "cross": sum(p["kind"] == "cross" for p in ps),
                     "replace": sum(p["kind"] == "replace" for p in ps),
                     "summarised": sum(bool(p.get("summary")) for p in ps)})
    idx = {"site_title": cfg.get("site_title", "arXiv daily"), "categories": cfg["categories"],
           "latest": days[0]["date"] if days else None, "dates": days}
    old_path = DATA / "index.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    if {k: v for k, v in old.items() if k != "updated_at"} != idx:   # avoid empty commits
        idx["updated_at"] = now_utc()
        write_json(old_path, idx)
    return idx


# ----------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-summarise the current day")
    ap.add_argument("--fixtures", type=Path, help="read saved pages instead of the network")
    ap.add_argument("--no-summary", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    cats = list(cfg["categories"])
    DATA.mkdir(exist_ok=True)
    log(f"[{now_utc()}] fetching {', '.join(cats)}")
    http = FixtureHttp(args.fixtures) if args.fixtures else fetch.Http(delay=float(cfg.get("request_delay_seconds", 15)))
    try:
        day_iso, papers, source = fetch.fetch_day(cats, http=http, log=log)
    except fetch.FetchError as e:
        log(f"  fetch failed: {e}")
        return 1
    if not papers or not day_iso:
        log("  no announcement available (weekend, holiday, or not yet published)")
        rebuild_index(cfg)
        return 0

    include = cfg.get("include", {})
    papers = [p for p in papers if include.get(p.kind, True)]
    path = DATA / f"{day_iso}.json"
    old = json.loads(path.read_text()) if path.exists() else None
    prev = {p["id"]: p for p in (old or {}).get("papers", [])}

    # keep summaries already produced for this day
    rows = []
    for p in papers:
        row = p.to_dict()
        o = prev.get(p.id)
        if o:
            for k in ("summary", "summary_error", "summary_attempts"):
                if k in o:
                    row[k] = o[k]
        rows.append(row)

    day = {"date": day_iso, "source": source, "fetched_at": now_utc(),
           "model": (old or {}).get("model"), "language": (old or {}).get("language"),
           "categories": cats, "counts": counts_of(rows, cats), "papers": rows}
    log(f"  {day_iso}: {len(rows)} papers from {source}"
        f" ({sum(r['kind']=='new' for r in rows)} new, {sum(r['kind']=='cross' for r in rows)} cross,"
        f" {sum(r['kind']=='replace' for r in rows)} replacements)")
    write_json(path, day)

    if not args.no_summary:
        summarise_all(day, cfg, Client.from_env(), args.force)
    strip = lambda d: {k: v for k, v in (d or {}).items() if k != "fetched_at"}
    if strip(day) != strip(old):
        write_json(path, day)
    elif old:
        write_json(path, old)       # nothing changed: restore the original file byte-for-byte
        log("  no changes since the last run")
    rebuild_index(cfg)
    log(f"[{now_utc()}] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
