import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

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
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        pool_recycle=300,
        pool_pre_ping=True,
        connect_args={
            "sslmode":             "require",
            "connect_timeout":     10,
            "options":             "-c statement_timeout=20000",
            "keepalives":          1,
            "keepalives_idle":     30,
            "keepalives_interval": 10,
            "keepalives_count":    3,
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
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception as e:
            logging.warning("Session close failed (stale connection — harmless): %s", e)


def warmup_pool():
    """Pre-open pool connections at startup so first requests aren't slow."""
    if use_sqlite:
        return
    try:
        conns = []
        for _ in range(3):
            conn = engine.connect()
            conn.execute(text("SELECT 1"))
            conns.append(conn)
        for conn in conns:
            conn.close()
        logging.info("✅ DB connection pool warmed up (3 connections)")
    except Exception as e:
        logging.warning("Pool warmup failed (non-fatal): %s", e)


def test_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logging.info("DB connection OK")
        return True
    except Exception as e:
        logging.error("DB connection failed: %s", e)
        return False


def init_db():
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
    try:
        engine.dispose()
        logging.info("All database connections closed")
    except Exception as e:
        logging.warning("Error closing connections: %s", e)


# ============================================
# SEQUENCE SYNCHRONIZATION UTILITIES
# ============================================

def sync_sequence(table_name: str, column_name: str, schema: str = "StreemLyne_MT") -> int:
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
    if use_sqlite:
        session.add(obj)
        return

    table_name = obj.__tablename__
    pk_columns = [c.name for c in obj.__table__.primary_key.columns]
    if not pk_columns:
        session.add(obj)
        return

    pk_column = pk_columns[0]

    for attempt in range(max_retries + 1):
        try:
            session.add(obj)
            session.flush()
            return
        except Exception as e:
            error_msg = str(e).lower()
            if 'duplicate key' in error_msg and attempt < max_retries:
                logging.warning(f"⚠️ Duplicate key on {table_name} - syncing sequence (attempt {attempt + 1})")
                session.rollback()
                try:
                    sync_sequence(table_name, pk_column)
                except Exception as sync_err:
                    logging.error(f"Sequence sync failed: {sync_err}")
                    raise e
                if obj in session:
                    session.expunge(obj)
            else:
                raise