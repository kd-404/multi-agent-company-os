import logging

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, LargeBinary
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

from .config import settings

# Azure PostgreSQL needs sslmode=require; psycopg2 picks this up from the
# connection string itself, e.g.:
# postgresql://user:pass@your-server.postgres.database.azure.com:5432/loomwell?sslmode=require
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # "admin" or "user"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ChatMessage(Base):
    """Stores CEO-chatbot conversation history per user, for continuity."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Design(Base):
    """
    Output of the design agent: one row per generated T-shirt design.
    status starts "pending" (needs admin review); later an admin can
    approve/reject it. This table is the seed of the future product
    catalog - it's deliberately NOT the catalog itself yet.

    The generated image is stored as bytes IN THIS ROW (image_data), not
    as a file on disk. Azure App Service (Linux) runs the app from a
    temp-extracted folder outside /home, which is wiped on every restart
    or container recycle - files written there at runtime don't survive.
    Postgres is the one piece of this stack that's actually persistent,
    so that's where generated images live.
    """
    __tablename__ = "designs"

    id = Column(Integer, primary_key=True, index=True)
    trend_query = Column(String(500), nullable=False)      # what we searched for
    trend_summary = Column(Text, nullable=False)            # Tavily's synthesized answer
    sources = Column(Text, nullable=True)                   # newline-separated source URLs
    image_prompt = Column(Text, nullable=False)              # what we actually sent to the image model
    image_data = Column(LargeBinary, nullable=False)         # the PNG bytes themselves
    status = Column(String(20), nullable=False, default="pending")  # pending/approved/rejected
    image_hash = Column(String(70), nullable=True)           # legacy, unused (kept so no destructive migration is needed)
    vision_tags = Column(Text, nullable=True)                 # comma-separated tags from Azure Vision, see app/visual_search.py
    dominant_color = Column(String(20), nullable=True)        # "r,g,b" of the design itself, background excluded
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # --- Warehouse agent fields ---
    # Loomwell prints on demand - there's no physical warehouse yet - so
    # this is a SIMULATED stock count the warehouse agent manages: it starts
    # full on approval and is decremented on each (currently simulated)
    # sale, so the low-stock/reprint-recommendation logic has something
    # real to react to. Swap in real inventory numbers later without
    # changing the warehouse agent's logic.
    virtual_stock = Column(Integer, nullable=False, default=50)

    # --- Marketing agent fields ---
    # Drafted once per design by the marketing agent (rule-based, from the
    # same trend research + Vision tags already on this row - no extra AI
    # call needed). Null until "Draft caption" has been run for this design.
    social_caption = Column(Text, nullable=True)
    social_hashtags = Column(String(400), nullable=True)

    # --- Product matrix (see app/garments.py) ---
    # Which garment type/color this design's mockups render onto, assigned
    # once at generation time (app/garments.pick_garment_and_color) so the
    # same design always shows up the same way site-wide, rather than a
    # different shirt on every request. Null on designs created before this
    # existed - compositing falls back to garments.DEFAULT_GARMENT/COLOR.
    garment = Column(String(20), nullable=True)
    color = Column(String(20), nullable=True)


class MockupTemplate(Base):
    """
    One row per (garment, color, camera angle) combo - e.g. ("hoodie",
    "black", "model") - a blank product photo generated ONCE via the
    design agent's same image pipeline, then reused forever as the
    backdrop every approved design assigned to that combo gets composited
    onto (see app/compositing.py and app/garments.py for the matrix).

    This is deliberately separate from Design: it's not a product a
    customer sees, it's a fixed template asset. Re-running the generator
    overwrites the row for that exact combo (upsert), so there's only ever
    one "current" template per (garment, color, slot).
    """
    __tablename__ = "mockup_templates"

    id = Column(Integer, primary_key=True, index=True)
    garment = Column(String(20), nullable=False, default="tshirt")
    color = Column(String(20), nullable=False, default="white")
    slot = Column(String(20), nullable=False)  # "front" | "back" | "model"
    image_data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Order(Base):
    """
    One row per checkout attempt for a single design (see
    app/routes/payment_routes.py). Created in "created" status the moment
    a Razorpay order is opened, flipped to "paid" only after this server
    independently verifies Razorpay's signature on the callback - never
    trusts the browser's word alone that a payment succeeded. Doesn't
    exist at all in simulated mode (no Razorpay keys configured yet) -
    that path still goes through the older AgentActivity-only
    simulate_order(), unchanged.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    design_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    amount_inr = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="created")  # created | paid | failed
    razorpay_order_id = Column(String(64), nullable=True, index=True)
    razorpay_payment_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SearchLog(Base):
    """
    One row per visual-search request, used only to power the admin
    "Customer interest" view: which approved designs keep coming up as the
    best match for what visitors upload. This never stores the uploaded
    photo itself, only which existing design it matched and how closely.
    """
    __tablename__ = "search_logs"

    id = Column(Integer, primary_key=True, index=True)
    matched_design_id = Column(Integer, nullable=True, index=True)
    score = Column(Integer, nullable=False)  # similarity * 100, as an int (0-100)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentActivity(Base):
    """
    One row per notable thing an agent did - the shared feed behind the
    admin "Agent Status" live dashboard and the "Run full pipeline" demo.
    Written by app/agent_log.py's log_activity(), called from every agent
    (design, marketing, warehouse, payment, ceo) at the point it actually
    does something, not on a timer - so "latest activity per agent" is a
    real status, not a heartbeat.

    agent: "design" | "marketing" | "warehouse" | "payment" | "ceo"
    status: "ok" | "alert" | "error" | "simulated" (payment only, until
            Razorpay is wired up for real - never claims a real charge)
    """
    __tablename__ = "agent_activities"

    id = Column(Integer, primary_key=True, index=True)
    agent = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    design_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class EvalMetric(Base):
    """
    One row per scored stage of a Design-agent pipeline run - the
    evaluation layer behind the admin "Evaluation" dashboard. Every
    _generate_one_design() call writes one row per stage it attempts, win
    or lose, so the dashboard can show real success-rate/latency/quality
    trends across runs, not just the latest one.

    stage: "trend_research" | "image_generation" | "vision_tagging" | "overall"
    metric: "latency_ms" | "success" (1/0) | "relevance_score" (0-100, see
            app/evaluation.py - a stand-in for a Foundry groundedness/
            relevance evaluator: how much the Vision tags on the finished
            image actually overlap with the trend-research brief that
            prompted it, i.e. did the image agent actually listen to the
            research, or just generate something generic)
    run_seq: 1-based index of this design's generation among all designs
             generated so far, so "performance over iterations" has a
             stable x-axis independent of wall-clock gaps between runs.
    """
    __tablename__ = "eval_metrics"

    id = Column(Integer, primary_key=True, index=True)
    design_id = Column(Integer, nullable=True, index=True)
    run_seq = Column(Integer, nullable=False, index=True)
    stage = Column(String(30), nullable=False, index=True)
    metric = Column(String(30), nullable=False, index=True)
    value = Column(Integer, nullable=False)  # ints only: ms, 0/1, or 0-100 score
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CheckoutEvent(Base):
    """
    One row per funnel step in the demo/mimic checkout flow (see
    app/routes/checkout_routes.py) - NOT tied to real Razorpay, which
    stays separate in Order/payment_routes.py for whenever real keys are
    configured. This is what answers "how many people got to checkout and
    how many actually went through" (the admin "Checkout Funnel" panel):
    every open of the checkout modal logs a "opened" row, every completed
    demo confirmation logs a "paid" row, both carrying the real logged-in
    user's email and the design/amount involved - no separate guest-
    identity system, since buying already requires being logged in.

    stage: "opened" | "paid"
    """
    __tablename__ = "checkout_events"

    id = Column(Integer, primary_key=True, index=True)
    design_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    user_email = Column(String(255), nullable=False)
    stage = Column(String(20), nullable=False, index=True)
    amount_inr = Column(Integer, nullable=False)
    shipping_name = Column(String(200), nullable=True)
    shipping_address = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations():
    """
    Base.metadata.create_all only creates tables that don't exist yet - it
    never alters an existing table, so a new column added to an existing
    model (like Design.image_hash/vision_tags/dominant_color here) needs
    to be added by hand. This keeps that to tiny, safe, idempotent
    statements instead of asking for another DROP TABLE (which would wipe
    real approved designs/images that already exist in production).
    """
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    is_postgres = engine.dialect.name == "postgresql"

    def _add_missing_columns(table: str, columns_to_add: dict[str, str]):
        existing_columns = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as conn:
            for col_name, col_type in columns_to_add.items():
                if col_name in existing_columns:
                    continue
                if is_postgres:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
                else:
                    # SQLite (local dev fallback) has no "IF NOT EXISTS" for
                    # ADD COLUMN, but we've already filtered to missing
                    # columns, so this is safe as-is.
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))

    if "designs" in table_names:
        _add_missing_columns("designs", {
            "image_hash": "VARCHAR(70)",
            "vision_tags": "TEXT",
            "dominant_color": "VARCHAR(20)",
            "virtual_stock": "INTEGER NOT NULL DEFAULT 50",
            "social_caption": "TEXT",
            "social_hashtags": "VARCHAR(400)",
            "garment": "VARCHAR(20)",
            "color": "VARCHAR(20)",
        })

    if "mockup_templates" in table_names:
        # mockup_templates used to be one row per slot ("front"/"back"/
        # "model") with a UNIQUE constraint on slot alone. Now it's one row
        # per (garment, color, slot) - see app/garments.py - so that old
        # single-column uniqueness has to go before we can store more than
        # one color/garment per slot.
        if is_postgres:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE mockup_templates DROP CONSTRAINT IF EXISTS mockup_templates_slot_key"
                ))
        _add_missing_columns("mockup_templates", {
            "garment": "VARCHAR(20) NOT NULL DEFAULT 'tshirt'",
            "color": "VARCHAR(20) NOT NULL DEFAULT 'white'",
        })
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_mockup_templates_combo "
                    "ON mockup_templates (garment, color, slot)"
                ))
        except Exception:
            # Best-effort: app-level upsert logic (filter-then-insert-or-
            # update) already enforces "one row per combo" without this
            # index; it's a safety net, not load-bearing.
            logging.getLogger(__name__).exception(
                "Could not create ux_mockup_templates_combo index (non-fatal)"
            )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
