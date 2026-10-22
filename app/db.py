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
    image_hash = Column(String(70), nullable=True)           # perceptual hash, see app/visual_search.py
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class MockupTemplate(Base):
    """
    One row per camera angle ("front", "back", "side") - a blank, plain
    white T-shirt product photo generated ONCE via the design agent's same
    image pipeline, then reused forever as the backdrop every approved
    design gets composited onto (see app/compositing.py).

    This is deliberately separate from Design: it's not a product a
    customer sees, it's a fixed template asset. Re-running the generator
    overwrites the row for that slot (upsert), so there's only ever one
    "current" template per angle.
    """
    __tablename__ = "mockup_templates"

    id = Column(Integer, primary_key=True, index=True)
    slot = Column(String(20), unique=True, nullable=False)  # "front" | "back" | "side"
    image_data = Column(LargeBinary, nullable=False)
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


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations():
    """
    Base.metadata.create_all only creates tables that don't exist yet - it
    never alters an existing table, so a new column added to an existing
    model (like Design.image_hash here) needs to be added by hand. This
    keeps that to one tiny, safe, idempotent statement instead of asking
    for another DROP TABLE (which would wipe real approved designs/images
    that already exist in production).
    """
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    if "designs" not in inspector.get_table_names():
        return
    existing_columns = {c["name"] for c in inspector.get_columns("designs")}
    if "image_hash" in existing_columns:
        return
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE designs ADD COLUMN IF NOT EXISTS image_hash VARCHAR(70)"))
        else:
            # SQLite (local dev fallback) - no IF NOT EXISTS guard needed,
            # we already checked the column is missing above.
            conn.execute(text("ALTER TABLE designs ADD COLUMN image_hash VARCHAR(70)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
