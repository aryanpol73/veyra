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
