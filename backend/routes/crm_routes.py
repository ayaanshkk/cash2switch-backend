# -*- coding: utf-8 -*-
"""
CRM Routes Blueprint
Defines API endpoints for CRM module
"""
from flask import Blueprint, request, g, jsonify, current_app
from functools import wraps
from datetime import datetime, timedelta
from backend.crm.controllers.crm_controller import CRMController
from backend.crm.middleware.tenant_middleware import require_tenant
from backend.crm.utils.role_helpers import is_crm_leads_admin_role
from .auth_helpers import token_required
from ..dummy_local_dashboard_data import (
    dummy_leads_by_stage,
    dummy_leads_list,
    dummy_leads_period_breakdown,
    dummy_leads_salesperson_breakdown,
    dummy_leads_stage_breakdown,
    dummy_leads_stats,
    dummy_leads_staff_performance,
    dummy_leads_supplier_breakdown,
    local_demo_dashboard_enabled,
)
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

OFFSHORE_ROLE_ID = 5


def _staff_period_bounds(period: str):
    now = datetime.now()
    key = (period or "daily").strip().lower()
    if key == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        multiplier = 7
    elif key == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        multiplier = 30
    else:
        key = "daily"
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        multiplier = 1
    return key, start, end, multiplier


def _resolve_opportunity_ts_expr(db) -> str:
    rows = db.execute_query(
        '''
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
              AND table_name = 'Opportunity_Details'
        '''
    )
    columns = {str((r or {}).get('column_name') or '').strip().lower() for r in (rows or [])}
    if 'updated_at' in columns:
        return 'od."updated_at"'
    if 'modified_at' in columns:
        return 'od."modified_at"'
    if 'created_at' in columns:
        return 'od."created_at"'
    return 'NOW()'


def _safe_float(v):
    try:
        if v is None:
            return 0.0
        return float(v)
    except Exception:
        try:
            txt = str(v).replace(",", "").strip()
            return float(txt) if txt else 0.0
        except Exception:
            return 0.0


def _lead_stage_bucket(stage_name: str) -> str:
    s = (stage_name or "").strip().lower()
    if s in ("converted", "already renewed", "renewed", "renewed directly"):
        return "converted"
    if s in ("lost", "lost cot", "invalid number", "meter de-energised"):
        return "lost"
    if s in ("callback", "not answered", "broker in place", "email only", "complaint", "incorrect supplier", "priced", "end date changed"):
        return "in_progress"
    return "not_contacted"

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
        
        user_id = getattr(current_user, 'id', None) or getattr(current_user, 'user_id', None)
        employee_id = getattr(current_user, 'employee_id', None)
        role_name = getattr(current_user, 'role', None)
        normalized_role = str(role_name).strip().lower() if role_name else None
        admin_user = is_crm_leads_admin_role(role_name)

        current_app.logger.warning(
            'crm.get_leads start tenant=%s user_id=%s employee_id=%s is_admin=%s role=%s service=%s exclude_stage=%s',
            tenant_id, user_id, employee_id, admin_user, normalized_role, service_param, exclude_stage
        )

        if local_demo_dashboard_enabled():
            scoped_employee_id = request.args.get('employee_id', type=int) if admin_user else employee_id
            rows = dummy_leads_list(scoped_employee_id)
            if exclude_stage:
                rows = [r for r in rows if (r.get('stage_name') or '').strip().lower() != exclude_stage.strip().lower()]
            return jsonify(rows), 200

        filters = {
            'service_id': service_id,
        }

        if exclude_stage:
            filters['exclude_stage'] = exclude_stage

        # Non-admins must have employee_id to scope rows; admins list the whole tenant.
        if not admin_user and not employee_id:
            current_app.logger.warning(
                'crm.get_leads empty_result reason=no_employee_id tenant=%s user_id=%s',
                tenant_id, user_id
            )
            return jsonify([]), 200

        db = get_supabase_client()

        project_exclusion_sql = '''
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd."opportunity_id" = od."opportunity_id"
            )
        '''

        query = f'''
            SELECT
                od."opportunity_id",
                od."tenant_lead_id",
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                od."contact_person",
                od."tel_number",
                od."email",
                od."mpan_mpr",
                od."mpan_bottom",
                od."start_date",
                od."end_date",
                od."service_id",
                od."stage_id",
                sm."stage_name",
                od."opportunity_owner_employee_id",
                em."employee_name" AS assigned_to_name,
                od."created_at",
                od."supplier_id",
                sup."supplier_company_name" AS supplier_name,
                od."annual_usage",
                od."stand_charge",
                od."rate_1",
                od."net_notch",
                od."payment_type",
                od."postcode",
                od."mobile_no"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup
                ON od."supplier_id" = sup."supplier_id"
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
            AND od."service_id" = %s
            {project_exclusion_sql}
        '''
        params = [tenant_id, tenant_id, service_id]

        if not admin_user:
            query += '''
                AND od."opportunity_owner_employee_id" = %s
                AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
            '''
            params.append(employee_id)

        if exclude_stage:
            query += ' AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != LOWER(%s))'
            params.append(exclude_stage)

        query += ' ORDER BY od."created_at" DESC'

        rows = db.execute_query(query, tuple(params))

        # Fallback: some tenants have Project_Details rows for all opportunities,
        # which makes the strict exclusion return zero leads.
        if not (rows or []):
            fallback_query = query.replace(project_exclusion_sql, "")
            rows = db.execute_query(fallback_query, tuple(params))
            current_app.logger.warning(
                'crm.get_leads fallback_without_project_exclusion tenant=%s service_id=%s is_admin=%s rows=%s',
                tenant_id,
                service_id,
                admin_user,
                len(rows or []),
            )

        if admin_user and not (rows or []):
            try:
                tscope = (
                    '(od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s)) '
                    'AND od."service_id" = %s'
                )
                p = (tenant_id, tenant_id, service_id)
                c_all = db.execute_query(
                    f'SELECT COUNT(*) AS c FROM "StreemLyne_MT"."Opportunity_Details" od '
                    f'LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id" '
                    f'WHERE {tscope}',
                    p,
                    fetch_one=True,
                )
                c_no_proj = db.execute_query(
                    f'SELECT COUNT(*) AS c FROM "StreemLyne_MT"."Opportunity_Details" od '
                    f'LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id" '
                    f'WHERE {tscope} AND NOT EXISTS ('
                    f'SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd '
                    f'WHERE pd."opportunity_id" = od."opportunity_id")',
                    p,
                    fetch_one=True,
                )
                c_after_lost = None
                if exclude_stage:
                    c_after_lost = db.execute_query(
                        f'SELECT COUNT(*) AS c FROM "StreemLyne_MT"."Opportunity_Details" od '
                        f'LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id" '
                        f'LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id" '
                        f'WHERE {tscope} AND NOT EXISTS ('
                        f'SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd '
                        f'WHERE pd."opportunity_id" = od."opportunity_id") '
                        f'AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != LOWER(%s))',
                        p + (exclude_stage,),
                        fetch_one=True,
                    )
                current_app.logger.warning(
                    'crm.get_leads empty diagnostic tenant=%s service_id=%s exclude_stage=%r: '
                    'opportunities_matching_tenant_service=%s without_project_row=%s after_exclude_stage=%s '
                    '(if without_project_row=0 but first>0, every matching opportunity already has Project_Details)',
                    tenant_id,
                    service_id,
                    exclude_stage,
                    (c_all or {}).get('c'),
                    (c_no_proj or {}).get('c'),
                    (c_after_lost or {}).get('c') if exclude_stage else 'n/a',
                )
            except Exception as diag_e:
                current_app.logger.warning('crm.get_leads diagnostic query failed: %s', diag_e)

        def _iso(v):
            return v.isoformat() if getattr(v, 'isoformat', None) else (v or None)

        results = [{
            'opportunity_id':                r.get('opportunity_id'),
            'tenant_lead_id':                r.get('tenant_lead_id'),
            'business_name':                 r.get('business_name'),
            'contact_person':                r.get('contact_person'),
            'tel_number':                    str(r.get('tel_number')).replace('.0', '') if r.get('tel_number') else None,
            'mobile_no':                     r.get('mobile_no'),
            'email':                         r.get('email'),
            'mpan_mpr':                      r.get('mpan_mpr'),
            'mpan_bottom':                   r.get('mpan_bottom'),
            'start_date':                    _iso(r.get('start_date')),
            'end_date':                      _iso(r.get('end_date')),
            'service_id':                    r.get('service_id'),
            'stage_id':                      r.get('stage_id'),
            'stage_name':                    r.get('stage_name'),
            'opportunity_owner_employee_id': r.get('opportunity_owner_employee_id'),
            'assigned_to_name':              r.get('assigned_to_name'),
            'created_at':                    _iso(r.get('created_at')),
            'supplier_id':                   r.get('supplier_id'),
            'supplier_name':                 r.get('supplier_name'),
            'annual_usage':                  r.get('annual_usage'),
            'stand_charge':                  r.get('stand_charge'),
            'rate_1':                        r.get('rate_1'),
            'net_notch':                     r.get('net_notch'),
            'payment_type':                  r.get('payment_type'),
            'postcode':                      r.get('postcode'),
        } for r in (rows or [])]

        current_app.logger.warning(
            'crm.get_leads result tenant=%s user_id=%s employee_id=%s is_admin=%s returned=%s first_ids=%s',
            tenant_id,
            user_id,
            employee_id,
            admin_user,
            len(results),
            [r.get('tenant_lead_id') or r.get('opportunity_id') for r in results[:5]]
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

        like_q = f'%{q.lower()}%'
        rows = db.execute_query('''
            SELECT
                od."opportunity_id",
                od."tenant_lead_id",
                COALESCE(od."business_name", cm."client_company_name", od."opportunity_title") AS business_name,
                COALESCE(od."contact_person", cm."client_contact_name") AS contact_person,
                COALESCE(od."tel_number", cm."client_phone") AS tel_number,
                od."mobile_no",
                COALESCE(od."email", cm."client_email") AS email,
                od."mpan_mpr",
                od."mpan_bottom",
                od."start_date",
                od."end_date",
                od."service_id",
                od."stage_id",
                sm."stage_name",
                od."opportunity_owner_employee_id",
                em."employee_name" AS assigned_to_name,
                od."created_at",
                od."supplier_id",
                sup."supplier_company_name" AS supplier_name,
                od."annual_usage",
                od."stand_charge",
                od."rate_1",
                od."net_notch",
                od."payment_type",
                od."postcode"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                   ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em
                   ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                   ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup
                   ON od."supplier_id" = sup."supplier_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
            AND od."service_id" = %s
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
            AND (
                LOWER(COALESCE(od."business_name", cm."client_company_name", od."opportunity_title", '')) LIKE %s
                OR LOWER(COALESCE(od."contact_person", cm."client_contact_name", '')) LIKE %s
                OR LOWER(COALESCE(od."email", cm."client_email", '')) LIKE %s
                OR LOWER(COALESCE(od."tel_number", cm."client_phone", '')) LIKE %s
                OR LOWER(COALESCE(od."mpan_mpr", '')) LIKE %s
            )
            ORDER BY od."created_at" DESC
        ''', (tenant_id, tenant_id, service_id, like_q, like_q, like_q, like_q, like_q))

        def _iso(v):
            return v.isoformat() if getattr(v, 'isoformat', None) else (v or None)

        results = [{
            'opportunity_id':                r.get('opportunity_id'),
            'tenant_lead_id':                r.get('tenant_lead_id'),
            'business_name':                 r.get('business_name'),
            'contact_person':                r.get('contact_person'),
            'tel_number':                    str(r.get('tel_number')).replace('.0', '') if r.get('tel_number') else None,
            'mobile_no':                     r.get('mobile_no'),
            'email':                         r.get('email'),
            'mpan_mpr':                      r.get('mpan_mpr'),
            'mpan_bottom':                   r.get('mpan_bottom'),
            'start_date':                    _iso(r.get('start_date')),
            'end_date':                      _iso(r.get('end_date')),
            'service_id':                    r.get('service_id'),
            'stage_id':                      r.get('stage_id'),
            'stage_name':                    r.get('stage_name'),
            'opportunity_owner_employee_id': r.get('opportunity_owner_employee_id'),
            'assigned_to_name':              r.get('assigned_to_name'),
            'created_at':                    _iso(r.get('created_at')),
            'supplier_id':                   r.get('supplier_id'),
            'supplier_name':                 r.get('supplier_name'),
            'annual_usage':                  r.get('annual_usage'),
            'stand_charge':                  r.get('stand_charge'),
            'rate_1':                        r.get('rate_1'),
            'net_notch':                     r.get('net_notch'),
            'payment_type':                  r.get('payment_type'),
            'postcode':                      r.get('postcode'),
        } for r in (rows or [])]

        return jsonify(results), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@crm_bp.route('/leads/stats', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats():
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        current_user = request.current_user
        role_name = getattr(current_user, 'role', None)
        admin_user = is_crm_leads_admin_role(role_name)
        my_emp_id = getattr(current_user, 'employee_id', None)
        requested_employee_id = request.args.get('employee_id', type=int)
        employee_id = requested_employee_id if admin_user else my_emp_id

        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_stats(employee_id)), 200

        db = get_supabase_client()
        base_sql = '''
            SELECT
                od."opportunity_id",
                od."created_at",
                od."end_date",
                od."annual_usage",
                COALESCE(sm."stage_name", 'Unknown') AS stage_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND od."service_id" = %s
              AND NOT EXISTS (
                SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd."opportunity_id" = od."opportunity_id"
              )
              {employee_filter}
        '''
        params = [tenant_id, tenant_id, service_id]
        if employee_id:
            sql = base_sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = %s')
            params.append(employee_id)
        else:
            sql = base_sql.format(employee_filter='')

        rows = db.execute_query(sql, tuple(params)) or []
        today = datetime.utcnow().date()
        last_30 = today - timedelta(days=30)

        converted_leads = 0
        in_progress = 0
        lost_leads = 0
        new_leads = 0
        leads_30_60 = 0
        leads_61_90 = 0
        leads_91_180 = 0
        not_due = 0
        total_annual_usage = 0.0
        recent_30d = 0
        stage_breakdown = {}

        for r in rows:
            stage_name = r.get('stage_name') or 'Unknown'
            bucket = _lead_stage_bucket(stage_name)
            if bucket == "converted":
                converted_leads += 1
            elif bucket == "in_progress":
                in_progress += 1
            elif bucket == "lost":
                lost_leads += 1
            else:
                new_leads += 1

            stage_breakdown[stage_name] = stage_breakdown.get(stage_name, 0) + 1
            total_annual_usage += _safe_float(r.get('annual_usage'))

            created_at = r.get('created_at')
            if created_at and hasattr(created_at, 'date') and created_at.date() >= last_30:
                recent_30d += 1

            end_date = r.get('end_date')
            if end_date:
                d = end_date if not hasattr(end_date, 'date') else end_date.date()
                days = (d - today).days
                if 30 <= days <= 60:
                    leads_30_60 += 1
                elif 61 <= days <= 90:
                    leads_61_90 += 1
                elif 91 <= days <= 180:
                    leads_91_180 += 1
                elif days >= 365:
                    not_due += 1

        total_leads = len(rows)
        active_leads = max(0, total_leads - lost_leads)
        conversion_rate = round((converted_leads / total_leads) * 100, 1) if total_leads else 0

        return jsonify({
            'total_leads': total_leads,
            'active_leads': active_leads,
            'converted_leads': converted_leads,
            'new_leads': new_leads,
            'in_progress': in_progress,
            'lost_leads': lost_leads,
            'conversion_rate': conversion_rate,
            'total_value': 0,
            'recent_leads_30d': recent_30d,
            'allocated_leads': 0,
            'unallocated_leads': total_leads,
            'stage_breakdown': stage_breakdown,
            'leads_30_60_days': leads_30_60,
            'leads_61_90_days': leads_61_90,
            'leads_91_180_days': leads_91_180,
            'not_due_leads': not_due,
            'total_annual_usage': total_annual_usage,
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/stage-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stage_breakdown():
    from backend.crm.supabase_client import get_supabase_client
    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        admin_user = is_crm_leads_admin_role(getattr(current_user, 'role', None))
        employee_id = request.args.get('employee_id', type=int) if admin_user else getattr(current_user, 'employee_id', None)

        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_stage_breakdown(employee_id)), 200

        db = get_supabase_client()
        sql = '''
            SELECT COALESCE(sm."stage_name", 'Unknown') AS stage_name, COUNT(od."opportunity_id")::bigint AS count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND od."service_id" = %s
              AND NOT EXISTS (SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd WHERE pd."opportunity_id" = od."opportunity_id")
              {employee_filter}
            GROUP BY COALESCE(sm."stage_name", 'Unknown')
            ORDER BY count DESC
        '''
        params = [tenant_id, tenant_id, service_id]
        if employee_id:
            sql = sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = %s')
            params.append(employee_id)
        else:
            sql = sql.format(employee_filter='')
        rows = db.execute_query(sql, tuple(params)) or []
        return jsonify([
            {'stage_id': i + 1, 'stage_name': r.get('stage_name') or 'Unknown', 'count': int(r.get('count') or 0), 'total_value': 0}
            for i, r in enumerate(rows)
        ]), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/supplier-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_supplier_breakdown():
    from backend.crm.supabase_client import get_supabase_client
    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        admin_user = is_crm_leads_admin_role(getattr(current_user, 'role', None))
        employee_id = request.args.get('employee_id', type=int) if admin_user else getattr(current_user, 'employee_id', None)

        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_supplier_breakdown(employee_id)), 200

        db = get_supabase_client()
        sql = '''
            SELECT COALESCE(sup."supplier_company_name", 'Unknown') AS supplier_name, COUNT(od."opportunity_id")::bigint AS lead_count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id" = sup."supplier_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND od."service_id" = %s
              AND NOT EXISTS (SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd WHERE pd."opportunity_id" = od."opportunity_id")
              {employee_filter}
            GROUP BY COALESCE(sup."supplier_company_name", 'Unknown')
            ORDER BY lead_count DESC
        '''
        params = [tenant_id, tenant_id, service_id]
        if employee_id:
            sql = sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = %s')
            params.append(employee_id)
        else:
            sql = sql.format(employee_filter='')
        rows = db.execute_query(sql, tuple(params)) or []
        return jsonify([
            {'supplier_name': r.get('supplier_name') or 'Unknown', 'lead_count': int(r.get('lead_count') or 0), 'total_value': 0}
            for r in rows
        ]), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/salesperson-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_salesperson_breakdown():
    from backend.crm.supabase_client import get_supabase_client
    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        admin_user = is_crm_leads_admin_role(getattr(current_user, 'role', None))
        if not admin_user:
            return jsonify([]), 200
        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_salesperson_breakdown()), 200
        db = get_supabase_client()
        rows = db.execute_query('''
            SELECT em."employee_id", em."employee_name", COALESCE(sm."stage_name", 'Unknown') AS stage_name, COUNT(od."opportunity_id")::bigint AS cnt
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND od."service_id" = %s
              AND NOT EXISTS (SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd WHERE pd."opportunity_id" = od."opportunity_id")
            GROUP BY em."employee_id", em."employee_name", COALESCE(sm."stage_name", 'Unknown')
            ORDER BY em."employee_name" ASC
        ''', (tenant_id, tenant_id, service_id)) or []

        grouped = {}
        for r in rows:
            eid = r.get('employee_id')
            if eid not in grouped:
                grouped[eid] = {
                    'employee_id': eid,
                    'employee_name': r.get('employee_name') or 'Unknown',
                    'total_leads': 0,
                    'converted_count': 0,
                    'in_progress_count': 0,
                    'not_contacted_count': 0,
                    'lost_count': 0,
                    'conversion_rate': 0,
                    'total_value': 0,
                }
            c = int(r.get('cnt') or 0)
            grouped[eid]['total_leads'] += c
            bucket = _lead_stage_bucket(r.get('stage_name') or '')
            if bucket == "converted":
                grouped[eid]['converted_count'] += c
            elif bucket == "in_progress":
                grouped[eid]['in_progress_count'] += c
            elif bucket == "lost":
                grouped[eid]['lost_count'] += c
            else:
                grouped[eid]['not_contacted_count'] += c

        out = []
        for v in grouped.values():
            total = v['total_leads'] or 0
            v['conversion_rate'] = round((v['converted_count'] / total) * 100, 1) if total else 0
            out.append(v)
        out.sort(key=lambda x: x['total_leads'], reverse=True)
        return jsonify(out), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/by-stage', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_by_stage():
    from backend.crm.supabase_client import get_supabase_client
    try:
        tenant_id = g.tenant_id
        stage = (request.args.get('stage') or '').strip().lower()
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        admin_user = is_crm_leads_admin_role(getattr(current_user, 'role', None))
        employee_id = request.args.get('employee_id', type=int) if admin_user else getattr(current_user, 'employee_id', None)

        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_by_stage(stage, employee_id)), 200

        db = get_supabase_client()

        stage_filter_sql = ''
        stage_params = []
        if stage == 'in_progress':
            stage_filter_sql = " AND LOWER(COALESCE(sm.\"stage_name\", '')) IN ('callback','not answered','broker in place','email only','complaint','incorrect supplier','priced','end date changed')"
        elif stage == 'lost':
            stage_filter_sql = " AND LOWER(COALESCE(sm.\"stage_name\", '')) IN ('lost','lost cot','invalid number','meter de-energised')"
        elif stage:
            stage_filter_sql = " AND LOWER(COALESCE(sm.\"stage_name\", '')) = %s"
            stage_params.append(stage)

        sql = f'''
            SELECT
                od."opportunity_id",
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                od."contact_person",
                od."tel_number",
                od."email",
                COALESCE(sm."stage_name", 'Unknown') AS stage_name,
                COALESCE(em."employee_name", 'Unassigned') AS assigned_to_name,
                od."opportunity_owner_employee_id" AS assigned_to_id,
                od."created_at",
                od."annual_usage",
                CASE WHEN od."service_id" = 2 THEN 'water' ELSE 'utilities' END AS service_name,
                od."end_date"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND od."service_id" = %s
              AND NOT EXISTS (SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd WHERE pd."opportunity_id" = od."opportunity_id")
              {employee_filter}
              {stage_filter_sql}
            ORDER BY od."created_at" DESC
        '''
        params = [tenant_id, tenant_id, service_id]
        if employee_id:
            sql = sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = %s')
            params.append(employee_id)
        else:
            sql = sql.format(employee_filter='')
        params.extend(stage_params)
        rows = db.execute_query(sql, tuple(params)) or []

        today = datetime.utcnow().date()
        leads = []
        for r in rows:
            end_date = r.get('end_date')
            end_d = end_date.date() if hasattr(end_date, 'date') else end_date
            days = (end_d - today).days if end_d else None
            leads.append({
                'opportunity_id': r.get('opportunity_id'),
                'business_name': r.get('business_name'),
                'contact_person': r.get('contact_person'),
                'tel_number': str(r.get('tel_number') or ''),
                'email': r.get('email'),
                'stage_name': r.get('stage_name') or 'Unknown',
                'opportunity_value': 0,
                'assigned_to_name': r.get('assigned_to_name') or 'Unassigned',
                'assigned_to_id': r.get('assigned_to_id'),
                'created_at': r.get('created_at').isoformat() if r.get('created_at') and hasattr(r.get('created_at'), 'isoformat') else None,
                'annual_usage': _safe_float(r.get('annual_usage')),
                'service_name': r.get('service_name') or 'utilities',
                'end_date': end_d.isoformat() if end_d and hasattr(end_d, 'isoformat') else None,
                'days_until_due': days,
            })
        return jsonify({'leads': leads}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/period-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_period_breakdown():
    from backend.crm.supabase_client import get_supabase_client
    try:
        tenant_id = g.tenant_id
        period = (request.args.get('period') or '').strip().lower()
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        admin_user = is_crm_leads_admin_role(getattr(current_user, 'role', None))
        employee_id = request.args.get('employee_id', type=int) if admin_user else getattr(current_user, 'employee_id', None)

        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_period_breakdown(period, employee_id)), 200

        db = get_supabase_client()

        sql = '''
            SELECT
                od."opportunity_id",
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                od."contact_person",
                od."tel_number",
                od."email",
                COALESCE(sm."stage_name", 'Unknown') AS stage_name,
                COALESCE(em."employee_name", 'Unassigned') AS assigned_to_name,
                od."opportunity_owner_employee_id" AS assigned_to_id,
                od."created_at",
                od."annual_usage",
                od."end_date",
                CASE WHEN od."service_id" = 2 THEN 'water' ELSE 'utilities' END AS service_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND od."service_id" = %s
              AND NOT EXISTS (SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd WHERE pd."opportunity_id" = od."opportunity_id")
              {employee_filter}
            ORDER BY od."created_at" DESC
        '''
        params = [tenant_id, tenant_id, service_id]
        if employee_id:
            sql = sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = %s')
            params.append(employee_id)
        else:
            sql = sql.format(employee_filter='')
        rows = db.execute_query(sql, tuple(params)) or []

        today = datetime.utcnow().date()
        leads = []
        for r in rows:
            end_date = r.get('end_date')
            end_d = end_date.date() if hasattr(end_date, 'date') else end_date
            days = (end_d - today).days if end_d else None

            include = False
            if period == '30-60':
                include = days is not None and 30 <= days <= 60
            elif period == '61-90':
                include = days is not None and 61 <= days <= 90
            elif period == '91-180':
                include = days is not None and 91 <= days <= 180
            elif period == 'not-due':
                include = days is not None and days >= 365
            else:
                include = True

            if not include:
                continue

            leads.append({
                'opportunity_id': r.get('opportunity_id'),
                'business_name': r.get('business_name'),
                'contact_person': r.get('contact_person'),
                'tel_number': str(r.get('tel_number') or ''),
                'email': r.get('email'),
                'stage_name': r.get('stage_name') or 'Unknown',
                'opportunity_value': 0,
                'assigned_to_name': r.get('assigned_to_name') or 'Unassigned',
                'assigned_to_id': r.get('assigned_to_id'),
                'created_at': r.get('created_at').isoformat() if r.get('created_at') and hasattr(r.get('created_at'), 'isoformat') else None,
                'annual_usage': _safe_float(r.get('annual_usage')),
                'service_name': r.get('service_name') or 'utilities',
                'end_date': end_d.isoformat() if end_d and hasattr(end_d, 'isoformat') else None,
                'days_until_due': days,
            })

        return jsonify({'period': period, 'leads': leads}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
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
 
        # Same tenant resolution as GET /leads (direct tenant_id or via linked client).
        query = f'''
            SELECT sm."stage_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
            AND od."service_id" = %s
            AND NOT EXISTS (
                SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
            {employee_filter}
        '''
 
        params = [tenant_id, tenant_id, service_id]
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

@crm_bp.route('/leads/staff-performance', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_staff_performance():
    """
    GET /api/crm/leads/staff-performance
    Team performance split by employee with period-aware goals.
    Goals:
      - standard staff: 100 leads/day
      - offshore role_id=5: 180 leads/day
    Query params:
      - period: daily|weekly|monthly
      - service: utilities|water
      - employee_id: optional (admins only)
    """
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        period, start_dt, end_dt, goal_multiplier = _staff_period_bounds(request.args.get('period', 'daily'))

        current_user = request.current_user
        role_name = getattr(current_user, 'role', None)
        admin_user = is_crm_leads_admin_role(role_name)
        my_emp_id = getattr(current_user, 'employee_id', None)
        only_employee_id = request.args.get('employee_id', type=int)

        if not admin_user:
            if my_emp_id is None:
                return jsonify([]), 200
            only_employee_id = my_emp_id

        if local_demo_dashboard_enabled():
            return jsonify(dummy_leads_staff_performance(period, only_employee_id)), 200

        db = get_supabase_client()
        ts_expr = _resolve_opportunity_ts_expr(db)

        base_sql = f'''
            SELECT
                em."employee_id",
                em."employee_name",
                COALESCE(sm."stage_name", 'Unknown') AS stage_name,
                COUNT(od."opportunity_id")::bigint AS cnt,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM "StreemLyne_MT"."User_Master" um
                        INNER JOIN "StreemLyne_MT"."User_Role_Mapping" urm
                            ON urm."user_id" = um."user_id"
                        WHERE um."employee_id" = em."employee_id"
                          AND urm."role_id" = {OFFSHORE_ROLE_ID}
                    ) THEN 1 ELSE 0
                END AS is_offshore
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od."stage_id" = sm."stage_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
              AND em."tenant_id" = %s
              AND od."service_id" = %s
              AND od."opportunity_owner_employee_id" IS NOT NULL
              AND {ts_expr} >= %s
              AND {ts_expr} < %s
              AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd."opportunity_id" = od."opportunity_id"
              )
              {{employee_filter}}
            GROUP BY em."employee_id", em."employee_name", COALESCE(sm."stage_name", 'Unknown'), is_offshore
            ORDER BY em."employee_name" ASC
        '''
        params = [tenant_id, tenant_id, tenant_id, service_id, start_dt, end_dt]
        if only_employee_id:
            sql = base_sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = %s')
            params.append(only_employee_id)
        else:
            sql = base_sql.format(employee_filter='')

        rows = db.execute_query(sql, tuple(params))

        employees = {}
        for r in (rows or []):
            eid = r.get('employee_id')
            if eid is None:
                continue

            if eid not in employees:
                employees[eid] = {
                    'employee_id': eid,
                    'employee_name': r.get('employee_name') or 'Unknown',
                    'role_id': OFFSHORE_ROLE_ID if int(r.get('is_offshore') or 0) == 1 else None,
                    'converted_count': 0,
                    'in_progress_count': 0,
                    'not_contacted_count': 0,
                    'lost_count': 0,
                    'renewed_count': 0,
                    'renewed_directly_count': 0,
                    'end_date_changed_count': 0,
                    'priced_count': 0,
                    'total_contacts': 0,
                }

            stage = str((r or {}).get('stage_name') or '').strip().lower()
            count = int((r or {}).get('cnt') or 0)
            employees[eid]['total_contacts'] += count

            if stage == 'converted':
                employees[eid]['converted_count'] += count
            elif stage in ('already renewed', 'renewed'):
                employees[eid]['converted_count'] += count
                employees[eid]['renewed_count'] += count
            elif stage == 'renewed directly':
                employees[eid]['converted_count'] += count
                employees[eid]['renewed_directly_count'] += count
            elif stage == 'end date changed':
                employees[eid]['end_date_changed_count'] += count
            elif stage == 'priced':
                employees[eid]['priced_count'] += count
                employees[eid]['in_progress_count'] += count
            elif stage in ('callback', 'not answered', 'broker in place', 'email only', 'complaint', 'incorrect supplier'):
                employees[eid]['in_progress_count'] += count
            elif stage in ('lost', 'lost cot', 'invalid number', 'meter de-energised'):
                employees[eid]['lost_count'] += count
            else:
                employees[eid]['not_contacted_count'] += count

        output = []
        for emp in employees.values():
            total = emp['total_contacts'] or 0
            converted = emp['converted_count'] or 0
            conversion_rate = round((converted / total) * 100) if total > 0 else 0
            daily_target = 180 if emp.get('role_id') == OFFSHORE_ROLE_ID else 100
            goal_target = daily_target * goal_multiplier
            goal_achieved = total
            goal_progress_pct = round((goal_achieved / goal_target) * 100, 1) if goal_target > 0 else 0

            output.append({
                'employee_id': emp['employee_id'],
                'employee_name': emp['employee_name'],
                'role_id': emp.get('role_id'),
                'total_contacts': total,
                'converted_count': converted,
                'renewed_count': converted,
                'in_progress_count': emp['in_progress_count'],
                'not_contacted_count': emp['not_contacted_count'],
                'lost_count': emp['lost_count'],
                'renewed_directly_count': emp['renewed_directly_count'],
                'end_date_changed_count': emp['end_date_changed_count'],
                'priced_count': emp['priced_count'],
                'conversion_rate': conversion_rate,
                'goal_target': goal_target,
                'goal_achieved': goal_achieved,
                'goal_progress_pct': min(100, max(0, goal_progress_pct)),
                'goal_hit': goal_achieved >= goal_target,
                'period': period,
            })

        output.sort(key=lambda x: x['employee_name'].lower())
        return jsonify(output), 200

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
    """
    from backend.crm.supabase_client import get_supabase_client
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        logger.warning('🔍 stats-by-employee: tenant_id=%s service_id=%s', tenant_id, service_id)

        db = get_supabase_client()

        # ✅ FIX: Filter by is_allocated=FALSE to show unallocated leads
        rows = db.execute_query('''
            SELECT
                em."employee_id",
                em."employee_name",
                COUNT(od."opportunity_id") AS count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
            AND od."service_id" = %s
            AND od."opportunity_owner_employee_id" IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd."opportunity_id" = od."opportunity_id"
            )
            GROUP BY em."employee_id", em."employee_name"
            HAVING COUNT(od."opportunity_id") > 0
            ORDER BY count DESC
        ''', (tenant_id, tenant_id, service_id))

        logger.warning('📊 Raw rows from DB: %s', rows)
        logger.warning('📊 Number of rows: %s', len(rows) if rows else 0)

        stats = [
            {
                'employee_id':   r.get('employee_id'),
                'employee_name': r.get('employee_name'),
                'count':         int(r.get('count') or 0),
            }
            for r in (rows or [])
        ]

        logger.warning('📊 Final stats array: %s', stats)

        return jsonify({'stats': stats}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error('❌ Error in stats-by-employee: %s', str(e))
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/stats-by-employee-detailed', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats_by_employee_detailed():
    """
    GET /api/crm/leads/stats-by-employee-detailed
    Per-employee lead counts split by CRM stage (same scope as stats-by-employee).
    Optional query: employee_id (admins only) to inspect one person.
    Non-admins always receive only their own employee_id row.
    """
    from backend.crm.supabase_client import get_supabase_client

    try:
        tenant_id = g.tenant_id
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        current_user = request.current_user
        role_name = getattr(current_user, 'role', None)
        admin_user = is_crm_leads_admin_role(role_name)
        my_emp_id = getattr(current_user, 'employee_id', None)

        only_employee_id = request.args.get('employee_id', type=int)
        if not admin_user:
            if my_emp_id is None:
                return jsonify({'employees': []}), 200
            only_employee_id = my_emp_id

        db = get_supabase_client()

        base_where = '''
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od."stage_id" = sm."stage_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
            AND od."service_id" = %s
            AND od."opportunity_owner_employee_id" IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd."opportunity_id" = od."opportunity_id"
            )
        '''
        params = [tenant_id, tenant_id, service_id]

        if only_employee_id:
            base_where += ' AND od."opportunity_owner_employee_id" = %s'
            params.append(only_employee_id)

        query = f'''
            SELECT
                em."employee_id",
                em."employee_name",
                COALESCE(sm."stage_name", 'Unknown') AS stage_name,
                COUNT(od."opportunity_id")::bigint AS cnt
            {base_where}
            GROUP BY em."employee_id", em."employee_name", COALESCE(sm."stage_name", 'Unknown')
            HAVING COUNT(od."opportunity_id") > 0
            ORDER BY em."employee_name" ASC, cnt DESC
        '''

        rows = db.execute_query(query, tuple(params))

        grouped = {}
        for r in rows or []:
            eid = r.get('employee_id')
            if eid is None:
                continue
            if eid not in grouped:
                grouped[eid] = {
                    'employee_id': eid,
                    'employee_name': r.get('employee_name') or '—',
                    'total': 0,
                    'by_stage': [],
                }
            c = int(r.get('cnt') or r.get('count') or 0)
            grouped[eid]['by_stage'].append({
                'stage_name': r.get('stage_name') or 'Unknown',
                'count': c,
            })
            grouped[eid]['total'] += c

        for v in grouped.values():
            v['by_stage'].sort(key=lambda x: -x['count'])

        employees = sorted(grouped.values(), key=lambda x: -x['total'])

        return jsonify({'employees': employees}), 200

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

@crm_bp.route('/leads/<int:opportunity_id>/callback', methods=['OPTIONS'])
def leads_callback_options(opportunity_id):
    return jsonify({}), 200


@crm_bp.route('/leads/<int:opportunity_id>/callback', methods=['POST'], provide_automatic_options=False)
@token_required
@tenant_from_jwt
def leads_callback(opportunity_id):
    """
    POST /api/crm/leads/<opportunity_id>/callback
    Save a callback/status update for a lead.
    Updates stage_id on Opportunity_Details based on status.
    """
    from backend.crm.supabase_client import get_supabase_client
    from datetime import datetime
 
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
            SELECT opportunity_id, stage_id, client_id
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = %s
            AND ("tenant_lead_id" = %s OR opportunity_id = %s)
            LIMIT 1
        ''', (tenant_id, opportunity_id, opportunity_id), fetch_one=True)
 
        if not lead:
            return jsonify({'error': 'Lead not found'}), 404
 
        # Use the resolved real opportunity_id for all subsequent DB operations
        real_id = lead['opportunity_id']
        lead_client_id = lead.get('client_id')

        def _parse_date(value):
            if not value:
                return None
            try:
                return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
            except Exception:
                return None

        def _save_interaction():
            # Calendar and lead history read from Client_Interactions.
            # Persist every callback/status update here so date changes reflect immediately.
            if not lead_client_id:
                logger.warning(
                    'leads_callback: skipping interaction insert (no client_id) for opportunity_id=%s',
                    real_id
                )
                return

            reminder_dt = _parse_date(callback_date)
            contact_dt = _parse_date(called_date) or datetime.utcnow().date()
            formatted_notes = f"[{status}] {notes}".strip() if notes else f"[{status}]"

            db.execute_update('''
                INSERT INTO "StreemLyne_MT"."Client_Interactions"
                    ("client_id", "contact_date", "contact_method", "reminder_date", "notes", "next_steps", "created_at")
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ''', (lead_client_id, contact_dt, 1, reminder_dt, formatted_notes, status))
 
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
            _save_interaction()

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
            _save_interaction()

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

        _save_interaction()

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
        role_name = getattr(current_user, 'role', None)
        normalized_role = str(role_name).strip().lower() if role_name else None
        admin_user = is_crm_leads_admin_role(role_name)

        import logging
        logging.getLogger(__name__).warning(
            '🔍 get_allocated_leads: employee_id=%s is_admin=%s tenant=%s service=%s',
            employee_id, admin_user, tenant_id, service_param
        )

        if not admin_user and not employee_id:
            return jsonify([]), 200

        db = get_supabase_client()

        if admin_user:
            query = '''
                SELECT od.*, sm."stage_name", em."employee_name" AS assigned_to_name,
                       COALESCE(od."business_name", od."opportunity_title") AS business_name,
                       sup."supplier_company_name" AS supplier_name
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
                LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
                LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id" = sup."supplier_id"
                LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
                WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
                AND od."service_id" = %s
                AND od."is_allocated" = TRUE
                ORDER BY od."created_at" DESC
            '''
            rows = db.execute_query(query, (tenant_id, tenant_id, service_id))
        else:
            query = '''
                SELECT od.*, sm."stage_name", em."employee_name" AS assigned_to_name,
                       COALESCE(od."business_name", od."opportunity_title") AS business_name,
                       sup."supplier_company_name" AS supplier_name
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
                LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
                LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id" = sup."supplier_id"
                LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
                WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
                AND od."service_id" = %s
                AND od."opportunity_owner_employee_id" = %s
                AND od."is_allocated" = TRUE
                ORDER BY od."created_at" DESC
            '''
            rows = db.execute_query(query, (tenant_id, tenant_id, service_id, employee_id))
        
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
