"""
Live multi-agent status dashboard + "run the whole pipeline" demo.

GET endpoints just read the AgentActivity feed that every agent already
writes to during normal operation (design_routes, marketing_routes,
warehouse_routes, payment_routes) - this file adds no new agent logic of
its own for those.

The demo endpoint is different: it actually RUNS one real pass through
every agent, live, in order - real Tavily research, real image
generation, a real rule-based caption draft, a clearly-labeled simulated
order, and a real stock update from that simulated sale. Nothing here is
faked except the payment (which says so). Good for watching the company
"run itself" in an interview, not a background process - it only runs
when this endpoint is called.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db, AgentActivity, Design, User
from ..auth import require_admin
from ..agent_log import log_activity, activity_to_dict, AGENTS
from .design_routes import _generate_one_design
from .marketing_routes import _draft_caption
from .warehouse_routes import record_sale
from .payment_routes import simulate_order

router = APIRouter()


@router.get("/api/admin/agents/status")
def agents_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    out = []
    for agent in AGENTS:
        latest = (
            db.query(AgentActivity)
            .filter(AgentActivity.agent == agent, AgentActivity.status != "start")
            .order_by(AgentActivity.created_at.desc())
            .first()
        )
        out.append({"agent": agent, "latest": activity_to_dict(latest) if latest else None})
    return out


@router.get("/api/admin/agents/feed")
def agents_feed(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    rows = db.query(AgentActivity).filter(AgentActivity.status != "start").order_by(AgentActivity.created_at.desc()).limit(30).all()
    return [activity_to_dict(r) for r in rows]


@router.post("/api/admin/agents/run-demo")
def run_demo(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    steps = []

    steps.append(activity_to_dict(
        log_activity(db, "ceo", "ok", "Kicking off a full pipeline demo run.")
    ))

    design_result = _generate_one_design(
        "trending T-shirt graphic design patterns, colors and styles right now (pipeline demo run)",
        db,
    )
    if design_result["status"] != "ok":
        steps.append({
            "agent": "design", "status": "error",
            "message": f"Demo stopped at the design stage: {design_result.get('detail')}",
        })
        log_activity(db, "ceo", "error", "Pipeline demo stopped early - design stage failed.")
        return {"steps": steps, "ok": False}

    design_id = design_result["id"]
    steps.append({
        "agent": "design", "status": "ok",
        "message": f"Generated design #{design_id} from live trend research.",
    })

    design = db.query(Design).filter(Design.id == design_id).first()
    design.status = "approved"  # auto-approve so the demo is visible on /shop immediately
    caption, hashtags = _draft_caption(design)
    design.social_caption, design.social_hashtags = caption, hashtags
    db.commit()
    steps.append(activity_to_dict(
        log_activity(db, "marketing", "ok", f"Drafted a social caption for design #{design_id}.", design_id=design_id)
    ))

    steps.append(activity_to_dict(simulate_order(db, design_id)))

    sale_entry = record_sale(db, design_id, qty=1)
    if sale_entry:
        steps.append(activity_to_dict(sale_entry))

    steps.append(activity_to_dict(log_activity(
        db, "ceo", "ok",
        f"Pipeline run complete for design #{design_id}: researched, generated, captioned, "
        f"test-ordered, and stock updated.",
    )))

    return {"steps": steps, "ok": True, "design_id": design_id}
