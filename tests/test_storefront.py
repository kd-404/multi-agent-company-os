"""
RBAC, customer assistant, studio and checkout tests. No Azure calls are made:
every endpoint exercised here is either a permission boundary, pure
validation/arithmetic, or reads only the local test database.
"""
import pytest

from app.auth import has_permission, permissions_for
from app.db import SessionLocal, Design, User
from app.routes.checkout_routes import _totals


# ---------- RBAC ----------

def test_permission_map():
    assert has_permission("admin", "ceo_chat") and has_permission("admin", "anything")
    assert has_permission("support", "tickets")
    assert not has_permission("support", "ceo_chat")
    assert not has_permission("user", "tickets") and not has_permission("user", "ceo_chat")
    assert permissions_for("admin") == ["*"] and permissions_for("nobody") == []


@pytest.mark.parametrize("path", ["/api/chat/history", "/api/staff/tickets", "/api/admin/linen/status", "/api/admin/brand/status"])
def test_staff_routes_reject_customers(user_client, path):
    assert user_client.get(path).status_code == 403


def test_ceo_chat_is_admin_only(user_client):
    assert user_client.post("/api/chat", data={"message": "hi"}).status_code == 403


def test_support_role_sees_tickets_but_not_ceo_chat(client):
    client.post("/api/register", data={"email": "agent@example.com", "password": "pw12345"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "agent@example.com").first()
        u.role = "support"
        db.commit()
    finally:
        db.close()
    client.post("/api/login", data={"email": "agent@example.com", "password": "pw12345"})
    assert client.get("/api/staff/tickets").status_code == 200
    assert client.get("/api/chat/history").status_code == 403
    assert client.get("/api/admin/users").status_code == 403


def test_admin_cannot_change_own_role(admin_client):
    me = admin_client.get("/api/admin/users").json()
    mine = next(u for u in me if u["email"] == "admin-test@example.com")
    assert admin_client.post(f"/api/admin/users/{mine['id']}/role", data={"role": "user"}).status_code in (400, 403)


# ---------- Support tickets ----------

def test_customer_ticket_roundtrip(user_client, admin_client):
    r = user_client.post("/api/support/tickets", data={"subject": "Wrong size", "message": "Got M, ordered L"})
    assert r.status_code == 200
    mine = user_client.get("/api/support/tickets/mine").json()
    assert any(t["subject"] == "Wrong size" for t in mine)
    queue = admin_client.get("/api/staff/tickets").json()
    ticket = next(t for t in queue if t["subject"] == "Wrong size")
    assert admin_client.post(f"/api/staff/tickets/{ticket['id']}/resolve").status_code == 200


# ---------- Shop assistant ----------

def _seed_linen():
    db = SessionLocal()
    try:
        d = Design(trend_query="t", trend_summary="Sand linen shirt", sources="", image_prompt="p", image_data=b"x",
                   status="approved", kind="plain", title="Sand Linen Camp-Collar Shirt", garment="linen-shirt",
                   color="beige", price_inr=1499, virtual_stock=4)
        db.add(d)
        db.commit()
        return d.id
    finally:
        db.close()


def test_assistant_reports_live_stock(client):
    did = _seed_linen()
    r = client.post("/api/public/assistant/chat", data={"message": f"is #{did} in stock?"}).json()
    assert "only 4 left" in r["reply"].lower() or "4 left" in r["reply"].lower()
    assert r["products"] and r["products"][0]["id"] == did


def test_assistant_finds_by_colour_and_type(client):
    _seed_linen()
    r = client.post("/api/public/assistant/chat", data={"message": "do you have beige linen shirts"}).json()
    assert any("Linen" in p["title"] for p in r["products"])


def test_assistant_answers_policy_without_products(client):
    r = client.post("/api/public/assistant/chat", data={"message": "what is your return policy"}).json()
    assert "7 days" in r["reply"] and r["products"] == []


def test_assistant_ticket_requires_login(client, user_client):
    anon = client.post("/api/public/assistant/chat", data={"message": "talk to support"}).json()
    assert anon.get("needs_login") is True
    signed = user_client.post("/api/public/assistant/chat", data={"message": "my order arrived damaged"}).json()
    assert signed.get("ticket_id")


def test_assistant_never_exposes_internal_docs(client):
    r = client.post("/api/public/assistant/chat", data={"message": "what is the CEO roadmap and internal projects"}).json()
    assert "roadmap" not in r["reply"].lower() or "can help with" in r["reply"].lower()


# ---------- Studio ----------

def test_studio_requires_login(client):
    assert client.post("/api/studio/generate", data={"garment": "tshirt", "color": "white", "prompt": "a horse"}).status_code == 401


def test_studio_rejects_blocked_prompt(user_client):
    r = user_client.post("/api/studio/generate", data={"garment": "tshirt", "color": "white", "prompt": "mickey mouse on a hoodie"})
    assert r.status_code == 400


def test_studio_rejects_bad_garment_and_color(user_client):
    assert user_client.post("/api/studio/generate", data={"garment": "shorts", "color": "white", "prompt": "a calm sea"}).status_code == 400
    assert user_client.post("/api/studio/generate", data={"garment": "hoodie", "color": "beige", "prompt": "a calm sea"}).status_code == 400


def test_studio_upload_rejects_non_image(user_client):
    r = user_client.post("/api/studio/upload", data={"garment": "tshirt", "color": "white"}, files={"file": ("a.png", b"not an image", "image/png")})
    assert r.status_code == 400


def test_studio_designs_are_private(user_client, client):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO(); Image.new("RGB", (40, 40), (200, 30, 30)).save(buf, "PNG")
    r = user_client.post("/api/studio/upload", data={"garment": "tshirt", "color": "white"}, files={"file": ("a.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert user_client.get(f"/api/studio/design/{cid}/art").status_code == 200
    client.post("/api/register", data={"email": "other@example.com", "password": "pw12345"})
    client.post("/api/login", data={"email": "other@example.com", "password": "pw12345"})
    assert client.get(f"/api/studio/design/{cid}/art").status_code == 404


# ---------- Checkout ----------

ITEM = {"price": 899, "mrp": 1120}


def test_totals_delivery_fee_and_free_threshold():
    assert _totals(ITEM, 1, None)["delivery"] == 59
    assert _totals(ITEM, 2, None)["delivery"] == 0       # 1798 >= 999
    assert _totals({"price": 1499, "mrp": 1870}, 1, None)["delivery"] == 0


def test_totals_coupon_and_cap():
    t = _totals(ITEM, 1, "welcome10")
    assert t["coupon_discount"] == 89 and t["total"] == 899 - 89 + 59
    big = _totals({"price": 5000, "mrp": 6250}, 1, "WELCOME10")
    assert big["coupon_discount"] == 200               # capped
    bad = _totals(ITEM, 1, "NOPE")
    assert bad["coupon"] is None and bad["coupon_discount"] == 0


def test_totals_clamp_quantity():
    assert _totals(ITEM, 99, None)["quantity"] == 10
    assert _totals(ITEM, 0, None)["quantity"] == 1


def test_checkout_requires_login(client):
    assert client.get("/api/checkout/item/design/1").status_code == 401


def test_checkout_full_funnel(user_client, admin_client):
    did = _seed_linen()
    assert user_client.get(f"/api/checkout/item/design/{did}").status_code == 200
    addr = {"name": "Asha Rao", "phone": "9876543210", "pincode": "560001", "address": "12 MG Road, Indiranagar",
            "city": "Bengaluru", "state": "Karnataka"}
    assert user_client.post(f"/api/checkout/address/design/{did}", data=addr).status_code == 200
    assert user_client.post(f"/api/checkout/payment/design/{did}", data={"quantity": 1}).status_code == 200
    r = user_client.post(f"/api/checkout/confirm/design/{did}", data={**addr, "size": "M", "quantity": 1, "payment_method": "upi"})
    assert r.status_code == 200 and r.json()["order_id"].startswith("LW")
    funnel = admin_client.get("/api/admin/checkout-funnel/summary").json()
    counts = {s["stage"]: s["count"] for s in funnel["stages"]}
    assert counts["opened"] >= 1 and counts["address"] >= 1 and counts["payment"] >= 1 and counts["paid"] >= 1


def test_checkout_validation_and_payment_method(user_client):
    did = _seed_linen()
    bad = {"name": "A", "phone": "123", "pincode": "12", "address": "x", "city": "", "state": ""}
    r = user_client.post(f"/api/checkout/address/design/{did}", data=bad)
    assert r.status_code == 422 and "phone" in r.json()["detail"]["errors"]
    good = {"name": "Asha Rao", "phone": "9876543210", "pincode": "560001", "address": "12 MG Road, Indiranagar",
            "city": "Bengaluru", "state": "Karnataka", "size": "M", "quantity": 1}
    assert user_client.post(f"/api/checkout/confirm/design/{did}", data={**good, "payment_method": "bitcoin"}).status_code == 422
    assert user_client.post(f"/api/checkout/confirm/design/{did}", data={**good, "size": "XXL", "payment_method": "upi"}).status_code == 422


def test_checkout_blocks_oversell(user_client):
    did = _seed_linen()  # stock 4
    good = {"name": "Asha Rao", "phone": "9876543210", "pincode": "560001", "address": "12 MG Road, Indiranagar",
            "city": "Bengaluru", "state": "Karnataka", "size": "M", "quantity": 9, "payment_method": "cod"}
    assert user_client.post(f"/api/checkout/confirm/design/{did}", data=good).status_code == 409


def test_custom_item_is_owner_only(user_client, client):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO(); Image.new("RGB", (40, 40), (10, 90, 160)).save(buf, "PNG")
    cid = user_client.post("/api/studio/upload", data={"garment": "hoodie", "color": "black"}, files={"file": ("a.png", buf.getvalue(), "image/png")}).json()["id"]
    assert user_client.get(f"/api/checkout/item/custom/{cid}").status_code == 200
    client.post("/api/register", data={"email": "thief@example.com", "password": "pw12345"})
    client.post("/api/login", data={"email": "thief@example.com", "password": "pw12345"})
    assert client.get(f"/api/checkout/item/custom/{cid}").status_code == 404
