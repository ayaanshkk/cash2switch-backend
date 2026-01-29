# -*- coding: utf-8 -*-
"""
Deal/Contract Repository
Handles database operations for Energy_Contract_Master table
"""
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client


class DealRepository:
    """
    Repository for Energy_Contract_Master table (CRM Deals/Contracts)
    All queries are tenant-filtered for multi-tenant isolation
    """
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_deals(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all deals/contracts for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (status, etc.)
        
        Returns:
            List of contract records
        """
        query = """
            SELECT 
                ecm.*,
                um."user_name" as owner_name
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON ecm."contract_owner_id" = um."User_id"
            WHERE ecm."Tenant_id" = %s
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('status'):
                query += ' AND ecm."contract_status" = %s'
                params.append(filters['status'])
            
            if filters.get('contract_owner_id'):
                query += ' AND ecm."contract_owner_id" = %s'
                params.append(filters['contract_owner_id'])
        
        query += ' ORDER BY ecm."created_at" DESC'
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching deals for tenant {tenant_id}: {e}")
            return []
    
    def get_deal_by_id(self, tenant_id: int, contract_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific deal/contract by ID (with tenant isolation)
        
        Args:
            tenant_id: Tenant identifier
            contract_id: Contract identifier
        
        Returns:
            Contract record or None
        """
        query = """
            SELECT 
                ecm.*,
                um."user_name" as owner_name
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON ecm."contract_owner_id" = um."User_id"
            WHERE ecm."Tenant_id" = %s
            AND ecm."Contract_id" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, contract_id), fetch_one=True)
        except Exception as e:
            print(f"Error fetching deal {contract_id}: {e}")
            return None
    
    def get_deal_stats(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get deal/contract statistics for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with deal statistics
        """
        query = """
            SELECT 
                COUNT(*) as total_contracts,
                COUNT(CASE WHEN "contract_status" = 'Active' THEN 1 END) as active_contracts,
                COUNT(CASE WHEN "contract_status" = 'Pending' THEN 1 END) as pending_contracts,
                COUNT(CASE WHEN "contract_status" = 'Expired' THEN 1 END) as expired_contracts,
                SUM(CASE WHEN "contract_status" = 'Active' THEN "contract_value" ELSE 0 END) as active_value
            FROM "StreemLyne_MT"."Energy_Contract_Master"
            WHERE "Tenant_id" = %s
        """
        
        try:
            result = self.db.execute_query(query, (tenant_id,), fetch_one=True)
            return result or {
                'total_contracts': 0,
                'active_contracts': 0,
                'pending_contracts': 0,
                'expired_contracts': 0,
                'active_value': 0
            }
        except Exception as e:
            print(f"Error fetching deal stats: {e}")
            return {
                'total_contracts': 0,
                'active_contracts': 0,
                'pending_contracts': 0,
                'expired_contracts': 0,
                'active_value': 0
            }
