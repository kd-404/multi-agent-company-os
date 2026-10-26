"""Agent Floor: registry integrity, step() logging, and admin-only access."""
import pytest

from app.agent_log import step
from app.agent_registry import EDGES, HOPS, LANES, NODES, PLACES, node_ids
from app.db import AgentActivity, SessionLocal


def _lane_ids():
    return {l["id"] if isinstance(l, dict) else l[0] for l in LANES}


def _nid(n):
    return n["id"] if isinstance(n, dict) else n[0]


def test_registry_integrity():
    ids = node_ids()
    assert len(ids) == len(set(ids)) and len(ids) >= 25
    lanes = _lane_ids()
    for n in NODES:
        assert n["lane"] in lanes
        assert n["kind"] in ("ai", "tool", "rule", "human")
    for e in EDGES:
        f, t = (e["from"], e["to"]) if isinstance(e, dict) else (e[0], e[1])
        assert f in ids and t in ids
    for h in HOPS:
        assert h["from"] in PLACES and h["to"] in PLACES
        assert all(n in ids for n in h["nodes"])


def test_step_writes_start_then_ok():
    db = SessionLocal()
    try:
        with step(db, "design", "trend_scout", "Searching", run_id="t-1") as st:
            st.done = "Found it"
        rows = db.query(AgentActivity).filter(AgentActivity.run_id == "t-1").order_by(AgentActivity.id).all()
        assert [r.status for r in rows] == ["start", "ok"]
        assert rows[1].message == "Found it" and rows[1].duration_ms is not None
    finally:
        db.close()


def test_step_logs_error_and_reraises():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            with step(db, "design", "image_gen", "Painting", run_id="t-2"):
                raise ValueError("boom")
        last = db.query(AgentActivity).filter(AgentActivity.run_id == "t-2").order_by(AgentActivity.id.desc()).first()
        assert last.status == "error" and "boom" in last.message
    finally:
        db.close()


@pytest.mark.parametrize("path", ["/api/admin/floor/registry", "/api/admin/floor/state"])
def test_floor_api_rejects_customers(user_client, path):
    assert user_client.get(path).status_code == 403


def test_floor_state_for_admin(admin_client):
    reg = admin_client.get("/api/admin/floor/registry").json()
    assert reg["nodes"] and reg["places"]
    st = admin_client.get("/api/admin/floor/state").json()
    assert set(st) >= {"nodes", "events", "stats"}
    assert "working" in st["stats"]
