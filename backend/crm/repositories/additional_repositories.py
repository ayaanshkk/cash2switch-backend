# -*- coding: utf-8 -*-
"""
Additional CRM Repositories
Handles database operations for supporting tables
"""
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client


class RoleRepository:
    """Repository for Role_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_roles(self, tenant_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all roles (system + tenant-specific)
        
        Args:
            tenant_id: Optional tenant filter
        
        Returns:
            List of role records
        """
        if tenant_id:
            query = """
                SELECT * FROM "Role_Master"
                WHERE tenant_id IS NULL OR tenant_id = %s
                ORDER BY role_name
            """
            params = (tenant_id,)
        else:
            query = 'SELECT * FROM "Role_Master" ORDER BY role_name'
            params = None
        
        try:
            return self.db.execute_query(query, params)
        except Exception as e:
            print(f"Error fetching roles: {e}")
            return []


class StageRepository:
    """Repository for Stage_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_stages(self, pipeline_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all pipeline stages
        
        Args:
            pipeline_type: Optional filter by pipeline type
        
        Returns:
            List of stage records
        """
        if pipeline_type:
            query = """
                SELECT * FROM "Stage_Master"
                WHERE pipeline_type = %s
                ORDER BY stage_order
            """
            params = (pipeline_type,)
        else:
            query = 'SELECT * FROM "Stage_Master" ORDER BY stage_order'
            params = None
        
        try:
            return self.db.execute_query(query, params)
        except Exception as e:
            print(f"Error fetching stages: {e}")
            return []


class ServiceRepository:
    """Repository for Services_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_services(self, tenant_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all services
        
        Args:
            tenant_id: Optional tenant filter
        
        Returns:
            List of service records
        """
        if tenant_id:
            query = """
                SELECT * FROM "Services_Master"
                WHERE tenant_id IS NULL OR tenant_id = %s
                ORDER BY service_name
            """
            params = (tenant_id,)
        else:
            query = 'SELECT * FROM "Services_Master" ORDER BY service_name'
            params = None
        
        try:
            return self.db.execute_query(query, params)
        except Exception as e:
            print(f"Error fetching services: {e}")
            return []


class SupplierRepository:
    """Repository for Supplier_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_suppliers(self, tenant_id: int) -> List[Dict[str, Any]]:
        """
        Get all suppliers for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            List of supplier records
        """
        query = """
            SELECT * FROM "Supplier_Master"
            WHERE tenant_id = %s
            ORDER BY supplier_name
        """
        
        try:
            return self.db.execute_query(query, (tenant_id,))
        except Exception as e:
            print(f"Error fetching suppliers: {e}")
            return []


class InteractionRepository:
    """Repository for Client_Interactions table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_interactions(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all client interactions for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (client_id, user_id, interaction_type)
        
        Returns:
            List of interaction records
        """
        query = """
            SELECT 
                ci.*,
                um.user_name as created_by_name
            FROM "Client_Interactions" ci
            LEFT JOIN "User_Master" um ON ci.created_by = um.user_id
            WHERE ci.tenant_id = %s
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('client_id'):
                query += " AND ci.client_id = %s"
                params.append(filters['client_id'])
            
            if filters.get('interaction_type'):
                query += " AND ci.interaction_type = %s"
                params.append(filters['interaction_type'])
            
            if filters.get('user_id'):
                query += " AND ci.created_by = %s"
                params.append(filters['user_id'])
        
        query += " ORDER BY ci.interaction_date DESC"
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching interactions: {e}")
            return []
    
    def get_interactions_by_opportunity(self, tenant_id: int, opportunity_id: int) -> List[Dict[str, Any]]:
        """
        Get all interactions related to an opportunity
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity identifier
        
        Returns:
            List of interaction records
        """
        query = """
            SELECT 
                ci.*,
                um.user_name as created_by_name
            FROM "Client_Interactions" ci
            LEFT JOIN "User_Master" um ON ci.created_by = um.user_id
            WHERE ci.tenant_id = %s
            AND ci.opportunity_id = %s
            ORDER BY ci.interaction_date DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, opportunity_id))
        except Exception as e:
            print(f"Error fetching interactions by opportunity: {e}")
            return []
