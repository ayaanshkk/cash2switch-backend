# -*- coding: utf-8 -*-
"""
Lead/Opportunity Repository
Handles database operations for Opportunity_Details table
"""
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client


class LeadRepository:
    """
    Repository for Opportunity_Details table (CRM Leads)
    All queries are tenant-filtered for multi-tenant isolation
    """
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_leads(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all leads for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (stage, status, assigned_to, etc.)
        
        Returns:
            List of lead/opportunity records
        """
        query = """
            SELECT 
                od.*,
                sm.stage_name,
                um.user_name as assigned_to_name
            FROM "Opportunity_Details" od
            LEFT JOIN "Stage_Master" sm ON od.stage_id = sm.stage_id
            LEFT JOIN "User_Master" um ON od.assigned_to = um.user_id
            WHERE od.tenant_id = %s
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('stage_id'):
                query += " AND od.stage_id = %s"
                params.append(filters['stage_id'])
            
            if filters.get('status'):
                query += " AND od.status = %s"
                params.append(filters['status'])
            
            if filters.get('assigned_to'):
                query += " AND od.assigned_to = %s"
                params.append(filters['assigned_to'])
        
        query += " ORDER BY od.created_at DESC"
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching leads for tenant {tenant_id}: {e}")
            return []
    
    def get_lead_by_id(self, tenant_id: int, opportunity_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific lead by ID (with tenant isolation)
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity/Lead identifier
        
        Returns:
            Lead record or None
        """
        query = """
            SELECT 
                od.*,
                sm.stage_name,
                um.user_name as assigned_to_name
            FROM "Opportunity_Details" od
            LEFT JOIN "Stage_Master" sm ON od.stage_id = sm.stage_id
            LEFT JOIN "User_Master" um ON od.assigned_to = um.user_id
            WHERE od.tenant_id = %s
            AND od.opportunity_id = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, opportunity_id), fetch_one=True)
        except Exception as e:
            print(f"Error fetching lead {opportunity_id}: {e}")
            return None
    
    def get_leads_by_stage(self, tenant_id: int, stage_id: int) -> List[Dict[str, Any]]:
        """
        Get all leads in a specific pipeline stage
        
        Args:
            tenant_id: Tenant identifier
            stage_id: Stage identifier
        
        Returns:
            List of leads in the specified stage
        """
        query = """
            SELECT 
                od.*,
                sm.stage_name,
                um.user_name as assigned_to_name
            FROM "Opportunity_Details" od
            LEFT JOIN "Stage_Master" sm ON od.stage_id = sm.stage_id
            LEFT JOIN "User_Master" um ON od.assigned_to = um.user_id
            WHERE od.tenant_id = %s
            AND od.stage_id = %s
            ORDER BY od.created_at DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, stage_id))
        except Exception as e:
            print(f"Error fetching leads by stage: {e}")
            return []
    
    def get_lead_stats(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get lead statistics for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with lead statistics
        """
        query = """
            SELECT 
                COUNT(*) as total_leads,
                COUNT(CASE WHEN status = 'Open' THEN 1 END) as open_leads,
                COUNT(CASE WHEN status = 'Won' THEN 1 END) as won_leads,
                COUNT(CASE WHEN status = 'Lost' THEN 1 END) as lost_leads,
                SUM(CASE WHEN status = 'Won' THEN estimated_value ELSE 0 END) as won_value,
                SUM(estimated_value) as total_value
            FROM "Opportunity_Details"
            WHERE tenant_id = %s
        """
        
        try:
            result = self.db.execute_query(query, (tenant_id,), fetch_one=True)
            return result or {
                'total_leads': 0,
                'open_leads': 0,
                'won_leads': 0,
                'lost_leads': 0,
                'won_value': 0,
                'total_value': 0
            }
        except Exception as e:
            print(f"Error fetching lead stats: {e}")
            return {
                'total_leads': 0,
                'open_leads': 0,
                'won_leads': 0,
                'lost_leads': 0,
                'won_value': 0,
                'total_value': 0
            }
