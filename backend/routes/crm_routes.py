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

def _is_admin_from_db(user):
    """Mirror renewals: look up role from DB instead of trusting user.role attribute."""
    from backend.db import SessionLocal
    from sqlalchemy import text
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT rm.role_name
            FROM "StreemLyne_MT"."User_Role_Mapping" urm
            JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE urm.user_id = :user_id
            LIMIT 1
        """), {'user_id': user.user_id}).fetchone()
        role = result[0] if result else None
        return role in ['Platform Admin', 'Tenant Super Admin']
    except Exception:
        return False
    finally:
        session.close()

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
    GET /api/crm/leads

    Business rules (mirrors renewals get_energy_customers + get_priced_customers):

    ADMIN (Platform Admin / Tenant Super Admin):
      - Sees ALL leads for the tenant across all employees.
      - Optional ?salesperson=<employee_id> to drill into one agent.
      - No is_allocated filter — admin needs full visibility to assign.

    NON-ADMIN (Salesperson):
      - Sees only their own NON-ALLOCATED leads.
      - is_allocated=TRUE means the lead was reassigned away from them and
        belongs in /allocated instead.
    """
    from backend.crm.supabase_client import get_supabase_client
    from backend.crm.utils.role_helpers import is_admin_user
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id    = g.tenant_id
        current_user = request.current_user
        service_param     = request.args.get('service', 'utilities')
        service_id        = 2 if service_param.strip().lower() == 'water' else 1
        exclude_stage     = request.args.get('exclude_stage', '')
        salesperson_param = request.args.get('salesperson')

        employee_id = getattr(current_user, 'employee_id', None)
        is_admin = _is_admin_from_db(current_user)

        logger.warning(
            '🔍 get_leads: employee_id=%s is_admin=%s tenant=%s service=%s',
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
        '''
        params = [tenant_id, service_id]

        if is_admin:
            # Admin sees all leads; optionally filter to one salesperson
            if salesperson_param and salesperson_param != 'All':
                try:
                    query += ' AND od."opportunity_owner_employee_id" = %s'
                    params.append(int(salesperson_param))
                except ValueError:
                    pass
        else:
            # Non-admin: own non-allocated leads only
            if not employee_id:
                logger.warning('⚠️ Non-admin has no employee_id - returning empty')
                return jsonify([]), 200
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

        logger.warning(
            '✅ get_leads returning %d leads (is_admin=%s employee_id=%s)',
            len(results), is_admin, employee_id
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

    return crm_controller.update_lead(opportunity_id)


@crm_bp.route('/leads/<int:opportunity_id>/status', methods=['PATCH'])
@token_required
@tenant_from_jwt
def update_lead_status(opportunity_id):
    return crm_controller.update_lead_status(opportunity_id)


@crm_bp.route('/leads/assign', methods=['PATCH'])
@token_required
@tenant_from_jwt
def assign_leads():
    """
    PATCH /api/crm/leads/assign
    Bulk assign leads to an employee.

    Business rules (mirrors bulk_assign_clients in renewals):
      - Sets opportunity_owner_employee_id = target employee
      - Sets is_allocated = TRUE so the lead moves to the recipient's /allocated list
        and disappears from the assigner's main list
    """
    return crm_controller.assign_leads()


@crm_bp.route('/leads/<int:opportunity_id>', methods=['DELETE'])
@token_required
@tenant_from_jwt
def delete_lead(opportunity_id):
    return crm_controller.delete_lead(opportunity_id)


@crm_bp.route('/leads/search-all', methods=['GET'])
@token_required
@tenant_from_jwt
def search_all_leads():
    """
    GET /api/crm/leads/search-all?q=...&service=...
    Cross-team text search — returns all matching leads across the tenant
    regardless of assignment or is_allocated status.
    Used by non-admins to find leads assigned to other team members (shown in amber).

    Mirrors: /energy-clients/search-all in energy_customer_routes.py
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

        # Full text search across the tenant — no is_allocated or employee filter
        rows = db.execute_query('''
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
            AND (
                COALESCE(od."business_name", od."opportunity_title") ILIKE %s
                OR od."contact_person"   ILIKE %s
                OR od."tel_number"       ILIKE %s
                OR od."email"            ILIKE %s
                OR od."mpan_mpr"         ILIKE %s
            )
            ORDER BY od."created_at" DESC
            LIMIT 50
        ''', (tenant_id, service_id, f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%'))

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
    GET /api/crm/leads/performance?service=...

    Admin: metrics across ALL leads for the tenant.
    Non-admin: metrics for their own leads only.
    """
    from backend.crm.supabase_client import get_supabase_client
    from backend.crm.utils.role_helpers import is_admin_user
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id    = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        is_admin = _is_admin_from_db(current_user)
        employee_id   = getattr(current_user, 'employee_id', None)

        db = get_supabase_client()

        query = '''
            SELECT sm."stage_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = %s
            AND od."service_id" = %s
        '''
        params = [tenant_id, service_id]

        # Non-admins only see their own performance numbers
        if not is_admin and employee_id:
            query += ' AND od."opportunity_owner_employee_id" = %s'
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
            'converted_count':        converted_count,
            'renewed_count':          renewed_count,
            'renewed_directly_count': renewed_directly_count,
            'end_date_changed_count': end_date_changed_count,
            'priced_count':           priced_count,
            'contacted_count':        in_progress_count,
            'not_contacted_count':    not_contacted_count,
            'lost_count':             lost_count,
            'success_rate':           success_rate,
            'total_customers':        total,
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
    GET /api/crm/leads/stats-by-employee?service=...
    Returns lead counts grouped by employee for the Team Overview panel.

    Admin: counts ALL leads per employee (allocated + non-allocated) so the
    team overview shows total workload per salesperson.
    Non-admin: returns only their own count.

    Returns: { stats: [{ employee_id, employee_name, count }] }
    """
    from backend.crm.supabase_client import get_supabase_client
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id    = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        is_admin = _is_admin_from_db(current_user)
        employee_id   = getattr(current_user, 'employee_id', None)

        logger.warning(
            '🔍 stats-by-employee: tenant_id=%s service_id=%s is_admin=%s',
            tenant_id, service_id, is_admin
        )

        db = get_supabase_client()

        if is_admin:
            # Admin: show ALL leads per employee (no is_allocated filter)
            # This matches what the admin sees in get_leads (all tenant leads)
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
                GROUP BY em."employee_id", em."employee_name"
                HAVING COUNT(od."opportunity_id") > 0
                ORDER BY count DESC
            ''', (tenant_id, service_id))
        else:
            # Non-admin: just their own non-allocated count
            if not employee_id:
                return jsonify({'stats': []}), 200
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
                AND od."opportunity_owner_employee_id" = %s
                AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
                GROUP BY em."employee_id", em."employee_name"
            ''', (tenant_id, service_id, employee_id))

        stats = [
            {
                'employee_id':   r.get('employee_id'),
                'employee_name': r.get('employee_name'),
                'count':         int(r.get('count') or 0),
            }
            for r in (rows or [])
        ]

        logger.warning('📊 stats-by-employee result: %s', stats)

        return jsonify({'stats': stats}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'stats': []}), 500


@crm_bp.route('/leads/bulk-delete', methods=['POST'])
@require_tenant
def bulk_delete_leads():
    return crm_controller.bulk_delete_leads()


@crm_bp.route('/leads/table', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_table():
    return crm_controller.get_leads_table()


@crm_bp.route('/leads/import/preview', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads_preview():
    return crm_controller.import_leads_preview()


@crm_bp.route('/leads/import/confirm', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads_confirm():
    return crm_controller.import_leads_confirm()


@crm_bp.route('/leads/recycle-bin', methods=['GET'])
@token_required
@tenant_from_jwt
def get_recycle_bin():
    return crm_controller.get_recycle_bin()


@crm_bp.route('/leads/cleanup', methods=['PATCH'])
@token_required
@tenant_from_jwt
def delete_expired_lost_leads():
    return crm_controller.delete_expired_lost_leads()


@crm_bp.route('/leads/import', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads():
    """
    POST /api/crm/leads/import
    Single-step import: validate then insert in one request.
    """
    try:
        tenant_id = g.tenant_id

        service_param = request.args.get('service', 'electricity')
        service_value = service_param.strip().lower() if isinstance(service_param, str) else 'electricity'
        service_id = 2 if service_value == 'water' else 1

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

        preview_result = crm_controller.crm_service.preview_lead_import(tenant_id, file)

        if not preview_result.get('success'):
            return jsonify({
                'success': False,
                'message': preview_result.get('message', 'Validation failed'),
                'total_rows': preview_result.get('total_rows', 0),
                'successful': 0,
                'failed': preview_result.get('total_rows', 1),
                'errors': preview_result.get('errors', ['Validation failed'])
            }), 400

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

        all_rows = preview_result.get('rows', [])
        validated_data = [row['data'] for row in all_rows if row.get('is_valid', False)]

        created_by = getattr(request.current_user, 'id', None)

        confirm_result = crm_controller.crm_service.confirm_lead_import(tenant_id, validated_data, created_by, service_id)

        if 'success' in confirm_result and not confirm_result['success']:
            return jsonify({
                'success': False,
                'message': confirm_result.get('message', 'Import failed'),
                'total_rows': preview_result.get('total_rows', 0),
                'successful': 0,
                'failed': preview_result.get('total_rows', 0),
                'errors': [confirm_result.get('error', 'Import failed')]
            }), 400

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
    try:
        from flask import send_file
        from openpyxl import Workbook
        from io import BytesIO

        wb = Workbook()
        ws = wb.active
        ws.title = "Leads Import"

        headers = [
            'Business Name', 'Contact Person', 'Tel Number', 'Email',
            'MPAN_MPR', 'Start Date', 'End Date', 'Annual Usage',
            'Address', 'Site Address'
        ]
        ws.append(headers)

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

        from openpyxl.styles import Font, PatternFill
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")

        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except Exception:
                    pass
            ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

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
    return crm_controller.get_leads_by_customer_type()


@crm_bp.route('/leads/allocated', methods=['GET'])
@token_required
@tenant_from_jwt
def get_allocated_leads():
    """
    GET /api/crm/leads/allocated
    Get leads that were reassigned TO the current user (is_allocated = TRUE).

    Mirrors: /energy-clients/allocated in renewals.
    """
    from backend.crm.supabase_client import get_supabase_client
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        employee_id = getattr(current_user, 'employee_id', None)

        logger.warning(
            '🔍 get_allocated_leads: employee_id=%s tenant=%s service=%s',
            employee_id, tenant_id, service_param
        )

        if not employee_id:
            return jsonify([]), 200

        db = get_supabase_client()

        rows = db.execute_query('''
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
            AND od."opportunity_owner_employee_id" = %s
            AND od."is_allocated" = TRUE
            ORDER BY od."created_at" DESC
        ''', (tenant_id, service_id, employee_id))

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

        logger.warning(
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
    Leads do not support archiving (unlike renewals), so this always returns [].
    Kept as a stub so the frontend doesn't get a 404.
    """
    return jsonify([]), 200


@crm_bp.route('/leads/<int:opportunity_id>/callback', methods=['POST', 'OPTIONS'])
@token_required
@tenant_from_jwt
def leads_callback(opportunity_id):
    """
    POST /api/crm/leads/<opportunity_id>/callback
    Save a callback/status update for a lead.

    Mirrors: /energy-clients/<client_id>/callback in renewals.

    Business rules for is_allocated:
      - Status updates do NOT change is_allocated.
      - Only the assign endpoint changes is_allocated.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    from backend.crm.supabase_client import get_supabase_client
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id = g.tenant_id

        data = request.get_json(force=True, silent=True) or {}

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

        status_config = {
            "Callback":           {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Not Answered":       {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Priced":             {"requires_date": False, "requires_sold": True,  "deletes_record": False, "requires_notes": False},
            "Lost":               {"requires_date": True,  "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Lost COT":           {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Already Renewed":    {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Invalid Number":     {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Meter De-energised": {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Broker in Place":    {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "End Date Changed":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Complaint":          {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Email Only":         {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Renewed Directly":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Incorrect Supplier": {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Converted":          {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": False},
        }

        if status not in status_config:
            return jsonify({'error': f'Invalid status: {status}'}), 400

        cfg = status_config[status]

        if cfg['requires_notes'] and not (notes or '').strip():
            return jsonify({'error': 'Notes are required for this status'}), 400

        if cfg['requires_sold'] and is_sold is None:
            return jsonify({'error': 'Please select if the contract was sold'}), 400

        if status == 'Already Renewed' and not renewed_by:
            return jsonify({'error': 'Please select if renewed by customer or agent'}), 400

        db = get_supabase_client()

        # Verify lead belongs to tenant and resolve real opportunity_id
        lead = db.execute_query('''
            SELECT opportunity_id, stage_id
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = %s
            AND ("tenant_lead_id" = %s OR opportunity_id = %s)
            LIMIT 1
        ''', (tenant_id, opportunity_id, opportunity_id), fetch_one=True)

        if not lead:
            return jsonify({'error': 'Lead not found'}), 404

        real_id = lead['opportunity_id']

        # Handle statuses that send to recycle bin
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

        # Handle Priced: not sold → move to Priced page
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

        # Update end date if provided
        if new_end_date_str and status in ('End Date Changed', 'Already Renewed'):
            db.execute_update('''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET end_date = %s
                WHERE opportunity_id = %s AND tenant_id = %s
            ''', (new_end_date_str, real_id, tenant_id))

        # Update supplier if provided (Already Renewed with new supplier)
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

        # Update stage_id
        if stage_id:
            db.execute_update('''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET stage_id = %s
                WHERE opportunity_id = %s AND tenant_id = %s
            ''', (stage_id, real_id, tenant_id))

        logger.info('leads_callback: saved status=%s for real_id=%s (url_id=%s)',
                    status, real_id, opportunity_id)

        return jsonify({
            'success': True,
            'message': 'Callback saved successfully',
            'status': status,
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/priced', methods=['GET'])
@token_required
@tenant_from_jwt
def get_priced_leads():
    """
    GET /api/crm/leads/priced
    Get leads in the Priced stage for the current employee.
    Mirrors: /energy-clients/priced in renewals.
    """
    from backend.crm.supabase_client import get_supabase_client
    from backend.crm.utils.role_helpers import is_admin_user
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id = g.tenant_id
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        is_admin = is_admin_user(current_user)
        employee_id = getattr(current_user, 'employee_id', None)
        salesperson_param = request.args.get('salesperson')

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
            AND LOWER(sm."stage_name") = 'priced'
        '''
        params = [tenant_id, service_id]

        if is_admin and salesperson_param and salesperson_param != 'All':
            try:
                query += ' AND od."opportunity_owner_employee_id" = %s'
                params.append(int(salesperson_param))
            except ValueError:
                pass
        elif not is_admin and employee_id:
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
        return jsonify(results), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ========================================
# CLIENT ROUTES
# ========================================

@crm_bp.route('/clients', methods=['POST'])
@require_tenant
def create_client():
    return crm_controller.create_client()


@crm_bp.route('/clients/<int:client_id>/call-summary', methods=['POST'])
@require_tenant
def create_call_summary(client_id):
    return crm_controller.create_call_summary(client_id)


@crm_bp.route('/clients/<int:client_id>/upload', methods=['POST'])
@require_tenant
def client_upload_document(client_id):
    return crm_controller.client_upload_document(client_id)


# ========================================
# PROJECT ROUTES
# ========================================

@crm_bp.route('/projects', methods=['GET'])
@require_tenant
def get_projects():
    return crm_controller.get_projects()


@crm_bp.route('/projects/<int:project_id>', methods=['GET'])
@require_tenant
def get_project_detail(project_id):
    return crm_controller.get_project_detail(project_id)


# ========================================
# DEAL/CONTRACT ROUTES
# ========================================

@crm_bp.route('/deals', methods=['GET'])
@require_tenant
def get_deals():
    return crm_controller.get_deals()


@crm_bp.route('/deals/<int:contract_id>', methods=['GET'])
@require_tenant
def get_deal_detail(contract_id):
    return crm_controller.get_deal_detail(contract_id)


# ========================================
# USER ROUTES
# ========================================

@crm_bp.route('/users', methods=['GET'])
@require_tenant
def get_users():
    return crm_controller.get_users()


@crm_bp.route('/employees', methods=['GET'])
@token_required
@tenant_from_jwt
def get_employees():
    return crm_controller.get_employees()


# ========================================
# SUPPORTING DATA ROUTES
# ========================================

@crm_bp.route('/roles', methods=['GET'])
def get_roles():
    return crm_controller.get_roles()


@crm_bp.route('/stages', methods=['GET'], strict_slashes=False)
@token_required
@tenant_from_jwt
def get_stages():
    return crm_controller.get_stages()


@crm_bp.route('/services', methods=['GET'])
def get_services():
    return crm_controller.get_services()


@crm_bp.route('/suppliers', methods=['GET'])
@require_tenant
def get_suppliers():
    return crm_controller.get_suppliers()


@crm_bp.route('/interactions', methods=['GET'])
@require_tenant
def get_interactions():
    return crm_controller.get_interactions()


# ========================================
# DASHBOARD ROUTE
# ========================================

@crm_bp.route('/dashboard', methods=['GET'])
@require_tenant
def get_dashboard():
    return crm_controller.get_dashboard()


@crm_bp.route('/priced', methods=['GET'])
@token_required
@tenant_from_jwt
def get_priced():
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
                od.notes                                                AS notes,
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


# ========================================
# HEALTH CHECK
# ========================================

@crm_bp.route('/health', methods=['GET'])
def health_check():
    return {
        'success': True,
        'module': 'CRM',
        'status': 'operational',
        'message': 'StreemLyne CRM module is running'
    }, 200


@crm_bp.route('/debug/tenant/<int:tenant_id>', methods=['GET'])
def debug_tenant_lookup(tenant_id):
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