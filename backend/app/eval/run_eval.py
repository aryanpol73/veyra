"""Run the leakage-safe backtest and store the metrics.

    python -m app.eval.run_eval --mode masked        # names/products masked in every prompt (default)
    python -m app.eval.run_eval --mode none          # unmasked: flagged "possibly contaminated"
    python -m app.eval.run_eval --mode post_cutoff   # only events after the model's training cutoff
    python -m app.eval.run_eval --synthetic          # also run the synthetic injection test (labelled synthetic)

Each run uses a FRESH SQLite file under data/eval/, so the live database is never touched by replay.
Results are written to eval_runs / eval_events in the live database for the Evaluation page.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# gpt-oss (Groq default) training-data cutoff per its model card: June 2024. Other models: set MODEL_CUTOFF.
MODEL_CUTOFF = date.fromisoformat(os.environ.get("MODEL_CUTOFF", "2024-06-01"))
REPLAY_START = datetime(2026, 5, 1, tzinfo=timezone.utc)
REPLAY_END = datetime(2026, 11, 18, tzinfo=timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["masked", "none", "post_cutoff"], default="masked")
    ap.add_argument("--start", default=REPLAY_START.date().isoformat())
    ap.add_argument("--end", default=REPLAY_END.date().isoformat())
    ap.add_argument("--no-agents", action="store_true", help="ingest only (no LLM): checks the pipeline")
    ap.add_argument("--synthetic", action="store_true", help="also run the synthetic injection test")
    ap.add_argument("--classify", choices=["rules", "llm"], default="rules",
                    help="signal classification in replay: deterministic rules (default; saves ~45%% of tokens and removes "
                         "a contamination channel) or the LLM classifier the live system uses")
    ap.add_argument("--score-only", metavar="REPLAY_DB", help="score an existing replay DB (e.g. an interrupted run) "
                    "without re-running the replay; tokens are read from its agent_runs")
    a = ap.parse_args()

    # Point the app at a fresh replay DB BEFORE importing anything that creates the engine.
    from app.config import DATA_DIR  # config import does not create an engine

    live_db_url = os.environ.get("DB_URL") or f"sqlite:///{(DATA_DIR / 'veyra.db').as_posix()}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    eval_dir = DATA_DIR / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    replay_db = Path(a.score_only).resolve() if a.score_only else eval_dir / f"replay_{a.mode}_{stamp}.db"
    if a.score_only and not replay_db.exists():
        print(f"no such replay DB: {replay_db}")
        return 2
    os.environ["DB_URL"] = f"sqlite:///{replay_db.as_posix()}"

    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.eval import metrics as M
    from app.eval.replay import monthly_steps, run_replay

    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc)
    s = get_settings()
    s.classify_with_llm = a.classify == "llm"
    print(f"replay {a.mode}: {start:%Y-%m-%d} -> {end:%Y-%m-%d}, db {replay_db.name}, LLM "
          f"{s.llm_provider}/{s.model_strong if s.llm_configured else 'NOT CONFIGURED'}", flush=True)
    if a.score_only:
        logs = []
    else:
        logs = run_replay(monthly_steps(start, end), mode="none" if a.mode == "post_cutoff" else a.mode,
                          agents=not a.no_agents, progress=lambda m: print(m, flush=True))

    events = M.load_ground_truth()
    if a.mode == "post_cutoff":
        events = [e for e in events if e.public_date > MODEL_CUTOFF]
    with SessionLocal() as db:
        metrics = M.evaluate(db, events, (start, end))
        from sqlalchemy import select as _select

        from app.db.models import AgentRun

        failed = db.execute(_select(AgentRun.kind, AgentRun.error).where(AgentRun.error.is_not(None))).all()
        from sqlalchemy import func as _func

        graph_tokens = db.scalar(_select(_func.sum(AgentRun.tokens_in)).where(AgentRun.kind == "agent_graph")) or 0
        steps_seen = [str(t) for t in db.scalars(_select(_func.distinct(_func.date(AgentRun.input["as_of"].as_string())))
                                                  .where(AgentRun.kind == "agent_graph"))]
    result = M.to_dict(metrics)
    result["config"].update(mode=a.mode, model_strong=s.model_strong, model_fast=s.model_fast, provider=s.llm_provider,
                            model_cutoff=MODEL_CUTOFF.isoformat(), replay_db=replay_db.name, agents=not a.no_agents,
                            possibly_contaminated=a.mode == "none", classification=a.classify,
                            llm_errors=len(failed), llm_error_kinds=sorted({k for k, _ in failed}),
                            degraded=any(k in ("strategist", "skeptic", "skeptic_verdict") for k, _ in failed),
                            steps=[l["as_of"] for l in logs] or sorted(x for x in steps_seen if x and x != "None"),
                            tokens=sum((ag.get("tokens") or 0) for l in logs for ag in l["agents"]) or graph_tokens,
                            scored_existing_db=bool(a.score_only))
    if a.synthetic:
        result["synthetic_test"] = synthetic_injection()

    _save(live_db_url, a.mode, result)
    _print(result)
    return 0


def synthetic_injection() -> dict:
    """Machinery test (NOT real-world accuracy): inject known signal patterns for a fake company and
    check the strategist + deterministic judge respond as designed. Everything is labelled synthetic."""
    from app.agents import judge
    from app.agents.strategist import run_strategist
    from app.db.models import Competitor, Hypothesis, Signal
    from app.db.session import audit_into, session_scope

    now = REPLAY_END + timedelta(days=1)
    cases = {
        "independent": [("pricing", "plan_change", "SynthCo pricing page now lists a usage-based 'Compute credits' plan", "page:1"),
                        ("pricing", "plan_change", "SynthCo docs add a 'Billing for compute credits' guide", "page:2"),
                        ("market", "news_mention", "SynthCo CFO says usage-based pricing is the company's future", "news:3")],
        "one_press_release_x3": [("market", "news_mention", "SynthCo moves to usage-based compute credits", "news:same"),
                                 ("market", "news_mention", "SynthCo shifts to usage-based compute credit billing", "news:same"),
                                 ("market", "news_mention", "Report: SynthCo adopts usage-based compute credits", "news:same")],
    }
    out = {}
    with session_scope() as db, audit_into(db):
        for name, sigs in cases.items():
            comp = Competitor(name=f"SynthCo-{name}-{datetime.now(timezone.utc):%H%M%S}", domain=f"{name.replace('_', '-')}.synthco.example", product_urls=[],
                              notes="SYNTHETIC test competitor")
            db.add(comp)
            db.flush()
            for i, (cat, typ, summary, group) in enumerate(sigs):
                db.add(Signal(competitor_id=comp.id, type=typ, category=cat, summary=summary,
                              evidence_url=f"https://{comp.domain}/{i}", observed_at=now - timedelta(days=3 - i),
                              detected_at=now, origin_group=f"{comp.id}:{group}", event_confidence=0.95, priority="high",
                              raw={"kind": "page" if group.startswith("page") else "news"}, synthetic=True))
            db.flush()
            r = run_strategist(db, comp, now)
            for hid in r["new_hypothesis_ids"]:
                h = db.get(Hypothesis, hid)
                h.synthetic = True
                judge.rescore(db, h, now, "synthetic test")
            hyps = [db.get(Hypothesis, hid) for hid in r["new_hypothesis_ids"]]
            out[name] = {"hypotheses": [{"statement": h.statement, "confidence": h.confidence} for h in hyps],
                         "max_confidence": max([h.confidence for h in hyps] or [0.0])}
    ind, dup = out["independent"]["max_confidence"], out["one_press_release_x3"]["max_confidence"]
    out["expectation"] = ("independent evidence should score clearly higher (by >= 0.05) than one press release "
                          "counted three times")
    out["margin"] = round(ind - dup, 4)
    out["passed"] = bool(dup > 0 and ind - dup >= 0.05)
    return out


def _save(live_db_url: str, mode: str, result: dict) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.models import Base, EvalEvent, EvalRun

    eng = create_engine(live_db_url)
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        run = EvalRun(config=result["config"], metrics=dict(result), contamination_mode=mode)
        db.add(run)
        db.flush()
        for e in result["events"]:
            db.add(EvalEvent(eval_run_id=run.id, competitor=e["competitor"], event_label=e["label"],
                             public_date=datetime.fromisoformat(e["public_date"]).replace(tzinfo=timezone.utc),
                             category=e["category"], detected_at=datetime.fromisoformat(e["detected_at"]) if e["detected_at"] else None,
                             lead_days=e["lead_days"], matched_hypothesis_id=e["matched_hypothesis_id"],
                             is_true_positive=e["is_true_positive"]))
        db.commit()
        print(f"saved eval_run #{run.id}", flush=True)


def _print(r: dict) -> None:
    keys = ["n_events", "n_hypotheses", "n_detected", "true_positives", "precision", "recall", "fp_rate",
            "false_alarms_per_competitor_month", "lead_median", "early_detections", "brier_hypotheses",
            "brier_predictions", "n_predictions_resolved"]
    print(json.dumps({k: r[k] for k in keys}, indent=2))
    for b in r["calibration"]:
        print(f"  calibration {b['bin']:6} n={b['n']} hits={b['hits']} observed={b['observed_rate']} wilson95={b['wilson_95']}")
    for e in r["events"]:
        print(f"  {'TP' if e['is_true_positive'] else '--'} {e['public_date']} {e['competitor']}: {e['label']} "
              f"lead={e['lead_days']} H{e['matched_hypothesis_id']}")
    if "synthetic_test" in r:
        print("  synthetic test passed:", r["synthetic_test"]["passed"])


if __name__ == "__main__":
    sys.exit(main())
