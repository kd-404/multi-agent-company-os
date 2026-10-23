"""
Shared helper for writing to the AgentActivity feed - the one place every
agent (design, marketing, warehouse, payment, ceo) reports what it just
did. This is what makes the admin "Agent Status" dashboard and the "Run
full pipeline" demo real: they read this table, they don't fake a status.
"""
import logging

from sqlalchemy.orm import Session

from .db import AgentActivity

log = logging.getLogger(__name__)

# The five agents this project currently has. Keep in sync with whichever
# ones actually call log_activity - this list drives the status dashboard.
AGENTS = ("design", "marketing", "warehouse", "payment", "ceo")


def log_activity(
    db: Session, agent: str, status: str, message: str, design_id: int | None = None
) -> AgentActivity:
    entry = AgentActivity(agent=agent, status=status, message=message, design_id=design_id)
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
        "created_at": a.created_at.isoformat(),
    }
