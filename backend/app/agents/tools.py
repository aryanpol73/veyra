"""Tools available to the Investigator and the Skeptic's discriminating tests.

Every tool:
  * respects `as_of` (replay mode): DB/snapshot reads are filtered to observed_at <= as_of and
    live network tools are disabled, so a backtest can never see the future;
  * returns compact text for the LLM plus structured `items` (url / signal_id) that are the ONLY
    things a finding may cite (no evidence that the tools did not actually return);
  * counts against hard budgets (per-hypothesis tool calls, per-cycle fetches).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.collectors.base import FetchError, fetcher
from app.collectors.pages import html_to_text
from app.config import get_settings
from app.db.models import BeliefHistory, Competitor, Signal, Snapshot, Source

PUBLIC_ALLOWLIST = ("boards-api.greenhouse.io", "job-boards.greenhouse.io", "boards.greenhouse.io",
                    "api.lever.co", "jobs.lever.co", "web.archive.org")


@dataclass
class CycleBudget:
    """Shared across all investigations in one cycle."""
    max_fetches: int
    fetches: int = 0


@dataclass
class ToolContext:
    db: Session
    competitor: Competitor
    as_of: datetime | None = None  # None = live
    cycle_budget: CycleBudget | None = None
    seen_urls: set[str] = field(default_factory=set)
    seen_signal_ids: set[int] = field(default_factory=set)
    calls: list[dict] = field(default_factory=list)

    @property
    def now(self) -> datetime:
        return self.as_of or datetime.now(timezone.utc)

    @property
    def replay(self) -> bool:
        return self.as_of is not None


@dataclass
class ToolResult:
    text: str
    items: list[dict[str, Any]] = field(default_factory=list)  # {"url", "signal_id"?, "snippet"}


def _kw_regex(keywords: list[str] | str | None) -> re.Pattern | None:
    if not keywords:
        return None
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.strip() for k in keywords if k and k.strip()][:8]
    return re.compile("|".join(re.escape(k) for k in keywords), re.I) if keywords else None


def _latest(ctx: ToolContext, source_type: str, url_like: str | None = None) -> list[tuple[Source, Snapshot]]:
    q = select(Source).where(Source.competitor_id == ctx.competitor.id, Source.source_type == source_type)
    if url_like:
        q = q.where(Source.url.like(f"%{url_like}%"))
    out = []
    for src in ctx.db.scalars(q).all():
        sq = select(Snapshot).where(Snapshot.source_id == src.id)
        if ctx.as_of:
            sq = sq.where(Snapshot.observed_at <= ctx.as_of)
        snap = ctx.db.scalars(sq.order_by(Snapshot.observed_at.desc()).limit(1)).first()
        if snap:
            out.append((src, snap))
    return out


# ---------------------------------------------------------------- tools
def query_signals(ctx: ToolContext, keywords: list[str] | None = None, category: str | None = None,
                  type: str | None = None, days: int = 120, **_) -> ToolResult:
    q = select(Signal).where(Signal.competitor_id == ctx.competitor.id,
                             Signal.observed_at >= ctx.now - timedelta(days=int(days or 120)))
    if ctx.as_of:
        q = q.where(Signal.observed_at <= ctx.as_of)
    if category:
        q = q.where(Signal.category == category)
    if type:
        q = q.where(Signal.type == type)
    kws = [keywords] if isinstance(keywords, str) else [k for k in (keywords or []) if k and k.strip()][:8]
    if kws:
        q = q.where(or_(*[Signal.summary.ilike(f"%{k.strip()}%") for k in kws]))
    rows = ctx.db.scalars(q.order_by(Signal.observed_at.desc()).limit(12)).all()
    items = [{"signal_id": s.id, "url": s.evidence_url, "snippet": s.summary[:200]} for s in rows]
    text = "\n".join(f"S{s.id} [{s.type}, {s.observed_at:%Y-%m-%d}] {s.summary[:180]}" for s in rows) or "no matching signals"
    return ToolResult(text, items)


def search_jobs(ctx: ToolContext, keywords: list[str] | str | None = None, **_) -> ToolResult:
    rx = _kw_regex(keywords)
    snaps = _latest(ctx, "jobs")
    if not snaps:
        return ToolResult("no job board data collected for this competitor")
    src, snap = snaps[0]
    postings = snap.meta.get("postings", [])
    hits = [p for p in postings if rx is None or rx.search(p["title"]) or any(rx.search(k) for k in p.get("keywords", []))]
    items = [{"url": p.get("url"), "snippet": f"{p['title']} ({p.get('location')}, posted {p['first_published'][:10]})"} for p in hits[:15]]
    text = (f"{len(hits)} of {len(postings)} open postings match (board snapshot {snap.observed_at:%Y-%m-%d}):\n"
            + "\n".join(f"- {i['snippet']} {i['url']}" for i in items))
    return ToolResult(text, items)


def search_changelog(ctx: ToolContext, keywords: list[str] | str | None = None, **_) -> ToolResult:
    rx = _kw_regex(keywords)
    items: list[dict] = []
    for src, snap in _latest(ctx, "news"):
        if snap.meta.get("kind") != "blog":
            continue
        for it in snap.meta.get("items", []):
            if rx is None or rx.search(it["title"]):
                items.append({"url": it["url"], "snippet": f"{it['title']} ({(it.get('published') or '')[:10]})"})
    for src, snap in _latest(ctx, "page"):
        if not re.search(r"changelog|release|whats-new", src.url):
            continue
        for line in snap.content_text.splitlines():
            if rx and rx.search(line) and len(line) > 20:
                items.append({"url": src.url, "snippet": line[:200]})
    items = items[:15]
    text = "\n".join(f"- {i['snippet']} {i['url']}" for i in items) or "no matching changelog/blog entries"
    return ToolResult(text, items)


def check_ct_logs(ctx: ToolContext, keywords: list[str] | str | None = None, **_) -> ToolResult:
    rx = _kw_regex(keywords)
    snaps = [x for x in _latest(ctx, "early_signal", "certspotter")]
    if not snaps:
        return ToolResult("no CT data collected")
    subs = snaps[0][1].meta.get("subdomains", {})
    hits = sorted((s for s in subs if rx is None or rx.search(s)), key=lambda s: subs[s]["first_seen"] or "", reverse=True)[:15]
    items = [{"url": f"https://crt.sh/?q={s}", "snippet": f"{s} first cert {subs[s]['first_seen'][:10]} ({subs[s]['certs']} certs)"} for s in hits]
    return ToolResult("\n".join(f"- {i['snippet']}" for i in items) or "no matching subdomains in CT logs "
                      "(note: absence in CT is weak evidence)", items)


def diff_sitemap(ctx: ToolContext, keywords: list[str] | str | None = None, **_) -> ToolResult:
    rx = _kw_regex(keywords)
    snaps = _latest(ctx, "early_signal", "sitemap")
    if not snaps:
        return ToolResult("no sitemap collected")
    src, snap = snaps[0]
    paths = [p for p in snap.content_text.splitlines() if rx is None or rx.search(p)]
    items = [{"url": f"https://{ctx.competitor.domain}{p}", "snippet": p} for p in paths[:20]]
    return ToolResult(f"{len(paths)} sitemap paths match:\n" + "\n".join(f"- {p}" for p in paths[:20]), items)


def fetch_url(ctx: ToolContext, url: str = "", keywords: list[str] | str | None = None, **_) -> ToolResult:
    if ctx.replay:
        return ToolResult("fetch_url is disabled in replay mode (no live data after as_of)")
    host = urlparse(url).netloc.lower()
    dom = ctx.competitor.domain.lower()
    if not (host == dom or host.endswith("." + dom) or host in PUBLIC_ALLOWLIST):
        return ToolResult(f"refused: {host} is outside the allowed domains ({dom}, job boards, web.archive.org)")
    b = ctx.cycle_budget
    if b and b.fetches >= b.max_fetches:
        return ToolResult("refused: cycle fetch budget exhausted")
    if b:
        b.fetches += 1
    try:
        res = fetcher().get(url, ttl_s=6 * 3600)
    except FetchError as e:
        return ToolResult(f"fetch failed: {e}")
    text = html_to_text(res.text) if "<html" in res.text[:2000].lower() else res.text
    rx = _kw_regex(keywords)
    lines = [ln for ln in text.splitlines() if rx is None or rx.search(ln)][:15] if rx else text.splitlines()[:25]
    snippet = "\n".join(lines)[:1500]
    return ToolResult(f"{url} ({len(text)} chars; {'matching lines' if rx else 'first lines'}):\n{snippet}",
                      [{"url": url, "snippet": snippet[:300]}])


def query_hypothesis_history(ctx: ToolContext, hypothesis_id: int = 0, **_) -> ToolResult:
    rows = ctx.db.scalars(select(BeliefHistory).where(BeliefHistory.hypothesis_id == int(hypothesis_id or 0))
                          .order_by(BeliefHistory.ts)).all()
    return ToolResult("\n".join(f"{r.ts:%Y-%m-%d} conf={r.confidence:.2f} ({r.delta:+.2f}) {r.reason[:120]}" for r in rows)
                      or "no history")


def web_search(ctx: ToolContext, **_) -> ToolResult:
    return ToolResult("web_search is not available in this deployment (no search API; and disabled in replay)")


TOOLS: dict[str, tuple[Callable[..., ToolResult], str]] = {
    "query_signals": (query_signals, 'signals already collected. args: {"keywords": [..], "category"?: str, "type"?: str, "days"?: int}'),
    "search_jobs": (search_jobs, 'open job postings. args: {"keywords": [..]}'),
    "search_changelog": (search_changelog, 'official blog/changelog entries. args: {"keywords": [..]}'),
    "check_ct_logs": (check_ct_logs, 'Certificate Transparency subdomains. args: {"keywords": [..]}'),
    "diff_sitemap": (diff_sitemap, 'sitemap URL paths. args: {"keywords": [..]}'),
    "fetch_url": (fetch_url, 'fetch one page on the competitor domain / job boards / web.archive.org. args: {"url": str, "keywords"?: [..]}'),
    "query_hypothesis_history": (query_hypothesis_history, 'belief history. args: {"hypothesis_id": int}'),
    "web_search": (web_search, "unavailable"),
}
TOOL_NAMES = tuple(TOOLS)


def tool_menu() -> str:
    return "\n".join(f"- {name}: {desc}" for name, (_, desc) in TOOLS.items() if name != "web_search")


def run_tool(ctx: ToolContext, name: str, args: dict | None) -> ToolResult:
    fn = TOOLS.get(name, (None, ""))[0]
    if fn is None:
        res = ToolResult(f"unknown tool {name}")
    else:
        try:
            res = fn(ctx, **(args or {}))
        except TypeError as e:
            res = ToolResult(f"bad arguments for {name}: {e}")
    for it in res.items:
        if it.get("url"):
            ctx.seen_urls.add(it["url"])
        if it.get("signal_id"):
            ctx.seen_signal_ids.add(int(it["signal_id"]))
    ctx.calls.append({"tool": name, "args": args or {}, "result": res.text[:600], "n_items": len(res.items)})
    return res
