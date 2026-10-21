"""
Admin-only endpoints: promote/create admins, see all users. Keeping
admin-creation behind require_admin means the FIRST admin must be made
directly in the database (one-time, see README "First admin" section) —
there is deliberately no public way to self-register as admin.
"""
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, User
from ..auth import require_admin, hash_password

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
