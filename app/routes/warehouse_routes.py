"""
Warehouse agent. Loomwell prints on demand - there's no physical
warehouse - so "stock" here is a simulated per-design count
(Design.virtual_stock, starts at 50) that real sales will decrement once
checkout is wired up. Until then, record_sale() is called by the
pipeline demo (and will be called for real once Payment lands).

This is a true autonomous agent, not just a numbers panel: scan() reacts
to its own state (low stock + sustained customer interest, reusing the
same 7-day search-interest signal design_routes.search_trends already
computes) and WRITES a recommendation to the shared agent feed on its
own, the same way the CEO assistant answers status questions - nobody
has to read a table and decide, the agent already flagged it.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, Design, SearchLog, User
from ..auth import require_admin
from ..agent_log import log_activity

log = logging.getLogger(__name__)
router = APIRouter()

LOW_STOCK_THRESHOLD = 10
INTEREST_WINDOW_DAYS = 7
INTEREST_THRESHOLD = 2  # same bar as design_routes.search_trends uses for "trending"


def _interest_counts(db: Session) -> dict[int, int]:
    window_start = datetime.now(timezone.utc) - timedelta(days=INTEREST_WINDOW_DAYS)
    logs = (
        db.query(SearchLog)
        .filter(SearchLog.created_at >= window_start, SearchLog.matched_design_id.isnot(None))
        .all()
    )
    counts: dict[int, int] = {}
    for entry in logs:
        counts[entry.matched_design_id] = counts.get(entry.matched_design_id, 0) + 1
    return counts


def _build_status(db: Session) -> list[dict]:
    designs = (
        db.query(Design)
        .filter(Design.status == "approved")
        .order_by(Design.created_at.desc())
        .all()
    )
    interest = _interest_counts(db)

    out = []
    for d in designs:
        count = interest.get(d.id, 0)
        low_stock = d.virtual_stock <= LOW_STOCK_THRESHOLD
        out.append({
            "id": d.id,
            "image_url": f"/api/admin/design/{d.id}/image",
            "trend_summary": d.trend_summary,
            "virtual_stock": d.virtual_stock,
            "interest_7d": count,
            "low_stock": low_stock,
            "recommend_reprint": low_stock and count >= INTEREST_THRESHOLD,
        })
    return out


@router.get("/api/admin/warehouse/status")
def warehouse_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return _build_status(db)


@router.post("/api/admin/warehouse/scan")
def warehouse_scan(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """The agent checks its own state and decides whether to speak up."""
    status_list = _build_status(db)
    flagged = [s for s in status_list if s["recommend_reprint"]]

    if flagged:
        summary = "; ".join(
            f"#{s['id']} ({s['virtual_stock']} left, {s['interest_7d']} recent searches)" for s in flagged
        )
        log_activity(db, "warehouse", "alert", f"Recommend reprinting: {summary}")
    else:
        log_activity(db, "warehouse", "ok", f"Checked {len(status_list)} approved design(s) - stock healthy.")

    return {"flagged": flagged, "checked": len(status_list)}


@router.post("/api/admin/warehouse/restock/{design_id}")
def restock(
    design_id: int,
    qty: int = Form(default=50),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")
    design.virtual_stock += max(0, qty)
    db.commit()
    log_activity(
        db, "warehouse", "ok",
        f"Restocked design #{design.id} by {qty} units (now {design.virtual_stock}).",
        design_id=design.id,
    )
    return {"id": design.id, "virtual_stock": design.virtual_stock}


def record_sale(db: Session, design_id: int, qty: int = 1):
    """
    Called once checkout is real (or, for now, by the pipeline demo) after
    an order goes through. Decrements virtual stock and lets the agent
    react immediately if that sale pushed it below the low-stock bar.
    Returns the AgentActivity entry it wrote.
    """
    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        return None
    design.virtual_stock = max(0, design.virtual_stock - qty)
    db.commit()

    if design.virtual_stock <= LOW_STOCK_THRESHOLD:
        return log_activity(
            db, "warehouse", "alert",
            f"Design #{design.id} stock low ({design.virtual_stock} left) after a sale - consider reprinting.",
            design_id=design.id,
        )
    return log_activity(
        db, "warehouse", "ok",
        f"Sale recorded for design #{design.id}, {design.virtual_stock} left.",
        design_id=design.id,
    )
