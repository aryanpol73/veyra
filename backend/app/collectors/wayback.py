"""Wayback Machine helpers (CDX lookup + original-page fetch via the `id_` flag).

Used for (a) a historical baseline on a page's first cycle, so the very first run can show
real changes, and (b) building the frozen replay dataset in Phase 3.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.collectors.base import FetchError, fetcher

log = logging.getLogger("argus.wayback")
CDX = "http://web.archive.org/cdx/search/cdx"


def list_snapshots(url: str, start: datetime, end: datetime, monthly: bool = True) -> list[str]:
    """Return 14-digit Wayback timestamps of 200-status captures between start and end."""
    q = (f"{CDX}?url={url}&output=json&from={start:%Y%m%d}&to={end:%Y%m%d}"
         f"&filter=statuscode:200&fl=timestamp" + ("&collapse=timestamp:6" if monthly else ""))
    try:
        rows = json.loads(fetcher().get(q, ttl_s=7 * 86400, timeout=30).text or "[]")
    except (FetchError, json.JSONDecodeError) as e:
        log.info("wayback cdx failed for %s: %s", url, e)
        return []
    return [r[0] for r in rows[1:]]  # first row is the header


def fetch_snapshot(url: str, ts: str) -> str | None:
    try:
        return fetcher().get(f"https://web.archive.org/web/{ts}id_/{url}", ttl_s=30 * 86400, timeout=30).text
    except FetchError as e:
        log.info("wayback fetch failed %s@%s: %s", url, ts, e)
        return None


def ts_to_dt(ts: str) -> datetime:
    return datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def baseline_before(url: str, days_ago: int = 30) -> tuple[str, datetime] | None:
    """Most recent capture at least `days_ago` old (looks back up to 6 months)."""
    end = datetime.now(timezone.utc) - timedelta(days=days_ago)
    stamps = list_snapshots(url, end - timedelta(days=180), end, monthly=False)
    for ts in reversed(stamps[-3:]):
        html = fetch_snapshot(url, ts)
        if html:
            return html, ts_to_dt(ts)
    return None
