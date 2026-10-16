"""Generate offline fixtures that mimic arxiv.org/list/<cat>/new and the RSS feed.
All entries are synthetic samples (ids 2699.9xxxx) used only to test parsing and the UI."""
import html
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
DATE_LONG = "Thursday, 15 October 2026"
NAMES = {"astro-ph.CO": "Cosmology and Nongalactic Astrophysics", "astro-ph.GA": "Astrophysics of Galaxies",
         "gr-qc": "General Relativity and Quantum Cosmology", "hep-th": "High Energy Physics - Theory",
         "astro-ph.HE": "High Energy Astrophysical Phenomena", "hep-ph": "High Energy Physics - Phenomenology"}

S = [  # id, title, authors, comments, cats(primary first), abstract
 ("2699.90001", "Sample: Scale-dependent bias constraints on $f_{\\rm NL}^{\\rm local}$ from a quasar sample",
  ["A. Sample", "B. Placeholder", "C. Example"], "18 pages, 9 figures", ["astro-ph.CO"],
  "Sample abstract for testing. We measure the large-scale power spectrum of a quasar sample and constrain local primordial non-Gaussianity through the scale-dependent bias. Marginalising over the response $b_\\phi$, we obtain $f_{\\rm NL}^{\\rm local} = 2 \\pm 9$ (68%). Imaging systematics are mitigated with a neural-network weighting scheme."),
 ("2699.90002", "Sample: Parity-odd four-point function of luminous red galaxies with simulation-based covariance",
  ["D. Testcase", "E. Mockingbird"], "12 pages", ["astro-ph.CO", "gr-qc"],
  "Sample abstract for testing. We estimate the parity-odd part of the galaxy four-point correlation function using an isotropic basis and a covariance from 4000 mocks. We find no evidence for parity violation once the covariance is estimated from simulations rather than analytically."),
 ("2699.90003", "Sample: Bars & spirals in Milky Way analogues at $z<0.1$",
  ["F. Ångström-Dummy", "G. Example"], "Accepted to MNRAS", ["astro-ph.GA"],
  "Sample abstract for testing. Using integral-field spectroscopy of 300 disc galaxies we show that strong bars quench the central star formation rate by a factor of two relative to unbarred discs at fixed stellar mass."),
 ("2699.90004", "Sample: Chiral gravitational waves from axion-gauge field dynamics",
  ["H. Sample", "I. Placeholder"], "", ["gr-qc", "astro-ph.CO", "hep-th"],
  "Sample abstract for testing. A rolling axion coupled to an SU(2) gauge field sources circularly polarised tensor modes. We compute the resulting TB and EB spectra and forecast detectability with a LiteBIRD-like mission."),
 ("2699.90005", "Sample: Quasinormal modes of rotating black holes in modified gravity",
  ["J. Example"], "30 pages", ["gr-qc"],
  "Sample abstract for testing. We compute the quasinormal mode spectrum of slowly rotating black holes in a scalar-Gauss-Bonnet theory and quantify deviations from the Kerr spectrum."),
 ("2699.90006", "Sample: Cross-listed note on cosmic birefringence from string axiverse",
  ["K. Crosslist"], "", ["hep-th", "astro-ph.CO"],
  "Sample abstract for testing. Axion-like fields from string compactifications rotate the CMB polarisation plane; we relate the isotropic birefringence angle to the axion decay constant."),
 ("2699.90007", "Sample: Satellite galaxies as tracers of halo assembly",
  ["L. Placeholder", "M. Sample", "N. Test", "O. Test", "P. Test", "Q. Test", "R. Test", "S. Test"], "", ["astro-ph.GA", "astro-ph.CO"],
  "Sample abstract for testing. Satellite abundances in hydrodynamical simulations correlate with halo formation time at fixed mass, offering an observable proxy for assembly bias."),
 ("2610.90008", "Sample (replacement): Lensing of the CMB by cosmic strings",
  ["T. Revised"], "v2: matches published version", ["astro-ph.CO"],
  "Sample abstract for testing. We update constraints on the string tension from CMB lensing reconstruction."),
]
LISTING = {
 "astro-ph.CO": {"new": ["2699.90001", "2699.90002"], "cross": ["2699.90004", "2699.90006", "2699.90007"], "replace": ["2610.90008"]},
 "astro-ph.GA": {"new": ["2699.90003", "2699.90007"], "cross": [], "replace": []},
 "gr-qc": {"new": ["2699.90004", "2699.90005"], "cross": ["2699.90002"], "replace": []},
}
by_id = {s[0]: s for s in S}

def entry(n, sid):
    _, title, authors, comments, cats, abstract = by_id[sid]
    subj = f"<span class=\"primary-subject\">{NAMES[cats[0]]} ({cats[0]})</span>" + "".join(f"; {NAMES[c]} ({c})" for c in cats[1:])
    au = ", ".join(f"<a href=\"https://arxiv.org/a/{html.escape(a.split()[-1].lower())}_1\">{html.escape(a)}</a>" for a in authors)
    com = f"<div class='list-comments mathjax'><span class='descriptor'>Comments:</span>\n {html.escape(comments)}\n</div>" if comments else ""
    return f"""<dt>
  <a name='item{n}'>[{n}]</a>
  <a href ="/abs/{sid}" title="Abstract" id="{sid}">arXiv:{sid}</a>
  [<a href="/pdf/{sid}" title="Download PDF" id="pdf-{sid}">pdf</a>, <a href="https://arxiv.org/html/{sid}v1" title="View HTML">html</a>, <a href="/format/{sid}">other</a>]
</dt>
<dd>
  <div class='meta'>
    <div class='list-title mathjax'><span class='descriptor'>Title:</span>
      {html.escape(title)}
    </div>
    <div class='list-authors'>{au}</div>
    {com}
    <div class='list-subjects'><span class='descriptor'>Subjects:</span>
      {subj}
    </div>
    <p class='mathjax'>
      {html.escape(abstract)}
    </p>
  </div>
</dd>"""

for cat, secs in LISTING.items():
    n, body = 1, []
    for sec, head in (("new", "New submissions"), ("cross", "Cross submissions"), ("replace", "Replacement submissions")):
        ids = secs[sec]
        if not ids: continue
        body.append(f"<h3>{head} (showing {len(ids)} of {len(ids)} entries)</h3>\n<dl id='articles'>")
        for sid in ids:
            body.append(entry(n, sid)); n += 1
        body.append("</dl>")
    page = f"""<!DOCTYPE html><html lang="en"><head><title>{cat} new submissions</title></head><body>
<div id="dlpage"><h1>{NAMES[cat]}</h1>
<div class='paging'>Total of {n-1} entries</div>
<h3>Showing new listings for {DATE_LONG}</h3>
{''.join(body)}
</div></body></html>"""
    (OUT / f"list-{cat}.html").write_text(page)

items = []
for sid, title, authors, comments, cats, abstract in S:
    kind = "replace" if sid.startswith("2610") else ("new" if cats[0] in LISTING else "cross")
    items.append(f"""<item><title>{html.escape(title)}</title><link>https://arxiv.org/abs/{sid}</link>
<description>{html.escape(f"arXiv:{sid}v1 Announce Type: {kind} \nAbstract: {abstract}")}</description>
<guid isPermaLink="false">oai:arXiv.org:{sid}v1</guid>{''.join(f'<category>{c}</category>' for c in cats)}
<pubDate>Thu, 15 Oct 2026 00:00:00 -0400</pubDate><arxiv:announce_type>{kind}</arxiv:announce_type>
<dc:rights>http://creativecommons.org/licenses/by/4.0/</dc:rights><dc:creator>{html.escape(', '.join(authors))}</dc:creator></item>""")
(OUT / "rss.xml").write_text(f"""<?xml version='1.0' encoding='UTF-8'?>
<rss xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
<channel><title>astro-ph.CO+astro-ph.GA+gr-qc updates on arXiv.org</title><link>http://rss.arxiv.org/rss/astro-ph.CO+astro-ph.GA+gr-qc</link>
<description>updates</description><language>en-us</language><lastBuildDate>Thu, 15 Oct 2026 04:00:25 +0000</lastBuildDate>
<pubDate>Thu, 15 Oct 2026 00:00:00 -0400</pubDate><skipDays><day>Saturday</day><day>Sunday</day></skipDays>
{''.join(items)}
</channel></rss>""")
print("fixtures written to", OUT)
