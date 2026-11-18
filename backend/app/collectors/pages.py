"""Pages collector: pricing / homepage / product / changelog pages -> normalized main text."""
from __future__ import annotations

import re
from datetime import datetime

import trafilatura
from selectolax.parser import HTMLParser

from app.collectors.base import RawObservation, fetcher, now, sha

# Lines that change constantly without meaning anything (dropped before hashing/diffing).
NOISE_LINE = re.compile(
    r"(©|\(c\)|copyright|all rights reserved|cookie|privacy policy|terms of service|"
    r"accept all|manage preferences|skip to (main )?content|^\s*(19|20)\d{2}\s*$|"
    r"^\s*(last )?updated:? .{0,30}$|^\s*\d{1,2}:\d{2}\s*(am|pm)?\s*$)",
    re.I,
)
DATE_TOKEN = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2},? (19|20)\d{2}\b|"
    r"\b(19|20)\d{2}-\d{2}-\d{2}\b",
    re.I,
)


def html_to_text(html: str) -> str:
    """Main text via trafilatura; fall back to cleaned body text for JS-heavy pricing pages."""
    text = trafilatura.extract(html, include_tables=True, include_comments=False, favor_recall=True) or ""
    if len(text) < 600:
        tree = HTMLParser(html)
        for sel in ("script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"):
            for n in tree.css(sel):
                n.decompose()
        body = tree.body
        alt = body.text(separator="\n") if body else ""
        if len(alt) > len(text):
            text = alt
    return normalize_text(text)


def normalize_text(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 2 or NOISE_LINE.search(line):
            continue
        line = DATE_TOKEN.sub("<date>", line)
        if out and out[-1] == line:
            continue
        out.append(line)
    return "\n".join(out)


class PagesCollector:
    source_type = "page"

    def collect(self, competitor, source, as_of: datetime | None = None) -> list[RawObservation]:
        res = fetcher().get(source.url, ttl_s=3 * 3600)
        text = html_to_text(res.text)
        return [RawObservation(
            competitor_id=competitor.id, source_id=source.id, source_type="page", url=source.url,
            fetched_at=res.fetched_at, observed_at=now(), content_text=text, content_hash=sha(text),
            meta={"chars": len(text), "from_cache": res.from_cache},
        )]
