"""
Shared pytest fixtures for the reliability/stress-test suite
(tests/test_reliability.py) - see docs/FAILURE_MODES.md for what this
suite is checking and why.

Points DATABASE_URL at a fresh temp-file SQLite DB *before* app.db (and
therefore app.main) is ever imported, since the engine is created at
module-import time from settings.DATABASE_URL - setting this in a fixture
after import would be too late. No real Azure/Tavily/Razorpay/Instagram
credentials are needed: every route that touches those is either never
exercised by these tests (we're testing auth/validation boundaries and
pure logic, not live third-party calls) or lazily constructs its client
only when called.
"""
import os
import tempfile

import pytest

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import SessionLocal, User  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_client():
    """A TestClient already logged in as an admin - register a normal
    account, promote it directly in the DB (same shortcut the real admin
    SQL-console step in README §4 takes), then log in."""
    with TestClient(app) as c:
        email = "admin-test@example.com"
        c.post("/api/register", data={"email": email, "password": "pw12345"})
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            user.role = "admin"
            db.commit()
        finally:
            db.close()
        login = c.post("/api/login", data={"email": email, "password": "pw12345"})
        assert login.status_code == 200
        yield c


@pytest.fixture()
def user_client():
    """A TestClient logged in as an ordinary (non-admin) user."""
    with TestClient(app) as c:
        email = "user-test@example.com"
        c.post("/api/register", data={"email": email, "password": "pw12345"})
        login = c.post("/api/login", data={"email": email, "password": "pw12345"})
        assert login.status_code == 200
        yield c
