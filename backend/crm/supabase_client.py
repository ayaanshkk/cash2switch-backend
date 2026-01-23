# -*- coding: utf-8 -*-
"""
Supabase Client for StreemLyne CRM
Connects to external Supabase database using environment variables
"""
import os
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()

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
        
        # Extract connection details from Supabase URL
        # Format: https://PROJECT_ID.supabase.co
        project_id = self.supabase_url.replace('https://', '').replace('.supabase.co', '')
        
        # Supabase connection string format
        # Using direct connection for pooler compatibility
        self.connection_string = f"postgresql://postgres.{project_id}:@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
        
        # Try to extract password from DATABASE_URL if available
        database_url = os.getenv('DATABASE_URL')
        if database_url and 'supabase' in database_url:
            self.connection_string = database_url.replace('postgres://', 'postgresql://')
            if not self.connection_string.startswith('postgresql+psycopg2://'):
                self.connection_string = self.connection_string.replace('postgresql://', 'postgresql+psycopg2://')
            # Remove the psycopg2 driver prefix for psycopg2 library
            self.connection_string = self.connection_string.replace('postgresql+psycopg2://', 'postgresql://')
    
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


# Singleton instance
_supabase_client = None

def get_supabase_client() -> SupabaseClient:
    """
    Get singleton Supabase client instance
    """
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
