# -*- coding: utf-8 -*-
"""
CRM Routes Blueprint
Defines API endpoints for CRM module
"""
from flask import Blueprint, request, g, jsonify
from functools import wraps
from backend.crm.controllers.crm_controller import CRMController
from backend.crm.middleware.tenant_middleware import require_tenant
from .auth_helpers import token_required

# Lightweight helper: attach tenant_id from decoded JWT to `g` (no new auth logic)
def tenant_from_jwt(f):
    """Set g.tenant_id from request.current_user.tenant_id (returns 401 if missing).

    This is a thin wiring decorator that relies on the existing `token_required`
    to populate `request.current_user`. It does NOT perform authentication itself.
    """
    @wraps(f)
    def _wrap(*args, **kwargs):
        current_user = getattr(request, 'current_user', None)
        if not current_user or getattr(current_user, 'tenant_id', None) is None:
            return jsonify({
                'error': 'Missing tenant in token',
                'message': 'Authenticated token must include tenant_id'
            }), 401
        # Propagate tenant_id to Flask `g` for downstream code that expects it
        g.tenant_id = getattr(current_user, 'tenant_id')
        return f(*args, **kwargs)
    return _wrap

# Create blueprint
crm_bp = Blueprint('crm', __name__, url_prefix='/api/crm')

# Initialize controller
crm_controller = CRMController()

# ========================================
# LEAD ROUTES
# ========================================

@crm_bp.route('/leads', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads():
    """
    Get all leads for the current tenant
    
    Query Parameters:
        - stage_id: Filter by stage
        - status: Filter by status (Open, Won, Lost)
        - assigned_to: Filter by assigned user
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: List of leads with statistics
        401: Missing tenant in token
        404: Tenant not found
        500: Internal server error
    """
    return crm_controller.get_leads()


@crm_bp.route('/leads/<int:opportunity_id>', methods=['GET'])
@token_required
@tenant_from_jwt
def get_lead_detail(opportunity_id):
    """
    Get details of a specific lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: Lead details with related interactions
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.get_lead_detail(opportunity_id)


@crm_bp.route('/leads', methods=['POST'])
@token_required
@tenant_from_jwt
def create_lead():
    """
    Create a new lead
    
    Request Body:
        - opportunity_name: Lead/opportunity name (required)
        - client_name: Client name (required)
        - stage_id: Stage identifier (optional)
        - status: Lead status (optional)
        - estimated_value: Estimated value (optional)
        - assigned_to: Assigned user ID (optional)
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        201: Lead created successfully
        400: Invalid request data
        500: Internal server error
    """
    return crm_controller.create_lead()


@crm_bp.route('/leads/<int:opportunity_id>', methods=['PUT'])
@token_required
@tenant_from_jwt
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
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: Lead updated successfully
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.update_lead(opportunity_id)


@crm_bp.route('/leads/<int:opportunity_id>/status', methods=['PATCH'])
@token_required
@tenant_from_jwt
def update_lead_status(opportunity_id):
    """
    Update lead status (stage_id) only.
    When stage becomes 'Lost', lead is soft-deleted (deleted_at=NOW()).
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Request Body:
        { "stage_id": <number> }
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: Status updated successfully
        400: Missing or invalid stage_id
        404: Lead not found or access denied
        500: Internal server error
    """
    return crm_controller.update_lead_status(opportunity_id)


@crm_bp.route('/leads/<int:opportunity_id>', methods=['DELETE'])
@token_required
@tenant_from_jwt
def delete_lead(opportunity_id):
    """
    Delete a lead
    
    Path Parameters:
        - opportunity_id: Opportunity identifier
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: Lead deleted successfully
        404: Lead not found
        500: Internal server error
    """
    return crm_controller.delete_lead(opportunity_id)


@crm_bp.route('/leads/table', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_table():
    """
    Get leads table for CRM UI (flat rows: id, name, business_name, contact_person,
    tel_number, mpan_mpr, supplier, annual_usage, start_date, end_date, status,
    assigned_to, callback_parameter, call_summary).

    Authentication:
        - JWT (token must include `tenant_id`)

    Returns:
        200: { success, data, count }
        500: Internal server error
    """
    return crm_controller.get_leads_table()


@crm_bp.route('/leads/import/preview', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads_preview():
    """
    POST /api/crm/leads/import/preview
    Accepts multipart/form-data with an Excel (.xlsx) or CSV (.csv) file and
    returns a validation preview (no DB writes).

    Notes:
      - Tenant is derived from the authenticated JWT (request.current_user.tenant_id)
      - Frontend must NOT send `X-Tenant-ID`

    Request:
      - file: file to import

    Returns:
      200: preview JSON (see API docs)
      400: invalid request / unsupported file
    """
    return crm_controller.import_leads_preview()


@crm_bp.route('/leads/import/confirm', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads_confirm():
    """
    POST /api/crm/leads/import/confirm
    Accepts JSON array (validated rows from preview) and inserts Opportunity_Details
    where possible. Partial success allowed; duplicates/skipped rows reported.

    Notes:
      - Tenant is derived from the authenticated JWT (request.current_user.tenant_id)
      - Frontend must NOT send `X-Tenant-ID`

    Request body: [ { row_number, data: {...}, is_valid, errors }, ... ]

    Returns:
      200: { success, inserted, skipped, errors }
      400: invalid request
    """
    return crm_controller.import_leads_confirm()


@crm_bp.route('/leads/recycle-bin', methods=['GET'])
@token_required
@tenant_from_jwt
def get_recycle_bin():
    """
    Get all soft-deleted (Lost) leads for the tenant.
    
    Query Parameters:
        - None
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: { success, data, count } - List of deleted leads with deleted_at timestamp
        500: Internal server error
    """
    return crm_controller.get_recycle_bin()


@crm_bp.route('/leads/cleanup', methods=['PATCH'])
@token_required
@tenant_from_jwt
def delete_expired_lost_leads():
    """
    Permanently delete Lost leads older than N days.
    Admin operation (controlled by token_required + tenant_from_jwt).
    
    Request Body (optional):
        { "days": 30 }  # Default: 30 days. Records with deleted_at < NOW() - INTERVAL will be permanently removed.
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: { success, deleted_count, message }
        500: Internal server error
    """
    return crm_controller.delete_expired_lost_leads()


@crm_bp.route('/leads/import', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads():
    """
    POST /api/crm/leads/import
    Single-step import: accepts file, validates, and imports in one request.
    Compatible with BulkImportModal component.

    Request:
      - file: Excel (.xlsx, .xls) or CSV file

    Returns:
      200: {
        success: bool,
        message: str,
        total_rows: int,
        successful: int,
        failed: int,
        errors: list[str]
      }
    """
    try:
        tenant_id = g.tenant_id
        
        # Check if file is provided
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file provided',
                'total_rows': 0,
                'successful': 0,
                'failed': 1,
                'errors': ['No file uploaded']
            }), 400

        file = request.files.get('file')
        
        # Debug
        print(f"DEBUG: File received - {file.filename if file else 'None'}")
        
        # Step 1: Validate and preview
        preview_result = crm_controller.crm_service.preview_lead_import(tenant_id, file)
        
        # Debug preview result
        print(f"DEBUG: Preview result: success={preview_result.get('success')}, valid_rows={preview_result.get('valid_rows')}, total_rows={preview_result.get('total_rows')}")
        
        if not preview_result.get('success'):
            return jsonify({
                'success': False,
                'message': preview_result.get('message', 'Validation failed'),
                'total_rows': preview_result.get('total_rows', 0),
                'successful': 0,
                'failed': preview_result.get('total_rows', 1),
                'errors': preview_result.get('errors', ['Validation failed'])
            }), 400
        
        # If no valid rows, return early
        valid_rows = preview_result.get('valid_rows', 0)
        if valid_rows == 0:
            return jsonify({
                'success': False,
                'message': 'No valid rows to import',
                'total_rows': preview_result.get('total_rows', 0),
                'successful': 0,
                'failed': preview_result.get('invalid_rows', 0),
                'errors': preview_result.get('errors', ['No valid data found'])
            }), 400
        
        # Step 2: Import the validated rows directly
        # preview_result contains 'rows' with structure: {'row_number', 'data', 'is_valid', 'errors'}
        # We need to extract only valid rows and their 'data' field
        all_rows = preview_result.get('rows', [])
        validated_data = [row['data'] for row in all_rows if row.get('is_valid', False)]
        
        created_by = getattr(request.current_user, 'id', None)
        
        # Debug: print what we're sending
        print(f"DEBUG: validated_data type={type(validated_data)}, length={len(validated_data) if isinstance(validated_data, list) else 'N/A'}")
        if validated_data and isinstance(validated_data, list):
            print(f"DEBUG: First row keys: {list(validated_data[0].keys()) if validated_data else 'empty'}")
        
        confirm_result = crm_controller.crm_service.confirm_lead_import(tenant_id, validated_data, created_by)
        
        # Check if confirm returned an error (has 'success':False key)
        if 'success' in confirm_result and not confirm_result['success']:
            return jsonify({
                'success': False,
                'message': confirm_result.get('message', 'Import failed'),
                'total_rows': preview_result.get('total_rows', 0),
                'successful': 0,
                'failed': preview_result.get('total_rows', 0),
                'errors': [confirm_result.get('error', 'Import failed')]
            }), 400
        
        # Format response to match BulkImportModal expectations
        inserted = confirm_result.get('inserted', 0)
        skipped = confirm_result.get('skipped', 0)
        
        return jsonify({
            'success': inserted > 0 or skipped == preview_result.get('total_rows', 0),
            'message': f"Successfully imported {inserted} lead(s)" if inserted > 0 else "No new leads imported",
            'total_rows': preview_result.get('total_rows', 0),
            'successful': inserted,
            'failed': skipped,
            'errors': confirm_result.get('errors', [])
        }), 200
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': str(e),
            'total_rows': 0,
            'successful': 0,
            'failed': 1,
            'errors': [str(e)]
        }), 500


@crm_bp.route('/leads/import/template', methods=['GET'])
def download_leads_template():
    """
    GET /api/crm/leads/import/template
    Downloads an Excel template for lead imports.
    No authentication required for template download.
    
    Returns:
      200: Excel file with headers and example data
    """
    try:
        from flask import send_file
        from openpyxl import Workbook
        from io import BytesIO
        
        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Leads Import"
        
        # Headers (match the expected column names from validation)
        headers = [
            'Business Name', 'Contact Person', 'Tel Number', 'Email',
            'MPAN_MPR', 'Start Date', 'End Date', 'Annual Usage',
            'Address', 'Site Address'
        ]
        ws.append(headers)
        
        # Example data
        ws.append([
            'Acme Corp', 'John Doe', '0207123456', 'john@acme.com',
            '1234567890123', '2024-01-01', '2025-01-01', '50000',
            '123 Main St, London', '456 Business Park, London'
        ])
        ws.append([
            'Tech Solutions Ltd', 'Jane Smith', '0207987654', 'jane@techsolutions.co.uk',
            '9876543210987', '2024-06-01', '2025-06-01', '75000',
            '789 Tech Ave, Manchester', '789 Tech Ave, Manchester'
        ])
        
        # Style headers
        from openpyxl.styles import Font, PatternFill
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        
        # Auto-size columns
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='leads_import_template.xlsx'
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/customer-type', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_by_customer_type():
    """
    Get leads filtered by customer type (NEW/EXISTING)
    
    Query Parameters:
        - type: 'NEW' or 'EXISTING' (optional, returns all if not specified)
        - stage_id: Filter by stage
        - lead_status: Filter by lead status
        - assigned_employee_id: Filter by assigned employee
    
    Notes:
        - Tenant is derived from the authenticated JWT (request.current_user.tenant_id)
        - Do not send `X-Tenant-ID` for Leads endpoints
    
    Returns:
        200: List of leads with customer_type classification
        500: Internal server error
    """
    return crm_controller.get_leads_by_customer_type()


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
@token_required
def get_stages():
    """
    Get all pipeline stages
    
    Query Parameters:
        - pipeline_type: Filter by pipeline type (lead, sales, training)
    
    Returns:
        200: List of stages with stage_id and stage_name
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

