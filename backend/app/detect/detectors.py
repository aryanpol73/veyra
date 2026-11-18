"""Per-source change detectors: (previous snapshot, new observation) -> SignalDrafts.

First-run policy (no previous snapshot), chosen so day one shows REAL, dated signals:
  page          -> diff against a Wayback capture >= 30 days old (if one exists), else baseline only
  jobs          -> postings first published in the last 14 days count as "new"
  news / blog   -> items published in the last 30 days
  CT subdomains -> hosts whose every live certificate was issued in the last 21 days
  sitemap       -> baseline only (sitemaps carry no reliable creation dates)
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import llm
from app.agents import prompts
from app.collectors import wayback
from app.collectors.base import RawObservation, sha
from app.collectors.pages import html_to_text
from app.config import get_settings
from app.db.models import Competitor, Snapshot, Source
from app.detect import semantic_diff as sd
from app.detect.normalize import PRIORITY_RULES, SignalDraft, assign_news_group, persist

log = logging.getLogger("veyra.detect")

JOBS_LOOKBACK_DAYS = 14
NEWS_LOOKBACK_DAYS = 30
CT_LOOKBACK_DAYS = 21


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _now(obs: RawObservation) -> datetime:
    return obs.observed_at


# ======================= pages =======================
def detect_page(db: Session, comp: Competitor, src: Source, obs: RawObservation,
                prev: Snapshot | None, cur: Snapshot, *, allow_wayback: bool = True) -> list[SignalDraft]:
    baseline_note = None
    if prev is None and not allow_wayback:
        return []  # replay: the first frozen capture is the baseline (no network)
    if prev is None:
        wb = wayback.baseline_before(src.url, days_ago=30)
        if not wb:
            return []
        html, ts = wb
        text = html_to_text(html)
        prev = Snapshot(source_id=src.id, fetched_at=obs.fetched_at, observed_at=ts, content_hash=sha(text),
                        content_text=text, meta={"wayback_ts": ts.strftime("%Y%m%d%H%M%S"), "baseline": True})
        db.add(prev)
        db.flush()
        baseline_note = f"https://web.archive.org/web/{ts:%Y%m%d%H%M%S}/{src.url}"
    if prev.content_hash == obs.content_hash:
        return []
    ch = sd.diff_text(prev.content_text, obs.content_text)
    if sd.is_trivial(ch):
        return []
    kind = sd.page_kind(src.url, comp.pricing_url)
    events, by = sd.classify(ch, kind, comp.name)
    pct = sd.price_pct(ch)
    group = f"page:{src.id}:{cur.id}"
    old_url = baseline_note or (f"https://web.archive.org/web/{prev.meta['wayback_ts']}/{src.url}" if prev.meta.get("wayback_ts") else None)
    drafts = []
    for e in events:
        # a launch seen on a changelog page is usually the same announcement as a feed post/news article
        g = (assign_news_group(db, comp.id, e.new_value or e.summary, _now(obs)) if e.type == "feature_launch" else None) or group
        drafts.append(SignalDraft(
            type=e.type, category=e.category, summary=e.summary, old_value=e.old_value, new_value=e.new_value,
            evidence_url=src.url, observed_at=_now(obs), event_confidence=0.95, origin_group=g,
            dedup_basis=f"{src.id}|{e.type}|{obs.content_hash}",
            raw={"classified_by": by, "page_kind": kind, "added": ch.added[:25], "removed": ch.removed[:25],
                 "title": e.new_value or e.summary,
                 "changed_between": [prev.observed_at.isoformat(), obs.observed_at.isoformat()],
                 "previous_version_url": old_url, "price_pct": pct if e.type == "price_change" else None},
        ))
    return drafts


def page_gone(comp: Competitor, src: Source, prev: Snapshot | None, err: str, when: datetime) -> list[SignalDraft]:
    """A tracked page that used to exist now returns 404/410 -> removal."""
    if prev is None or not any(code in err for code in ("HTTP 404", "HTTP 410")):
        return []
    return [SignalDraft(type="removal", category="product", summary=f"{src.url} is no longer available ({err}).",
                        old_value=prev.content_text[:300], new_value=None, evidence_url=src.url, observed_at=when,
                        event_confidence=0.9, dedup_basis=f"gone|{src.id}|{prev.content_hash}",
                        raw={"classified_by": "rules", "error": err})]


# ======================= jobs =======================
def _weekly_z(dates: list[datetime], now: datetime, weeks: int = 12) -> tuple[float, int, float]:
    """z-score of the last-2-weeks weekly rate vs the prior (weeks-2) weekly counts.
    Caveat: filled roles leave the board, so older weeks are under-counted (inflates z)."""
    buckets = [0] * weeks
    for d in dates:
        w = int((now - d).days // 7)
        if 0 <= w < weeks:
            buckets[w] += 1
    recent_rate = (buckets[0] + buckets[1]) / 2
    prior = buckets[2:]
    mu = statistics.mean(prior)
    sd_ = statistics.pstdev(prior) or 1.0
    return (recent_rate - mu) / sd_, buckets[0] + buckets[1], mu


def board_url(comp: Competitor) -> str:
    if comp.careers_provider == "lever":
        return f"https://jobs.lever.co/{comp.careers_token}"
    return f"https://job-boards.greenhouse.io/{comp.careers_token}"


def detect_jobs(db: Session, comp: Competitor, src: Source, obs: RawObservation,
                prev: Snapshot | None, cur: Snapshot) -> list[SignalDraft]:
    now = _now(obs)
    # local copies with parsed dates (never mutate obs.meta: it is the stored snapshot JSON)
    postings = [dict(p, _dt=_dt(p["first_published"])) for p in obs.meta["postings"]]
    if prev is not None:
        prev_ids = {p["id"] for p in prev.meta.get("postings", [])}
        new = [p for p in postings if p["id"] not in prev_ids]
        removed = [p for p in prev.meta.get("postings", []) if p["id"] not in {q["id"] for q in postings}]
        older = [p for p in prev.meta.get("postings", [])]
    else:
        cutoff = now - timedelta(days=JOBS_LOOKBACK_DAYS)
        new = [p for p in postings if p["_dt"] and p["_dt"] >= cutoff]
        removed = []
        older = [p for p in postings if p not in new]
    week = now.strftime("%G-W%V")
    group = f"jobs:{comp.id}:{week}"
    board = board_url(comp)
    drafts: list[SignalDraft] = []

    # spike (overall + per keyword area)
    areas: dict[str, list[datetime]] = defaultdict(list)
    for p in postings:
        if p["_dt"]:
            areas["all"].append(p["_dt"])
            for k in p["keywords"]:
                areas[k].append(p["_dt"])
    for area, dates in areas.items():
        z, recent, mu = _weekly_z(dates, now)
        min_n = 5 if area == "all" else 3
        if z > 1.5 and recent >= min_n:
            label = "overall" if area == "all" else f"in {area}"
            drafts.append(SignalDraft(
                type="hiring_spike", summary=f"{comp.name} opened {recent} roles {label} in the last 2 weeks "
                f"(~{recent / 2:.1f}/week vs ~{mu:.1f}/week before; z={z:.1f}).",
                new_value=str(recent), old_value=f"{mu:.1f}/week", evidence_url=board, observed_at=now,
                event_confidence=0.7, origin_group=group, dedup_basis=f"spike|{area}|{week}",
                raw={"area": area, "z": round(z, 2), "recent_2w": recent, "prior_weekly_mean": round(mu, 2),
                     "caveat": "Filled roles drop off the board, so older weeks are under-counted.",
                     "classified_by": "rules"}))

    # tech keywords among new postings
    by_kw: dict[str, list[dict]] = defaultdict(list)
    for p in new:
        for k in p["keywords"]:
            by_kw[k].append(p)
    for k, ps in by_kw.items():
        if len(ps) < 2:
            continue
        titles = "; ".join(p["title"] for p in ps[:4])
        drafts.append(SignalDraft(
            type="hiring_tech_keyword", summary=f"{len(ps)} new {comp.name} postings mention {k}: {titles}"[:380],
            new_value=k, evidence_url=ps[0].get("url") or board, observed_at=max(p["_dt"] or now for p in ps),
            event_confidence=0.95, origin_group=group, dedup_basis=f"kw|{k}|{','.join(sorted(p['id'] for p in ps))}",
            raw={"keyword": k, "postings": [{"title": p["title"], "url": p.get("url")} for p in ps[:20]], "classified_by": "rules"}))

    # new locations
    known_locs = {p["location"] for p in older if p.get("location")}
    if known_locs:  # need a baseline to call something "new"
        new_locs = Counter(p["location"] for p in new if p.get("location") and p["location"] not in known_locs)
        for loc, n in new_locs.items():
            example = next(p for p in new if p.get("location") == loc)
            drafts.append(SignalDraft(
                type="hiring_new_location", summary=f"{comp.name} is hiring in a new location: {loc} ({n} role(s), e.g. {example['title']}).",
                new_value=loc, evidence_url=example.get("url") or board, observed_at=example["_dt"] or now,
                event_confidence=0.9, origin_group=group, dedup_basis=f"loc|{loc}",
                raw={"location": loc, "count": n, "classified_by": "rules"}))

    # withdrawn postings
    if prev is not None and len(removed) >= max(5, 0.10 * len(prev.meta.get("postings", []))):
        drafts.append(SignalDraft(
            type="removal", category="hiring", summary=f"{len(removed)} {comp.name} job postings were withdrawn since the last check.",
            old_value=str(len(prev.meta.get('postings', []))), new_value=str(len(postings)), evidence_url=board,
            observed_at=now, event_confidence=0.9, origin_group=group,
            dedup_basis=f"withdrawn|{sha(','.join(sorted(p['id'] for p in removed)))}",
            raw={"titles": [p["title"] for p in removed[:30]], "classified_by": "rules"}))
    return drafts


# ======================= news =======================
class NewsLabel(BaseModel):
    index: int
    type: str = Field(pattern="^(funding|acquisition|partnership|feature_launch|plan_change|news_mention)$")
    summary: str = Field(max_length=300)


class NewsLabels(BaseModel):
    items: list[NewsLabel]


NEWS_RULES = [
    ("funding", r"\b(raises?|raised|funding|series [a-h]|valuation|investment round)\b"),
    ("acquisition", r"\b(acquires?|acquired|acquisition|buys|to buy)\b"),
    ("partnership", r"\b(partners? with|partnership|teams up|integrat(es|ion) with)\b"),
    ("plan_change", r"\b(pricing|price|billing|plans?|per seat|usage-based)\b"),
    ("feature_launch", r"\b(launches|launched|introduc(es|ing)|unveils?|now available|now supports?|rolls? out|"
                       r"generally available|general availability|in beta|public beta|ships)\b"),
]
# Official changelog/blog titles are terse ("Vercel Blob supports TTLs"): these verbs signal a shipped feature.
BLOG_FEATURE = r"\b(supports?|adds?|added|support for|available|enables?|new)\b"


def classify_news_rules(title: str, kind: str) -> str:
    import re
    for t, rx in NEWS_RULES:
        if re.search(rx, title, re.I):
            return t
    if kind == "blog" and re.search(BLOG_FEATURE, title, re.I):
        return "feature_launch"
    return "news_mention"


def classify_news(comp: Competitor, items: list[dict]) -> tuple[dict[int, NewsLabel], str]:
    if not items:
        return {}, "rules"
    if get_settings().llm_configured:
        labels: dict[int, NewsLabel] = {}
        for start in range(0, len(items), 25):
            chunk = items[start:start + 25]
            user = f"Competitor: {comp.name}\n" + "\n".join(
                f"{start + i}. [{it['kind']}] {it['title']}" for i, it in enumerate(chunk))
            out = llm.complete_json(role="fast", system=prompts.NEWS_CLASSIFIER, user=user, schema=NewsLabels, kind="classify_news")
            if out is None:
                break
            labels.update({lab.index: lab for lab in out.items})
        if labels:
            return labels, "llm"
    return {i: NewsLabel(index=i, type=classify_news_rules(it["title"], it["kind"]), summary=it["title"])
            for i, it in enumerate(items)}, "rules"


def detect_news(db: Session, comp: Competitor, src: Source, obs: RawObservation,
                prev: Snapshot | None, cur: Snapshot, *, replay: bool = False, detected_at: datetime | None = None) -> int:
    """News is persisted item by item so later items can join earlier ones' origin_group. Returns count."""
    now = _now(obs)
    seen = set(prev.content_text.splitlines()) if prev else set()
    lookback = now - timedelta(days=NEWS_LOOKBACK_DAYS if prev is None else 60)
    items = [i for i in obs.meta["items"] if i["url"] not in seen and _dt(i["published"]) and _dt(i["published"]) >= lookback]
    labels, by = classify_news(comp, items)
    official = obs.meta.get("kind") == "blog"
    n = 0
    for idx, it in enumerate(items):
        lab = labels.get(idx)
        typ = lab.type if lab else "news_mention"
        published = _dt(it["published"])
        group = assign_news_group(db, comp.id, it["title"], published)
        d = SignalDraft(
            type=typ, summary=(lab.summary if lab else it["title"])[:400], new_value=it["title"],
            evidence_url=it["url"], observed_at=published, event_confidence=0.95 if official else 0.7,
            origin_group=group, dedup_basis=f"url|{it['url']}",
            raw={"title": it["title"], "publisher": it.get("publisher"), "kind": it["kind"], "classified_by": by,
                 "source_reliability_hint": "official" if official else "news"})
        n += len(persist(db, comp.id, src.id, [d], replay=replay, detected_at=detected_at))
    return n


# ======================= early signals =======================
def detect_ct(db: Session, comp: Competitor, src: Source, obs: RawObservation,
              prev: Snapshot | None, cur: Snapshot) -> list[SignalDraft]:
    now = _now(obs)
    subs: dict = obs.meta["subdomains"]
    if prev is not None:
        new = [s for s in subs if s not in set(prev.content_text.splitlines())]
    else:
        firsts = [_dt(v["first_seen"]) for v in subs.values() if v["first_seen"]]
        coverage_ok = bool(firsts) and min(firsts) < now - timedelta(days=45)
        cutoff = now - timedelta(days=CT_LOOKBACK_DAYS)
        new = [s for s, v in subs.items() if coverage_ok and v["first_seen"] and _dt(v["first_seen"]) >= cutoff]
    rx = PRIORITY_RULES["interesting_path"]
    new.sort(key=lambda s: (not rx.search(s), s))
    drafts = []
    for s in new[:15]:
        v = subs[s]
        label = s.removesuffix("." + comp.domain).split(".")[-1]
        drafts.append(SignalDraft(
            type="new_subdomain", summary=f"New TLS certificate for {s} (first seen {v['first_seen'][:10]}). Lead, not proof: may be internal or a test.",
            new_value=s, evidence_url=f"https://crt.sh/?q={s}", observed_at=_dt(v["first_seen"]) or now,
            event_confidence=0.8, origin_group=f"ct:{comp.id}:{label}", dedup_basis=f"sub|{s}",
            raw={"certs": v["certs"], "first_seen": v["first_seen"], "classified_by": "rules", "lead_not_proof": True}))
    return drafts


def detect_sitemap(db: Session, comp: Competitor, src: Source, obs: RawObservation,
                   prev: Snapshot | None, cur: Snapshot) -> list[SignalDraft]:
    if prev is None:
        return []
    now = _now(obs)
    old, new_paths = set(prev.content_text.splitlines()), set(obs.content_text.splitlines())
    added = sorted(new_paths - old)
    removed = sorted(old - new_paths)
    rx = PRIORITY_RULES["interesting_path"]
    drafts: list[SignalDraft] = []
    by_section: dict[str, list[str]] = defaultdict(list)
    for p in added:
        by_section[p.strip("/").split("/")[0] if p.strip("/") else "/"].append(p)
    for section, paths in by_section.items():
        if len(paths) > 8:  # e.g. a batch of blog posts: one aggregate signal
            drafts.append(SignalDraft(
                type="new_sitemap_path", summary=f"{len(paths)} new pages under /{section} in {comp.name}'s sitemap.",
                new_value=f"/{section}", evidence_url=f"https://{comp.domain}{paths[0]}", observed_at=now,
                event_confidence=0.85, origin_group=f"sitemap:{comp.id}:{section}",
                dedup_basis=f"section|{section}|{sha(','.join(paths))}", raw={"paths": paths[:50], "classified_by": "rules"}))
        else:
            for p in paths:
                drafts.append(SignalDraft(
                    type="new_sitemap_path", summary=f"New page in {comp.name}'s sitemap: {p}",
                    new_value=p, evidence_url=f"https://{comp.domain}{p}", observed_at=now, event_confidence=0.85,
                    origin_group=f"sitemap:{comp.id}:{section}", dedup_basis=f"path|{p}", raw={"classified_by": "rules"}))
    for p in [p for p in removed if rx.search(p)][:10]:
        drafts.append(SignalDraft(
            type="removal", category="product", summary=f"Page removed from {comp.name}'s sitemap: {p}", old_value=p,
            evidence_url=f"https://web.archive.org/web/*/{comp.domain}{p}", observed_at=now, event_confidence=0.7,
            dedup_basis=f"sitemap-removed|{p}", raw={"classified_by": "rules"}))
    return drafts[:30]
