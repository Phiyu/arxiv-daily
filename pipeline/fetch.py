"""Fetch the day's arXiv announcement for a set of categories.

Primary source: the listing pages  https://arxiv.org/list/<cat>/new
  - refreshed at the 20:00 ET announcement (00:00/01:00 UTC), so they are ready
    when the 02:10 UTC job starts;
  - allowed by arxiv.org/robots.txt (/list), crawl-delay 15 s, which we respect.
Fallback source: the RSS feed  https://rss.arxiv.org/rss/<cat>+<cat>
  - rebuilt at midnight ET (04:00/05:00 UTC), used if the listing pages fail to parse.

Only the Python standard library is used.
"""
from __future__ import annotations

import email.utils
import html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

USER_AGENT = "arxiv-daily/1.0 (personal digest; +https://hongfeiy.com/arxiv-daily/)"
LIST_URL = "https://arxiv.org/list/{cat}/new?skip=0&show=2000"
RSS_URL = "https://rss.arxiv.org/rss/{cats}"

ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
OLD_ID_RE = re.compile(r"([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?")
CAT_IN_PARENS = re.compile(r"\(([a-z\-]+(?:\.[A-Za-z\-]+)?)\)")
KIND_RANK = {"new": 0, "cross": 1, "replace": 2}


@dataclass
class Paper:
    id: str
    version: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    comments: str = ""
    journal_ref: str = ""
    primary: str = ""
    categories: list[str] = field(default_factory=list)
    kind: str = "new"                 # new | cross | replace
    listed_in: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class FetchError(RuntimeError):
    pass


# --------------------------------------------------------------------------- http
class Http:
    """Polite single-connection client: one request at a time, fixed delay between requests."""

    def __init__(self, delay: float = 15.0, timeout: float = 60.0, retries: int = 3):
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self._last = 0.0

    def get(self, url: str) -> str:
        err: Exception | None = None
        for attempt in range(self.retries):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    self._last = time.monotonic()
                    return r.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError) as e:
                self._last = time.monotonic()
                err = e
                code = getattr(e, "code", None)
                if code and 400 <= code < 500 and code != 429:
                    break
                time.sleep(self.delay * (attempt + 1))
        raise FetchError(f"GET {url} failed: {err}")


# --------------------------------------------------------------- listing-page parser
def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _strip_label(s: str, label: str) -> str:
    s = _norm_space(s)
    return s[len(label):].strip() if s.lower().startswith(label.lower()) else s


class _ListingParser(HTMLParser):
    """Tolerant parser for arxiv.org/list/<cat>/new.

    Relies on long-standing markup: <h3> section headings, <dt> with a link to /abs/<id>,
    <dd> containing div.list-title / div.list-authors / div.list-comments /
    div.list-journal-ref / div.list-subjects and a <p> abstract. If class names are missing
    it falls back to the visible labels ("Title:", "Comments:", "Subjects:").
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.date_text = ""
        self.entries: list[dict] = []
        self._section = "new"
        self._stack: list[tuple[str, str]] = []   # (tag, field)
        self._buf: dict[str, list[str]] = {}
        self._cur: dict | None = None
        self._in_h3 = False
        self._h3: list[str] = []
        self._in_dt = False
        self._authors_a = False

    # helpers
    def _field(self) -> str:
        for _, f in reversed(self._stack):
            if f:
                return f
        return ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag in ("h2", "h3", "h4"):
            self._in_h3, self._h3 = True, []
            return
        if tag == "dt":
            self._in_dt = True
            self._cur = {"section": self._section, "fields": {"title": [], "authors": [], "comments": [],
                                                              "journal": [], "subjects": [], "abstract": [], "primary": []}}
            self.entries.append(self._cur)
            return
        if tag == "dd":
            self._in_dt = False
        if self._in_dt and tag == "a" and self._cur is not None and "id" not in self._cur:
            href = a.get("href", "")
            m = re.search(r"/abs/(" + ID_RE.pattern + r"|" + OLD_ID_RE.pattern + r")", href)
            if m:
                self._cur["id"] = m.group(1)
        f = ""
        if self._cur is not None and not self._in_dt:
            if "list-title" in cls: f = "title"
            elif "list-authors" in cls: f = "authors"
            elif "list-comments" in cls: f = "comments"
            elif "list-journal-ref" in cls: f = "journal"
            elif "list-subjects" in cls: f = "subjects"
            elif "primary-subject" in cls: f = "primary"
            elif tag == "p": f = "abstract"
            elif "descriptor" in cls: f = "_skip"
        if tag == "a" and self._field() == "authors":
            self._authors_a = True
            self._cur["fields"]["authors"].append("\x1f")   # author separator
        self._stack.append((tag, f))

    def handle_endtag(self, tag):
        if tag in ("h2", "h3", "h4") and self._in_h3:
            self._in_h3 = False
            t = _norm_space("".join(self._h3))
            low = t.lower()
            m = re.search(r"new listings for\s+(.+)$", t, re.I)
            if m:
                self.date_text = m.group(1).strip()
            elif low.startswith("new submissions"):
                self._section = "new"
            elif low.startswith("cross"):
                self._section = "cross"
            elif low.startswith("replacement"):
                self._section = "replace"
            return
        if tag == "dt":
            self._in_dt = False
        if tag == "a":
            self._authors_a = False
        # pop to the matching tag (tolerates unclosed tags)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._in_h3:
            self._h3.append(data)
            return
        if self._cur is None or self._in_dt:
            return
        f = self._field()
        if f == "_skip" or not f:
            return
        if f == "primary":
            self._cur["fields"]["primary"].append(data)
            self._cur["fields"]["subjects"].append(data)
            return
        if f == "authors" and not self._authors_a:
            return      # commas / labels between author links
        self._cur["fields"][f].append(data)


def parse_listing(text: str, category: str) -> tuple[str, list[Paper]]:
    """Return (listing date ISO, papers) for one /list/<cat>/new page."""
    p = _ListingParser()
    p.feed(text)
    date_iso = ""
    if p.date_text:
        try:
            date_iso = datetime.strptime(p.date_text, "%A, %d %B %Y").date().isoformat()
        except ValueError:
            m = re.search(r"(\d{1,2}) (\w+) (\d{4})", p.date_text)
            if m:
                date_iso = datetime.strptime(" ".join(m.groups()), "%d %B %Y").date().isoformat()
    papers = []
    for e in p.entries:
        if "id" not in e:
            continue
        fields = {k: "".join(v) for k, v in e["fields"].items()}
        ident = e["id"]
        m = ID_RE.fullmatch(ident) or OLD_ID_RE.fullmatch(ident)
        base, ver = (m.group(1), m.group(2) or "") if m else (ident, "")
        subjects = _strip_label(fields["subjects"], "Subjects:")
        cats = CAT_IN_PARENS.findall(subjects)
        prim = CAT_IN_PARENS.findall(fields["primary"])
        authors = [_norm_space(a) for a in "".join(e["fields"]["authors"]).split("\x1f")]
        authors = [a for a in authors if a and a.lower() != "authors:"]
        papers.append(Paper(
            id=base, version=ver,
            title=_strip_label(fields["title"], "Title:"),
            authors=authors,
            abstract=_norm_space(fields["abstract"]),
            comments=_strip_label(fields["comments"], "Comments:"),
            journal_ref=_strip_label(fields["journal"], "Journal-ref:"),
            primary=prim[0] if prim else (cats[0] if cats else ""),
            categories=cats,
            kind=e["section"],
            listed_in=[category],
        ))
    return date_iso, papers


# ----------------------------------------------------------------------- RSS parser
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rss(text: str) -> tuple[str, list[Paper]]:
    root = ET.fromstring(text)
    channel = next((c for c in root if _local(c.tag) == "channel"), root)
    date_iso = ""
    for c in channel:
        if _local(c.tag) == "pubDate" and c.text:
            dt = email.utils.parsedate_to_datetime(c.text.strip())
            date_iso = dt.date().isoformat()
    papers = []
    for item in channel:
        if _local(item.tag) != "item":
            continue
        d: dict[str, list[str]] = {}
        for c in item:
            d.setdefault(_local(c.tag), []).append((c.text or "").strip())
        guid = (d.get("guid") or [""])[0]
        m = ID_RE.search(guid) or OLD_ID_RE.search(guid)
        if not m:
            continue
        desc = html.unescape((d.get("description") or [""])[0])
        abstract = desc.split("Abstract:", 1)[1] if "Abstract:" in desc else desc
        atype = (d.get("announce_type") or ["new"])[0]
        kind = {"new": "new", "cross": "cross", "replace": "replace", "replace-cross": "replace"}.get(atype, "new")
        creators = (d.get("creator") or [""])[0]
        authors = [a.strip() for a in re.split(r",\s*|\s+and\s+", creators) if a.strip()]
        cats = d.get("category") or []
        papers.append(Paper(
            id=m.group(1), version=m.group(2) or "",
            title=_norm_space(html.unescape((d.get("title") or [""])[0])),
            authors=authors, abstract=_norm_space(abstract),
            primary=cats[0] if cats else "", categories=cats, kind=kind, listed_in=[],
        ))
    return date_iso, papers


# --------------------------------------------------------------------------- merge
def merge(lists: list[list[Paper]], tracked: list[str]) -> list[Paper]:
    out: dict[str, Paper] = {}
    for lst in lists:
        for p in lst:
            q = out.get(p.id)
            if q is None:
                out[p.id] = p
                continue
            q.listed_in = sorted(set(q.listed_in) | set(p.listed_in))
            if KIND_RANK[p.kind] < KIND_RANK[q.kind]:
                q.kind = p.kind
            for attr in ("title", "abstract", "comments", "journal_ref", "primary", "version"):
                if not getattr(q, attr) and getattr(p, attr):
                    setattr(q, attr, getattr(p, attr))
            if not q.authors:
                q.authors = p.authors
            q.categories = q.categories or p.categories
    for p in out.values():
        if not p.listed_in:
            p.listed_in = [c for c in p.categories if c in tracked]
    return sorted(out.values(), key=lambda p: (KIND_RANK[p.kind], p.id))


def fetch_day(categories: list[str], delay: float = 15.0, http: Http | None = None,
              log=print) -> tuple[str, list[Paper], str]:
    """Return (listing date, papers, source)."""
    http = http or Http(delay=delay)
    dates, lists = set(), []
    try:
        for cat in categories:
            date_iso, papers = parse_listing(http.get(LIST_URL.format(cat=cat)), cat)
            log(f"  listing {cat}: {len(papers)} entries, date {date_iso or '?'}")
            if not papers or not date_iso:
                raise FetchError(f"listing page for {cat} could not be parsed")
            dates.add(date_iso)
            lists.append(papers)
        if len(dates) != 1:
            raise FetchError(f"listing pages disagree on the date: {sorted(dates)}")
        return dates.pop(), merge(lists, categories), "listing"
    except FetchError as e:
        log(f"  listing pages unavailable ({e}); trying RSS")
    date_iso, papers = parse_rss(http.get(RSS_URL.format(cats="+".join(categories))))
    log(f"  rss: {len(papers)} entries, date {date_iso or '?'}")
    return date_iso, merge([papers], categories), "rss"
