# -*- coding: utf-8 -*-
"""
Tenant Repository
Handles database operations for Tenant_Master table
"""
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client


class TenantRepository:
    """
    Repository for Tenant_Master table operations
    Provides data access methods for tenant management
    """
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_tenant_by_id(self, tenant_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve tenant by ID
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Tenant record or None if not found
        """
        query = """
            SELECT *
            FROM "StreemLyne_MT"."Tenant_Master"
            WHERE "Tenant_id" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (tenant_id,), fetch_one=True)
        except Exception as e:
            print(f"Error fetching tenant {tenant_id}: {e}")
            return None
    
    def get_all_tenants(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieve all tenants
        
        Args:
            active_only: If True, only return active tenants
        
        Returns:
            List of tenant records
        """
        if active_only:
            query = """
                SELECT *
                FROM "StreemLyne_MT"."Tenant_Master"
                WHERE "is_active" = TRUE
                ORDER BY "tenant_company_name"
            """
        else:
            query = """
                SELECT *
                FROM "StreemLyne_MT"."Tenant_Master"
                ORDER BY "tenant_company_name"
            """
        
        try:
            return self.db.execute_query(query)
        except Exception as e:
            print(f"Error fetching tenants: {e}")
            return []
    
    def get_tenant_modules(self, tenant_id: int) -> List[Dict[str, Any]]:
        """
        Get all modules assigned to a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            List of module records
        """
        query = """
            SELECT 
                tmm.*,
                mm."module_name",
                mm."module_code"
            FROM "StreemLyne_MT"."Tenant_Module_Mapping" tmm
            INNER JOIN "StreemLyne_MT"."Module_Master" mm ON tmm."module_id" = mm."module_id"
            WHERE tmm."Tenant_id" = %s
            AND tmm."is_active" = TRUE
        """
        
        try:
            return self.db.execute_query(query, (tenant_id,))
        except Exception as e:
            print(f"Error fetching tenant modules: {e}")
            return []

    def ensure_default_tenant(self) -> Optional[Dict[str, Any]]:
        """
        Ensure at least one tenant exists; return it. Used in non-production when
        tenant is not found so the request can proceed with a default tenant.
        Returns None if no tenant exists and one could not be created (e.g. stub DB).
        """
        try:
            tenants = self.db.execute_query(
                'SELECT * FROM "StreemLyne_MT"."Tenant_Master" ORDER BY "Tenant_id" LIMIT 1'
            )
            if tenants and len(tenants) > 0:
                return tenants[0]
            ins = (
                'INSERT INTO "StreemLyne_MT"."Tenant_Master" '
                '("tenant_company_name", "is_active") VALUES (%s, %s) RETURNING "Tenant_id", "tenant_company_name", "is_active"'
            )
            row = self.db.execute_insert(ins, ("Default Tenant", True), returning=True)
            if row:
                return row
        except Exception:
            pass
        return None
