import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logging.warning("No DATABASE_URL found. Using SQLite.")
    DATABASE_URL = "sqlite:///./local.db"
    use_sqlite = True
else:
    use_sqlite = False
    
    # Fix postgres:// to postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    # Fix psycopg2 dialect
    if not DATABASE_URL.startswith("postgresql+psycopg2://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    
    logging.info("Using hosted PostgreSQL database.")

# ============================================
# ENGINE CONFIGURATION
# ============================================
# Supabase/PostgreSQL: do not add pgBouncer or extra URL params; use connect_args only.
if use_sqlite:
    # SQLite config (for local development)
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True
    )
else:
    # PostgreSQL/Supabase: minimal engine options for SQLAlchemy compatibility.
    # pool_pre_ping=True checks connections before use; sslmode=require for Supabase TLS.
    # No pgBouncer-specific options are passed.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"sslmode": "require"}
    )

# ============================================
# SESSION CONFIGURATION
# ============================================
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False  # Important: prevents detached instance errors
)

Base = declarative_base()


def get_db():
    """
    Provide a database session with automatic cleanup.
    Usage:
        with get_db() as db:
            # use db here
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """Quick DB connection test"""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logging.info("DB connection OK")
            return True
    except Exception as e:
        logging.error("DB connection failed: %s", e)
        return False


def init_db():
    """Initialize database tables"""
    try:
        # Import models so SQLAlchemy knows about them
        from backend.models import (
            User, LoginAttempt, Session,
            Customer, Job, Assignment,
            Quotation, QuotationItem,
            Invoice, InvoiceLineItem, Payment,
            AuditLog, ActionItem, DataImport,
            CustomerDocument
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
    """Close all active database sessions (for cleanup)"""
    try:
        engine.dispose()
        logging.info("All database connections closed")
    except Exception as e:
        logging.warning("Error closing connections: %s", e)