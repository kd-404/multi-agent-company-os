from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
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
    """
    __tablename__ = "designs"

    id = Column(Integer, primary_key=True, index=True)
    trend_query = Column(String(500), nullable=False)      # what we searched for
    trend_summary = Column(Text, nullable=False)            # Tavily's synthesized answer
    sources = Column(Text, nullable=True)                   # newline-separated source URLs
    image_prompt = Column(Text, nullable=False)              # what we actually sent to the image model
    image_path = Column(String(500), nullable=False)         # relative path under /static
    status = Column(String(20), nullable=False, default="pending")  # pending/approved/rejected
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
