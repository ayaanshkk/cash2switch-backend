# -*- coding: utf-8 -*-
"""
Supabase Client for StreemLyne CRM
Connects to external Supabase database using environment variables.
When Supabase env vars are missing (local/test), returns a stub so app uses SQLite.
"""
import os
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()


def _supabase_env_configured() -> bool:
    """True if we have enough env to build a Supabase DB connection."""
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
    """
    Stub matching SupabaseClient interface when Supabase is not configured.
    Used so local/test can run with SQLite without Supabase credentials.
    """
    @contextmanager
    def get_connection(self):
        yield None

    def execute_query(
        self, query: str, params: tuple = None, fetch_one: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        return None if fetch_one else []

    def execute_insert(
        self, query: str, params: tuple = None, returning: bool = True
    ) -> Optional[Dict[str, Any]]:
        return None

    def execute_update(self, query: str, params: tuple = None) -> int:
        return 0

    def execute_delete(self, query: str, params: tuple = None) -> int:
        return 0

    def test_connection(self) -> bool:
        return True


class SupabaseClient:
    """
    PostgreSQL client for StreemLyne Supabase database
    Uses psycopg2 for direct database access
    """
    
    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.service_role_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not self.supabase_url or not self.service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
        
        # Priority 1: Use SUPABASE_DB_URL if provided (dedicated CRM connection)
        supabase_db_url = os.getenv('SUPABASE_DB_URL')
        if supabase_db_url:
            self.connection_string = supabase_db_url.replace('postgres://', 'postgresql://')
            print(f"✅ SupabaseClient: Using SUPABASE_DB_URL")
        else:
            # Priority 2: Use DATABASE_URL if provided (contains password)
            database_url = os.getenv('DATABASE_URL')
            if database_url and 'supabase' in database_url:
                # Clean up the connection string for psycopg2
                self.connection_string = database_url.replace('postgres://', 'postgresql://')
                self.connection_string = self.connection_string.replace('postgresql+psycopg2://', 'postgresql://')
                print(f"✅ SupabaseClient: Using DATABASE_URL")
            else:
                # Priority 3: Try to use SUPABASE_DB_PASSWORD if set
                db_password = os.getenv('SUPABASE_DB_PASSWORD')
            
            if db_password:
                # Extract project ID from Supabase URL
                # Format: https://PROJECT_ID.supabase.co
                project_id = self.supabase_url.replace('https://', '').replace('.supabase.co', '')
                
                # Construct connection string with password
                self.connection_string = f"postgresql://postgres.{project_id}:{db_password}@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
                print(f"✅ SupabaseClient: Using SUPABASE_DB_PASSWORD")
            else:
                raise ValueError(
                    "Supabase database password not found. Please set either:\n"
                    "  1. DATABASE_URL (full connection string), OR\n"
                    "  2. SUPABASE_DB_PASSWORD (database password only)\n"
                    "Example: DATABASE_URL=postgresql+psycopg2://postgres.PROJECT_ID:PASSWORD@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
                )
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections
        Automatically handles connection cleanup
        """
        conn = None
        try:
            conn = psycopg2.connect(
                self.connection_string,
                cursor_factory=RealDictCursor,
                connect_timeout=10
            )
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    
    def execute_query(self, query: str, params: tuple = None, fetch_one: bool = False) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a SELECT query and return results
        
        Args:
            query: SQL query string
            params: Query parameters (tuple)
            fetch_one: If True, return single result instead of list
        
        Returns:
            List of dictionaries or single dictionary (if fetch_one=True)
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                
                if fetch_one:
                    result = cursor.fetchone()
                    return dict(result) if result else None
                
                results = cursor.fetchall()
                return [dict(row) for row in results]
    
    def execute_insert(self, query: str, params: tuple = None, returning: bool = True) -> Optional[Dict[str, Any]]:
        """
        Execute an INSERT query
        
        Args:
            query: SQL INSERT query
            params: Query parameters
            returning: If True, expects RETURNING clause in query
        
        Returns:
            Inserted record (if returning=True)
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                
                if returning:
                    result = cursor.fetchone()
                    return dict(result) if result else None
                
                return None
    
    def execute_update(self, query: str, params: tuple = None) -> int:
        """
        Execute an UPDATE query
        
        Args:
            query: SQL UPDATE query
            params: Query parameters
        
        Returns:
            Number of rows affected
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount
    
    def execute_delete(self, query: str, params: tuple = None) -> int:
        """
        Execute a DELETE query
        
        Args:
            query: SQL DELETE query
            params: Query parameters
        
        Returns:
            Number of rows deleted
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount
    
    def test_connection(self) -> bool:
        """
        Test database connection
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return True
        except Exception as e:
            print(f"Connection test failed: {e}")
            return False


# Singleton instance (SupabaseClient or _LocalCRMDBStub)
_supabase_client = None


def get_supabase_client():
    """
    Get singleton Supabase client instance.
    When Supabase env vars are missing (local/test), returns a stub so
    the app can run with SQLite without crashing.
    """
    global _supabase_client
    if _supabase_client is None:
        if _supabase_env_configured():
            _supabase_client = SupabaseClient()
        else:
            _supabase_client = _LocalCRMDBStub()
    return _supabase_client
