# Veyra demo script (3–4 minutes)

Everything below exists in the database after the steps in **Before the demo**. Hypothesis numbers (H1, H5, H7) are this
machine's IDs; search by the statement if yours differ.

## Before the demo (do this 10+ minutes ahead)

1. Start the app with `py -3.11 run.py`, open http://localhost:5173 and check that **Overview → Test LLM** says ok.
2. Import the backtest hypotheses for step 3b (they appear with a **Replay** badge):
   `cd backend && .venv/Scripts/python -m app.eval.import_replay ../data/eval/replay_masked_20261119-113648.db`
3. Optionally generate today's brief on **Reports → Generate brief**.
4. **Groq free-tier note:** a live cycle with agents uses about 20–30k tokens per competitor, and the daily cap is 200k per
   model. Don't run an evaluation the same day as the demo. If chat says it hit the rate limit, show a saved answer
   (step 5) instead.

## 1. The problem (20 s)

> Competitor-monitoring tools tell you *what changed*. They don't tell you what it *means*, how sure to be, or whether
> there's a boring explanation.

Open **Intelligence Feed** and filter **pricing**. Point at the signal "2 listed price(s) changed on the pricing page:
$0.40 per 1M → $0.35 per 1M; $5 per 1M → $4.50 per 1M". That's a typical alert.

Then open **Hypotheses → "Vercel is shifting its pricing model toward usage-based billing and lowering entry thresholds"**
(live H1, *Likely 0.78*). Several signals are combined into one claim about strategy, with sources.

## 2. A live cycle (40 s)

On **Intelligence Feed**, click **Run cycle now**. The panel shows each source as it's checked: pricing pages, Greenhouse
job boards, blog feeds, Bing News, Certificate Transparency and sitemaps. It's polite crawling: robots.txt, at least 2 s per
host, responses cached.

While it runs, explain:
- **Typed signals:** price_change, hiring_tech_keyword, new_subdomain, and so on.
- **Noise filtering:** copyright years, dates and reordering are dropped before anything reaches the LLM.
- **Origin groups:** three articles about one announcement share an origin group and count once.

## 3. Inside a hypothesis (90 s)

**a. The skeptic changes an outcome.** Open **"Airtable is emphasizing AI/LLM capabilities…"** (live H5).
- **Belief over time:** 0.20 → 0.58 (strategist) → 0.62 (investigator) → **0.33** (after the skeptic).
- **Investigation:**
  - The plan was "check blog for AI announcements, search jobs for AI titles, check pricing for AI tiers".
  - The tool calls really ran: the changelog returned nothing, and the job search found 2 matching postings.
  - It stopped by the convergence rule.
- **Skeptic:** the alternative "the AI mentions come from a couple of customer-success roles, not an org-wide push" was
  **tested** with `search_jobs`. Only 2 of 11 postings matched, both Customer Success Manager roles, so the alternative is
  supported, and confidence dropped.

**b. Evidence for and against.** Open the **Replay**-badged **"Vercel is shifting to a higher-priced, usage-based
billing model aimed at enterprise customers"** (H7, from the backtest).
- **Evidence:** 11 supporting and 6 contradicting items.
- **What contradicts it:** price cuts such as "Reduced pricing for Turbo build machines" and "GPT-5.6 Sol is now 50% off".
- **Timeline:** it rises to 0.80 by June, then falls to 0.13 (*stale*) by November as cuts pile up.
- Point out the **contribution** column: decay, source reliability and the "same origin ×0.2" independence weight.

Say: "the score is computed by deterministic code, not the LLM, and it's labelled *uncalibrated*; the Evaluation page
shows why."

## 4. An early signal (20 s)

**Intelligence Feed → category Early signal.** Show **"New TLS certificate for braintrust.staging.figma.com"** (first seen
2026-11-13), with its crt.sh evidence link. It's labelled **"Lead, not proof"**: Certificate Transparency logs reveal new
hostnames before any announcement, but a staging subdomain may only be a test. It carries a low source weight (0.35).

## 5. Ask Veyra (30 s)

**Ask Veyra → "How has Vercel's pricing strategy evolved?"**
- **Expected:** an answer about the Hobby-limit cuts, the lower unit prices and usage-based builds, with clickable
  source chips.
- **Timeline:** a mini belief chart (0.20 → 0.75 → 0.78) drawn from the database, not from the model's text.
- **Citations:** answers can cite only sources a tool returned. Open **show tool calls** to prove it.

## 6. Does it actually work? (40 s)

Open **Evaluation** (masked mode).
- **Setup:** a leakage-safe backtest replayed month by month over 107 Wayback captures, scored against 15 real
  announcements labelled **before** the first run.
- **Headline:** precision 0.13 and recall 0.13. The 2 catches came **60 and 90 days early**: Vercel's enterprise
  commitment contracts and its AI Gateway build-out.
- **Calibration:** the high bin is 1 of 8 (Wilson 95% interval 0.02–0.47). The scores are overconfident, and the page
  says so.
- **Honesty about the run:** it's flagged *degraded* (one call hit the daily cap). The synthetic test exposed and fixed
  a real flaw, so a post-fix re-run is pending.

Close with:

> Veyra forms and tests hypotheses, and measures itself, including when the measurement is unflattering.

## If something fails during the demo

| Symptom | What to do |
|---|---|
| Chat: "rate limit is reached" | Groq's daily cap; it shows what the tools found. Go to step 3, which needs no LLM. |
| Run cycle takes long | It rate-limits itself to 2 s per host; the agents run after collection. Keep talking, or show the Feed as it fills. |
| Port 5173/8000 in use | An old server is still running. `run.py` refuses to start and names the port; stop it and re-run. |
