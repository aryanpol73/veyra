"""Semantic page diff: block diff -> deterministic noise pre-filter -> typed events.

Classification uses LLM_FAST when configured; otherwise a transparent rule-based fallback
(every signal records `classified_by` in raw so the UI/eval can tell them apart).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.agents import prompts
from app.config import get_settings

MONEY = re.compile(r"(?:[$€£]\s?(\d{1,5}(?:[.,]\d{1,2})?))|(?:(\d{1,5}(?:[.,]\d{1,2})?)\s?(?:USD|EUR|usd))")
NUMBER = re.compile(r"\d")
PLAN_NAMES = re.compile(r"\b(free|hobby|starter|plus|pro|premium|team|teams|business|enterprise|organization|professional)\b", re.I)
CONTACT_SALES = re.compile(r"\b(contact (sales|us)|talk to sales|get a quote|custom pricing)\b", re.I)
LAUNCH_WORDS = re.compile(r"\b(introducing|now available|announcing|just launched|launches|launched|now in beta|public beta|"
                          r"generally available|general availability)\b|^new:", re.I)
MIN_CHANGED_TOKENS = 8


@dataclass
class PageChange:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed_tokens(self) -> int:
        return sum(len(line.split()) for line in self.added + self.removed)

    def money(self) -> tuple[list[float], list[float]]:
        return sorted(x for line in self.removed for x in amounts(line)), sorted(x for line in self.added for x in amounts(line))

    def paired(self) -> list[tuple[str, str]]:
        """Pair each removed line with its most similar added line once numbers are masked
        ("$0.40 per 1M" <-> "Starting at $0.35 per 1M"). Greedy, each added line used once."""
        pairs, used = [], set()
        for old in self.removed:
            if not NUMBER.search(old):
                continue
            mo = _mask(old)
            best, best_r = None, 0.6
            for j, new in enumerate(self.added):
                if j in used or not NUMBER.search(new):
                    continue
                r = difflib.SequenceMatcher(None, mo, _mask(new)).ratio()
                if r > best_r:
                    best, best_r = j, r
            if best is not None:
                used.add(best)
                pairs.append((old, self.added[best]))
        return pairs

    def price_pairs(self) -> list[tuple[str, str, float, float]]:
        """(old line, new line, old amount, new amount) where a paired line's price changed."""
        out = []
        for old, new in self.paired():
            a, b = amounts(old), amounts(new)
            if len(a) == len(b) and a and a != b:
                for x, y in zip(a, b):
                    if x != y:
                        out.append((old, new, x, y))
        return out

    def limit_pairs(self) -> list[tuple[str, str]]:
        """Paired lines whose non-price numbers changed (quotas, seats, limits)."""
        return [(o, n) for o, n in self.paired() if not amounts(o) and not amounts(n) and _nums(o) != _nums(n)]


def amounts(line: str) -> list[float]:
    return [float((a or b).replace(",", "")) for a, b in MONEY.findall(line)]


def _nums(line: str) -> list[str]:
    return re.findall(r"\d[\d,.]*", line)


def _mask(line: str) -> str:
    return re.sub(r"\d[\d,.]*", "#", line.lower().replace("starting at ", ""))


def diff_text(old: str, new: str) -> PageChange:
    a, b = old.splitlines(), new.splitlines()
    ch = PageChange()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            ch.removed += a[i1:i2]
        if tag in ("replace", "insert"):
            ch.added += b[j1:j2]
    # pure re-ordering: same lines, different positions -> not a change
    common = set(ch.added) & set(ch.removed)
    ch.added = [x for x in ch.added if x not in common]
    ch.removed = [x for x in ch.removed if x not in common]
    return ch


def is_trivial(ch: PageChange) -> bool:
    """Deterministic pre-filter. Non-trivial if enough tokens changed OR any number/plan name changed."""
    if not ch.added and not ch.removed:
        return True
    lines = ch.added + ch.removed
    if any(NUMBER.search(x) for x in lines) or any(PLAN_NAMES.search(x) for x in lines):
        # numbers changed — but ignore if the only digits are in short noise-like lines (e.g. "3 min read")
        meaningful = [x for x in lines if NUMBER.search(x) and (MONEY.search(x) or PLAN_NAMES.search(x) or len(x.split()) > 3)]
        if meaningful:
            return False
    return ch.changed_tokens < MIN_CHANGED_TOKENS


def price_pct(ch: PageChange) -> float | None:
    """Largest relative change among line-paired prices (deterministic; drives priority), or None."""
    pcts = [abs(y - x) / x for _, _, x, y in ch.price_pairs() if x > 0]
    return max(pcts) if pcts else None


# ---------- classification ----------
EventType = Literal["price_change", "plan_change", "feature_launch", "positioning_change", "removal", "noise"]
Category = Literal["pricing", "product", "market"]


class ClassifiedEvent(BaseModel):
    type: EventType
    category: Category
    summary: str = Field(max_length=400)
    old_value: str | None = None
    new_value: str | None = None


class PageClassification(BaseModel):
    events: list[ClassifiedEvent] = Field(default_factory=list, max_length=3)


def _clip(lines: list[str], n: int = 40, chars: int = 3000) -> str:
    return "\n".join(lines[:n])[:chars]


def classify_rules(ch: PageChange, page_kind: str) -> list[ClassifiedEvent]:
    old_amt, new_amt = ch.money()
    events: list[ClassifiedEvent] = []
    added_txt, removed_txt = "\n".join(ch.added), "\n".join(ch.removed)
    pp = ch.price_pairs()
    if pp:
        shown = "; ".join(f"{o} → {n}" for o, n, _, _ in pp[:3])
        events.append(ClassifiedEvent(
            type="price_change", category="pricing",
            summary=f"{len(pp)} listed price(s) changed on the {page_kind} page: {shown}"[:400],
            old_value="; ".join(o for o, _, _, _ in pp[:5])[:300], new_value="; ".join(n for _, n, _, _ in pp[:5])[:300]))
    lp = ch.limit_pairs()
    if lp and page_kind == "pricing":
        shown = "; ".join(f"{o} → {n}" for o, n in lp[:4])
        events.append(ClassifiedEvent(
            type="plan_change", category="pricing",
            summary=f"{len(lp)} plan limit(s) changed on the pricing page: {shown}"[:400],
            old_value="; ".join(o for o, _ in lp[:6])[:300], new_value="; ".join(n for _, n in lp[:6])[:300]))
    if not pp and old_amt and not new_amt and CONTACT_SALES.search(added_txt):
        events.append(ClassifiedEvent(
            type="removal", category="pricing",
            summary=f"Listed prices were removed from the {page_kind} page in favour of a 'contact sales' path.",
            old_value=", ".join(map(str, old_amt)), new_value="contact sales"))
    added_plans = set(p.lower() for p in PLAN_NAMES.findall(added_txt)) - set(p.lower() for p in PLAN_NAMES.findall(removed_txt))
    if page_kind == "pricing" and added_plans and not events:
        events.append(ClassifiedEvent(type="plan_change", category="pricing",
                                      summary=f"Pricing page now mentions plan tier(s): {', '.join(sorted(added_plans))}.",
                                      new_value=", ".join(sorted(added_plans))))
    launches = [x for x in ch.added if LAUNCH_WORDS.search(x)]
    if launches:
        events.append(ClassifiedEvent(type="feature_launch", category="product",
                                      summary=f"New launch wording on the {page_kind} page: \"{launches[0][:160]}\"",
                                      new_value=launches[0][:300]))
    if not events and ch.changed_tokens >= 40 and page_kind == "homepage":
        events.append(ClassifiedEvent(type="positioning_change", category="market",
                                      summary="Homepage messaging changed substantially.",
                                      old_value=_clip(ch.removed, 3, 300), new_value=_clip(ch.added, 3, 300)))
    return events[:3]


def classify(ch: PageChange, page_kind: str, competitor: str) -> tuple[list[ClassifiedEvent], str]:
    """Returns (events, classified_by)."""
    if get_settings().llm_configured and get_settings().classify_with_llm:
        user = prompts.SIGNAL_CLASSIFIER_USER.format(
            competitor=competitor, page_kind=page_kind, removed=_clip(ch.removed) or "(none)", added=_clip(ch.added) or "(none)")
        out = llm.complete_json(role="fast", system=prompts.SIGNAL_CLASSIFIER, user=user,
                                schema=PageClassification, kind="classify_page")
        if out is not None:
            return [e for e in out.events if e.type != "noise"], "llm"
    return classify_rules(ch, page_kind), "rules"


def page_kind(url: str, pricing_url: str | None) -> str:
    if pricing_url and url.rstrip("/") == pricing_url.rstrip("/"):
        return "pricing"
    path = re.sub(r"^https?://[^/]+", "", url).strip("/")
    if not path:
        return "homepage"
    if re.search(r"changelog|release|whats-new|updates", path):
        return "changelog"
    if "docs" in path:
        return "docs"
    return "product"
