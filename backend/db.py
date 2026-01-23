import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("WARNING: No DATABASE_URL found. Using SQLite.")
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
    
    print("SUCCESS: Using hosted PostgreSQL database.")

# Add essential connection parameters for Supabase
if not use_sqlite:
    # Parse URL to add parameters
    if "?" in DATABASE_URL:
        # Parameters already exist, append to them
        if "sslmode" not in DATABASE_URL:
            DATABASE_URL += "&sslmode=require"
        if "connect_timeout" not in DATABASE_URL:
            DATABASE_URL += "&connect_timeout=10"
    else:
        # No parameters yet, add them
        DATABASE_URL += "?sslmode=require&connect_timeout=10"

# ============================================
# ENGINE CONFIGURATION
# ============================================
if use_sqlite:
    # SQLite config (for local development)
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True
    )
else:
    # PostgreSQL/Supabase config
    # Use QueuePool with strict limits for Supabase free tier
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,  # Changed from NullPool
        pool_size=2,          # Very small pool for free tier
        max_overflow=1,       # Allow 1 extra connection
        pool_timeout=30,      # Wait up to 30 seconds for connection
        pool_recycle=300,     # Recycle connections every 5 minutes
        pool_pre_ping=True,   # Test connections before using
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",  # 30 second query timeout
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
        future=True,
        echo=False  # Set to True for SQL debugging
    )
    
    # Add connection pool event listeners to handle cleanup
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_conn, connection_record):
        """Called when a connection is retrieved from the pool"""
        pass
    
    @event.listens_for(engine, "close")
    def receive_close(dbapi_conn, connection_record):
        """Called when a connection is returned to the pool"""
        pass

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
            print("SUCCESS: DB connection OK")
            return True
    except Exception as e:
        print(f"ERROR: DB connection failed: {e}")
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
        print("SUCCESS: Database tables initialized")
        return True

    except Exception as e:
        print(f"ERROR: Failed to initialize database: {e}")
        import traceback
        traceback.print_exc()
        return False


def close_all_sessions():
    """Close all active database sessions (for cleanup)"""
    try:
        engine.dispose()
        print("SUCCESS: All database connections closed")
    except Exception as e:
        print(f"WARNING: Error closing connections: {e}")