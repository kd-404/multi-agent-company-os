"""
Agent Floor API: the static map of agents (agent_registry.py) plus LIVE
state computed from the agent_activities table. Nothing here is invented -
a node is "working" only while its latest row is a `start` row, it is
"waiting" only if a human genuinely has something to do, and a node with no
activity is shown as idle (or planned, if the agent isn't built).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, AgentActivity, Design, SupportTicket, User
from ..auth import require_admin
from ..agent_registry import NODES, registry_payload

router = APIRouter()

WORKING_TTL_S = 300      # a start row older than this with no finish is treated as stalled, not working
FRESH_S = 90             # "just finished" window
ALWAYS_ON = {"rbac", "retry", "evals", "storefront", "prompt_writer", "payment"}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _event(a: AgentActivity, names: dict) -> dict:
    return {
        "id": a.id, "node": a.node, "name": names.get(a.node, a.agent.title()), "agent": a.agent,
        "status": a.status, "message": a.message, "design_id": a.design_id, "run_id": a.run_id,
        "duration_ms": a.duration_ms, "at": _utc(a.created_at).isoformat(),
    }


@router.get("/api/admin/floor/registry")
def floor_registry(_admin: User = Depends(require_admin)):
    return registry_payload()


@router.get("/api/admin/floor/state")
def floor_state(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    names = {n["id"]: n["name"] for n in NODES}
    kinds = {n["id"]: n["kind"] for n in NODES}

    pending_designs = db.query(Design).filter(Design.status == "pending").count()
    open_tickets = db.query(SupportTicket).filter(SupportTicket.status == "open").count()

    recent = db.query(AgentActivity).filter(AgentActivity.created_at >= day_ago).all()
    nodes = {}
    for n in NODES:
        rows = [r for r in recent if r.node == n["id"]]
        latest_any = db.query(AgentActivity).filter(AgentActivity.node == n["id"]).order_by(AgentActivity.id.desc()).first()
        durations = [r.duration_ms for r in rows if r.duration_ms and r.status == "ok"]
        done = [r for r in rows if r.status in ("ok", "alert", "simulated")]
        errs = [r for r in rows if r.status == "error"]
        st = "idle"
        msg, at = None, None
        if latest_any:
            at = _utc(latest_any.created_at)
            age = (now - at).total_seconds()
            msg = latest_any.message
            if latest_any.status == "start" and age < WORKING_TTL_S:
                st = "working"
            elif latest_any.status == "error" and age < 3600:
                st = "error"
            elif age < FRESH_S:
                st = "finished"
            else:
                st = "ok"
        if not n["built"]:
            st = "planned"
        elif n["id"] == "human_approval" and pending_designs:
            st, msg = "waiting", f"{pending_designs} design(s) waiting for your approval"
        elif n["id"] == "support_desk" and open_tickets:
            st, msg = "waiting", f"{open_tickets} open ticket(s)"
        elif st == "idle" and n["id"] in ALWAYS_ON:
            st = "ok"
        nodes[n["id"]] = {
            "status": st, "message": msg, "at": at.isoformat() if at else None,
            "runs_24h": len(done), "errors_24h": len(errs),
            "avg_ms": int(sum(durations) / len(durations)) if durations else None,
        }

    events = db.query(AgentActivity).order_by(AgentActivity.id.desc()).limit(80).all()

    # Latest pipeline run (design or photo) for the side panel's step-by-step view
    last_run = db.query(AgentActivity).filter(AgentActivity.run_id.isnot(None)).order_by(AgentActivity.id.desc()).first()
    run = None
    if last_run:
        rows = db.query(AgentActivity).filter(AgentActivity.run_id == last_run.run_id).order_by(AgentActivity.id.asc()).all()
        steps = []
        for r in rows:
            if r.status == "start":
                steps.append({"node": r.node, "name": names.get(r.node, r.agent), "label": r.message, "status": "working",
                              "duration_ms": None, "at": _utc(r.created_at).isoformat()})
            elif steps and steps[-1]["node"] == r.node and steps[-1]["status"] == "working":
                steps[-1].update(status="error" if r.status == "error" else "done", label=r.message, duration_ms=r.duration_ms)
            elif r.node:
                steps.append({"node": r.node, "name": names.get(r.node, r.agent), "label": r.message,
                              "status": "wait" if r.status == "wait" else "error" if r.status == "error" else "done",
                              "duration_ms": r.duration_ms, "at": _utc(r.created_at).isoformat()})
        design = None
        did = next((r.design_id for r in reversed(rows) if r.design_id), None)
        if did:
            d = db.query(Design).filter(Design.id == did).first()
            if d:
                design = {"id": d.id, "status": d.status, "garment": d.garment, "color": d.color,
                          "tags": [t for t in (d.vision_tags or "").split(",") if t][:6],
                          "summary": d.trend_summary[:220], "image_url": f"/api/admin/design/{d.id}/image"}
        run = {"run_id": last_run.run_id, "kind": last_run.run_id.split("-")[0], "steps": steps, "design": design,
               "running": any(s["status"] == "working" for s in steps),
               "title": next((r.message for r in rows if r.node is None and r.status == "ok"), "Pipeline run")}

    ai_calls = sum(1 for r in recent if kinds.get(r.node) == "ai" and r.status == "ok")
    stats = {
        "working": sum(1 for v in nodes.values() if v["status"] == "working"),
        "needs_you": pending_designs + open_tickets,
        "model_calls_24h": ai_calls,
        "errors_24h": sum(1 for r in recent if r.status == "error"),
        "runs_24h": len({r.run_id for r in recent if r.run_id}),
        "image_model": settings.FOUNDRY_IMAGE_DEPLOYMENT,
        "pending_designs": pending_designs, "open_tickets": open_tickets,
    }
    return {"now": now.isoformat(), "nodes": nodes, "events": [_event(e, names) for e in events], "run": run, "stats": stats}
