# -*- coding: utf-8 -*-
"""
Supabase Client for StreemLyne CRM
Connects to external Supabase database using environment variables.
Uses ThreadedConnectionPool to prevent MaxClientsInSessionMode errors.
"""
import os
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2 import pool as psycopg2_pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()


def _supabase_env_configured() -> bool:
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return False
    if os.getenv("SUPABASE_DB_URL"):
        return True
    database_url = os.getenv("DATABASE_URL") or ""
    if database_url and "supabase" in database_url:
        return True
    if os.getenv("SUPABASE_DB_PASSWORD"):
        return True
    return False


class _LocalCRMDBStub:
    @contextmanager
    def get_connection(self):
        yield None

    def execute_query(self, query: str, params: tuple = None, fetch_one: bool = False):
        return None if fetch_one else []

    def execute_insert(self, query: str, params: tuple = None, returning: bool = True):
        return None

    def execute_update(self, query: str, params: tuple = None) -> int:
        return 0

    def execute_delete(self, query: str, params: tuple = None) -> int:
        return 0

    def test_connection(self) -> bool:
        return True


class SupabaseClient:
    """
    PostgreSQL client for StreemLyne Supabase database.
    Uses ThreadedConnectionPool to reuse connections and avoid exhausting
    Supabase's session-mode pool limit.
    """

    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.service_role_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

        if not self.supabase_url or not self.service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

        # Build connection string — prefer SUPABASE_DB_URL (transaction pooler)
        supabase_db_url = os.getenv('SUPABASE_DB_URL')
        if supabase_db_url:
            self.connection_string = supabase_db_url.replace('postgres://', 'postgresql://')
            print(f"[OK] SupabaseClient: Using SUPABASE_DB_URL")
        else:
            database_url = os.getenv('DATABASE_URL')
            if database_url and 'supabase' in database_url:
                self.connection_string = database_url.replace('postgres://', 'postgresql://')
                self.connection_string = self.connection_string.replace('postgresql+psycopg2://', 'postgresql://')
                print(f"[OK] SupabaseClient: Using DATABASE_URL")
            else:
                db_password = os.getenv('SUPABASE_DB_PASSWORD')
                if db_password:
                    project_id = self.supabase_url.replace('https://', '').replace('.supabase.co', '')
                    self.connection_string = (
                        f"postgresql://postgres.{project_id}:{db_password}"
                        f"@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
                    )
                    print(f"[OK] SupabaseClient: Using SUPABASE_DB_PASSWORD")
                else:
                    raise ValueError(
                        "Supabase database password not found. Set DATABASE_URL or SUPABASE_DB_PASSWORD."
                    )

        # ✅ Create a threaded connection pool
        # minconn=1: keep at least 1 connection alive
        # maxconn=8: never open more than 8 simultaneous connections
        # Supabase transaction pooler (port 6543) supports many more than session mode (port 5432)
        try:
            self._pool = psycopg2_pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=8,
                dsn=self.connection_string,
                cursor_factory=RealDictCursor,
                connect_timeout=10,
                options="-c search_path=StreemLyne_MT,public"
            )
            print(f"[OK] SupabaseClient: Connection pool created (min=1, max=8)")
        except Exception as e:
            print(f"[ERROR] SupabaseClient: Failed to create connection pool: {e}")
            raise

    @contextmanager
    def get_connection(self):
        """
        Borrow a connection from the pool, yield it, then return it.
        Always returns the connection even on error — never leaks.
        """
        conn = None
        try:
            conn = self._pool.getconn()
            yield conn
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise e
        finally:
            if conn:
                try:
                    self._pool.putconn(conn)
                except Exception:
                    pass

    def execute_query(
        self, query: str, params: tuple = None, fetch_one: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if fetch_one:
                    result = cursor.fetchone()
                    return dict(result) if result else None
                results = cursor.fetchall()
                return [dict(row) for row in results]

    def execute_insert(
        self, query: str, params: tuple = None, returning: bool = True
    ) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                if returning:
                    result = cursor.fetchone()
                    return dict(result) if result else None
                return None

    def execute_update(self, query: str, params: tuple = None) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount

    def execute_delete(self, query: str, params: tuple = None) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount

    def test_connection(self) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return True
        except Exception as e:
            print(f"Connection test failed: {e}")
            return False

    def close_pool(self):
        """Cleanly close all connections in the pool (call on app shutdown)."""
        try:
            self._pool.closeall()
            print("[OK] SupabaseClient: Connection pool closed")
        except Exception as e:
            print(f"[WARN] SupabaseClient: Error closing pool: {e}")


# Singleton instance
_supabase_client = None


def get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        if _supabase_env_configured():
            _supabase_client = SupabaseClient()
        else:
            _supabase_client = _LocalCRMDBStub()
    return _supabase_client