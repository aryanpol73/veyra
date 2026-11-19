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
- [x] Phase 3: frozen Wayback dataset, leakage-safe replay, ground truth, metrics, contamination modes, Evaluation page
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

## Evaluation (pilot backtest)

```bash
cd backend
.venv/Scripts/python -m app.eval.dataset                 # (re)build the frozen dataset from the Wayback Machine
.venv/Scripts/python -m app.eval.run_eval --mode masked --synthetic
.venv/Scripts/python -m app.eval.run_eval --mode none    # flagged "possibly contaminated"
```

- **Data:** `data/replay/` holds 107 monthly Wayback captures (Jan-Nov 2026) of each competitor's pricing, homepage and
  changelog pages plus blog feeds. There's no historical jobs, CT or news-search data, so those sources are off in replay.
- **Replay:** the same detectors and agent graph step `as_of` monthly from 2026-05-01 to 2026-11-18 in a separate SQLite
  file. Tools filter by `as_of`, live fetches raise, and `tests/test_replay.py` asserts no post-`as_of` data leaks.
- **Ground truth:** `backend/app/eval/ground_truth.yaml` has 15 real events, each dated by an official announcement. It was
  labelled and committed (`2be03ce`) before the first replay. Matching is keyword-on-statement, defined in the file.
- **Metrics:** precision, recall, lead time, false-positive rate, false alarms per competitor-month, Brier scores, and
  3-bin calibration with Wilson 95% intervals (`backend/app/eval/metrics.py`).
- **Contamination:** `masked` replaces company and product names with tokens in every prompt, including classification.
  `none` is unmasked. `post_cutoff` keeps only events after the model's training cutoff; gpt-oss's cutoff is mid-2024,
  so on this 2026 dataset it keeps every event. A synthetic injection test checks that the machinery behaves as designed
  (independent evidence should beat one press release counted three times); it is labelled synthetic and measures nothing
  about real-world accuracy.

### Pilot results (masked mode, run #3, 2026-11-19)

| Metric | Value | n |
|---|---|---|
| Precision | 0.13 | 15 detected hypotheses |
| Recall | 0.13 | 15 events |
| Lead time (true positives) | +90 d, +60 d | 2 |
| False alarms per competitor-month | 0.66 | |
| Brier (hypotheses, final confidence) | 0.405 | 18 |
| Brier (resolved predictions) | 0.335 | 18 |
| Calibration, high bin (>= 0.7) | 1/8 hits, Wilson 95% [0.02, 0.47] | 8 |

**Reading this honestly:** Veyra caught Vercel's enterprise commitment contracts and its AI Gateway build-out months early. It
missed most specific launches (Vercel CI, Figma Motion, Specs): its hypotheses tend to be broad themes ("building a developer
platform", "expanding AI tooling") that the pre-declared keywords don't match, and high-confidence hypotheses are mostly not
specific events, so scores are **overconfident and uncalibrated**. This run is flagged *degraded*: 1 strategist call hit Groq's
daily cap on the final step. The synthetic injection test then exposed a flaw (the strategist could merge independent page
diffs into one origin group); it's fixed and regression-tested, and **both modes must be re-run** to report post-fix numbers.

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
- Groq's free tier allows 200k tokens/day per model; one masked backtest uses ~230k, so a full masked + unmasked pair needs 2 days.
- The evaluation is a pilot: 15 events, one labeller, monthly resolution (lead times are +/- ~30 days), keyword matching.
- Masking hides names, not facts; a model may still recognise a company from product details.
- A "new subdomain" on the first run means every live certificate for it is < 21 days old; renewals can occasionally look new.
