"""Build the frozen replay dataset from the Wayback Machine.

    python -m app.eval.dataset [--start 2026-01-01] [--end 2026-11-18]

For every seeded competitor's pricing / product / changelog pages and blog feeds, take one capture
per month (CDX collapse=timestamp:6) and store the NORMALISED content with its capture time as
observed_at. Replay reads only these files, filtered by observed_at <= as_of, so it can never see
the future. Jobs, CT logs and news search are NOT in the dataset (no reliable public history).

Layout: data/replay/<competitor>/<source_key>/<YYYYMMDDhhmmss>.json  + data/replay/manifest.json
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import feedparser

from app.collectors import wayback
from app.collectors.base import sha
from app.collectors.news import _entry_dt, canonical_url, normalize_title
from app.collectors.pages import html_to_text
from app.config import REPLAY_DATA_DIR
from app.eval.companies import BACKTEST_COMPANIES as COMPETITORS

log = logging.getLogger("veyra.dataset")
REPLAY_DIR = REPLAY_DATA_DIR


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def source_key(url: str) -> str:
    return sha(url)[:10]


def feed_items(xml: str, competitor: str) -> list[dict]:
    feed = feedparser.parse(xml)
    out = []
    for e in feed.entries[:100]:
        if not e.get("link") or not e.get("title"):
            continue
        pub = _entry_dt(e)
        out.append({"title": e.title.strip(), "norm_title": normalize_title(e.title), "url": canonical_url(e.link),
                    "published": pub.isoformat() if pub else None, "publisher": competitor, "kind": "blog"})
    return out


def build(start: datetime, end: datetime) -> dict:
    manifest = {"built_at": datetime.now(timezone.utc).isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                "competitors": {}}
    for c in COMPETITORS:
        comp = {"sources": []}
        targets = [("page", u) for u in [c["pricing_url"], *c["product_urls"]] if u] + [("news", u) for u in c.get("feed_urls", [])]
        for stype, url in targets:
            stamps = wayback.list_snapshots(url, start, end, monthly=True)
            saved = 0
            folder = REPLAY_DIR / slug(c["name"]) / source_key(url)
            folder.mkdir(parents=True, exist_ok=True)
            for ts in stamps:
                path = folder / f"{ts}.json"
                if path.exists():
                    saved += 1
                    continue
                raw = wayback.fetch_snapshot(url, ts)
                if not raw:
                    continue
                observed = wayback.ts_to_dt(ts)
                if stype == "page":
                    text, meta = html_to_text(raw), {}
                else:
                    items = [i for i in feed_items(raw, c["name"]) if i["published"] and i["published"] <= observed.isoformat()]
                    text, meta = "\n".join(sorted(i["url"] for i in items)), {"items": items, "kind": "blog"}
                if len(text) < 50:
                    continue
                path.write_text(json.dumps({"url": url, "source_type": stype, "wayback_ts": ts,
                                            "wayback_url": f"https://web.archive.org/web/{ts}/{url}",
                                            "observed_at": observed.isoformat(), "content_text": text,
                                            "content_hash": sha(text), "meta": meta}), "utf-8")
                saved += 1
            comp["sources"].append({"url": url, "source_type": stype, "key": source_key(url), "captures": saved})
            log.info("%s %s: %d captures", c["name"], url, saved)
        manifest["competitors"][c["name"]] = comp
    (REPLAY_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    return manifest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-11-18")
    a = ap.parse_args()
    m = build(datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc), datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc))
    for name, comp in m["competitors"].items():
        print(name, [(s["url"], s["captures"]) for s in comp["sources"]])
