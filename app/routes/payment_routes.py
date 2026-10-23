"""
Payment agent - placeholder until Razorpay is wired into real checkout
(that's the frontend-phase work: cart -> Razorpay test mode -> this
agent). It exists now so the live "Agent Status" dashboard and the
"Run full pipeline" demo have a real fifth agent to show, without ever
claiming money moved. Every entry it writes has status="simulated" and
says so in the message - never dressed up as a real transaction.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db, User
from ..auth import require_admin
from ..agent_log import log_activity, AgentActivity

router = APIRouter()


def simulate_order(db: Session, design_id: int, amount_inr: int = 899) -> AgentActivity:
    """Returns the AgentActivity entry it wrote."""
    return log_activity(
        db, "payment", "simulated",
        f"Simulated a test order for design #{design_id}: ₹{amount_inr} "
        f"(Razorpay isn't wired up yet - no real charge happened).",
        design_id=design_id,
    )


@router.post("/api/admin/payment/simulate/{design_id}")
def simulate_order_endpoint(
    design_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    entry = simulate_order(db, design_id)
    return {"design_id": design_id, "status": entry.status, "message": entry.message}
