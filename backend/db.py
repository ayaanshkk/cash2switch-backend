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
        pool_size=10,        # ✅ Increase from 2
        max_overflow=10,     # ✅ Increase from 3 (20 total connections max)
        pool_timeout=30,     # ✅ Increase from 20
        pool_recycle=600,    # ✅ Recycle every 10 min
        pool_pre_ping=True,

        connect_args={
            "sslmode": "require",
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
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


# ============================================
# SEQUENCE SYNCHRONIZATION UTILITIES
# ============================================

def sync_sequence(table_name: str, column_name: str, schema: str = "StreemLyne_MT") -> int:
    """
    Synchronize a PostgreSQL sequence with the actual max ID in the table.
    Fixes "duplicate key" errors caused by out-of-sync sequences after bulk imports.
    
    Args:
        table_name: Name of the table (e.g., "Client_Interactions")
        column_name: Name of the auto-increment column (e.g., "interaction_id")
        schema: Database schema name (default: "StreemLyne_MT")
    
    Returns:
        The new sequence value after sync
    
    Example:
        >>> sync_sequence("Client_Interactions", "interaction_id")
        3257
    """
    if use_sqlite:
        logging.warning("Sequence sync not needed for SQLite")
        return 0
    
    session = SessionLocal()
    try:
        result = session.execute(text(f"""
            SELECT setval(
                pg_get_serial_sequence('"{schema}"."{table_name}"', '{column_name}'),
                COALESCE((SELECT MAX({column_name}) FROM "{schema}"."{table_name}"), 1),
                true
            )
        """))
        new_val = result.scalar()
        session.commit()
        logging.info(f"✅ Synced {schema}.{table_name}.{column_name} sequence to {new_val}")
        return int(new_val)
    except Exception as e:
        session.rollback()
        logging.error(f"❌ Failed to sync sequence for {schema}.{table_name}.{column_name}: {e}")
        raise
    finally:
        session.close()


def sync_all_sequences() -> dict:
    """
    Sync all known sequences in the StreemLyne_MT schema.
    Call this after bulk imports or when you encounter duplicate key errors.
    
    Returns:
        Dictionary mapping table.column to new sequence values
    
    Example:
        >>> results = sync_all_sequences()
        >>> print(results)
        {
            'Client_Interactions.interaction_id': 3257,
            'Opportunity_Details.opportunity_id': 12459,
            ...
        }
    """
    if use_sqlite:
        logging.warning("Sequence sync not needed for SQLite")
        return {}
    
    sequences_to_sync = [
        ("Client_Interactions", "interaction_id"),
        ("Opportunity_Details", "opportunity_id"),
        ("Client_Master", "client_id"),
        ("Project_Details", "project_id"),
        ("Energy_Contract_Master", "contract_id"),
        ("Employee_Master", "employee_id"),
        ("Supplier_Master", "supplier_id"),
        ("Stage_Master", "stage_id"),
        ("Service_Master", "service_id"),
        ("Role_Master", "role_id"),
        ("User_Master", "user_id"),
    ]
    
    results = {}
    for table, column in sequences_to_sync:
        try:
            new_val = sync_sequence(table, column)
            results[f"{table}.{column}"] = new_val
        except Exception as e:
            results[f"{table}.{column}"] = f"ERROR: {str(e)}"
            logging.warning(f"Failed to sync {table}.{column}: {e}")
    
    return results


def safe_add_with_sequence_retry(session, obj, max_retries: int = 2):
    """
    Add an object to the session with automatic sequence sync on duplicate key errors.
    
    This is a safety wrapper for session.add() that handles the "duplicate key" error
    by syncing the sequence and retrying the insert.
    
    Args:
        session: SQLAlchemy session
        obj: ORM object to add
        max_retries: Maximum number of retry attempts (default: 2)
    
    Example:
        >>> from backend.models import Client_Interactions
        >>> interaction = Client_Interactions(client_id=123, ...)
        >>> safe_add_with_sequence_retry(session, interaction)
        >>> session.commit()
    """
    if use_sqlite:
        session.add(obj)
        return
    
    table_name = obj.__tablename__
    
    # Try to determine the primary key column
    pk_columns = [c.name for c in obj.__table__.primary_key.columns]
    if not pk_columns:
        session.add(obj)
        return
    
    pk_column = pk_columns[0]  # Assume first PK is the auto-increment
    
    for attempt in range(max_retries + 1):
        try:
            session.add(obj)
            session.flush()
            return  # Success
        except Exception as e:
            error_msg = str(e).lower()
            if 'duplicate key' in error_msg and attempt < max_retries:
                logging.warning(f"⚠️ Duplicate key on {table_name} - syncing sequence (attempt {attempt + 1})")
                session.rollback()
                
                # Sync the sequence
                try:
                    sync_sequence(table_name, pk_column)
                except Exception as sync_err:
                    logging.error(f"Sequence sync failed: {sync_err}")
                    raise e  # Re-raise original error
                
                # Remove the object from the session and re-add it
                if obj in session:
                    session.expunge(obj)
            else:
                raise  