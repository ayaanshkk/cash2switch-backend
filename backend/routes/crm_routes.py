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
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        exclude_stage = request.args.get('exclude_stage', '')
        
        employee_id = getattr(current_user, 'employee_id', None)

        import logging
        logging.getLogger(__name__).warning(
            '🔍 get_leads: employee_id=%s tenant=%s service=%s',
            employee_id, tenant_id, service_param
        )

        db = get_supabase_client()

        query = '''
            SELECT
                od.*,
                sm."stage_name",
                em."employee_name"          AS assigned_to_name,
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                sup."supplier_company_name" AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od."stage_id"    = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id"  = sup."supplier_id"
            WHERE od."tenant_id" = %s
            AND od."service_id" = %s
        '''
        params = [tenant_id, service_id]

        # ✅ COPY EXACT LOGIC FROM RENEWALS (customer_routes.py line 93-99)
        # EVERYONE (including admins) only sees their own NON-ALLOCATED leads
        if not employee_id:
            logging.getLogger(__name__).warning('⚠️ User has no employee_id - returning empty')
            return jsonify([]), 200
        
        query += '''
            AND od."opportunity_owner_employee_id" = %s
            AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
        '''
        params.extend([employee_id])

        if exclude_stage:
            query += ' AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != LOWER(%s))'
            params.append(exclude_stage)

        query += ' ORDER BY od."created_at" DESC'

        rows = db.execute_query(query, tuple(params))

        def _s(v):
            if v is None: return None
            if hasattr(v, 'isoformat'): return v.isoformat()
            try:
                from decimal import Decimal
                if isinstance(v, Decimal): return float(v)
            except ImportError:
                pass
            return v

        results = [{k: _s(v) for k, v in row.items()} for row in (rows or [])]
        
        logging.getLogger(__name__).warning(
            '✅ get_leads returning %d leads for employee_id=%s',
            len(results), employee_id
        )
        
        return jsonify(results), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/<int:opportunity_id>', methods=['GET'])
@token_required
@tenant_from_jwt
def get_lead_detail(opportunity_id):
    """
    GET /api/crm/leads/<id>
    Accepts both tenant_lead_id (the display ID in the URL) and opportunity_id.
    Tries tenant_lead_id first, then falls back to opportunity_id.
    """
    from backend.crm.supabase_client import get_supabase_client
 
    try:
        tenant_id = g.tenant_id
        db = get_supabase_client()
 
        LEAD_SELECT = '''
            SELECT
                od.*,
                sm."stage_name",
                em."employee_name"          AS assigned_to_name,
                COALESCE(od."business_name", od."opportunity_title")
                                            AS business_name,
                sup."supplier_company_name" AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm
                   ON od."stage_id"     = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em
                   ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup
                   ON od."supplier_id"  = sup."supplier_id"
            WHERE od."tenant_id" = %s
        '''
 
        # Try tenant_lead_id first (this is the display ID shown in the URL)
        row = db.execute_query(
            LEAD_SELECT + ' AND od."tenant_lead_id" = %s LIMIT 1',
            (tenant_id, opportunity_id),
            fetch_one=True
        )
 
        # Fall back to opportunity_id (internal DB primary key)
        if not row:
            row = db.execute_query(
                LEAD_SELECT + ' AND od."opportunity_id" = %s LIMIT 1',
                (tenant_id, opportunity_id),
                fetch_one=True
            )
 
        if not row:
            return jsonify({'error': 'Lead not found'}), 404
 
        # Serialise dates / decimals so JSON doesn't choke
        def _serial(v):
            if v is None:
                return None
            if hasattr(v, 'isoformat'):
                return v.isoformat()
            try:
                from decimal import Decimal
                if isinstance(v, Decimal):
                    return float(v)
            except ImportError:
                pass
            return v
 
        result = {k: _serial(v) for k, v in row.items()}
        return jsonify(result), 200
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

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


@crm_bp.route('/leads/<int:opportunity_id>', methods=['PUT', 'PATCH'])
@token_required
@tenant_from_jwt
def update_lead(opportunity_id):
    """
    PUT  /api/crm/leads/<opportunity_id>  — full update via controller
    PATCH /api/crm/leads/<opportunity_id> — partial field update (any fields)
    """
    if request.method == 'PATCH':
        from backend.crm.supabase_client import get_supabase_client
 
        # Fields that are safe to update directly via PATCH
        ALLOWED_PATCH_FIELDS = {
            'stage_id', 'status',
            # contact
            'business_name', 'contact_person', 'tel_number', 'mobile_no',
            'email', 'position', 'company_number', 'date_of_birth',
            'opportunity_owner_employee_id',
            # contract
            'mpan_mpr', 'mpan_bottom', 'supplier_id',
            'annual_usage', 'start_date', 'end_date', 'payment_type',
            'term_sold', 'net_notch', 'comms_paid', 'aggregator',
            'site_name', 'month_sold',
            # address
            'house_name', 'house_number', 'door_number', 'address',
            'town', 'county', 'postcode',
            # charges
            'stand_charge', 'rate_1', 'rate_2', 'rate_3',
            'night_charge', 'eve_weekend_charge',
            'other_charges_1', 'other_charges_2', 'other_charges_3',
            # banking
            'bank_name', 'bank_account_number', 'bank_sort_code',
            'charity_ltd_company_number', 'partner_details',
            # others
            'meter_ref', 'uplift', 'comments', 'document_details',
        }
 
        try:
            tenant_id = g.tenant_id
            data = request.get_json() or {}
 
            # Filter to only allowed fields.
            # NOTE: explicitly keep None values so callers can nullify optional fields.
            # Non-nullable columns (e.g. stage_id) must never be set to NULL —
            # the frontend always sends a valid value for those.
            update_fields = {
                k: v for k, v in data.items()
                if k in ALLOWED_PATCH_FIELDS
            }
 
            if not update_fields:
                return jsonify({'error': 'No valid fields provided'}), 400
 
            db = get_supabase_client()
 
            # Resolve the actual opportunity_id from either tenant_lead_id or opportunity_id
            id_row = db.execute_query('''
                SELECT "opportunity_id" FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE "tenant_id" = %s
                AND ("tenant_lead_id" = %s OR "opportunity_id" = %s)
                LIMIT 1
            ''', (tenant_id, opportunity_id, opportunity_id), fetch_one=True)
 
            if not id_row:
                return jsonify({'error': 'Lead not found'}), 404
 
            real_id = id_row['opportunity_id']
 
            # Build SET clause dynamically
            set_parts = [f'"{k}" = %s' for k in update_fields]
            params = list(update_fields.values()) + [real_id, tenant_id]
 
            try:
                db.execute_update(
                    f'UPDATE "StreemLyne_MT"."Opportunity_Details" '
                    f'SET {", ".join(set_parts)} '
                    f'WHERE "opportunity_id" = %s AND "tenant_id" = %s',
                    tuple(params)
                )
            except Exception as db_err:
                import traceback; traceback.print_exc()
                return jsonify({'error': f'Database update failed: {str(db_err)}'}), 500
 
            # Return the updated record
            updated = db.execute_query('''
                SELECT
                    od.*,
                    sm."stage_name",
                    em."employee_name" AS assigned_to_name,
                    COALESCE(od."business_name", od."opportunity_title") AS business_name,
                    sup."supplier_company_name" AS supplier_name
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od."stage_id"   = sm."stage_id"
                LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od."opportunity_owner_employee_id" = em."employee_id"
                LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id" = sup."supplier_id"
                WHERE od."opportunity_id" = %s AND od."tenant_id" = %s
                LIMIT 1
            ''', (real_id, tenant_id), fetch_one=True)
 
            return jsonify(updated or {'success': True}), 200
 
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'error': str(e)}), 500
 
    # PUT — full update via controller
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


@crm_bp.route('/leads/assign', methods=['PATCH'])
@token_required
@tenant_from_jwt
def assign_leads():
    """
    PATCH /api/crm/leads/assign
    Bulk assign leads to an employee. Admin only.
    Request body: { lead_ids: [...], employee_id: N }
    """
    return crm_controller.assign_leads()


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

@crm_bp.route('/leads/search-all', methods=['GET'])
@token_required
@tenant_from_jwt
def search_all_leads():
    """
    GET /api/crm/leads/search-all?q=...&service=...
    Cross-team search — returns all matching leads across the tenant.
    Used by non-admins to see leads assigned to other team members (shown in amber).
    """
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        q = request.args.get('q', '').strip()
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        if not q or len(q) < 2:
            return jsonify([]), 200

        db = get_supabase_client()

        rows = db.execute_query('''
            SELECT
                em."employee_id",
                em."employee_name",
                COUNT(od."opportunity_id") AS count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE od."tenant_id" = %s
            AND od."service_id" = %s
            AND COALESCE(od."is_allocated", FALSE) = FALSE
            GROUP BY em."employee_id", em."employee_name"
            HAVING COUNT(od."opportunity_id") > 0
            ORDER BY count DESC
        ''', (tenant_id, service_id))

        def _s(v):
            if v is None: return None
            if hasattr(v, 'isoformat'): return v.isoformat()
            try:
                from decimal import Decimal
                if isinstance(v, Decimal): return float(v)
            except ImportError:
                pass
            return v

        results = [{k: _s(v) for k, v in row.items()} for row in (rows or [])]
        return jsonify(results), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@crm_bp.route('/leads/performance', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_performance():
    """
    GET /api/crm/leads/performance
    Get lead performance metrics for the current tenant.
    Query params:
        - use_current_user: if 'true', filter by current logged-in user
        - service: 'utilities' or 'water'
    """
    from backend.crm.supabase_client import get_supabase_client
    from .auth_helpers import get_tenant_id_from_user
 
    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
 
        use_current_user = request.args.get('use_current_user', 'false').lower() == 'true'
        employee_id = None
        if use_current_user:
            current_user = request.current_user
            employee_id = getattr(current_user, 'employee_id', None) or getattr(current_user, 'id', None)
 
        db = get_supabase_client()
 
        employee_filter = 'AND od."opportunity_owner_employee_id" = %s' if employee_id else ''
 
        query = f'''
            SELECT sm."stage_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = %s
            AND od."service_id" = %s
            AND NOT EXISTS (
                SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
            {employee_filter}
        '''
 
        params = [tenant_id, service_id]
        if employee_id:
            params.append(employee_id)
 
        rows = db.execute_query(query, tuple(params))
 
        converted_count = 0
        renewed_count = 0
        in_progress_count = 0
        not_contacted_count = 0
        lost_count = 0
        renewed_directly_count = 0
        end_date_changed_count = 0
        priced_count = 0
 
        for r in (rows or []):
            stage = (r.get('stage_name') or '').lower()
            if stage == 'converted':
                converted_count += 1
            elif stage in ['already renewed', 'renewed']:
                renewed_count += 1
            elif stage == 'renewed directly':
                renewed_directly_count += 1
            elif stage == 'end date changed':
                end_date_changed_count += 1
            elif stage == 'priced':
                priced_count += 1
            elif stage in ['callback', 'not answered', 'broker in place', 'email only',
                           'complaint', 'incorrect supplier']:
                in_progress_count += 1
            elif stage in ['lost', 'lost cot', 'invalid number', 'meter de-energised']:
                lost_count += 1
            else:
                not_contacted_count += 1
 
        total = len(rows or [])
        success_rate = round(
            ((converted_count + renewed_count + renewed_directly_count) / total * 100), 1
        ) if total > 0 else 0
 
        return jsonify({
            'converted_count':       converted_count,
            'renewed_count':         renewed_count,
            'renewed_directly_count': renewed_directly_count,
            'end_date_changed_count': end_date_changed_count,
            'priced_count':          priced_count,
            'contacted_count':       in_progress_count,
            'not_contacted_count':   not_contacted_count,
            'lost_count':            lost_count,
            'success_rate':          success_rate,
            'total_customers':       total,
        }), 200
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
 
 
@crm_bp.route('/leads/stats-by-employee', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats_by_employee():
    """
    GET /api/crm/leads/stats-by-employee
    Returns lead counts grouped by employee for the Team Overview panel.
    ✅ FIX: Use is_allocated=FALSE instead of NOT EXISTS check
    """
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        db = get_supabase_client()

        # ✅ FIX: Filter by is_allocated=FALSE to show unallocated leads
        rows = db.execute_query('''
            SELECT
                em."employee_id",
                em."employee_name",
                COUNT(od."opportunity_id") AS count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE od."tenant_id" = %s
            AND od."service_id" = %s
            AND COALESCE(od."is_allocated", FALSE) = FALSE
            GROUP BY em."employee_id", em."employee_name"
            HAVING COUNT(od."opportunity_id") > 0
            ORDER BY count DESC
        ''', (tenant_id, service_id))

        stats = [
            {
                'employee_id':   r.get('employee_id'),
                'employee_name': r.get('employee_name'),
                'count':         int(r.get('count') or 0),
            }
            for r in (rows or [])
        ]

        import logging
        logging.getLogger(__name__).warning('📊 Team Overview stats: %s', stats)

        return jsonify({'stats': stats}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

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
        
        # Map service query param to service_id
        service_param = request.args.get('service', 'electricity')
        service_value = service_param.strip().lower() if isinstance(service_param, str) else 'electricity'
        service_id = 2 if service_value == 'water' else 1
        
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
        
        confirm_result = crm_controller.crm_service.confirm_lead_import(tenant_id, validated_data, created_by, service_id)
        
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

@crm_bp.route('/clients/<int:client_id>/upload', methods=['POST'])
@require_tenant
def client_upload_document(client_id):
    """
    POST /api/crm/clients/<client_id>/upload
    Upload a document for a specific client
    
    Path Parameters:
        - client_id: Client identifier
    
    Form Data:
        - file: Document file (required)
        - document_name: Name of the document (optional)
        - document_description: Description (optional)
        - category: Document category (default: CLIENT_UPLOAD)
    
    Headers:
        - X-Tenant-ID: Tenant identifier (required)
    
    Returns:
        201: Document uploaded successfully
        400: Invalid file or data
        500: Internal server error
    """
    return crm_controller.client_upload_document(client_id)


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


@crm_bp.route('/employees', methods=['GET'])
@token_required
@tenant_from_jwt
def get_employees():
    """
    GET /api/crm/employees
    Get all employees for assignment dropdowns
    """
    return crm_controller.get_employees()


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


@crm_bp.route('/stages', methods=['GET'], strict_slashes=False)
@token_required
@tenant_from_jwt
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

@crm_bp.route('/priced', methods=['GET'])
@token_required
@tenant_from_jwt
def get_priced():
    """
    GET /api/crm/priced
    Get all priced leads and renewals
    
    Returns leads where stage_id = 8 (Priced stage)
    Returns renewals where Misc_Col1 = 'priced'
    
    Authentication:
        - JWT (token must include `tenant_id`)
    
    Returns:
        200: {
            success: true,
            leads: [...],
            renewals: [...],
            total_leads: int,
            total_renewals: int,
            total: int
        }
        500: Internal server error
    """
    return crm_controller.get_priced()

@crm_bp.route('/cleansing', methods=['GET'])
@token_required
@tenant_from_jwt
def get_cleansing():
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        db = get_supabase_client()
        records = []

        # ── 1. CRM Leads ──────────────────────────────────────────────────────
        lead_rows = db.execute_query(
            """
            SELECT
                od.opportunity_id                                       AS id,
                od.opportunity_id                                       AS client_id,
                od.tenant_lead_id                                       AS display_id,
                od.tenant_lead_id                                       AS display_order,
                COALESCE(od.business_name, od.opportunity_title)        AS business_name,
                od.contact_person,
                od.tel_number                                           AS phone,
                od.mobile_no,
                od.mpan_mpr,
                od.mpan_mpr                                             AS mpan_top,
                od.supplier_id,
                sup.supplier_company_name                               AS supplier_name,
                od.annual_usage,
                od.start_date,
                od.end_date,
                sm.stage_name                                           AS cleansing_reason,
                od.created_at                                           AS flagged_at,
                od.notes                                             AS notes,
                od.opportunity_owner_employee_id                        AS assigned_to_id,
                em.employee_name                                        AS assigned_to_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id    = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od.opportunity_owner_employee_id = em.employee_id
            WHERE od.tenant_id = %s
              AND sm.stage_name IN ('Invalid Number', 'Incorrect Supplier')
            ORDER BY od.created_at DESC
            """,
            (tenant_id,),
        )

        for r in lead_rows or []:
            def _s(v):
                if v is None: return None
                if hasattr(v, 'isoformat'): return v.isoformat()
                return v

            records.append({
                'id':               r.get('id'),
                'client_id':        r.get('client_id'),
                'display_id':       r.get('display_id'),
                'display_order':    r.get('display_order'),
                'business_name':    r.get('business_name') or 'Unknown',
                'contact_person':   r.get('contact_person'),
                'phone':            r.get('phone'),
                'mobile_no':        r.get('mobile_no'),
                'mpan_mpr':         r.get('mpan_mpr'),
                'mpan_top':         r.get('mpan_top'),
                'supplier_id':      r.get('supplier_id'),
                'supplier_name':    r.get('supplier_name'),
                'annual_usage':     r.get('annual_usage'),
                'start_date':       _s(r.get('start_date')),
                'end_date':         _s(r.get('end_date')),
                'cleansing_reason': r.get('cleansing_reason'),
                'flagged_at':       _s(r.get('flagged_at')),
                'notes':            r.get('notes'),
                'assigned_to_id':   r.get('assigned_to_id'),
                'assigned_to_name': r.get('assigned_to_name'),
                'source':           'lead',
            })

        # ── 2. Energy Clients ─────────────────────────────────────────────────
        try:
            from backend.models import Client_Master, Energy_Contract_Master, Project_Details, Supplier_Master
            from backend.db import SessionLocal

            session = SessionLocal()
            try:
                client_rows = (
                    session.query(Client_Master, Energy_Contract_Master, Supplier_Master)
                    .outerjoin(Project_Details, Client_Master.client_id == Project_Details.client_id)
                    .outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id)
                    .outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id)
                    .filter(
                        Client_Master.tenant_id == tenant_id,
                        Client_Master.is_deleted == True,
                        Client_Master.deleted_reason.in_(['Invalid Number', 'Incorrect Supplier']),
                    )
                    .all()
                )

                for client, contract, supplier in client_rows:
                    records.append({
                        'id':               client.client_id,
                        'client_id':        client.client_id,
                        'display_id':       getattr(client, 'display_id', None),
                        'display_order':    getattr(client, 'display_order', None),
                        'business_name':    getattr(client, 'client_company_name', None) or 'Unknown',
                        'contact_person':   getattr(client, 'client_contact_name', None),
                        'phone':            getattr(client, 'client_phone', None),
                        'mobile_no':        getattr(client, 'mobile_no', None),
                        'mpan_mpr':         getattr(contract, 'mpan_mpr', None) if contract else None,
                        'mpan_top':         getattr(contract, 'mpan_top', None) if contract else None,
                        'supplier_id':      contract.supplier_id if contract else None,
                        'supplier_name':    supplier.supplier_company_name if supplier else None,
                        'annual_usage':     getattr(contract, 'annual_usage', None) if contract else None,
                        'start_date':       contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,
                        'end_date':         contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
                        'cleansing_reason': client.deleted_reason,
                        'flagged_at':       client.deleted_at.isoformat() if client.deleted_at else None,
                        'notes':            getattr(client, 'deleted_notes', None),
                        'assigned_to_id':   getattr(client, 'assigned_to_id', None),
                        'assigned_to_name': None,
                        'source':           'energy_client',
                    })
            finally:
                session.close()

        except Exception as ec_err:
            import logging
            logging.getLogger(__name__).warning('Could not load energy clients for cleansing: %s', ec_err)

        records.sort(key=lambda x: x.get('flagged_at') or '', reverse=True)

        return jsonify({'records': records, 'total': len(records)}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@crm_bp.route('/leads/<int:opportunity_id>/callback', methods=['POST', 'OPTIONS'])
@token_required
@tenant_from_jwt
def leads_callback(opportunity_id):
    """
    POST /api/crm/leads/<opportunity_id>/callback
    Save a callback/status update for a lead.
    Updates stage_id on Opportunity_Details based on status.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    from backend.crm.supabase_client import get_supabase_client
 
    try:
        tenant_id = g.tenant_id
 
        # ✅ FIX: force=True parses JSON even without Content-Type: application/json
        # silent=True returns None instead of raising on parse error
        data = request.get_json(force=True, silent=True) or {}
 
        # Debug: log what we actually received so 400s are self-explanatory
        import logging
        logger = logging.getLogger(__name__)
        logger.info('leads_callback: opportunity_id=%s tenant=%s data_keys=%s',
                    opportunity_id, tenant_id, list(data.keys()) if data else 'EMPTY')
 
        status           = data.get('status')
        stage_id         = data.get('stage_id')
        notes            = data.get('notes', '')
        callback_date    = data.get('callback_date')
        called_date      = data.get('called_date')
        is_sold          = data.get('is_sold')
        new_end_date_str = data.get('new_end_date')
        renewed_by       = data.get('renewed_by')
        new_supplier     = data.get('new_supplier')
        new_address      = data.get('new_address')
 
        if not status:
            logger.warning('leads_callback: missing status, raw body=%s', request.get_data(as_text=True)[:200])
            return jsonify({'error': 'Status is required'}), 400
 
        # ── Status config ──────────────────────────────────────────────────────
        status_config = {
            "Callback":          {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Not Answered":      {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Priced":            {"requires_date": False, "requires_sold": True,  "deletes_record": False, "requires_notes": False},
            "Lost":              {"requires_date": True,  "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Lost COT":          {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Already Renewed":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Invalid Number":    {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Meter De-energised":{"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Broker in Place":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "End Date Changed":  {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Complaint":         {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Email Only":        {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Renewed Directly":  {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Incorrect Supplier":{"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Converted":         {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": False},
        }
 
        if status not in status_config:
            return jsonify({'error': f'Invalid status: {status}'}), 400
 
        cfg = status_config[status]
 
        # ── Validation ─────────────────────────────────────────────────────────
        if cfg['requires_notes'] and not (notes or '').strip():
            return jsonify({'error': 'Notes are required for this status'}), 400
 
        if cfg['requires_sold'] and is_sold is None:
            return jsonify({'error': 'Please select if the contract was sold'}), 400
 
        if status == 'Already Renewed' and not renewed_by:
            return jsonify({'error': 'Please select if renewed by customer or agent'}), 400
 
        db = get_supabase_client()
 
        # ── Verify lead belongs to tenant and resolve real opportunity_id ────────
        lead = db.execute_query('''
            SELECT opportunity_id, stage_id
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = %s
            AND ("tenant_lead_id" = %s OR opportunity_id = %s)
            LIMIT 1
        ''', (tenant_id, opportunity_id, opportunity_id), fetch_one=True)
 
        if not lead:
            return jsonify({'error': 'Lead not found'}), 404
 
        # Use the resolved real opportunity_id for all subsequent DB operations
        real_id = lead['opportunity_id']
 
        # ── Handle recycle bin statuses ────────────────────────────────────────
        if cfg['deletes_record']:
            lost_stage_id = stage_id
            if not lost_stage_id:
                lost_stage = db.execute_query(
                    'SELECT stage_id FROM "StreemLyne_MT"."Stage_Master" '
                    'WHERE LOWER(stage_name) = %s LIMIT 1',
                    (status.lower(),), fetch_one=True
                )
                lost_stage_id = lost_stage.get('stage_id') if lost_stage else 5
 
            db.execute_update('''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET stage_id = %s
                WHERE opportunity_id = %s AND tenant_id = %s
            ''', (lost_stage_id, real_id, tenant_id))
 
            return jsonify({
                'success': True,
                'message': f'Moved to recycle bin ({status})',
                'moved_to_recycle_bin': True,
            }), 200
 
        # ── Handle Priced: not sold → move to Priced page ─────────────────────
        if status == 'Priced' and is_sold is False:
            db.execute_update('''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET stage_id = %s
                WHERE opportunity_id = %s AND tenant_id = %s
            ''', (stage_id or 4, real_id, tenant_id))
 
            return jsonify({
                'success': True,
                'message': 'Moved to Priced page',
                'moved_to_priced': True,
            }), 200
 
        # ── Update end date if provided ────────────────────────────────────────
        if new_end_date_str and status in ('End Date Changed', 'Already Renewed'):
            db.execute_update('''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET end_date = %s
                WHERE opportunity_id = %s AND tenant_id = %s
            ''', (new_end_date_str, real_id, tenant_id))
 
        # ── Update supplier if provided ────────────────────────────────────────
        if new_supplier and new_supplier.strip():
            sup = db.execute_query('''
                SELECT supplier_id FROM "StreemLyne_MT"."Supplier_Master"
                WHERE LOWER(supplier_company_name) = LOWER(%s)
                LIMIT 1
            ''', (new_supplier.strip(),), fetch_one=True)
            if sup:
                db.execute_update('''
                    UPDATE "StreemLyne_MT"."Opportunity_Details"
                    SET supplier_id = %s
                    WHERE opportunity_id = %s AND tenant_id = %s
                ''', (sup['supplier_id'], real_id, tenant_id))
 
        # ── Update stage_id ────────────────────────────────────────────────────
        if stage_id:
            db.execute_update('''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET stage_id = %s
                WHERE opportunity_id = %s AND tenant_id = %s
            ''', (stage_id, real_id, tenant_id))
 
        logger.info('leads_callback: saved status=%s for real_id=%s (url_id=%s)', status, real_id, opportunity_id)
 
        return jsonify({
            'success': True,
            'message': 'Callback saved successfully',
            'status': status,
        }), 200
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@crm_bp.route('/leads/allocated', methods=['GET'])
@token_required
@tenant_from_jwt
def get_allocated_leads():
    """Get allocated/reassigned leads only (leads with is_allocated=TRUE)"""
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        employee_id = getattr(current_user, 'employee_id', None)
        
        import logging
        logging.getLogger(__name__).warning(
            '🔍 get_allocated_leads: employee_id=%s tenant=%s service=%s',
            employee_id, tenant_id, service_param
        )
        
        if not employee_id:
            return jsonify([]), 200
        
        db = get_supabase_client()

        query = '''
            SELECT od.*, sm."stage_name", em."employee_name" AS assigned_to_name,
                   COALESCE(od."business_name", od."opportunity_title") AS business_name,
                   sup."supplier_company_name" AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id" = sup."supplier_id"
            WHERE od."tenant_id" = %s 
            AND od."service_id" = %s
            AND od."opportunity_owner_employee_id" = %s
            AND od."is_allocated" = TRUE
            ORDER BY od."created_at" DESC
        '''
        
        rows = db.execute_query(query, (tenant_id, service_id, employee_id))
        
        def _s(v):
            if v is None: return None
            if hasattr(v, 'isoformat'): return v.isoformat()
            from decimal import Decimal
            if isinstance(v, Decimal): return float(v)
            return v

        results = [{k: _s(v) for k, v in row.items()} for row in (rows or [])]
        
        logging.getLogger(__name__).warning(
            '✅ get_allocated_leads returning %d leads for employee_id=%s',
            len(results), employee_id
        )

        return jsonify(results), 200
        
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@crm_bp.route('/leads/archives', methods=['GET'])
@token_required
@tenant_from_jwt
def get_archived_leads():
    """
    GET /api/crm/leads/archives
    Get archived leads (is_archived=TRUE) for the current user/tenant
    """
    from backend.crm.supabase_client import get_supabase_client
    from backend.crm.utils.role_helpers import is_admin_user

    try:
        tenant_id = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        is_admin = is_admin_user(current_user)
        employee_id = getattr(current_user, 'employee_id', None)

        import logging
        logging.getLogger(__name__).warning(
            '🔍 get_archived_leads: employee_id=%s is_admin=%s tenant=%s service=%s',
            employee_id, is_admin, tenant_id, service_param
        )

        db = get_supabase_client()

        query = '''
            SELECT
                od.*,
                sm."stage_name",
                em."employee_name"          AS assigned_to_name,
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                sup."supplier_company_name" AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od."stage_id"    = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id"  = sup."supplier_id"
            WHERE od."tenant_id" = %s
            AND od."service_id" = %s
            AND od."is_archived" = TRUE
        '''
        params = [tenant_id, service_id]

        # Non-admins can only see their own archived leads
        if not is_admin and employee_id:
            query += ' AND od."opportunity_owner_employee_id" = %s'
            params.append(employee_id)

        query += ' ORDER BY od."created_at" DESC'

        rows = db.execute_query(query, tuple(params))

        def _s(v):
            if v is None: return None
            if hasattr(v, 'isoformat'): return v.isoformat()
            try:
                from decimal import Decimal
                if isinstance(v, Decimal): return float(v)
            except ImportError:
                pass
            return v

        results = [{k: _s(v) for k, v in row.items()} for row in (rows or [])]
        
        logging.getLogger(__name__).warning(
            '✅ get_archived_leads returning %d archived leads',
            len(results)
        )
        
        return jsonify(results), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500