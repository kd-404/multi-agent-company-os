from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db, User
from ..auth import hash_password, verify_password, get_current_user

router = APIRouter()


@router.post("/api/register")
def register(
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),  # only ever "admin" if an existing admin creates it — see admin_routes
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    # Public self-registration is always "user" — admins are created separately
    # by an existing admin, never by this open endpoint.
    user = User(email=email, hashed_password=hash_password(password), role="user")
    db.add(user)
    db.commit()
    return {"status": "ok", "message": "Account created. Please log in."}


@router.post("/api/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    return {"status": "ok", "role": user.role}


@router.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@router.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "role": user.role}
