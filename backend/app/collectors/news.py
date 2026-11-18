"""News collector: Bing News RSS by query + the company's own blog/changelog feeds.

(Google News RSS is disallowed for bots by its robots.txt, so it is not used.)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser

from app.collectors.base import RawObservation, fetcher, now, sha

TRACKING = re.compile(r"^(utm_|ref$|fbclid|gclid|mc_)")


def canonical_url(url: str) -> str:
    """Unwrap Bing redirect links, drop tracking params, fragments and trailing slashes."""
    p = urlparse(url)
    if "bing.com" in p.netloc and "apiclick" in p.path:
        inner = parse_qs(p.query).get("url", [""])[0]
        if inner:
            p = urlparse(inner)
    q = [(k, v) for k, vs in parse_qs(p.query).items() for v in vs if not TRACKING.match(k)]
    return urlunparse((p.scheme.lower() or "https", p.netloc.lower().removeprefix("www."),
                       p.path.rstrip("/") or "/", "", urlencode(sorted(q)), ""))


def normalize_title(title: str) -> str:
    title = re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", title)  # strip " - Publisher"
    return re.sub(r"[^a-z0-9 ]+", "", title.lower()).strip()


def _entry_dt(e) -> datetime | None:
    for key in ("published", "updated"):
        v = e.get(key)
        if not v:
            continue
        try:
            return parsedate_to_datetime(v).astimezone(timezone.utc)
        except (TypeError, ValueError):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                pass
    return None


class NewsCollector:
    source_type = "news"

    def collect(self, competitor, source, as_of: datetime | None = None) -> list[RawObservation]:
        res = fetcher().get(source.url, ttl_s=3 * 3600)
        feed = feedparser.parse(res.text)
        kind = "news" if "bing.com" in source.url else "blog"
        items, seen = [], set()
        for e in feed.entries[:100]:
            if not e.get("link") or not e.get("title"):
                continue
            url = canonical_url(e.link)
            if url in seen:
                continue
            seen.add(url)
            pub = _entry_dt(e)
            items.append({
                "title": e.title.strip(),
                "norm_title": normalize_title(e.title),
                "url": url,
                "published": pub.isoformat() if pub else None,
                "publisher": (e.get("news_source") or e.get("source", {}).get("title") if kind == "news" else competitor.name),
                "kind": kind,
            })
        text = "\n".join(sorted(i["url"] for i in items))
        return [RawObservation(
            competitor_id=competitor.id, source_id=source.id, source_type="news", url=source.url,
            fetched_at=res.fetched_at, observed_at=now(), content_text=text, content_hash=sha(text),
            meta={"items": items, "kind": kind},
        )]
