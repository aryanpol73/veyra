from datetime import datetime, timedelta, timezone

from app.collectors.early_signals import parse_certspotter
from app.collectors.jobs import keywords_in, strip_boilerplate
from app.collectors.news import canonical_url, normalize_title
from app.collectors.pages import normalize_text
from app.detect import semantic_diff as sd
from app.detect.detectors import _weekly_z, classify_news_rules
from app.detect.normalize import SignalDraft, jaccard, priority_for

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


# ---------- noise pre-filter ----------
def test_normalize_drops_copyright_and_masks_dates():
    t = normalize_text("Pricing\n© 2026 Acme Inc. All rights reserved\nChangelog entry from Nov 3, 2026 adds SSO\nUpdated Nov 3\n2026\nPro $20")
    assert "©" not in t and "\n2026\n" not in t
    assert "Changelog entry from <date> adds SSO" in t and "Pro $20" in t and "Updated Nov 3" not in t


def test_year_bump_is_trivial():
    ch = sd.diff_text(normalize_text("Plans\n© 2025 Acme"), normalize_text("Plans\n© 2026 Acme"))
    assert sd.is_trivial(ch)


def test_reordering_is_trivial():
    assert sd.is_trivial(sd.diff_text("a line one here\nb line two here", "b line two here\na line one here"))


def test_small_copy_tweak_is_trivial_but_price_change_is_not():
    assert sd.is_trivial(sd.diff_text("Build faster", "Build quicker"))
    ch = sd.diff_text("Pro\n$20 per user/month", "Pro\n$25 per user/month")
    assert not sd.is_trivial(ch)
    assert abs(sd.price_pct(ch) - 0.25) < 1e-9


def test_rules_classifier_price_and_contact_sales():
    ev = sd.classify_rules(sd.diff_text("Pro\n$20 per user/month", "Pro\n$25 per user/month"), "pricing")
    assert ev[0].type == "price_change"
    ev = sd.classify_rules(sd.diff_text("Enterprise\n$99 per seat", "Enterprise\nContact sales for pricing"), "pricing")
    assert ev[0].type == "removal"


def test_launch_words_ignore_marketing_noun():
    ev = sd.classify_rules(sd.diff_text("x", "Generate 10 campaign ideas for our summer launch."), "homepage")
    assert not any(e.type == "feature_launch" for e in ev)
    ev = sd.classify_rules(sd.diff_text("x", "Introducing Agents: now available on all plans"), "homepage")
    assert any(e.type == "feature_launch" for e in ev)


# ---------- priority rule table ----------
def _d(t, **raw):
    return SignalDraft(type=t, summary="", evidence_url="u", observed_at=NOW, dedup_basis="b", event_confidence=1, raw=raw)


def test_priority_rules():
    assert priority_for(_d("price_change", price_pct=0.3)) == "critical"
    assert priority_for(_d("price_change", price_pct=0.1)) == "high"
    assert priority_for(_d("hiring_spike", z=2.5)) == "high"
    assert priority_for(_d("hiring_spike", z=1.6)) == "medium"
    assert priority_for(_d("news_mention")) == "low"


# ---------- news ----------
def test_canonical_url_unwraps_bing_and_strips_tracking():
    u = "http://www.bing.com/news/apiclick.aspx?ref=FexRss&url=https%3a%2f%2fwww.example.com%2fa%2f%3futm_source%3dx%26id%3d3"
    assert canonical_url(u) == "https://example.com/a?id=3"


def test_same_story_titles_group():
    a = normalize_title("Figma acquires Weavy to boost AI image tools - TechCrunch")
    b = normalize_title("Figma acquires Weavy, boosting its AI image tools | The Verge")
    assert jaccard(a, b) >= 0.4
    assert jaccard(a, "Vercel raises Series F at $9B valuation") < 0.2


def test_news_rules():
    assert classify_news_rules("Acme raises $50M Series C", "news") == "funding"
    assert classify_news_rules("Acme acquires Widget Co", "news") == "acquisition"
    assert classify_news_rules("Standard builds move to usage-based billing", "blog") == "plan_change"


# ---------- jobs ----------
def test_boilerplate_and_title_only_ai():
    blurb = "Acme is the AI-native platform for everyone on earth today."
    bodies = [f"{blurb} You will sell things to customers." for _ in range(5)] + [f"{blurb} You will fine-tune LLMs daily."]
    cleaned = strip_boilerplate(bodies)
    assert all(blurb not in b for b in cleaned)
    assert "AI/LLM" not in keywords_in("Account Executive", cleaned[0])
    assert "AI/LLM" in keywords_in("Software Engineer", cleaned[-1])
    assert "AI/LLM" in keywords_in("AI Engineer", "")


def test_weekly_z_detects_spike():
    steady = [NOW - timedelta(days=7 * w + 1) for w in range(2, 12)]  # 1/week before
    burst = [NOW - timedelta(days=d) for d in (1, 2, 3, 4, 8, 9)]  # 6 in last 2 weeks
    z, recent, mu = _weekly_z(steady + burst, NOW)
    assert recent == 6 and z > 1.5


# ---------- CT ----------
def test_certspotter_parse_drops_wildcards_and_apex():
    subs = parse_certspotter([
        {"not_before": "2026-11-10T00:00:00Z", "dns_names": ["acme.com", "*.acme.com", "ai.acme.com"]},
        {"not_before": "2026-09-01T00:00:00Z", "dns_names": ["ai.acme.com", "evil.com"]},
    ], "acme.com")
    assert list(subs) == ["ai.acme.com"]
    assert subs["ai.acme.com"]["first_seen"].startswith("2026-09-01") and subs["ai.acme.com"]["certs"] == 2


# ---------- line-paired pricing (regression: real Vercel pricing diff, Oct->Nov 2026) ----------
VERCEL_OLD = "Up to 1,000\nUp to 100\n$0.023 per GB\n$0.40 per 1M\n$5 per 1M\nStarting at $3 per 1M reads\nStarting at $0.08 per GB-month"
VERCEL_NEW = ("Up to 250\nUp to 40\nStarting at $0.023 per GB\nStarting at $0.35 per 1M\nStarting at $4.50 per 1M\n"
              "$3 per 1M reads\n$0.08 per GB-month\n200 CPU minutes / month included\n$0.0035 per CPU minute")


def test_price_pairs_compare_like_with_like():
    ch = sd.diff_text(VERCEL_OLD, VERCEL_NEW)
    moved = {(x, y) for _, _, x, y in ch.price_pairs()}
    assert moved == {(0.40, 0.35), (5.0, 4.5)}  # unchanged prices with reworded lines are not changes
    assert abs(sd.price_pct(ch) - 0.125) < 1e-9  # -> "high", not "critical"
    assert {(o, n) for o, n in ch.limit_pairs()} == {("Up to 1,000", "Up to 250"), ("Up to 100", "Up to 40")}
    types = [e.type for e in sd.classify_rules(ch, "pricing")]
    assert types[:2] == ["price_change", "plan_change"]


def test_blog_titles():
    assert classify_news_rules("Vercel Blob now supports TTLs for automatic deletion", "blog") == "feature_launch"
    assert classify_news_rules("How 3D transforms and Figma's agent brought a launch video to life", "blog") == "news_mention"
