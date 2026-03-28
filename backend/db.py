import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logging.warning("No DATABASE_URL found. Using SQLite.")
    DATABASE_URL = "sqlite:///./local.db"
    use_sqlite = True
else:
    use_sqlite = False

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    if not DATABASE_URL.startswith("postgresql+psycopg2://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")

    logging.info("Using hosted PostgreSQL database.")


# ============================================
# ENGINE CONFIGURATION
# ============================================

if use_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,

        # Render free tier: keep pool small (max ~25 connections total)
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,

        # ✅ FIX: was 1800 (30 min). Supabase/Render kill idle connections at
        # ~5 min. Recycling at 4 min ensures we never hand out a dead connection.
        pool_recycle=240,

        # Validate connection before use — discards dead sockets transparently.
        pool_pre_ping=True,

        connect_args={
            "sslmode": "require",
            # TCP keepalives detect dead sockets at the OS level
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "connect_timeout": 10,
        },

        future=True,
    )


@event.listens_for(engine, "connect")
def set_search_path(dbapi_connection, connection_record):
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute('SET search_path TO "StreemLyne_MT", public')
    cursor.close()


# ============================================
# SESSION CONFIGURATION
# ============================================

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False,
)

Base = declarative_base()


def get_db():
    """Provide a transactional database session with automatic cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        # Defensive close: session.close() itself can raise when the underlying
        # connection is already dead (rollback on close fails). This prevents that
        # from surfacing as a 500. With pool_pre_ping + pool_recycle this is rare.
        try:
            db.close()
        except Exception as e:
            logging.warning("Session close failed (stale connection — harmless): %s", e)


def test_connection() -> bool:
    """Quick DB connection test. Safe to call from /health endpoints."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logging.info("DB connection OK")
        return True
    except Exception as e:
        logging.error("DB connection failed: %s", e)
        return False


def init_db():
    """Initialize database tables."""
    try:
        from backend.models import (
            User, LoginAttempt, Session,
            Customer, Job, Assignment,
            Quotation, QuotationItem,
            Invoice, InvoiceLineItem, Payment,
            AuditLog, ActionItem, DataImport,
            CustomerDocument,
        )
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logging.info("Database tables initialized")
        return True
    except Exception as e:
        logging.error("Failed to initialize database: %s", e)
        import traceback
        traceback.print_exc()
        return False


def close_all_sessions():
    """Close all active database sessions (for cleanup)."""
    try:
        engine.dispose()
        logging.info("All database connections closed")
    except Exception as e:
        logging.warning("Error closing connections: %s", e)