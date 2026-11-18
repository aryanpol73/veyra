"""Jobs collector: public Greenhouse / Lever JSON boards -> normalized postings list."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from selectolax.parser import HTMLParser

from app.collectors.base import RawObservation, fetcher, now, sha

# keyword area -> (title regex, body regex). Companies mention "AI" in every posting's blurb,
# so broad terms count only in the TITLE; the body only counts specific technical terms.
TECH_KEYWORDS: dict[str, tuple[re.Pattern, re.Pattern | None]] = {
    "AI/LLM": (re.compile(r"\b(AI|LLMs?|GenAI|agents?|agentic|applied scientist)\b", re.I),
               re.compile(r"\b(LLMs?|large language models?|fine-tun\w+|RAG|retrieval-augmented|evals? harness|prompt engineering|PyTorch)\b")),
    "ML": (re.compile(r"\b(machine learning|ML|MLOps|data scien\w+)\b", re.I),
           re.compile(r"\b(PyTorch|TensorFlow|JAX|model training|deep learning)\b")),
    "Inference/GPU": (re.compile(r"\b(inference|GPU|compute)\b", re.I), re.compile(r"\b(CUDA|Triton|vLLM|GPU clusters?)\b")),
    "Rust": (re.compile(r"\bRust\b"), re.compile(r"\b(Rust)\b(?! ?Belt)")),
    "Security": (re.compile(r"\b(security|AppSec|trust|compliance)\b", re.I), re.compile(r"\b(FedRAMP|SOC ?2 Type II|threat modeling)\b")),
    "Data platform": (re.compile(r"\b(data platform|data infrastructure|data engineer\w*)\b", re.I), None),
    "Enterprise sales": (re.compile(r"\b(enterprise|strategic accounts?|majors)\b", re.I), None),
}


def _strip_html(html: str) -> str:
    if not html:
        return ""
    # Greenhouse double-escapes content (&lt;p&gt;); unescape by parsing twice.
    once = HTMLParser(html).text()
    return HTMLParser(once).text() if "<" in once else once


def keywords_in(title: str, body: str = "") -> list[str]:
    return [k for k, (t_rx, b_rx) in TECH_KEYWORDS.items()
            if t_rx.search(title) or (b_rx is not None and b_rx.search(body))]


def _parse_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):  # lever: ms epoch
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def strip_boilerplate(bodies: list[str], min_share: float = 0.3) -> list[str]:
    """Drop sentences that recur across many postings (company blurb, EEO text) so a company
    describing itself as "AI-native" doesn't make every sales role look like AI hiring."""
    if len(bodies) < 4:
        return bodies
    split = [[x.strip() for x in SENT_SPLIT.split(b) if len(x.strip()) > 20] for b in bodies]
    freq: dict[str, int] = {}
    for sents in split:
        for x in set(sents):
            freq[x] = freq.get(x, 0) + 1
    limit = max(3, min_share * len(bodies))
    return ["\n".join(x for x in sents if freq[x] < limit) for sents in split]


def parse_greenhouse(payload: dict) -> list[dict]:
    out = []
    jobs = payload.get("jobs", [])
    bodies = strip_boilerplate([_strip_html(j.get("content", "")) for j in jobs])
    for j, body in zip(jobs, bodies):
        out.append({
            "id": str(j["id"]),
            "title": j.get("title", "").strip(),
            "department": ", ".join(d["name"] for d in j.get("departments", [])) or None,
            "location": (j.get("location") or {}).get("name"),
            "first_published": (_parse_dt(j.get("first_published") or j.get("updated_at")) or now()).isoformat(),
            "url": j.get("absolute_url"),
            "keywords": keywords_in(j.get("title", ""), body),
        })
    return out


def parse_lever(payload: list) -> list[dict]:
    out = []
    bodies = strip_boilerplate([j.get("descriptionPlain") or "" for j in payload])
    for j, body in zip(payload, bodies):
        cats = j.get("categories") or {}
        out.append({
            "id": str(j["id"]),
            "title": (j.get("text") or "").strip(),
            "department": cats.get("team") or cats.get("department"),
            "location": cats.get("location"),
            "first_published": (_parse_dt(j.get("createdAt")) or now()).isoformat(),
            "url": j.get("hostedUrl"),
            "keywords": keywords_in(j.get("text") or "", body),
        })
    return out


class JobsCollector:
    source_type = "jobs"

    def collect(self, competitor, source, as_of: datetime | None = None) -> list[RawObservation]:
        res = fetcher().get(source.url, ttl_s=6 * 3600, timeout=40)
        data = json.loads(res.text)
        postings = parse_lever(data) if "lever.co" in source.url else parse_greenhouse(data)
        postings.sort(key=lambda p: p["id"])
        text = "\n".join(f"{p['id']}|{p['title']}|{p['department']}|{p['location']}" for p in postings)
        return [RawObservation(
            competitor_id=competitor.id, source_id=source.id, source_type="jobs", url=source.url,
            fetched_at=res.fetched_at, observed_at=now(), content_text=text, content_hash=sha(text),
            meta={"postings": postings, "count": len(postings)},
        )]
