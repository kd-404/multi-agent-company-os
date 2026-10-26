"""
Evaluation layer for the Design agent pipeline - the lean, honest stand-in
for what a Foundry Evaluation SDK + Application Insights setup would give
a client: every pipeline run is scored on real signals (not just "did it
crash"), logged per-run, and queryable as a trend over iterations, not
just a snapshot of the latest run.

Three things get scored per design-generation attempt, win or lose:
  1. success/failure PER STAGE (trend_research, image_generation,
     vision_tagging) - not just "the whole pipeline worked," because a
     Vision failure is recoverable (design still saves, untagged) while a
     trend-research or image-gen failure is not, and a dashboard that
     collapses both into one number hides that distinction from a client.
  2. LATENCY per stage - the slowest/most expensive call
     (image_generation) is exactly the one worth watching for drift.
  3. a RELEVANCE score (0-100) - a deliberately simple, explainable stand-in
     for a Foundry "groundedness" evaluator: how much do the Vision tags on
     the FINISHED image actually overlap with the words in the trend brief
     that was supposed to produce it? A pipeline that's technically
     succeeding (no errors, image saved) but drifting away from its own
     research brief is a real failure mode a client should be able to see
     on a dashboard - this metric is what would catch that, even though
     every individual call returned 200.

Why not call Foundry's real evaluator library? This Foundry account has
one general-purpose agent and one image deployment confirmed working
(see project docs) - provisioning a separate Evaluation resource is a real
Azure dependency this project doesn't have yet. This metric is designed to
be swapped for a real Foundry evaluator call later with no change to the
storage/dashboard layer: same (stage, metric, value) shape either way.
"""
import re
import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from .db import EvalMetric, Design

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with",
    "is", "are", "this", "that", "it", "as", "by", "at", "from", "be",
    "its", "their", "has", "have", "into", "more", "most", "very",
}


def next_run_seq(db: Session) -> int:
    """
    1-based sequence number for the generation attempt about to start,
    independent of success/failure - so "performance over N iterations"
    has a stable, gapless x-axis even across failed runs. Backed by how
    many "overall" rows already exist (each generation attempt writes
    exactly one), not by Design.id, since a failed run never creates a
    Design row at all.
    """
    count = db.query(EvalMetric).filter(EvalMetric.stage == "overall").count()
    return count + 1


def record_metric(db: Session, run_seq: int, stage: str, metric: str, value: int, design_id: int | None = None):
    row = EvalMetric(design_id=design_id, run_seq=run_seq, stage=stage, metric=metric, value=int(value))
    db.add(row)
    db.commit()


@contextmanager
def timed_stage(db: Session, run_seq: int, stage: str, design_id: int | None = None):
    """
    Wraps one pipeline stage: records latency_ms and success (1/0)
    regardless of outcome, then re-raises any exception so the caller's
    own try/except (which already handles the user-facing error message)
    is unaffected - this is pure instrumentation, never changes control flow.
    """
    start = time.monotonic()
    try:
        yield
    except Exception:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        record_metric(db, run_seq, stage, "latency_ms", elapsed_ms, design_id)
        record_metric(db, run_seq, stage, "success", 0, design_id)
        raise
    else:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        record_metric(db, run_seq, stage, "latency_ms", elapsed_ms, design_id)
        record_metric(db, run_seq, stage, "success", 1, design_id)


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def relevance_score(trend_summary: str, vision_tags: list[str]) -> int:
    """
    0-100: what fraction of the Vision tags on the finished image are
    actually grounded in words from the trend brief that was supposed to
    produce it. No tags at all (Vision failed) scores 0, not skipped -
    an ungrounded design should pull the trend line down, not be invisible
    to it.
    """
    if not vision_tags:
        return 0
    brief_words = _keywords(trend_summary)
    if not brief_words:
        return 0
    matched = 0
    for tag in vision_tags:
        tag_words = _keywords(tag)
        if tag_words & brief_words:
            matched += 1
    return round(100 * matched / len(vision_tags))


def summarize(db: Session, last_n: int = 30) -> dict:
    """
    Dashboard payload: per-stage success rate + average latency over the
    last `last_n` runs, plus the overall relevance-score trend as a plain
    list the frontend draws as a sparkline - "performance improving over
    iterations," the exact shape a client-facing eval dashboard needs,
    without needing a charting library dependency.
    """
    max_seq = db.query(EvalMetric.run_seq).order_by(EvalMetric.run_seq.desc()).first()
    if not max_seq:
        return {"runs": 0, "stages": {}, "relevance_trend": []}
    latest_seq = max_seq[0]
    window_start = max(1, latest_seq - last_n + 1)

    rows = (
        db.query(EvalMetric)
        .filter(EvalMetric.run_seq >= window_start, EvalMetric.run_seq <= latest_seq)
        .all()
    )

    stages: dict[str, dict] = {}
    relevance_by_seq: dict[int, int] = {}

    for r in rows:
        if r.stage == "overall" and r.metric == "relevance_score":
            relevance_by_seq[r.run_seq] = r.value
            continue
        bucket = stages.setdefault(r.stage, {"successes": 0, "attempts": 0, "latencies": []})
        if r.metric == "success":
            bucket["attempts"] += 1
            bucket["successes"] += r.value
        elif r.metric == "latency_ms":
            bucket["latencies"].append(r.value)

    stage_summary = {}
    for stage, b in stages.items():
        avg_latency = round(sum(b["latencies"]) / len(b["latencies"])) if b["latencies"] else 0
        success_rate = round(100 * b["successes"] / b["attempts"]) if b["attempts"] else 0
        stage_summary[stage] = {
            "success_rate_pct": success_rate,
            "avg_latency_ms": avg_latency,
            "attempts": b["attempts"],
        }

    relevance_trend = [
        {"run_seq": seq, "score": relevance_by_seq[seq]}
        for seq in sorted(relevance_by_seq)
    ]

    return {
        "runs": latest_seq,
        "stages": stage_summary,
        "relevance_trend": relevance_trend,
    }
