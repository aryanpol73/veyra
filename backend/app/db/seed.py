"""Seed 3 demo competitors (public SaaS with public Greenhouse job boards and blog feeds, verified 2026-11-18).

Run:  python -m app.db.seed           (idempotent; skips existing names)
Edit COMPETITORS to track different companies. careers_provider: greenhouse | lever.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import select

from app.collectors.early_signals import ct_url

from app.db.models import Competitor, Source
from app.db.session import init_db, session_scope

COMPETITORS = [
    {
        "name": "Vercel",
        "domain": "vercel.com",
        "pricing_url": "https://vercel.com/pricing",
        "product_urls": ["https://vercel.com/", "https://vercel.com/changelog"],
        "careers_provider": "greenhouse",
        "careers_token": "vercel",
        "news_query": "Vercel",
        "feed_urls": ["https://vercel.com/atom"],
    },
    {
        "name": "Figma",
        "domain": "figma.com",
        "pricing_url": "https://www.figma.com/pricing/",
        "product_urls": ["https://www.figma.com/", "https://www.figma.com/release-notes/"],
        "careers_provider": "greenhouse",
        "careers_token": "figma",
        "news_query": "Figma",
        "feed_urls": ["https://www.figma.com/blog/feed/atom.xml"],
    },
    {
        "name": "Airtable",
        "domain": "airtable.com",
        "pricing_url": "https://www.airtable.com/pricing",
        "product_urls": ["https://www.airtable.com/"],
        "careers_provider": "greenhouse",
        "careers_token": "airtable",
        "news_query": "Airtable",
        "feed_urls": [],
    },
]


def sources_for(c: Competitor) -> list[Source]:
    """Derive tracked sources from a competitor profile (also used when competitors are added via API)."""
    out: list[Source] = []
    for url in [c.pricing_url, *(c.product_urls or [])]:
        if url:
            out.append(Source(source_type="page", url=url))
    if c.careers_provider == "greenhouse" and c.careers_token:
        out.append(Source(source_type="jobs",
                          url=f"https://boards-api.greenhouse.io/v1/boards/{c.careers_token}/jobs?content=true"))
    elif c.careers_provider == "lever" and c.careers_token:
        out.append(Source(source_type="jobs", url=f"https://api.lever.co/v0/postings/{c.careers_token}?mode=json"))
    if c.news_query:  # Bing News RSS (Google News RSS is robots-disallowed)
        out.append(Source(source_type="news",
                          url=f"https://www.bing.com/news/search?q={quote_plus(c.news_query)}&format=rss"))
    for feed in c.feed_urls or []:
        out.append(Source(source_type="news", url=feed))
    out.append(Source(source_type="early_signal", url=ct_url(c.domain)))
    out.append(Source(source_type="early_signal", url=f"https://{c.domain}/sitemap.xml"))
    return out


def seed() -> int:
    init_db()
    added = 0
    with session_scope() as db:
        for data in COMPETITORS:
            if db.scalar(select(Competitor).where(Competitor.name == data["name"])):
                continue
            c = Competitor(**data)
            c.sources = sources_for(c)
            db.add(c)
            added += 1
    return added


if __name__ == "__main__":
    print(f"seeded {seed()} competitor(s)")
