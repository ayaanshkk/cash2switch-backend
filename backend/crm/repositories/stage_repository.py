# ========================================
# CREATE NEW FILE: backend/crm/repositories/stage_repository.py
# ========================================

"""
Stage Repository
Handles database operations for Stage_Master table
"""
import os
import logging
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _supabase_configured() -> bool:
    """True if Supabase env vars are set"""
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return False
    if os.getenv("SUPABASE_DB_URL"):
        return True
    if os.getenv("DATABASE_URL") and "supabase" in (os.getenv("DATABASE_URL") or ""):
        return True
    if os.getenv("SUPABASE_DB_PASSWORD"):
        return True
    return False


class _LocalCRMDBStub:
    """Stub DB adapter when Supabase is not configured"""
    def execute_query(self, query: str, params: tuple = None, fetch_one: bool = False):
        return None if fetch_one else []


class StageRepository:
    """Repository for Stage_Master table"""
    
    def __init__(self):
        if _supabase_configured():
            self.db = get_supabase_client()
        else:
            self.db = _LocalCRMDBStub()
    
    def get_all_stages(self) -> List[Dict[str, Any]]:
        """Get all stages"""
        query = """
            SELECT 
                "stage_id",
                "stage_name",
                "stage_description",
                "preceding_stage_id",
                "stage_type"
            FROM "StreemLyne_MT"."Stage_Master"
            ORDER BY "stage_id"
        """
        
        try:
            return self.db.execute_query(query)
        except Exception as e:
            logger.error(f"Error fetching stages: {e}")
            return []
    
    def get_stage_by_id(self, stage_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific stage by ID"""
        query = """
            SELECT 
                "stage_id",
                "stage_name",
                "stage_description",
                "preceding_stage_id",
                "stage_type"
            FROM "StreemLyne_MT"."Stage_Master"
            WHERE "stage_id" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (stage_id,), fetch_one=True)
        except Exception as e:
            logger.error(f"Error fetching stage {stage_id}: {e}")
            return None
    
    def get_stage_by_name(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific stage by name"""
        query = """
            SELECT 
                "stage_id",
                "stage_name",
                "stage_description",
                "preceding_stage_id",
                "stage_type"
            FROM "StreemLyne_MT"."Stage_Master"
            WHERE "stage_name" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (stage_name,), fetch_one=True)
        except Exception as e:
            logger.error(f"Error fetching stage by name '{stage_name}': {e}")
            return None