"""Customer support tickets: customers (and the shop assistant) create them;
staff with the 'tickets' permission (admin, support) work the queue."""
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, SupportTicket, User
from ..auth import get_current_user, require_permission
from ..agent_log import log_activity

router = APIRouter()


@router.post("/api/support/tickets")
def create_ticket(
    subject: str = Form(...), message: str = Form(...), design_id: int | None = Form(default=None),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    subject, message = subject.strip(), message.strip()
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Subject and message are required")
    t = SupportTicket(user_id=user.id, user_email=user.email, subject=subject[:200], message=message[:4000],
                      design_id=design_id, status="open")
    db.add(t)
    db.commit()
    log_activity(db, "support", "alert", f"Ticket #{t.id} opened: {t.subject[:70]}", node="support_desk")
    return {"status": "ok", "ticket_id": t.id}


@router.get("/api/support/tickets/mine")
def my_tickets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SupportTicket).filter(SupportTicket.user_id == user.id).order_by(SupportTicket.id.desc()).limit(50).all()
    return [_row(t) for t in rows]


@router.get("/api/staff/tickets")
def staff_tickets(
    status: str | None = None, db: Session = Depends(get_db),
    _staff: User = Depends(require_permission("tickets")),
):
    q = db.query(SupportTicket)
    if status in ("open", "resolved"):
        q = q.filter(SupportTicket.status == status)
    return [_row(t) for t in q.order_by(SupportTicket.id.desc()).limit(200).all()]


@router.post("/api/staff/tickets/{ticket_id}/resolve")
def resolve_ticket(
    ticket_id: int, db: Session = Depends(get_db),
    _staff: User = Depends(require_permission("tickets")),
):
    t = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    t.status = "resolved"
    db.commit()
    log_activity(db, "support", "ok", f"Ticket #{t.id} resolved by {_staff.email}.", node="support_desk")
    return {"status": "ok"}


def _row(t: SupportTicket) -> dict:
    return {"id": t.id, "user_email": t.user_email, "subject": t.subject, "message": t.message,
            "design_id": t.design_id, "status": t.status, "created_at": t.created_at.isoformat()}
