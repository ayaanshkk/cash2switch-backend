# -*- coding: utf-8 -*-
"""
Project Repository
Handles database operations for Project_Details table
"""
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client


class ProjectRepository:
    """
    Repository for Project_Details table (CRM Projects/Sites)
    All queries are tenant-filtered for multi-tenant isolation
    """
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_projects(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all projects for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (status, assigned_to, etc.)
        
        Returns:
            List of project records
        """
        query = """
            SELECT 
                pd.*,
                um."user_name" as project_manager_name
            FROM "StreemLyne_MT"."Project_Details" pd
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON pd."project_manager_id" = um."User_id"
            WHERE pd."Tenant_id" = %s
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('status'):
                query += ' AND pd."project_status" = %s'
                params.append(filters['status'])
            
            if filters.get('project_manager_id'):
                query += ' AND pd."project_manager_id" = %s'
                params.append(filters['project_manager_id'])
        
        query += ' ORDER BY pd."created_at" DESC'
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching projects for tenant {tenant_id}: {e}")
            return []
    
    def get_project_by_id(self, tenant_id: int, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific project by ID (with tenant isolation)
        
        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier
        
        Returns:
            Project record or None
        """
        query = """
            SELECT 
                pd.*,
                um."user_name" as project_manager_name
            FROM "StreemLyne_MT"."Project_Details" pd
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON pd."project_manager_id" = um."User_id"
            WHERE pd."Tenant_id" = %s
            AND pd."Project_id" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, project_id), fetch_one=True)
        except Exception as e:
            print(f"Error fetching project {project_id}: {e}")
            return None
    
    def get_project_stats(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get project statistics for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with project statistics
        """
        query = """
            SELECT 
                COUNT(*) as total_projects,
                COUNT(CASE WHEN "project_status" = 'Active' THEN 1 END) as active_projects,
                COUNT(CASE WHEN "project_status" = 'Completed' THEN 1 END) as completed_projects,
                COUNT(CASE WHEN "project_status" = 'On Hold' THEN 1 END) as onhold_projects
            FROM "StreemLyne_MT"."Project_Details"
            WHERE "Tenant_id" = %s
        """
        
        try:
            result = self.db.execute_query(query, (tenant_id,), fetch_one=True)
            return result or {
                'total_projects': 0,
                'active_projects': 0,
                'completed_projects': 0,
                'onhold_projects': 0
            }
        except Exception as e:
            print(f"Error fetching project stats: {e}")
            return {
                'total_projects': 0,
                'active_projects': 0,
                'completed_projects': 0,
                'onhold_projects': 0
            }
