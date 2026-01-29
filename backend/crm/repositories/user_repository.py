# -*- coding: utf-8 -*-
"""
User Repository
Handles database operations for User_Master table
"""
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client


class UserRepository:
    """
    Repository for User_Master table (Tenant Users)
    All queries are tenant-filtered for multi-tenant isolation
    """
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_users(self, tenant_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get all users for a tenant
        
        Args:
            tenant_id: Tenant identifier
            active_only: If True, only return active users
        
        Returns:
            List of user records
        """
        query = """
            SELECT 
                um.*,
                rm."role_name",
                rm."role_code"
            FROM "StreemLyne_MT"."User_Master" um
            LEFT JOIN "StreemLyne_MT"."Role_Master" rm ON um."Role_id" = rm."Role_id"
            WHERE um."Tenant_id" = %s
        """
        
        if active_only:
            query += ' AND um."is_active" = TRUE'
        
        query += ' ORDER BY um."user_name"'
        
        try:
            return self.db.execute_query(query, (tenant_id,))
        except Exception as e:
            print(f"Error fetching users for tenant {tenant_id}: {e}")
            return []
    
    def get_user_by_id(self, tenant_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific user by ID (with tenant isolation)
        
        Args:
            tenant_id: Tenant identifier
            user_id: User identifier
        
        Returns:
            User record or None
        """
        query = """
            SELECT 
                um.*,
                rm."role_name",
                rm."role_code"
            FROM "StreemLyne_MT"."User_Master" um
            LEFT JOIN "StreemLyne_MT"."Role_Master" rm ON um."Role_id" = rm."Role_id"
            WHERE um."Tenant_id" = %s
            AND um."User_id" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, user_id), fetch_one=True)
        except Exception as e:
            print(f"Error fetching user {user_id}: {e}")
            return None
    
    def get_users_by_role(self, tenant_id: int, role_id: int) -> List[Dict[str, Any]]:
        """
        Get all users with a specific role
        
        Args:
            tenant_id: Tenant identifier
            role_id: Role identifier
        
        Returns:
            List of users with the specified role
        """
        query = """
            SELECT 
                um.*,
                rm."role_name",
                rm."role_code"
            FROM "StreemLyne_MT"."User_Master" um
            LEFT JOIN "StreemLyne_MT"."Role_Master" rm ON um."Role_id" = rm."Role_id"
            WHERE um."Tenant_id" = %s
            AND um."Role_id" = %s
            AND um."is_active" = TRUE
            ORDER BY um."user_name"
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, role_id))
        except Exception as e:
            print(f"Error fetching users by role: {e}")
            return []
