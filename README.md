# arXiv daily

A static daily digest of **astro-ph.CO**, **astro-ph.GA** and **gr-qc** with short AI summaries,
a private keyword/author watchlist, and no tracking. It runs entirely on GitHub Actions and
GitHub Pages; once the user site has a custom domain it is served at
`https://hongfeiy.com/arxiv-daily/`.

```
02:00 UTC (Mon–Fri) ─► GitHub Actions ─► arxiv.org/list/<cat>/new  (RSS as fallback)
                                     ─► LLM API (title + abstract only)
                                     ─► data/<date>.json, data/index.json  ─► commit
                                                                             └► GitHub Pages
```

## How it works

| Step | What happens |
|---|---|
| Schedule | arXiv announces at 20:00 US Eastern, Sunday–Thursday (00:00/01:00 UTC Monday–Friday). The workflow first runs at **02:00 UTC** and retries at 02:40, 03:30, 05:30 and 09:00 UTC. |
| Fetch | Reads `https://arxiv.org/list/<category>/new` for each category, one request every 15 s (the crawl delay in arXiv's `robots.txt`). If those pages cannot be parsed it falls back to the RSS feed, which arXiv rebuilds at midnight Eastern. Papers listed in several categories are merged. |
| Summarise | Each new submission and cross-list gets a TL;DR, motivation, method, results and 3–5 tags. Replacements are listed but not summarised (see `config.json`). |
| Store | One JSON file per announcement day in `data/`, plus `data/index.json`. Days older than `keep_days` (120) are pruned. |
| Idempotent | A run that finds nothing new changes no files and makes no commit. A partly summarised day (API error, timeout) is completed by the next run. |

The fetcher only reads public listing pages and stores descriptive metadata, as arXiv's API terms allow, and every paper links back to its arXiv abstract page.

## Setup

1. **Create the repository** `phiyu/arxiv-daily` on GitHub (public, so Pages is free) and push this folder:
   ```sh
   git remote add origin git@github.com:Phiyu/arxiv-daily.git
   git push -u origin main
   ```
2. **Add the API key** under Settings → Secrets and variables → Actions → *Secrets*:
   - `LLM_API_KEY`: your provider's key.
3. **Add variables** on the *Variables* tab:

   | Variable | Example | Notes |
   |---|---|---|
   | `LLM_PROVIDER` | `openai` | `openai` means any OpenAI-compatible endpoint; `anthropic` for Claude |
   | `LLM_BASE_URL` | `https://api.deepseek.com` | omit for OpenAI itself; e.g. `https://dashscope.aliyuncs.com/compatible-mode/v1` for Qwen |
   | `LLM_MODEL` | `deepseek-chat` | e.g. `qwen-plus`, or `claude-haiku-4-5-20251001` with `anthropic` |
   | `SUMMARY_LANG` | `en` | `en` or `zh` |

   Check your provider's documentation for current model names. Without a key the site still works and shows abstracts without summaries.
4. **Allow the workflow to push**: Settings → Actions → General → Workflow permissions → *Read and write permissions*.
5. **Turn on Pages**: Settings → Pages → *Deploy from a branch* → `main` / `(root)`.
6. **First run**: Actions → *daily digest* → *Run workflow*. After it finishes, open `https://phiyu.github.io/arxiv-daily/` (or `https://hongfeiy.com/arxiv-daily/` once the custom domain is active on the user site).

## Privacy

**What is sent to the AI provider:** for each paper, only its arXiv category, title and abstract. These are public arXiv data. Author lists, your watchlist and anything about visitors are never sent (see `pipeline/llm.py`; a unit test enforces the exact payload).

**API key:**
- The key is stored as a GitHub Actions secret, which GitHub masks in logs.
- The code reads it from the environment only, never writes it to disk, and strips it from every error message.
- Action logs are public in a public repo, so they record counts only, never paper text or API responses.

**Watchlist and saved papers:**
- These live in your browser's `localStorage` and never leave the device.
- Use *Export* / *Import* to move them between computers.
- Nothing about your interests is in the repository.

**Visitors:**
- The page loads fonts, KaTeX and data from this site only: no CDN, no analytics, no cookies.
- A Content-Security-Policy blocks any other origin.
- Links to arXiv are sent with `no-referrer`.

**Commits:** data commits are authored by `github-actions[bot]`, so no personal e-mail address is published.

**Choosing a provider:** prefer one whose API terms exclude training on API inputs. The data are public anyway, but the setting also limits retention.

## Configuration

`config.json`:

| Key | Meaning |
|---|---|
| `categories` | arXiv categories to follow, with display names |
| `include` | which listing sections to keep (`new`, `cross`, `replace`) |
| `summarize` | which sections get AI summaries |
| `max_summaries_per_day` | cost cap |
| `concurrency` | parallel API requests |
| `keep_days` | how many days of data to keep in `data/` |
| `request_delay_seconds` | delay between arXiv requests (keep ≥ 15) |

Cost scales with volume. A typical day in these three categories has about 150–300 new submissions and cross-lists, at roughly 600 input and 250 output tokens per paper.

## Local development

```sh
python -m unittest discover -s tests          # offline tests, no network, no key
ARXIV_DAILY_DATA=/tmp/ad LLM_PROVIDER=mock \
  python -m pipeline.run --fixtures tests/fixtures   # sample run into /tmp/ad
python -m http.server 8000                    # then open http://localhost:8000
```

`tests/fixtures/` contains synthetic pages that mimic the arXiv listing markup and RSS feed (ids `2699.9xxxx`); regenerate them with `python tests/make_fixtures.py`.

## Files

```
index.html, assets/        static reader (vanilla JS, self-hosted KaTeX and fonts)
data/                      daily JSON written by the workflow
pipeline/fetch.py          listing-page and RSS parsers
pipeline/llm.py            OpenAI-compatible / Anthropic / mock clients
pipeline/run.py            orchestration, resume, index, pruning
.github/workflows/daily.yml
config.json
```

Thank you to arXiv for use of its open access interoperability. Fonts: Source Serif 4 and IBM Plex Sans (SIL OFL 1.1). Math: KaTeX (MIT).
