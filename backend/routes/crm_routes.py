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

@crm_bp.route('/leads/bulk-delete', methods=['POST'])
@require_tenant
def bulk_delete_leads():
    """
    Bulk delete multiple leads at once
    Automatically resets ID sequence to 1 if all leads are deleted
    
    Request Body:
        - opportunity_ids: List of opportunity IDs to delete (required)
    
    Example:
        {
            "opportunity_ids": [15, 16, 17, 18, 19, 20]
        }
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: {
            "success": true,
            "deleted": 6,
            "total_requested": 6,
            "errors": [],
            "message": "6 leads deleted successfully. ID sequence reset to 1."
        }
        400: Invalid request data
        500: Internal server error
    """
    return crm_controller.bulk_delete_leads()


@crm_bp.route('/leads/table', methods=['GET'])
@require_tenant
def get_leads_table():
    """
    Get leads table for CRM UI (flat rows: id, name, business_name, contact_person,
    tel_number, mpan_mpr, supplier, annual_usage, start_date, end_date, status,
    assigned_to, callback_parameter, call_summary).

    Headers:
        - X-Tenant-ID: Tenant identifier (required)

    Returns:
        200: { success, data, count }
        500: Internal server error
    """
    return crm_controller.get_leads_table()


@crm_bp.route('/leads/customer-type', methods=['GET'])
@require_tenant
def get_leads_by_customer_type():
    """
    Get leads filtered by customer type (NEW/EXISTING)
    
    Query Parameters:
        - type: 'NEW' or 'EXISTING' (optional, returns all if not specified)
        - stage_id: Filter by stage
        - lead_status: Filter by lead status
        - assigned_employee_id: Filter by assigned employee
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of leads with customer_type classification
        500: Internal server error
    """
    return crm_controller.get_leads_by_customer_type()

@crm_bp.route('/leads/<int:opportunity_id>/status', methods=['PATCH'])
@require_tenant
def update_lead_status(opportunity_id):
    """
    Update the status/stage of a lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Request Body:
        - stage_name: New stage name (e.g., "Called", "Priced", "Rejected", "Not Called")
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Lead status updated successfully
        404: Lead not found
        400: Invalid stage name
        500: Internal server error
    """
    return crm_controller.update_lead_status(opportunity_id)

@crm_bp.route('/priced', methods=['GET'])
@require_tenant
def get_priced_leads():
    """
    Get all priced leads for the current tenant
    These are leads with stage_name = 'Priced'
    
    Query Parameters:
        - assigned_to: Filter by assigned employee
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: List of priced leads
        500: Internal server error
    """
    return crm_controller.get_priced_leads()


@crm_bp.route('/priced/<int:opportunity_id>', methods=['GET'])
@require_tenant
def get_priced_lead_detail(opportunity_id):
    """
    Get details of a specific priced lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Priced lead details
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.get_priced_lead_detail(opportunity_id)


@crm_bp.route('/priced/<int:opportunity_id>/move-to-leads', methods=['PATCH'])
@require_tenant
def move_priced_to_leads(opportunity_id):
    """
    Move a priced lead back to leads page
    Changes stage from 'Priced' to 'Not Called'
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Lead moved back to leads page
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.move_priced_to_leads(opportunity_id)


@crm_bp.route('/priced/stats', methods=['GET'])
@require_tenant
def get_priced_stats():
    """
    Get statistics for priced leads
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: {
            "total_priced": 25,
            "total_value": 150000,
            "by_employee": {...}
        }
    """
    return crm_controller.get_priced_stats()


@crm_bp.route('/clients', methods=['POST'])
@require_tenant
def create_client():
    """
    Create a new client (Client_Master). Automatically inserts one record
    in Opportunity_Details so the client appears as a lead.

    Request Body:
        - client_company_name or business_name (required)
        - client_contact_name, client_phone, client_email, address, etc. (optional)

    Headers:
        - X-Tenant-ID: Tenant identifier (required)

    Returns:
        201: { success, data: { client, opportunity }, message }
        400: Validation error or missing body
        500: Internal server error
    """
    return crm_controller.create_client()


@crm_bp.route('/clients/<int:client_id>/call-summary', methods=['POST'])
@require_tenant
def create_call_summary(client_id):
    """
    Create a call summary/interaction record for a client
    
    Path Parameters:
        - client_id: Client identifier
    
    Request Body:
        - call_status: Call status (Phone, Email, Meeting, Other)
        - call_result: Result of the call
        - remarks: Additional remarks/notes
        - next_follow_up_date: Next follow-up date (YYYY-MM-DD)
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        201: Call summary created successfully
        400: Invalid request data
        500: Internal server error
    """
    return crm_controller.create_call_summary(client_id)


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

@crm_bp.route('/leads/import', methods=['POST'])
@require_tenant
def import_leads():
    """
    POST /api/crm/leads/import
    Bulk import leads from Excel/CSV file
    
    Request:
        - file: Excel (.xlsx, .xls) or CSV file
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Import results (total, successful, failed, errors)
        400: Invalid file or data
        500: Internal server error
    """
    return crm_controller.import_leads()


@crm_bp.route('/leads/import/template', methods=['GET'])
@require_tenant
def download_leads_template():
    """
    GET /api/crm/leads/import/template
    Download Excel template for bulk lead import
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        200: Excel file download
        500: Internal server error
    """
    return crm_controller.download_leads_template()
