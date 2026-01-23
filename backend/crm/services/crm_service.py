# -*- coding: utf-8 -*-
"""
CRM Services
Business logic layer for CRM operations
"""
from typing import Optional, Dict, Any, List
from backend.crm.repositories.lead_repository import LeadRepository
from backend.crm.repositories.project_repository import ProjectRepository
from backend.crm.repositories.deal_repository import DealRepository
from backend.crm.repositories.user_repository import UserRepository
from backend.crm.repositories.additional_repositories import (
    RoleRepository, StageRepository, ServiceRepository, 
    SupplierRepository, InteractionRepository
)


class CRMService:
    """
    Central CRM Service
    Handles business logic for all CRM operations
    """
    
    def __init__(self):
        self.lead_repo = LeadRepository()
        self.project_repo = ProjectRepository()
        self.deal_repo = DealRepository()
        self.user_repo = UserRepository()
        self.role_repo = RoleRepository()
        self.stage_repo = StageRepository()
        self.service_repo = ServiceRepository()
        self.supplier_repo = SupplierRepository()
        self.interaction_repo = InteractionRepository()
    
    # ========================================
    # LEAD OPERATIONS
    # ========================================
    
    def get_leads(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get all leads for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters
        
        Returns:
            Dictionary with leads data
        """
        leads = self.lead_repo.get_all_leads(tenant_id, filters)
        stats = self.lead_repo.get_lead_stats(tenant_id)
        
        return {
            'success': True,
            'data': leads,
            'stats': stats,
            'count': len(leads)
        }
    
    def get_lead_detail(self, tenant_id: int, opportunity_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a specific lead
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
        
        Returns:
            Dictionary with lead details
        """
        lead = self.lead_repo.get_lead_by_id(tenant_id, opportunity_id)
        
        if not lead:
            return {
                'success': False,
                'error': 'Lead not found',
                'message': f'No lead found with ID {opportunity_id}'
            }
        
        # Get related interactions
        interactions = self.interaction_repo.get_interactions_by_opportunity(tenant_id, opportunity_id)
        
        return {
            'success': True,
            'data': lead,
            'interactions': interactions
        }
    
    # ========================================
    # PROJECT OPERATIONS
    # ========================================
    
    def get_projects(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get all projects for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters
        
        Returns:
            Dictionary with projects data
        """
        projects = self.project_repo.get_all_projects(tenant_id, filters)
        stats = self.project_repo.get_project_stats(tenant_id)
        
        return {
            'success': True,
            'data': projects,
            'stats': stats,
            'count': len(projects)
        }
    
    def get_project_detail(self, tenant_id: int, project_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a specific project
        
        Args:
            tenant_id: Tenant identifier
            project_id: Project ID
        
        Returns:
            Dictionary with project details
        """
        project = self.project_repo.get_project_by_id(tenant_id, project_id)
        
        if not project:
            return {
                'success': False,
                'error': 'Project not found',
                'message': f'No project found with ID {project_id}'
            }
        
        return {
            'success': True,
            'data': project
        }
    
    # ========================================
    # DEAL OPERATIONS
    # ========================================
    
    def get_deals(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get all deals/contracts for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters
        
        Returns:
            Dictionary with deals data
        """
        deals = self.deal_repo.get_all_deals(tenant_id, filters)
        stats = self.deal_repo.get_deal_stats(tenant_id)
        
        return {
            'success': True,
            'data': deals,
            'stats': stats,
            'count': len(deals)
        }
    
    def get_deal_detail(self, tenant_id: int, contract_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a specific deal
        
        Args:
            tenant_id: Tenant identifier
            contract_id: Contract ID
        
        Returns:
            Dictionary with deal details
        """
        deal = self.deal_repo.get_deal_by_id(tenant_id, contract_id)
        
        if not deal:
            return {
                'success': False,
                'error': 'Deal not found',
                'message': f'No deal found with ID {contract_id}'
            }
        
        return {
            'success': True,
            'data': deal
        }
    
    # ========================================
    # USER OPERATIONS
    # ========================================
    
    def get_users(self, tenant_id: int, active_only: bool = True) -> Dict[str, Any]:
        """
        Get all users for a tenant
        
        Args:
            tenant_id: Tenant identifier
            active_only: Filter active users only
        
        Returns:
            Dictionary with users data
        """
        users = self.user_repo.get_all_users(tenant_id, active_only)
        
        return {
            'success': True,
            'data': users,
            'count': len(users)
        }
    
    # ========================================
    # SUPPORTING DATA OPERATIONS
    # ========================================
    
    def get_roles(self, tenant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get all roles"""
        roles = self.role_repo.get_all_roles(tenant_id)
        return {
            'success': True,
            'data': roles,
            'count': len(roles)
        }
    
    def get_stages(self, pipeline_type: Optional[str] = None) -> Dict[str, Any]:
        """Get all pipeline stages"""
        stages = self.stage_repo.get_all_stages(pipeline_type)
        return {
            'success': True,
            'data': stages,
            'count': len(stages)
        }
    
    def get_services(self, tenant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get all services"""
        services = self.service_repo.get_all_services(tenant_id)
        return {
            'success': True,
            'data': services,
            'count': len(services)
        }
    
    def get_suppliers(self, tenant_id: int) -> Dict[str, Any]:
        """Get all suppliers for a tenant"""
        suppliers = self.supplier_repo.get_all_suppliers(tenant_id)
        return {
            'success': True,
            'data': suppliers,
            'count': len(suppliers)
        }
    
    def get_interactions(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get all client interactions for a tenant"""
        interactions = self.interaction_repo.get_all_interactions(tenant_id, filters)
        return {
            'success': True,
            'data': interactions,
            'count': len(interactions)
        }
    
    # ========================================
    # DASHBOARD & ANALYTICS
    # ========================================
    
    def get_dashboard_summary(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get CRM dashboard summary with key metrics
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with dashboard metrics
        """
        lead_stats = self.lead_repo.get_lead_stats(tenant_id)
        project_stats = self.project_repo.get_project_stats(tenant_id)
        deal_stats = self.deal_repo.get_deal_stats(tenant_id)
        
        return {
            'success': True,
            'data': {
                'leads': lead_stats,
                'projects': project_stats,
                'deals': deal_stats
            }
        }
