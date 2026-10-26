"""
Shared helper for writing to the AgentActivity feed - the one place every
agent (design, marketing, warehouse, payment, ceo) reports what it just
did. This is what makes the admin "Agent Status" dashboard and the "Run
full pipeline" demo real: they read this table, they don't fake a status.
"""
import logging
import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from .db import AgentActivity

log = logging.getLogger(__name__)

# The five agents this project currently has. Keep in sync with whichever
# ones actually call log_activity - this list drives the status dashboard.
AGENTS = ("design", "marketing", "warehouse", "payment", "ceo")


def _default_node(agent: str, message: str) -> str | None:
    """Older call sites don't pass node=; map them to the right graph node."""
    m = message.lower()
    if agent in ("warehouse", "payment", "ceo"):
        return agent
    if agent == "marketing":
        if "caption" in m:
            return "caption_writer"
        if "instagram" in m:
            return "instagram"
        return "trend_radar"
    return None


def log_activity(
    db: Session, agent: str, status: str, message: str, design_id: int | None = None,
    node: str | None = None, run_id: str | None = None, duration_ms: int | None = None,
) -> AgentActivity:
    node = node or _default_node(agent, message)
    entry = AgentActivity(agent=agent, status=status, message=message, design_id=design_id,
                          node=node, run_id=run_id, duration_ms=duration_ms)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log.info("[%s] %s: %s", agent, status, message)
    return entry


def activity_to_dict(a: AgentActivity) -> dict:
    return {
        "id": a.id,
        "agent": a.agent,
        "status": a.status,
        "message": a.message,
        "design_id": a.design_id,
        "node": a.node,
        "run_id": a.run_id,
        "duration_ms": a.duration_ms,
        "created_at": a.created_at.isoformat(),
    }


def new_run_id(prefix: str = "run") -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Step:
    """Handle yielded by step(): set .done to change the finishing message."""
    def __init__(self, label: str):
        self.label = label
        self.done: str | None = None
        self.design_id: int | None = None


@contextmanager
def step(db: Session, agent: str, node: str, label: str, run_id: str | None = None, design_id: int | None = None):
    """
    Wraps one unit of agent work for the Agent Floor: writes a "start" row
    (the node shows as WORKING while only that row exists), then an "ok" or
    "error" row with the elapsed time. Never changes control flow - errors
    are re-raised exactly as before, and a failure to LOG is swallowed so
    observability can never break a real request.
    """
    st = Step(label)
    st.design_id = design_id
    t0 = time.monotonic()
    try:
        log_activity(db, agent, "start", label, design_id=design_id, node=node, run_id=run_id)
    except Exception:
        log.exception("agent_log: could not write start row")
    try:
        yield st
    except Exception as e:
        try:
            log_activity(db, agent, "error", f"{label} failed: {type(e).__name__}: {e}", design_id=st.design_id,
                         node=node, run_id=run_id, duration_ms=int((time.monotonic() - t0) * 1000))
        except Exception:
            log.exception("agent_log: could not write error row")
        raise
    else:
        try:
            log_activity(db, agent, "ok", st.done or label, design_id=st.design_id, node=node, run_id=run_id,
                         duration_ms=int((time.monotonic() - t0) * 1000))
        except Exception:
            log.exception("agent_log: could not write ok row")
