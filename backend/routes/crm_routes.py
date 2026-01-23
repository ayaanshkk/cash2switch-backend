# -*- coding: utf-8 -*-
"""
CRM Routes Blueprint
Defines API endpoints for CRM module
"""
from flask import Blueprint
from backend.crm.controllers.crm_controller import CRMController
from backend.crm.middleware.tenant_middleware import require_tenant

# Create blueprint
crm_bp = Blueprint('crm', __name__, url_prefix='/api/crm')

# Initialize controller
crm_controller = CRMController()

# ========================================
# LEAD ROUTES
# ========================================

@crm_bp.route('/leads', methods=['GET'])
@require_tenant
def get_leads():
    """
    Get all leads for the current tenant
    
    Query Parameters:
        - stage_id: Filter by stage
        - status: Filter by status (Open, Won, Lost)
        - assigned_to: Filter by assigned user
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of leads with statistics
        400: Missing or invalid tenant ID
        404: Tenant not found
        500: Internal server error
    """
    return crm_controller.get_leads()


@crm_bp.route('/leads/<int:opportunity_id>', methods=['GET'])
@require_tenant
def get_lead_detail(opportunity_id):
    """
    Get details of a specific lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Lead details with related interactions
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.get_lead_detail(opportunity_id)


@crm_bp.route('/leads', methods=['POST'])
@require_tenant
def create_lead():
    """
    Create a new lead
    
    Request Body:
        - opportunity_name: Lead/opportunity name (required)
        - client_name: Client name (required)
        - stage_id: Stage identifier (optional)
        - status: Lead status (optional, default: 'Open')
        - estimated_value: Estimated value (optional)
        - assigned_to: Assigned user ID (optional)
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        201: Lead created successfully
        400: Invalid request data
        500: Internal server error
    """
    return crm_controller.create_lead()


@crm_bp.route('/leads/<int:opportunity_id>', methods=['PUT'])
@require_tenant
def update_lead(opportunity_id):
    """
    Update an existing lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Request Body:
        - opportunity_name: Lead/opportunity name (optional)
        - client_name: Client name (optional)
        - stage_id: Stage identifier (optional)
        - status: Lead status (optional)
        - estimated_value: Estimated value (optional)
        - assigned_to: Assigned user ID (optional)
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Lead updated successfully
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.update_lead(opportunity_id)


@crm_bp.route('/leads/<int:opportunity_id>', methods=['DELETE'])
@require_tenant
def delete_lead(opportunity_id):
    """
    Delete a lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Lead deleted successfully
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.delete_lead(opportunity_id)


# ========================================
# PROJECT ROUTES
# ========================================

@crm_bp.route('/projects', methods=['GET'])
@require_tenant
def get_projects():
    """
    Get all projects for the current tenant
    
    Query Parameters:
        - status: Filter by project status
        - project_manager_id: Filter by project manager
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of projects with statistics
        500: Internal server error
    """
    return crm_controller.get_projects()


@crm_bp.route('/projects/<int:project_id>', methods=['GET'])
@require_tenant
def get_project_detail(project_id):
    """
    Get details of a specific project
    
    Path Parameters:
        - project_id: Project identifier
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Project details
        404: Project not found
        500: Internal server error
    """
    return crm_controller.get_project_detail(project_id)


# ========================================
# DEAL/CONTRACT ROUTES
# ========================================

@crm_bp.route('/deals', methods=['GET'])
@require_tenant
def get_deals():
    """
    Get all deals/contracts for the current tenant
    
    Query Parameters:
        - status: Filter by contract status
        - contract_owner_id: Filter by owner
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of deals with statistics
        500: Internal server error
    """
    return crm_controller.get_deals()


@crm_bp.route('/deals/<int:contract_id>', methods=['GET'])
@require_tenant
def get_deal_detail(contract_id):
    """
    Get details of a specific deal
    
    Path Parameters:
        - contract_id: Contract identifier
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Deal details
        404: Deal not found
        500: Internal server error
    """
    return crm_controller.get_deal_detail(contract_id)


# ========================================
# USER ROUTES
# ========================================

@crm_bp.route('/users', methods=['GET'])
@require_tenant
def get_users():
    """
    Get all users for the current tenant
    
    Query Parameters:
        - active_only: Filter active users only (default: true)
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of users
        500: Internal server error
    """
    return crm_controller.get_users()


# ========================================
# SUPPORTING DATA ROUTES
# ========================================

@crm_bp.route('/roles', methods=['GET'])
def get_roles():
    """
    Get all roles (system + tenant-specific)
    
    Returns:
        200: List of roles
        500: Internal server error
    """
    return crm_controller.get_roles()


@crm_bp.route('/stages', methods=['GET'])
def get_stages():
    """
    Get all pipeline stages
    
    Query Parameters:
        - pipeline_type: Filter by pipeline type
    
    Returns:
        200: List of stages
        500: Internal server error
    """
    return crm_controller.get_stages()


@crm_bp.route('/services', methods=['GET'])
def get_services():
    """
    Get all services
    
    Returns:
        200: List of services
        500: Internal server error
    """
    return crm_controller.get_services()


@crm_bp.route('/suppliers', methods=['GET'])
@require_tenant
def get_suppliers():
    """
    Get all suppliers for the current tenant
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of suppliers
        500: Internal server error
    """
    return crm_controller.get_suppliers()


@crm_bp.route('/interactions', methods=['GET'])
@require_tenant
def get_interactions():
    """
    Get all client interactions for the current tenant
    
    Query Parameters:
        - client_id: Filter by client
        - interaction_type: Filter by interaction type
        - user_id: Filter by user
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of interactions
        500: Internal server error
    """
    return crm_controller.get_interactions()


# ========================================
# DASHBOARD ROUTE
# ========================================

@crm_bp.route('/dashboard', methods=['GET'])
@require_tenant
def get_dashboard():
    """
    Get CRM dashboard summary with key metrics
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Dashboard metrics (leads, projects, deals statistics)
        500: Internal server error
    """
    return crm_controller.get_dashboard()


# ========================================
# HEALTH CHECK
# ========================================

@crm_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for CRM module
    
    Returns:
        200: CRM module is operational
    """
    return {
        'success': True,
        'module': 'CRM',
        'status': 'operational',
        'message': 'StreemLyne CRM module is running'
    }, 200


@crm_bp.route('/debug/tenant/<int:tenant_id>', methods=['GET'])
def debug_tenant_lookup(tenant_id):
    """Debug endpoint to test tenant lookup directly (NO middleware)"""
    try:
        from backend.crm.repositories.tenant_repository import TenantRepository
        repo = TenantRepository()
        tenant = repo.get_tenant_by_id(tenant_id)
        
        return {
            'success': True if tenant else False,
            'tenant_id_requested': tenant_id,
            'tenant_found': tenant is not None,
            'tenant_data': tenant,
            'message': 'Direct lookup (no middleware)'
        }, 200 if tenant else 404
    except Exception as e:
        import traceback
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, 500

