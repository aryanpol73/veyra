"""Early-signal collectors: Certificate Transparency subdomains + sitemap URL paths.

These are LEADS, not proof: a new subdomain may be an internal test, a new sitemap path may be
a stub. Labeled "Early Signal" in the UI and given low source reliability.

CT data comes from the Cert Spotter API (crt.sh's robots.txt disallows bots). Anonymous Cert
Spotter is limited to ~10 requests/hour, so results are cached for 24 h and only one page is read.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlparse

from app.collectors.base import FetchError, RawObservation, fetcher, now, sha

MAX_CHILD_SITEMAPS = 3
MAX_PATHS = 20_000


def ct_url(domain: str) -> str:
    return f"https://api.certspotter.com/v1/issuances?domain={domain}&include_subdomains=true&expand=dns_names"


def parse_certspotter(payload: list, domain: str) -> dict[str, dict]:
    """subdomain -> {first_seen, last_seen, certs}. Wildcards are dropped (they name no host)."""
    subs: dict[str, dict] = {}
    for iss in payload:
        nb = iss.get("not_before")
        for name in iss.get("dns_names", []):
            name = name.lower().strip(".")
            if name.startswith("*.") or not name.endswith(domain) or name == domain:
                continue
            s = subs.setdefault(name, {"first_seen": nb, "last_seen": nb, "certs": 0})
            s["certs"] += 1
            if nb and (s["first_seen"] is None or nb < s["first_seen"]):
                s["first_seen"] = nb
            if nb and (s["last_seen"] is None or nb > s["last_seen"]):
                s["last_seen"] = nb
    return subs


LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


class EarlySignalCollector:
    source_type = "early_signal"

    def collect(self, competitor, source, as_of: datetime | None = None) -> list[RawObservation]:
        if "certspotter" in source.url:
            return [self._ct(competitor, source)]
        return [self._sitemap(competitor, source)]

    def _ct(self, competitor, source) -> RawObservation:
        # Results come oldest-first, 100 per page; follow the `after` cursor so the NEWEST certs
        # (the interesting ones) aren't missed. Max 3 pages to respect the ~10 req/hour anon limit.
        res = fetcher().get(source.url, ttl_s=24 * 3600, timeout=20)
        issuances = json.loads(res.text)
        page = issuances
        for _ in range(2):
            if len(page) < 100:
                break
            try:
                page = json.loads(fetcher().get(f"{source.url}&after={page[-1]['id']}", ttl_s=24 * 3600, timeout=20).text)
            except FetchError:
                break
            issuances += page
        subs = parse_certspotter(issuances, competitor.domain)
        text = "\n".join(sorted(subs))
        return RawObservation(
            competitor_id=competitor.id, source_id=source.id, source_type="early_signal", url=source.url,
            fetched_at=res.fetched_at, observed_at=now(), content_text=text, content_hash=sha(text),
            meta={"kind": "ct", "subdomains": subs},
        )

    def _sitemap(self, competitor, source) -> RawObservation:
        res = fetcher().get(source.url, ttl_s=12 * 3600)
        locs = LOC.findall(res.text)
        if "<sitemapindex" in res.text[:2000].lower():
            paths: set[str] = set()
            children = [u for u in locs if not u.endswith(".gz")][:MAX_CHILD_SITEMAPS]
            for child in children:
                try:
                    paths |= {urlparse(u).path.rstrip("/") or "/" for u in LOC.findall(fetcher().get(child, ttl_s=12 * 3600).text)}
                except FetchError:
                    continue
            meta_children = children
        else:
            paths = {urlparse(u).path.rstrip("/") or "/" for u in locs}
            meta_children = []
        ordered = sorted(paths)[:MAX_PATHS]
        text = "\n".join(ordered)
        return RawObservation(
            competitor_id=competitor.id, source_id=source.id, source_type="early_signal", url=source.url,
            fetched_at=res.fetched_at, observed_at=now(), content_text=text, content_hash=sha(text),
            meta={"kind": "sitemap", "paths": len(ordered), "child_sitemaps": meta_children},
        )

