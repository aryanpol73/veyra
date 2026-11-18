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
| Groq (free tier) | `groq` | console.groq.com/keys | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` |
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
- [x] Phase 2: belief engine, LangGraph agents (strategist -> investigator -> skeptic -> judge), alerts, predictions, Hypotheses page
- [ ] Phase 3: replay backtest and evaluation
- [ ] Phase 4: chat, briefs, overview
- [ ] Phase 5: demo hardening

## How the agent core works

Each cycle, per competitor, a LangGraph graph runs `strategist -> judge -> investigator -> judge -> skeptic -> judge -> alert policy`.

| Step | LLM? | What it does |
|---|---|---|
| Strategist | strong | links new signals to hypotheses (stance + relevance, cited by ID), proposes at most 2 new ones with falsifiable predictions, flags same-event signals |
| Investigator | fast | bounded tool loop on hypotheses in the uncertain band (0.35-0.80): max 6 tool calls, 25 fetches per cycle, token budget; stops on convergence |
| Skeptic | strong | at >= 0.60: >= 2 concrete mundane alternatives, each with a tool test that is **actually run**; strict verdict per alternative |
| Judge | no | deterministic belief engine (`backend/app/belief/engine.py`), status, alert policy, prediction registry |

Guardrails enforced in code, not prompts: evidence may cite only signal IDs / URLs a tool returned; a re-found URL joins the
existing signal's origin group; nothing becomes "likely" before the skeptic has challenged it; alerts never fire on unchallenged
claims. Every LLM call and tool call is logged to `agent_runs`.

Confidence = sigmoid(logit(prior) + sum(stance x relevance x reliability x event_confidence x recency x independence x K)),
with independence 1.0 for the strongest item in an origin group and 0.2 for the rest, a per-category cap, and skeptic adjustments.

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
- Free-tier Groq rate limits constrain how many agent steps run per cycle (about 15-27k tokens per competitor per cycle).
- Groq's model lineup changes; if a model 404s, set `LLM_STRONG` / `LLM_FAST` in `.env`.
- Hiring-spike z-scores come from posting dates on the *current* board; filled roles disappear, so older weeks are under-counted.
- A "new subdomain" on the first run means every live certificate for it is < 21 days old; renewals can occasionally look new.
