from fastapi import Request, HTTPException, Depends
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import get_db, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Reads the signed session cookie (set at login) and loads the user."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Session invalid")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


# ---------- Role-based access control ----------
# One place that says what each role may do. "admin" can do everything ("*");
# "support" can work the customer-support queue and look at stock/orders but
# not generate designs, see the CEO assistant or manage users; "user" is a
# customer (storefront only). Routes ask for a named permission instead of
# hard-coding role names, so adding a role later is a one-line change here.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "support": {"tickets", "stock_view", "orders_view"},
    "user": set(),
}
VALID_ROLES = tuple(ROLE_PERMISSIONS)


def permissions_for(role: str) -> list[str]:
    perms = ROLE_PERMISSIONS.get(role, set())
    return ["*"] if "*" in perms else sorted(perms)


def has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or permission in perms


def require_permission(permission: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status_code=403, detail="You don't have access to this")
        return user
    return _dep


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Like get_current_user but returns None for signed-out visitors
    (the public shop assistant works without an account)."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()
