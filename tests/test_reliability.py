"""
Agent-to-agent / tool-use reliability stress-test suite.

What this suite is actually checking (see docs/FAILURE_MODES.md for the
narrative writeup): that malformed input, missing auth, and references
to nonexistent records fail the way they're SUPPOSED to - a clean 4xx with
a real error message - rather than a 500, a silent no-op, or (worse) a
state change that shouldn't have happened. It deliberately does NOT call
any real third-party API (Tavily, the image model, Vision, Razorpay,
Instagram) - those are covered by app/retry.py's own retry/backoff logic,
unit-tested directly below without touching the network, and by the
*_configured() simulated-mode fallback that already exists in the routes
themselves (see payment_routes.py / marketing_routes.py docstrings).
"""
import time

import httpx
import pytest

from app.db import SessionLocal, Design
from app.retry import with_retry, RetryExhausted


# ---------- Auth boundary: every admin-only route should reject cleanly ----------

ADMIN_GET_ROUTES = [
    "/api/admin/design/list",
    "/api/admin/evals/summary",
    "/api/admin/search-trends",
    "/api/admin/mockup-templates",
]

ADMIN_POST_ROUTES = [
    "/api/admin/design/generate",
    "/api/admin/design/generate-batch",
    "/api/admin/mockup-templates/generate",
]


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_get_routes_require_login(client, path):
    resp = client.get(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_get_routes_reject_non_admin(user_client, path):
    resp = user_client.get(path)
    assert resp.status_code == 403


@pytest.mark.parametrize("path", ADMIN_POST_ROUTES)
def test_admin_post_routes_require_login(client, path):
    resp = client.post(path)
    assert resp.status_code == 401


# ---------- Malformed / out-of-range input on real endpoints ----------

def test_reassign_rejects_unknown_garment(admin_client):
    design_id = _insert_design()
    resp = admin_client.post(
        f"/api/admin/design/{design_id}/reassign",
        data={"garment": "cargo-pants", "color": "white"},
    )
    assert resp.status_code == 400
    assert "garment" in resp.json()["detail"].lower()


def test_reassign_rejects_unknown_color(admin_client):
    design_id = _insert_design()
    resp = admin_client.post(
        f"/api/admin/design/{design_id}/reassign",
        data={"garment": "tshirt", "color": "neon-pink"},
    )
    assert resp.status_code == 400
    assert "color" in resp.json()["detail"].lower()


def test_reassign_rejects_missing_fields(admin_client):
    design_id = _insert_design()
    resp = admin_client.post(f"/api/admin/design/{design_id}/reassign", data={})
    assert resp.status_code == 422  # FastAPI's own Form(...) validation, not our code


def test_reassign_nonexistent_design_is_404_not_500(admin_client):
    resp = admin_client.post(
        "/api/admin/design/999999/reassign", data={"garment": "tshirt", "color": "white"}
    )
    assert resp.status_code == 404


def test_approve_nonexistent_design_is_404_not_500(admin_client):
    resp = admin_client.post("/api/admin/design/999999/approve")
    assert resp.status_code == 404


def test_public_mockup_nonexistent_design_is_404(client):
    resp = client.get("/api/public/design/999999/mockup/front")
    assert resp.status_code == 404


def test_public_mockup_invalid_slot_fails_cleanly(client):
    design_id = _insert_design(status="approved")
    resp = client.get(f"/api/public/design/{design_id}/mockup/not-a-real-slot")
    # Whatever the exact code, an unknown slot must not 500 - it's either a
    # clean 4xx or a 404 ("no template for this combo"), never a crash.
    assert resp.status_code < 500


def test_create_order_requires_login(client):
    design_id = _insert_design(status="approved")
    resp = client.post(f"/api/public/payment/create-order/{design_id}")
    assert resp.status_code == 401


def test_create_order_rejects_unapproved_design(user_client):
    design_id = _insert_design(status="pending")  # never approved
    resp = user_client.post(f"/api/public/payment/create-order/{design_id}")
    assert resp.status_code == 404


def test_verify_payment_rejects_malformed_payload(user_client):
    resp = user_client.post("/api/public/payment/verify", json={"not": "the right shape"})
    assert resp.status_code == 422


def test_verify_payment_without_razorpay_configured_is_409_not_500(user_client):
    # No RAZORPAY_KEY_ID/SECRET set in the test env - verify should refuse
    # cleanly rather than crash trying to compute an HMAC with an empty key.
    resp = user_client.post(
        "/api/public/payment/verify",
        json={
            "razorpay_order_id": "order_fake",
            "razorpay_payment_id": "pay_fake",
            "razorpay_signature": "deadbeef",
        },
    )
    assert resp.status_code == 409


def test_register_duplicate_email_is_400_not_500(client):
    client.post("/api/register", data={"email": "dupe@example.com", "password": "pw12345"})
    resp = client.post("/api/register", data={"email": "dupe@example.com", "password": "pw12345"})
    assert resp.status_code == 400


def test_login_wrong_password_is_401_not_500(client):
    client.post("/api/register", data={"email": "wrongpw@example.com", "password": "pw12345"})
    resp = client.post("/api/login", data={"email": "wrongpw@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_login_missing_fields_is_422(client):
    resp = client.post("/api/login", data={"email": "nobody@example.com"})  # no password
    assert resp.status_code == 422


# ---------- app/retry.py: the retry/backoff logic itself ----------

def test_with_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("simulated transient network failure")
        return "ok"

    result = with_retry(flaky, label="test_flaky", retries=3, base_delay=0.01)
    assert result == "ok"
    assert attempts["n"] == 3


def test_with_retry_gives_up_and_raises_retry_exhausted():
    def always_fails():
        raise httpx.ConnectError("simulated permanent network failure")

    with pytest.raises(RetryExhausted) as exc_info:
        with_retry(always_fails, label="test_always_fails", retries=2, base_delay=0.01)
    assert exc_info.value.attempts == 3  # 1 initial + 2 retries


def test_with_retry_does_not_retry_non_retryable_errors():
    attempts = {"n": 0}

    def bad_request():
        attempts["n"] += 1
        request = httpx.Request("POST", "https://example.com")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(bad_request, label="test_bad_request", retries=3, base_delay=0.01)
    assert attempts["n"] == 1  # no retries spent on a non-retryable 400


def test_with_retry_retries_on_429():
    attempts = {"n": 0}

    def rate_limited():
        attempts["n"] += 1
        if attempts["n"] < 2:
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return "ok"

    result = with_retry(rate_limited, label="test_rate_limited", retries=2, base_delay=0.01)
    assert result == "ok"
    assert attempts["n"] == 2


# ---------- app/evaluation.py: scoring logic ----------

def test_relevance_score_with_no_tags_is_zero():
    from app.evaluation import relevance_score
    assert relevance_score("floral minimalist line art trend", []) == 0


def test_relevance_score_rewards_grounded_tags():
    from app.evaluation import relevance_score
    score = relevance_score("bold streetwear graffiti style graphic", ["graffiti", "streetwear", "bold"])
    assert score == 100


def test_relevance_score_penalizes_ungrounded_tags():
    from app.evaluation import relevance_score
    score = relevance_score("bold streetwear graffiti style graphic", ["sailboat", "mountain"])
    assert score == 0


def test_eval_metrics_round_trip_through_summarize():
    from app.evaluation import next_run_seq, record_metric, summarize

    db = SessionLocal()
    try:
        seq = next_run_seq(db)
        record_metric(db, seq, "trend_research", "latency_ms", 1200)
        record_metric(db, seq, "trend_research", "success", 1)
        record_metric(db, seq, "overall", "relevance_score", 80)
        record_metric(db, seq, "overall", "success", 1)

        summary = summarize(db)
        assert summary["runs"] >= seq
        assert "trend_research" in summary["stages"]
        assert summary["stages"]["trend_research"]["success_rate_pct"] == 100
        assert any(p["run_seq"] == seq and p["score"] == 80 for p in summary["relevance_trend"])
    finally:
        db.close()


def _insert_design(status: str = "pending") -> int:
    db = SessionLocal()
    try:
        design = Design(
            trend_query="test query",
            trend_summary="test summary",
            image_prompt="test prompt",
            image_data=b"\x89PNG\r\n\x1a\nfake",
            status=status,
            garment="tshirt",
            color="white",
        )
        db.add(design)
        db.commit()
        db.refresh(design)
        return design.id
    finally:
        db.close()
