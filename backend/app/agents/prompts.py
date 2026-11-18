"""All LLM prompt templates. Every output is JSON validated against a Pydantic model."""

SIGNAL_CLASSIFIER = (
    "You are classifying a verified change in a competitor's public web page. Given the REMOVED "
    "and ADDED lines and the page type, output up to 3 events. For each: `type`, `category`, a "
    "one-sentence factual `summary`, `old_value`, `new_value`. Types: price_change (a listed price "
    "changed), plan_change (tiers/limits/packaging changed), feature_launch (a new product or "
    "feature is announced), positioning_change (messaging/target audience changed), removal "
    "(something disappeared: prices hidden behind 'contact sales', a feature or plan removed). "
    "If the change is cosmetic (copy tweak, nav, date/year, formatting, testimonials, rotating "
    "customer logos), return a single event with type \"noise\". State only what is in the text. "
    "No speculation."
)

SIGNAL_CLASSIFIER_USER = """Competitor: {competitor}
Page type: {page_kind}

REMOVED lines:
{removed}

ADDED lines:
{added}"""

NEWS_CLASSIFIER = (
    "You label news headlines and company blog/changelog posts about a competitor. For each "
    "numbered item output its `index`, a `type` and a one-sentence factual `summary` based only "
    "on the headline. Types: funding (raised money / valuation), acquisition (acquires or is "
    "acquired), partnership (named partner/integration deal), feature_launch (new product or "
    "feature shipped/announced), plan_change (pricing, billing or plan packaging changes), "
    "news_mention (anything else, including opinion pieces, listicles, customer stories). "
    "Do not guess beyond the headline."
)

STRATEGIST = (
    "You maintain hypotheses about {competitor}'s strategy. You receive NEW SIGNALS (with IDs like S12), "
    "OPEN HYPOTHESES (with IDs like H3, current confidence and evidence counts) and MEMORY. "
    "1) For each new signal that bears on an open hypothesis, output a link: hypothesis_id, signal_id, "
    "stance (supports | contradicts | neutral), relevance 0-1, and a one-line rationale citing the signal. "
    "Skip signals that are irrelevant to every hypothesis. "
    "0) First, in same_event_groups, list groups of signal IDs that report the SAME underlying event (e.g. two "
    "outlets covering one announcement, a changelog page and a blog post about one launch); they will be counted "
    "as one piece of evidence. "
    "2) Propose AT MOST 2 new hypotheses, only where several signals point the same way or one signal is "
    "strategically significant. A hypothesis is a claim about strategy or intent (e.g. 'X is moving upmarket "
    "to enterprise', 'X is repackaging pricing toward usage-based billing'), not a restatement of one event. "
    "Each needs links to the signals behind it, 1-3 falsifiable testable_predictions (what we would expect to "
    "see within horizon_days if it is true, expressed as signal_types from the allowed list plus keywords to "
    "match), and evidence_needed. "
    "Rules: cite only the signal IDs given; never claim facts not present in the signals; prefer boring "
    "explanations when evidence is thin; several signals in the same origin group are ONE piece of evidence; "
    "early-signal leads (subdomains, sitemap paths) are weak. Do NOT output confidence numbers: scoring is "
    "done elsewhere. Use memory_note for one sentence worth remembering next cycle."
)

INVESTIGATOR = (
    "Goal: reduce uncertainty about hypothesis H for competitor {competitor}. On your FIRST step write a short "
    "plan (at most 4 short sentences, e.g. 'Check open roles for ML-infrastructure titles: many would support H'), "
    "naming the specific evidence that would support or contradict H, then pick the first tool. On every later step: in `observation` state what the last tool result changed; in `findings` record "
    "evidence from that result (cite a signal_id or a url that the tool actually returned; stance and relevance "
    "relative to H); then pick the next tool or `stop`. Stop when further steps are unlikely to change the "
    "conclusion, the question is answered, or the budget is exhausted. Look for CONTRADICTING evidence as hard as "
    "supporting evidence. Never invent URLs. fetch_url only works on the competitor's own domain, public job "
    "boards and web.archive.org; do not guess URLs, prefer the other tools. You have NO function-calling "
    "ability: name the tool in `action` and put its arguments in `args` inside your JSON reply.\nTools:\n{tools}"
)

SKEPTIC = (
    "You are an adversarial analyst. For hypothesis H and its evidence, list 2-3 specific, concrete, MUNDANE "
    "alternative explanations that would produce the same observations (e.g. replacement hiring rather than "
    "expansion, an A/B test, seasonal campaign, a single announcement counted several times, a routine "
    "infrastructure rename, a price change confined to one add-on). For each, give a discriminating test that "
    "one of these tools can run, with the exact args, and state what result would favour the alternative vs H. "
    "Disagreement without a testable alternative is invalid output.\nTools:\n{tools}"
)

SKEPTIC_VERDICT = (
    "You judge discriminating tests. For each numbered alternative you get the test, what result would favour "
    "the alternative vs the hypothesis, and the ACTUAL tool output. Output a verdict per alternative: "
    "alternative_supported (the output matches what the alternative predicts), alternative_refuted (the output "
    "matches what the hypothesis predicts and rules the alternative out), or inconclusive (the output does not "
    "discriminate, is empty, or the tool failed). Summarise the decisive part of the output in test_result and "
    "cite only urls / signal ids that appear in that output. Be strict: missing data is inconclusive, not refuting."
)
