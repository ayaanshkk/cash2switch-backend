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
                sm."stage_name",
                um."user_name" as assigned_to_name,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE cm."tenant_id" = %s
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('stage_id'):
                query += ' AND od."stage_id" = %s'
                params.append(filters['stage_id'])
            
            if filters.get('status'):
                query += ' AND od."status" = %s'
                params.append(filters['status'])
            
            if filters.get('assigned_to'):
                query += ' AND od."opportunity_owner_employee_id" = %s'
                params.append(filters['assigned_to'])
        
        query += ' ORDER BY od."created_at" DESC'
        
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
                sm."stage_name",
                um."user_name" as assigned_to_name,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE cm."tenant_id" = %s
            AND od."opportunity_id" = %s
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
                sm."stage_name",
                um."user_name" as assigned_to_name,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE cm."tenant_id" = %s
            AND od."stage_id" = %s
            ORDER BY od."created_at" DESC
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
                SUM(od."opportunity_value") as total_value
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            WHERE cm."tenant_id" = %s
        """
        
        try:
            result = self.db.execute_query(query, (tenant_id,), fetch_one=True)
            return result or {
                'total_leads': 0,
                'total_value': 0
            }
        except Exception as e:
            print(f"Error fetching lead stats: {e}")
            return {
                'total_leads': 0,
                'total_value': 0
            }
    
    def create_lead(self, tenant_id: int, lead_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new lead/opportunity
        
        Args:
            tenant_id: Tenant identifier
            lead_data: Lead information (must include client_id that belongs to this tenant)
        
        Returns:
            Created lead record
        """
        # First validate that client_id belongs to this tenant
        client_check_query = """
            SELECT "client_id" FROM "StreemLyne_MT"."Client_Master"
            WHERE "client_id" = %s AND "tenant_id" = %s
        """
        
        try:
            client = self.db.execute_query(client_check_query, (lead_data.get('client_id'), tenant_id), fetch_one=True)
            if not client:
                print(f"Error: client_id {lead_data.get('client_id')} does not belong to tenant {tenant_id}")
                return None
            
            query = """
                INSERT INTO "StreemLyne_MT"."Opportunity_Details"
                ("client_id", "opportunity_title", "opportunity_description", 
                 "stage_id", "opportunity_value", "opportunity_owner_employee_id", "created_at")
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING *
            """
            
            return self.db.execute_insert(
                query,
                (
                    lead_data.get('client_id'),
                    lead_data.get('opportunity_title'),
                    lead_data.get('opportunity_description', ''),
                    lead_data.get('stage_id'),
                    lead_data.get('opportunity_value', 0),
                    lead_data.get('opportunity_owner_employee_id')
                ),
                returning=True
            )
        except Exception as e:
            print(f"Error creating lead: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_lead(self, opportunity_id: int, tenant_id: int, lead_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing lead
        
        Args:
            opportunity_id: Opportunity identifier
            tenant_id: Tenant identifier
            lead_data: Updated lead information
        
        Returns:
            Updated lead record
        """
        # Build dynamic update query based on provided fields
        update_fields = []
        params = []
        
        if 'opportunity_title' in lead_data and lead_data['opportunity_title'] is not None:
            update_fields.append('"opportunity_title" = %s')
            params.append(lead_data['opportunity_title'])
        
        if 'opportunity_description' in lead_data and lead_data['opportunity_description'] is not None:
            update_fields.append('"opportunity_description" = %s')
            params.append(lead_data['opportunity_description'])
        
        if 'stage_id' in lead_data and lead_data['stage_id'] is not None:
            update_fields.append('"stage_id" = %s')
            params.append(lead_data['stage_id'])
        
        if 'opportunity_value' in lead_data and lead_data['opportunity_value'] is not None:
            update_fields.append('"opportunity_value" = %s')
            params.append(lead_data['opportunity_value'])
        
        if 'opportunity_owner_employee_id' in lead_data and lead_data['opportunity_owner_employee_id'] is not None:
            update_fields.append('"opportunity_owner_employee_id" = %s')
            params.append(lead_data['opportunity_owner_employee_id'])
        
        if not update_fields:
            print("No fields to update")
            return self.get_lead_by_id(tenant_id, opportunity_id)
        
        # Validate tenant ownership through client_id
        query = f"""
            UPDATE "StreemLyne_MT"."Opportunity_Details" od
            SET {', '.join(update_fields)}
            FROM "StreemLyne_MT"."Client_Master" cm
            WHERE od."client_id" = cm."client_id"
            AND cm."tenant_id" = %s
            AND od."opportunity_id" = %s
            RETURNING od.*
        """
        
        params.extend([tenant_id, opportunity_id])
        
        try:
            result = self.db.execute_query(query, tuple(params), fetch_one=True)
            return result
        except Exception as e:
            print(f"Error updating lead: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def delete_lead(self, opportunity_id: int, tenant_id: int) -> bool:
        """
        Delete a lead/opportunity
        
        Args:
            opportunity_id: Opportunity identifier
            tenant_id: Tenant identifier
        
        Returns:
            True if deleted successfully
        """
        # Validate tenant ownership through client_id before deletion
        query = """
            DELETE FROM "StreemLyne_MT"."Opportunity_Details" od
            USING "StreemLyne_MT"."Client_Master" cm
            WHERE od."client_id" = cm."client_id"
            AND cm."tenant_id" = %s
            AND od."opportunity_id" = %s
        """
        
        try:
            rows_affected = self.db.execute_delete(query, (tenant_id, opportunity_id))
            return rows_affected > 0
        except Exception as e:
            print(f"Error deleting lead: {e}")
            import traceback
            traceback.print_exc()
            return False
