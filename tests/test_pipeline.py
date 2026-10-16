"""Offline tests: python -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

from pipeline import fetch, llm  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_listing(self):
        d, ps = fetch.parse_listing((FIX / "list-astro-ph.CO.html").read_text(), "astro-ph.CO")
        self.assertEqual(d, "2026-10-15")
        self.assertEqual([p.kind for p in ps], ["new", "new", "cross", "cross", "cross", "replace"])
        p = ps[0]
        self.assertEqual(p.id, "2699.90001")
        self.assertTrue(p.title.startswith("Sample: Scale-dependent bias"))
        self.assertIn("$f_{\\rm NL}^{\\rm local}$", p.title)
        self.assertEqual(p.authors, ["A. Sample", "B. Placeholder", "C. Example"])
        self.assertEqual(p.comments, "18 pages, 9 figures")
        self.assertEqual(p.primary, "astro-ph.CO")
        self.assertTrue(p.abstract.startswith("Sample abstract"))
        x = next(q for q in ps if q.id == "2699.90006")
        self.assertEqual(x.primary, "hep-th")
        self.assertEqual(x.categories, ["hep-th", "astro-ph.CO"])

    def test_html_entities_and_unicode(self):
        _, ps = fetch.parse_listing((FIX / "list-astro-ph.GA.html").read_text(), "astro-ph.GA")
        p = next(q for q in ps if q.id == "2699.90003")
        self.assertIn("Bars & spirals", p.title)
        self.assertEqual(p.authors[0], "F. Ångström-Dummy")

    def test_rss(self):
        d, ps = fetch.parse_rss((FIX / "rss.xml").read_text())
        self.assertEqual(d, "2026-10-15")
        self.assertEqual(len(ps), 8)
        self.assertEqual(ps[0].authors, ["A. Sample", "B. Placeholder", "C. Example"])
        self.assertTrue(ps[0].abstract.startswith("Sample abstract"))

    def test_merge(self):
        lists = [fetch.parse_listing((FIX / f"list-{c}.html").read_text(), c)[1]
                 for c in ("astro-ph.CO", "astro-ph.GA", "gr-qc")]
        ps = {p.id: p for p in fetch.merge(lists, ["astro-ph.CO", "astro-ph.GA", "gr-qc"])}
        self.assertEqual(len(ps), 8)
        self.assertEqual(ps["2699.90004"].kind, "new")              # new in gr-qc beats cross in CO
        self.assertEqual(ps["2699.90004"].listed_in, ["astro-ph.CO", "gr-qc"])
        self.assertEqual(ps["2699.90006"].kind, "cross")


class LLMTests(unittest.TestCase):
    def test_parse_and_redact(self):
        out = llm._parse('noise {"tldr": "x", "motivation": "m", "method": "", "results": "r", "tags": ["A", "b"]} tail')
        self.assertEqual(out["tags"], ["a", "b"])
        self.assertNotIn("sk-abcdef123456", llm._redact("bad key sk-abcdef123456 here", None))
        self.assertNotIn("SECRET", llm._redact("x SECRET y", "SECRET"))

    def test_only_title_and_abstract_are_sent(self):
        sent = {}
        c = llm.Client("openai", "m", "KEY", "https://example.invalid/v1")
        def fake_call(system, user):
            sent["system"], sent["user"] = system, user
            return '{"tldr":"t","motivation":"","method":"","results":"","tags":[]}'
        c._call = fake_call
        c.summarise("T", "ABSTRACT", "astro-ph.CO")
        self.assertEqual(sent["user"], "arXiv category: astro-ph.CO\nTitle: T\n\nAbstract:\nABSTRACT")


class RunTests(unittest.TestCase):
    def run_pipeline(self, data, *extra, rss_only=False):
        fix = FIX
        if rss_only:
            fix = Path(tempfile.mkdtemp()); (fix / "rss.xml").write_text((FIX / "rss.xml").read_text())
        env = {**os.environ, "ARXIV_DAILY_DATA": str(data), "LLM_PROVIDER": "mock"}
        r = subprocess.run([sys.executable, "-m", "pipeline.run", "--fixtures", str(fix), *extra],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_end_to_end_and_idempotent(self):
        data = Path(tempfile.mkdtemp())
        out = self.run_pipeline(data)
        day = json.loads((data / "2026-10-15.json").read_text())
        self.assertEqual(day["source"], "listing")
        summarised = [p for p in day["papers"] if p.get("summary")]
        self.assertEqual(len(summarised), 7)                         # replacements are not summarised
        idx = json.loads((data / "index.json").read_text())
        self.assertEqual(idx["latest"], "2026-10-15")
        before = (data / "2026-10-15.json").read_bytes(), (data / "index.json").read_bytes()
        out2 = self.run_pipeline(data)
        self.assertIn("no changes", out2)
        self.assertEqual(before, ((data / "2026-10-15.json").read_bytes(), (data / "index.json").read_bytes()))
        self.assertNotIn("Sample abstract", out + out2)             # logs never contain paper text

    def test_rss_fallback(self):
        data = Path(tempfile.mkdtemp())
        self.run_pipeline(data, rss_only=True)
        day = json.loads((data / "2026-10-15.json").read_text())
        self.assertEqual(day["source"], "rss")
        self.assertEqual(len(day["papers"]), 8)


if __name__ == "__main__":
    unittest.main()
