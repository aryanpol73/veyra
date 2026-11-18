# Veyra — Hypothesis-Driven Competitive Intelligence Agent

An autonomous, hypothesis-driven competitive intelligence system that investigates competing
explanations and measures its own prediction accuracy. (Not the first CI agent: Klue and Crayon
exist. Veyra differs in persistent hypotheses, adversarial validation, independence-aware
confidence, early-signal sources, and measurable backtesting.)

## Quick start

```bash
python run.py        # creates venv, installs deps, seeds DB, starts API :8000 + dashboard :5173
```

Then set your LLM in `.env` (copied from `.env.example`):

| Provider | `LLM_PROVIDER` | Key | Default strong / fast models |
|---|---|---|---|
| Groq (free tier) | `groq` | console.groq.com/keys | `llama-3.3-70b-versatile` / `llama-3.1-8b-instant` |
| Ollama Cloud | `ollama_cloud` | ollama.com/settings/keys | `gpt-oss:120b` / `gpt-oss:20b` |
| Local Ollama | `ollama_local` | none | `llama3.1:8b` |

Any OpenAI-compatible endpoint works through `LLM_BASE_URL`, `LLM_STRONG` and `LLM_FAST`.
Use "Test LLM" on the Overview page to check the connection.

> **Windows:** keep the repo at a short path (e.g. `C:\Users\you\veyra`). LangGraph's
> dependency `xxhash` ships a DLL that fails to load past the 260-char MAX_PATH limit.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

## Status

- [x] Phase 0: FastAPI, SQLAlchemy schema (all 15 tables), seed, provider-agnostic LLM client, React shell
- [x] Phase 1: collectors (pages, jobs, news/blog feeds, CT + sitemap), semantic diff, priority rules, dedup, Intelligence Feed
- [ ] Phase 2: agent core (strategist / investigator / skeptic / judge) and belief engine
- [ ] Phase 3: replay backtest and evaluation
- [ ] Phase 4: chat, briefs, overview
- [ ] Phase 5: demo hardening

## Data sources (all public, robots.txt respected, >=2 s per host, cached)

| Source | Endpoint | Notes |
|---|---|---|
| Pages | competitor pricing / homepage / changelog | trafilatura main text; first run diffs against a Wayback capture >= 30 days old |
| Jobs | Greenhouse / Lever public JSON | broad terms like "AI" count only in job titles (company blurbs mention AI everywhere) |
| News | Bing News RSS + company blog/changelog feeds | Google News RSS is robots-disallowed, so not used |
| Early signals | Cert Spotter CT API, `sitemap.xml` | crt.sh is robots-disallowed; Cert Spotter allows ~10 anonymous req/hour |

Without an LLM key, signals are labelled by transparent rules and badged "rule-classified".

## Limitations (kept honest; expanded as phases land)

- Confidence scores are an **uncalibrated heuristic** until the Evaluation page shows calibration.
- CT-log and sitemap signals are **leads, not proof**.
- Free-tier Groq rate limits constrain how many agent steps run per cycle.
- Hiring-spike z-scores come from posting dates on the *current* board; filled roles disappear, so older weeks are under-counted.
- A "new subdomain" on the first run means every live certificate for it is < 21 days old; renewals can occasionally look new.
