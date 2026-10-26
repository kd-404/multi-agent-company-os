"""
Admin-only endpoints: promote/create admins, see all users. Keeping
admin-creation behind require_admin means the FIRST admin must be made
directly in the database (one-time, see README "First admin" section) —
there is deliberately no public way to self-register as admin.
"""
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, User
from ..auth import require_admin, hash_password, VALID_ROLES

router = APIRouter()


@router.get("/api/admin/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    users = db.query(User).all()
    return [{"id": u.id, "email": u.email, "role": u.role} for u in users]


@router.post("/api/admin/create-admin")
def create_admin(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, hashed_password=hash_password(password), role="admin")
    db.add(user)
    db.commit()
    return {"status": "ok"}


@router.post("/api/admin/users/{user_id}/role")
def set_user_role(
    user_id: int,
    role: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """RBAC: promote a customer to support staff (or back). An admin can't
    change their own role, so the last admin can't lock everyone out."""
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(VALID_ROLES)}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You can't change your own role")
    user.role = role
    db.commit()
    return {"status": "ok", "id": user.id, "role": user.role}
