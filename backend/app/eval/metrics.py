"""Evaluation metrics computed from a replay database + hand-labelled ground truth.

Definitions (also shown on the Evaluation page):
  detection     a hypothesis "detects" at the first belief update where confidence >= THRESHOLD
  match         same competitor AND >= 1 ground-truth keyword ("a+b" = both) appears in the hypothesis statement
                (keywords were written into ground_truth.yaml BEFORE the replay was run)
  true positive a ground-truth event matched by a hypothesis detected no later than public_date + GRACE_DAYS
  lead time     public_date - detection date (positive = Veyra was early; negative = reacted after)
  precision     detected hypotheses that match some event / all detected hypotheses
  recall        events with a true positive / events inside the replay window
  FP rate       detected hypotheses matching no event / all detected hypotheses (= 1 - precision)
  Brier         mean (confidence - outcome)^2 for hypotheses (final confidence vs matched) and for resolved predictions
  calibration   3 bins (<0.4, 0.4-0.7, >=0.7) with Wilson 95% intervals; n is tiny, so intervals are wide
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BeliefHistory, Competitor, Hypothesis, Prediction

THRESHOLD = 0.5
GRACE_DAYS = 31  # replay steps are monthly: a hypothesis can only form at the step after an announcement
GROUND_TRUTH = Path(__file__).with_name("ground_truth.yaml")
BINS = [("low", 0.0, 0.4), ("medium", 0.4, 0.7), ("high", 0.7, 1.01)]


@dataclass
class GTEvent:
    id: str
    competitor: str
    label: str
    category: str
    public_date: date
    source_url: str
    keywords: list[str]
    notes: str = ""


@dataclass
class EventResult:
    id: str
    competitor: str
    label: str
    category: str
    public_date: str
    source_url: str
    detected_at: str | None = None
    lead_days: float | None = None
    matched_hypothesis_id: int | None = None
    matched_statement: str | None = None
    is_true_positive: bool = False


@dataclass
class Metrics:
    n_events: int
    n_hypotheses: int
    n_detected: int
    true_positives: int
    precision: float | None
    recall: float | None
    fp_rate: float | None
    false_alarms_per_competitor_month: float | None
    lead_days: list[float]
    lead_median: float | None
    early_detections: int
    brier_hypotheses: float | None
    brier_predictions: float | None
    n_predictions_resolved: int
    calibration: list[dict]
    # secondary view, added after the first (degraded) run showed decay penalising hypotheses that WERE right
    # earlier in the window: same bins on each hypothesis's peak confidence. The pre-declared metric stays primary.
    brier_hypotheses_peak: float | None = None
    calibration_peak: list[dict] = field(default_factory=list)
    events: list[EventResult] = field(default_factory=list)
    hypotheses: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)


def load_ground_truth(path: Path = GROUND_TRUTH) -> list[GTEvent]:
    data = yaml.safe_load(path.read_text("utf-8"))
    return [GTEvent(**{**e, "public_date": e["public_date"] if isinstance(e["public_date"], date)
                       else date.fromisoformat(str(e["public_date"]))}) for e in data["events"]]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def matches(statement: str, ev: GTEvent) -> bool:
    """Any keyword alternative matches; an alternative "a+b" needs every part present."""
    s = statement.lower()
    return any(all(part.strip().lower() in s for part in k.split("+")) for k in ev.keywords)


def evaluate(db: Session, events: list[GTEvent], window: tuple[datetime, datetime], *,
             threshold: float = THRESHOLD, grace_days: int = GRACE_DAYS) -> Metrics:
    start, end = window
    in_window = [e for e in events if start <= _day(e.public_date) <= end]
    # synthetic test data lives in the same replay DB: never score it as real
    comps = {c.id: c.name for c in db.scalars(select(Competitor)) if not (c.notes or "").startswith("SYNTHETIC")}
    hyps = [h for h in db.scalars(select(Hypothesis)) if not h.synthetic and h.competitor_id in comps]
    hist: dict[int, list[BeliefHistory]] = {}
    for b in db.scalars(select(BeliefHistory).order_by(BeliefHistory.ts, BeliefHistory.id)):
        hist.setdefault(b.hypothesis_id, []).append(b)

    info = []
    for h in hyps:
        rows = hist.get(h.id, [])
        det = next((_aware(b.ts) for b in rows if b.confidence >= threshold), None)
        info.append({"id": h.id, "competitor": comps[h.competitor_id], "statement": h.statement, "category": h.category,
                     "final_confidence": h.confidence, "max_confidence": max([b.confidence for b in rows] or [h.confidence]),
                     "status": h.status, "detected_at": det, "matched_event": None})

    results, leads = [], []
    for ev in in_window:
        r = EventResult(ev.id, ev.competitor, ev.label, ev.category, ev.public_date.isoformat(), ev.source_url)
        deadline = _day(ev.public_date) + timedelta(days=grace_days)
        cands = [i for i in info if i["competitor"] == ev.competitor and i["detected_at"] and i["detected_at"] <= deadline
                 and matches(i["statement"], ev)]
        if cands:
            best = min(cands, key=lambda i: i["detected_at"])
            r.detected_at = best["detected_at"].isoformat()
            r.lead_days = round((_day(ev.public_date) - best["detected_at"]).total_seconds() / 86400, 1)
            r.matched_hypothesis_id, r.matched_statement, r.is_true_positive = best["id"], best["statement"], True
            leads.append(r.lead_days)
            for i in cands:
                i["matched_event"] = i["matched_event"] or ev.id
        results.append(r)

    detected = [i for i in info if i["detected_at"]]
    matched_det = [i for i in detected if i["matched_event"]]
    months = max(1.0, (end - start).days / 30.4)
    n_comps = len(comps) or 1

    # hypothesis-level Brier + calibration: final confidence vs "matched a real event" (primary, pre-declared)
    ys = [(i["final_confidence"], 1 if i["matched_event"] else 0) for i in info]
    ys_peak = [(i["max_confidence"], 1 if i["matched_event"] else 0) for i in info]
    brier_h = statistics.mean((p - y) ** 2 for p, y in ys) if ys else None
    brier_peak = statistics.mean((p - y) ** 2 for p, y in ys_peak) if ys_peak else None
    calib, calib_peak = _bins(ys), _bins(ys_peak)

    real_ids = {h.id for h in hyps}
    preds = [p for p in db.scalars(select(Prediction)) if p.outcome in ("hit", "miss") and p.hypothesis_id in real_ids]
    brier_p = statistics.mean((p.confidence_at_creation - (1 if p.outcome == "hit" else 0)) ** 2 for p in preds) if preds else None

    return Metrics(
        n_events=len(in_window), n_hypotheses=len(info), n_detected=len(detected), true_positives=sum(r.is_true_positive for r in results),
        precision=round(len(matched_det) / len(detected), 3) if detected else None,
        recall=round(sum(r.is_true_positive for r in results) / len(in_window), 3) if in_window else None,
        fp_rate=round(1 - len(matched_det) / len(detected), 3) if detected else None,
        false_alarms_per_competitor_month=round((len(detected) - len(matched_det)) / (n_comps * months), 3) if detected else None,
        lead_days=leads, lead_median=statistics.median(leads) if leads else None, early_detections=sum(1 for x in leads if x > 0),
        brier_hypotheses=round(brier_h, 4) if brier_h is not None else None,
        brier_predictions=round(brier_p, 4) if brier_p is not None else None, n_predictions_resolved=len(preds),
        calibration=calib, brier_hypotheses_peak=round(brier_peak, 4) if brier_peak is not None else None,
        calibration_peak=calib_peak, events=results,
        hypotheses=[{**i, "detected_at": i["detected_at"].isoformat() if i["detected_at"] else None} for i in info],
        config={"threshold": threshold, "grace_days": grace_days, "window": [start.isoformat(), end.isoformat()],
                "events_total": len(events), "events_in_window": len(in_window)},
    )


def _bins(ys: list[tuple[float, int]]) -> list[dict]:
    out = []
    for name, lo, hi in BINS:
        members = [(p, y) for p, y in ys if lo <= p < hi]
        k, n = sum(y for _, y in members), len(members)
        ci = wilson(k, n)
        out.append({"bin": name, "range": [lo, min(hi, 1.0)], "n": n, "hits": k,
                    "mean_confidence": round(statistics.mean(p for p, _ in members), 3) if members else None,
                    "observed_rate": round(k / n, 3) if n else None,
                    "wilson_95": [round(ci[0], 3), round(ci[1], 3)] if ci else None})
    return out


def to_dict(m: Metrics) -> dict:
    return asdict(m)
