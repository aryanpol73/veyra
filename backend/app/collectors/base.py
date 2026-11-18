"""Collector interface + a polite, cached HTTP fetcher shared by every source.

Politeness rules (enforced here so no collector can skip them):
  * robots.txt checked for every URL (cached per host; if robots.txt is unreachable we allow)
  * >= PER_DOMAIN_DELAY_S between requests to the same host
  * descriptive User-Agent with contact email
  * on-disk response cache (TTL per call) so re-runs don't hammer sites
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.config import DATA_DIR, get_settings

log = logging.getLogger("veyra.fetch")
CACHE_DIR = DATA_DIR / "cache"
ROBOTS_AGENT = "VeyraCIBot"


@dataclass
class RawObservation:
    competitor_id: int
    source_id: int
    source_type: str  # page | jobs | news | early_signal
    url: str
    fetched_at: datetime
    observed_at: datetime
    content_text: str
    content_hash: str
    meta: dict[str, Any] = field(default_factory=dict)


class Collector(Protocol):
    source_type: str

    def collect(self, competitor, source, as_of: datetime | None = None) -> list[RawObservation]: ...


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def now() -> datetime:
    return datetime.now(timezone.utc)


class FetchError(Exception):
    pass


class RobotsBlocked(FetchError):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    fetched_at: datetime
    from_cache: bool


class Fetcher:
    """Thread-safe polite fetcher. One instance per process (see `fetcher()`)."""

    def __init__(self) -> None:
        s = get_settings()
        self.delay = s.per_domain_delay_s
        self.client = httpx.Client(
            headers={"User-Agent": s.user_agent, "Accept-Language": "en-US,en;q=0.8"},
            timeout=s.fetch_timeout_s,
            follow_redirects=True,
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.network_calls = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ---- robots ----
    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(p.netloc)
                r = self.client.get(f"{host}/robots.txt")
                if r.status_code >= 400:
                    rp = None  # no robots.txt -> everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(ROBOTS_AGENT, url)

    # ---- rate limit ----
    def _wait(self, netloc: str) -> None:
        with self._lock:
            last = self._last_hit.get(netloc, 0.0)
            gap = self.delay - (time.monotonic() - last)
            self._last_hit[netloc] = time.monotonic() + max(gap, 0)
        if gap > 0:
            time.sleep(gap)

    # ---- cache ----
    @staticmethod
    def _cache_path(url: str) -> Path:
        return CACHE_DIR / f"{sha(url)[:32]}.json"

    def get(self, url: str, *, ttl_s: int = 6 * 3600, timeout: float | None = None) -> FetchResult:
        cp = self._cache_path(url)
        if ttl_s > 0 and cp.exists() and time.time() - cp.stat().st_mtime < ttl_s:
            d = json.loads(cp.read_text("utf-8"))
            return FetchResult(url, d["status"], d["text"], datetime.fromisoformat(d["fetched_at"]), True)
        if not self.allowed(url):
            raise RobotsBlocked(f"robots.txt disallows {url}")
        self._wait(urlparse(url).netloc)
        try:
            r = self.client.get(url, timeout=timeout or self.client.timeout)
        except httpx.HTTPError as e:
            raise FetchError(f"{type(e).__name__}: {e}") from e
        self.network_calls += 1
        if r.status_code >= 400:
            raise FetchError(f"HTTP {r.status_code} for {url}")
        res = FetchResult(url, r.status_code, r.text, now(), False)
        cp.write_text(json.dumps({"status": r.status_code, "text": r.text, "fetched_at": res.fetched_at.isoformat()}), "utf-8")
        return res


_fetcher: Fetcher | None = None


def fetcher() -> Fetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = Fetcher()
    return _fetcher
