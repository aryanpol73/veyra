"""Derive the tracked sources (pages, jobs, news, early signals) from a competitor profile."""
from __future__ import annotations

from urllib.parse import quote_plus

from app.collectors.early_signals import ct_url
from app.db.models import Competitor, Source


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
