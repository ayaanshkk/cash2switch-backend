# -*- coding: utf-8 -*-
"""
CRM Routes Blueprint — uses SessionLocal (same connection as renewals).
All raw SQL queries use SQLAlchemy text() via SessionLocal so leads and
renewals always hit the same database connection.
"""
from datetime import datetime, timedelta

from backend.models import Client_Interactions, Client_Master
from flask import Blueprint, request, g, jsonify, current_app
from functools import wraps
from sqlalchemy import text, func
from backend.db import SessionLocal
from backend.crm.controllers.crm_controller import CRMController
from backend.crm.middleware.tenant_middleware import require_tenant
from backend.crm.utils.role_helpers import is_crm_leads_admin_role
from .auth_helpers import token_required
import logging
import re

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_admin_from_db(user) -> bool:
    """Look up role from DB — same pattern as energy_customer_routes.py."""
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT rm.role_name
            FROM "StreemLyne_MT"."User_Role_Mapping" urm
            JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE urm.user_id = :user_id
            LIMIT 1
        """), {'user_id': user.user_id}).fetchone()
        role = str(result[0]).strip().lower() if result and result[0] else None
        return role in ['platform admin', 'tenant super admin']
    except Exception:
        return False
    finally:
        session.close()


def _serial(v):
    """Serialise a DB value to a JSON-safe Python type."""
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


def _rows_to_list(rows):
    """Convert SQLAlchemy MappingResult rows to serialised list of dicts."""
    if not rows:
        return []
    return [{k: _serial(v) for k, v in dict(row).items()} for row in rows]


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


def log_lead_field_change(session, opportunity_id: int, field_name: str, old_value, new_value, tenant_id: str):
    """
    Log a field change to Client_Interactions with old → new format
    ✅ Auto-creates client_id if missing
    """
    def format_value(val):
        if val is None or val == '':
            return "—"
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, datetime):
            return val.strftime('%d/%m/%Y')
        if hasattr(val, 'isoformat'):
            return val.strftime('%d/%m/%Y')
        return str(val)
    
    old_formatted = format_value(old_value)
    new_formatted = format_value(new_value)
    
    if old_formatted == new_formatted:
        return
    
    change_note = f"Changed {field_name}: '{old_formatted}' → '{new_formatted}'"
    
    # ✅ Ensure client_id exists (creates if missing)
    try:
        client_id = ensure_lead_client_id(session, opportunity_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to ensure client_id for lead {opportunity_id}: {e}")
        return
    
    interaction = Client_Interactions(
        client_id=client_id,
        contact_date=datetime.utcnow().date(),
        contact_method=1,
        notes=change_note,
        next_steps='Field Updated',
        created_at=datetime.utcnow()
    )
    session.add(interaction)


def ensure_lead_client_id(session, opportunity_id: int, tenant_id: str) -> int:
    """
    Ensure a lead has a client_id (creates one if missing)
    Returns: client_id
    """
    lead = session.execute(text("""
        SELECT client_id FROM "StreemLyne_MT"."Opportunity_Details"
        WHERE opportunity_id = :opp_id
    """), {'opp_id': opportunity_id}).mappings().first()
    
    if lead and lead['client_id']:
        return lead['client_id']
    
    lead_data = session.execute(text("""
        SELECT business_name, contact_person, tel_number, email, opportunity_owner_employee_id
        FROM "StreemLyne_MT"."Opportunity_Details"
        WHERE opportunity_id = :opp_id
    """), {'opp_id': opportunity_id}).mappings().first()
    
    if not lead_data:
        raise ValueError(f"Lead {opportunity_id} not found")
    
    # Create Client_Master record
    client = Client_Master(
        tenant_id=int(tenant_id),
        assigned_employee_id=lead_data.get('opportunity_owner_employee_id'),
        client_company_name=lead_data.get('business_name') or '[IMPORTED LEADS]',
        client_contact_name=lead_data.get('contact_person') or '',
        client_phone=lead_data.get('tel_number') or '',
        client_email=lead_data.get('email') or '',
        default_currency_id=1,
        created_at=datetime.utcnow()
    )
    session.add(client)
    session.flush()
    
    # Link back to opportunity
    session.execute(text("""
        UPDATE "StreemLyne_MT"."Opportunity_Details"
        SET client_id = :client_id
        WHERE opportunity_id = :opp_id
    """), {'client_id': client.client_id, 'opp_id': opportunity_id})
    
    session.flush()
    return client.client_id


def tenant_from_jwt(f):
    """Set g.tenant_id (as int) from request.current_user.tenant_id."""
    @wraps(f)
    def _wrap(*args, **kwargs):
        current_user = getattr(request, 'current_user', None)
        if not current_user or getattr(current_user, 'tenant_id', None) is None:
            return jsonify({'error': 'Missing tenant in token'}), 401
        try:
            g.tenant_id = int(getattr(current_user, 'tenant_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid tenant_id in token'}), 401
        return f(*args, **kwargs)
    return _wrap


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


def _resolve_opportunity_ts_expr(session) -> str:
    """Resolve which timestamp column exists on Opportunity_Details"""
    try:
        rows = session.execute(text('''
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
              AND table_name = 'Opportunity_Details'
        ''')).mappings().all()
        
        columns = {str((r or {}).get('column_name') or '').strip().lower() for r in (rows or [])}
        if 'updated_at' in columns:
            return 'od."updated_at"'
        if 'modified_at' in columns:
            return 'od."modified_at"'
        if 'created_at' in columns:
            return 'od."created_at"'
        return 'NOW()'
    except Exception:
        return 'od."created_at"'


# ── Blueprint ─────────────────────────────────────────────────────────────────

crm_bp = Blueprint('crm', __name__, url_prefix='/api/crm')
crm_controller = CRMController()

OFFSHORE_ROLE_ID = 5


# ========================================
# LEAD ROUTES
# ========================================

@crm_bp.route('/leads', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads():
    """
    Get all leads with team overview stats and per-employee display_order
    Admin sees all tenant leads, non-admin sees only their own non-allocated leads
    ✅ EXCLUDES leads with stage "Priced" (they appear on /leads/priced instead)
    """
    session = SessionLocal()
    try:
        tenant_id    = str(g.tenant_id)
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        exclude_stage = request.args.get('exclude_stage', '')
        employee_id   = getattr(current_user, 'employee_id', None)

        logger.warning(
            '🔍 get_leads: employee_id=%s tenant=%s service=%s',
            employee_id, tenant_id, service_param
        )

        is_admin = _is_admin_from_db(current_user)

        if not is_admin and not employee_id:
            logger.warning('⚠️ No employee_id for non-admin - returning empty')
            return jsonify({'data': [], 'team_stats': []}), 200
        
        logger.warning('Skipped display_order recalculation on read-only leads request')

        # TEAM STATS QUERY - ✅ Excludes "Priced" stage from counts
        team_stats_rows = []
        
        if is_admin:
            team_stats_rows = session.execute(text("""
                SELECT 
                    em."employee_id",
                    em."employee_name",
                    COUNT(od."opportunity_id") as lead_count
                FROM "StreemLyne_MT"."Employee_Master" em
                LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od 
                    ON em."employee_id" = od."opportunity_owner_employee_id"
                    AND od."tenant_id" = :tenant_id
                    AND od."service_id" = :service_id
                    AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
                LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                    ON od."client_id" = cm."client_id"
                    AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                    ON od."stage_id" = sm."stage_id"
                WHERE em."tenant_id" = :tenant_id
                    AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != 'priced')
                GROUP BY em."employee_id", em."employee_name"
                ORDER BY em."employee_name"
            """), {'tenant_id': tenant_id, 'service_id': service_id}).mappings().all()
            
        team_stats = [
            {
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'lead_count': int(row['lead_count'] or 0)
            }
            for row in team_stats_rows
        ]

        logger.warning('📊 Team stats: %s', team_stats)

        # MAIN LEADS QUERY - ✅ Excludes "Priced" stage
        query = """
            SELECT
                od."opportunity_id",
                od."tenant_lead_id",
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                od."contact_person",
                od."tel_number",
                od."mobile_no",
                od."email",
                od."mpan_mpr",
                od."mpan_bottom",
                od."supplier_id",
                od."annual_usage",
                od."start_date",
                od."end_date",
                od."service_id",
                od."stage_id",
                od."created_at",
                od."opportunity_owner_employee_id",
                od."stand_charge",
                od."rate_1",
                od."net_notch",
                od."payment_type",
                od."postcode",
                COALESCE(cm."is_archived", FALSE) AS is_archived,
                od."is_allocated",
                od."is_cleansed",
                od."display_id",
                od."display_order",
                sm."stage_name",
                em."employee_name" AS assigned_to_name,
                sup."supplier_company_name" AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od."client_id"   = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od."stage_id"    = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id"  = sup."supplier_id"
            WHERE od."tenant_id" = :tenant_id
            AND od."service_id" = :service_id
            AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
            AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != 'priced')
        """
        params = {'tenant_id': tenant_id, 'service_id': service_id}

        if not is_admin:
            query += """
            AND od."opportunity_owner_employee_id" = :employee_id
            AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
            """
            params['employee_id'] = employee_id

        if exclude_stage:
            query += ' AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != LOWER(:exclude_stage))'
            params['exclude_stage'] = exclude_stage

        query += ' ORDER BY od."display_order" ASC NULLS LAST, od."created_at" DESC NULLS LAST, od."opportunity_id" DESC'

        rows = session.execute(text(query), params).mappings().all()
        results = _rows_to_list(rows)

        logger.warning(
            '✅ get_leads returning %d leads + %d team stats for employee_id=%s (is_admin=%s)',
            len(results), len(team_stats), employee_id, is_admin
        )

        return jsonify({
            'data': results,
            'team_stats': team_stats,
            'user_context': {
                'is_admin': is_admin,
                'employee_id': employee_id
            }
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error('❌ get_leads error: %s', str(e))
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            session.close()
        except Exception:
            pass

@crm_bp.route('/leads/<int:opportunity_id>', methods=['GET'])
@token_required
@tenant_from_jwt
def get_lead_detail(opportunity_id):
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)

        sql = """
            SELECT
                od.*,
                sm.stage_name,
                em.employee_name          AS assigned_to_name,
                COALESCE(od.business_name, od.opportunity_title) AS business_name,
                sup.supplier_company_name AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od.client_id   = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id   = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od.opportunity_owner_employee_id = em.employee_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
            WHERE od.tenant_id = :tenant_id
            AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
        """

        row = session.execute(
            text(sql + """
                AND (od.opportunity_id = :id OR od.tenant_lead_id = :id)
                ORDER BY CASE WHEN od.opportunity_id = :id THEN 0 ELSE 1 END
                LIMIT 1
            """),
            {'tenant_id': tenant_id, 'id': opportunity_id}
        ).mappings().first()

        if not row:
            return jsonify({'error': 'Lead not found'}), 404

        return jsonify({k: _serial(v) for k, v in dict(row).items()}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads', methods=['POST'])
@token_required
@tenant_from_jwt
def create_lead():
    return crm_controller.create_lead()


@crm_bp.route('/leads/<int:opportunity_id>', methods=['PUT', 'PATCH'])
@token_required
@tenant_from_jwt
def update_lead(opportunity_id):
    if request.method == 'PATCH':
        ALLOWED = {
            'stage_id','status','business_name','contact_person','tel_number',
            'mobile_no','email','position','company_number','date_of_birth',
            'opportunity_owner_employee_id','mpan_mpr','mpan_bottom','supplier_id',
            'annual_usage','start_date','end_date','payment_type','term_sold',
            'net_notch','comms_paid','aggregator','site_name','month_sold',
            'house_name','house_number','door_number','address','town','county',
            'postcode','stand_charge','rate_1','rate_2','rate_3','night_charge',
            'eve_weekend_charge','other_charges_1','other_charges_2','other_charges_3',
            'bank_name','bank_account_number','bank_sort_code',
            'charity_ltd_company_number','partner_details',
            'meter_ref','uplift','comments','document_details',
        }
        
        # Field name mappings for logging
        FIELD_DISPLAY_NAMES = {
            'business_name': 'Trading Name',
            'contact_person': 'Client Name',
            'tel_number': 'Tel Number',
            'mobile_no': 'Mobile Number',
            'email': 'Email',
            'position': 'Position',
            'company_number': 'Company Number',
            'date_of_birth': 'Date of Birth',
            'mpan_mpr': 'MPAN Top',
            'mpan_bottom': 'MPAN Bottom',
            'supplier_id': 'New Supplier',
            'annual_usage': 'Annual Usage',
            'start_date': 'Start Date',
            'end_date': 'Contract End',
            'payment_type': 'Payment Type',
            'term_sold': 'Term Sold',
            'net_notch': 'Net Notch',
            'comms_paid': 'Comms Paid',
            'aggregator': 'Aggregator',
            'site_name': 'Site Name',
            'month_sold': 'Month Sold',
            'house_name': 'House Name',
            'house_number': 'House Number',
            'door_number': 'Door Number',
            'address': 'Street',
            'town': 'Town',
            'county': 'County',
            'postcode': 'Post Code',
            'stand_charge': 'Standing Charge',
            'rate_1': 'Rate 1',
            'rate_2': 'Rate 2',
            'rate_3': 'Rate 3',
            'night_charge': 'Night Charge',
            'eve_weekend_charge': 'Eve/Weekend Charge',
            'other_charges_1': 'Other Charges 1',
            'other_charges_2': 'Other Charges 2',
            'other_charges_3': 'Other Charges 3',
            'bank_name': 'Bank Name',
            'bank_account_number': 'Account Number',
            'bank_sort_code': 'Sort Code',
            'charity_ltd_company_number': 'Charity/Ltd Company Number',
            'partner_details': 'Partner Details',
            'meter_ref': 'Meter Ref',
            'uplift': 'Uplift',
            'comments': 'Comments',
        }
        
        session = SessionLocal()
        try:
            tenant_id = str(g.tenant_id)
            data = request.get_json() or {}
            fields = {k: v for k, v in data.items() if k in ALLOWED}
            
            if not fields:
                return jsonify({'error': 'No valid fields provided'}), 400

            # Get current lead data
            current = session.execute(text("""
                SELECT * FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE tenant_id = :t
                AND (opportunity_id = :id OR tenant_lead_id = :id)
                ORDER BY CASE WHEN opportunity_id = :id THEN 0 ELSE 1 END
                LIMIT 1
            """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

            if not current:
                return jsonify({'error': 'Lead not found'}), 404

            real_id = current['opportunity_id']
            
            # Track changes for supplier_id with name resolution
            if 'supplier_id' in fields:
                old_supp_id = current.get('supplier_id')
                new_supp_id = fields['supplier_id']
                
                if old_supp_id != new_supp_id:
                    old_supp = session.execute(text(
                        'SELECT supplier_company_name FROM "StreemLyne_MT"."Supplier_Master" WHERE supplier_id = :id'
                    ), {'id': old_supp_id}).mappings().first() if old_supp_id else None
                    
                    new_supp = session.execute(text(
                        'SELECT supplier_company_name FROM "StreemLyne_MT"."Supplier_Master" WHERE supplier_id = :id'
                    ), {'id': new_supp_id}).mappings().first() if new_supp_id else None
                    
                    old_name = old_supp['supplier_company_name'] if old_supp else "—"
                    new_name = new_supp['supplier_company_name'] if new_supp else "—"
                    
                    log_lead_field_change(session, real_id, 'New Supplier', old_name, new_name, tenant_id)
            
            # Track assignment changes with employee names
            if 'opportunity_owner_employee_id' in fields:
                old_emp_id = current.get('opportunity_owner_employee_id')
                new_emp_id = fields['opportunity_owner_employee_id']
                
                if old_emp_id != new_emp_id:
                    old_emp = session.execute(text(
                        'SELECT employee_name FROM "StreemLyne_MT"."Employee_Master" WHERE employee_id = :id'
                    ), {'id': old_emp_id}).mappings().first() if old_emp_id else None
                    
                    new_emp = session.execute(text(
                        'SELECT employee_name FROM "StreemLyne_MT"."Employee_Master" WHERE employee_id = :id'
                    ), {'id': new_emp_id}).mappings().first() if new_emp_id else None
                    
                    old_name = old_emp['employee_name'] if old_emp else "Unassigned"
                    new_name = new_emp['employee_name'] if new_emp else "Unassigned"
                    
                    log_lead_field_change(session, real_id, 'Assigned To', old_name, new_name, tenant_id)
            
            # Track all other field changes
            for field, new_value in fields.items():
                if field in ['supplier_id', 'opportunity_owner_employee_id']:
                    continue
                
                display_name = FIELD_DISPLAY_NAMES.get(field, field)
                old_value = current.get(field)
                
                if old_value != new_value:
                    log_lead_field_change(session, real_id, display_name, old_value, new_value, tenant_id)

            # Apply updates
            set_clause = ', '.join(f'"{k}" = :{k}' for k in fields)
            params = {**fields, 'real_id': real_id, 'tenant_id': tenant_id}

            session.execute(text(
                f'UPDATE "StreemLyne_MT"."Opportunity_Details" '
                f'SET {set_clause} '
                f'WHERE opportunity_id = :real_id AND tenant_id = :tenant_id'
            ), params)
            
            session.commit()

            # Return updated lead
            updated = session.execute(text("""
                SELECT od.*, sm.stage_name,
                       em.employee_name AS assigned_to_name,
                       COALESCE(od.business_name, od.opportunity_title) AS business_name,
                       sup.supplier_company_name AS supplier_name
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id   = sm.stage_id
                LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od.opportunity_owner_employee_id = em.employee_id
                LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
                WHERE od.opportunity_id = :id AND od.tenant_id = :t LIMIT 1
            """), {'id': real_id, 't': tenant_id}).mappings().first()

            return jsonify({k: _serial(v) for k, v in dict(updated).items()} if updated else {'success': True}), 200

        except Exception as e:
            session.rollback()
            import traceback; traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            try: session.close()
            except Exception: pass

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
    session = SessionLocal()
    try:
        tenant_id     = str(g.tenant_id)
        q             = request.args.get('q', '').strip()
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1

        if not q or len(q) < 2:
            return jsonify([]), 200

        like = f'%{q}%'
        rows = session.execute(text("""
            SELECT od.*, sm.stage_name,
                   em.employee_name AS assigned_to_name,
                   COALESCE(od.business_name, od.opportunity_title) AS business_name,
                   sup.supplier_company_name AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od.client_id   = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id   = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od.opportunity_owner_employee_id = em.employee_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
            WHERE od.tenant_id  = :tenant_id
            AND   od.service_id = :service_id
            AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
            AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != 'priced')
            AND (
                COALESCE(od.business_name, od.opportunity_title) ILIKE :q
                OR od.contact_person ILIKE :q
                OR od.tel_number     ILIKE :q
                OR od.email          ILIKE :q
                OR od.mpan_mpr       ILIKE :q
            )
            ORDER BY od.created_at DESC
            LIMIT 50
        """), {'tenant_id': tenant_id, 'service_id': service_id, 'q': like}).mappings().all()

        return jsonify(_rows_to_list(rows)), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass

# ========================================
# LEADS STATS & BREAKDOWN ROUTES
# ========================================

@crm_bp.route('/leads/stats', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats():
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        my_emp_id = getattr(current_user, 'employee_id', None)
        requested_employee_id = request.args.get('employee_id', type=int)
        employee_id = requested_employee_id if is_admin else my_emp_id

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
            WHERE od."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
              {employee_filter}
        '''
        params = {'tenant_id': tenant_id, 'service_id': service_id}
        
        if employee_id:
            sql = text(base_sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = :employee_id'))
            params['employee_id'] = employee_id
        else:
            sql = text(base_sql.format(employee_filter=''))

        rows = session.execute(sql, params).mappings().all()
        today = datetime.utcnow().date()
        last_30 = today - timedelta(days=30)

        converted_leads = 0
        in_progress = 0
        lost_leads = 0
        new_leads = 0
        priced_leads = 0  # ✅ Track priced separately
        leads_30_60 = 0
        leads_61_90 = 0
        leads_91_180 = 0
        not_due = 0
        total_annual_usage = 0.0
        recent_30d = 0
        stage_breakdown = {}

        for r in rows:
            stage_name = r.get('stage_name') or 'Unknown'
            stage_lower = stage_name.lower()
            
            # ✅ Count priced separately
            if stage_lower == 'priced':
                priced_leads += 1
                stage_breakdown[stage_name] = stage_breakdown.get(stage_name, 0) + 1
                continue  # ✅ Skip from main counts
            
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

        # ✅ Total leads excludes priced (they're on the priced page)
        total_leads = len(rows) - priced_leads
        active_leads = max(0, total_leads - lost_leads)
        conversion_rate = round((converted_leads / total_leads) * 100, 1) if total_leads else 0

        return jsonify({
            'total_leads': total_leads,  # ✅ Excludes priced
            'active_leads': active_leads,
            'converted_leads': converted_leads,
            'new_leads': new_leads,
            'in_progress': in_progress,
            'lost_leads': lost_leads,
            'priced_leads': priced_leads,  # ✅ Show priced count separately
            'conversion_rate': conversion_rate,
            'total_value': 0,
            'recent_leads_30d': recent_30d,
            'allocated_leads': 0,
            'unallocated_leads': total_leads,
            'stage_breakdown': stage_breakdown,  # ✅ Includes all stages including Priced
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
    finally:
        try: session.close()
        except Exception: pass

@crm_bp.route('/leads/stage-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stage_breakdown():
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        employee_id = request.args.get('employee_id', type=int) if is_admin else getattr(current_user, 'employee_id', None)

        sql_base = '''
            SELECT COALESCE(sm."stage_name", 'Unknown') AS stage_name, COUNT(od."opportunity_id")::bigint AS count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
              {employee_filter}
            GROUP BY COALESCE(sm."stage_name", 'Unknown')
            ORDER BY count DESC
        '''
        params = {'tenant_id': tenant_id, 'service_id': service_id}
        
        if employee_id:
            sql = text(sql_base.format(employee_filter=' AND od."opportunity_owner_employee_id" = :employee_id'))
            params['employee_id'] = employee_id
        else:
            sql = text(sql_base.format(employee_filter=''))
            
        rows = session.execute(sql, params).mappings().all()
        
        return jsonify([
            {'stage_id': i + 1, 'stage_name': r.get('stage_name') or 'Unknown', 
             'count': int(r.get('count') or 0), 'total_value': 0}
            for i, r in enumerate(rows)
        ]), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/supplier-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_supplier_breakdown():
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        employee_id = request.args.get('employee_id', type=int) if is_admin else getattr(current_user, 'employee_id', None)

        sql_base = '''
            SELECT COALESCE(sup."supplier_company_name", 'Unknown') AS supplier_name, 
                   COUNT(od."opportunity_id")::bigint AS lead_count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id" = sup."supplier_id"
            WHERE od."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
              {employee_filter}
            GROUP BY COALESCE(sup."supplier_company_name", 'Unknown')
            ORDER BY lead_count DESC
        '''
        params = {'tenant_id': tenant_id, 'service_id': service_id}
        
        if employee_id:
            sql = text(sql_base.format(employee_filter=' AND od."opportunity_owner_employee_id" = :employee_id'))
            params['employee_id'] = employee_id
        else:
            sql = text(sql_base.format(employee_filter=''))
            
        rows = session.execute(sql, params).mappings().all()
        
        return jsonify([
            {'supplier_name': r.get('supplier_name') or 'Unknown', 
             'lead_count': int(r.get('lead_count') or 0), 'total_value': 0}
            for r in rows
        ]), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/salesperson-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_salesperson_breakdown():
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        
        if not is_admin:
            return jsonify([]), 200
            
        rows = session.execute(text('''
            SELECT em."employee_id", em."employee_name", 
                   COALESCE(sm."stage_name", 'Unknown') AS stage_name, 
                   COUNT(od."opportunity_id")::bigint AS cnt
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
            GROUP BY em."employee_id", em."employee_name", COALESCE(sm."stage_name", 'Unknown')
            ORDER BY em."employee_name" ASC
        '''), {'tenant_id': tenant_id, 'service_id': service_id}).mappings().all()

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
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/by-stage', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_by_stage():
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        stage = (request.args.get('stage') or '').strip().lower()
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        employee_id = request.args.get('employee_id', type=int) if is_admin else getattr(current_user, 'employee_id', None)

        stage_filter_sql = ''
        stage_params = []
        if stage == 'in_progress':
            stage_filter_sql = " AND LOWER(COALESCE(sm.\"stage_name\", '')) IN ('callback','not answered','broker in place','email only','complaint','incorrect supplier','priced','end date changed')"
        elif stage == 'lost':
            stage_filter_sql = " AND LOWER(COALESCE(sm.\"stage_name\", '')) IN ('lost','lost cot','invalid number','meter de-energised')"
        elif stage:
            stage_filter_sql = " AND LOWER(COALESCE(sm.\"stage_name\", '')) = :stage"
            stage_params.append(stage)

        sql_base = f'''
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
            WHERE od."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
              {{employee_filter}}
              {stage_filter_sql}
            ORDER BY od."created_at" DESC
        '''
        
        params = {'tenant_id': tenant_id, 'service_id': service_id}
        
        if employee_id:
            sql = text(sql_base.format(employee_filter=' AND od."opportunity_owner_employee_id" = :employee_id'))
            params['employee_id'] = employee_id
        else:
            sql = text(sql_base.format(employee_filter=''))
            
        if stage_params:
            params['stage'] = stage_params[0]
            
        rows = session.execute(sql, params).mappings().all()

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
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/period-breakdown', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_period_breakdown():
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        period = (request.args.get('period') or '').strip().lower()
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        employee_id = request.args.get('employee_id', type=int) if is_admin else getattr(current_user, 'employee_id', None)

        sql_base = '''
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
            WHERE od."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
              {employee_filter}
            ORDER BY od."created_at" DESC
        '''
        
        params = {'tenant_id': tenant_id, 'service_id': service_id}
        
        if employee_id:
            sql = text(sql_base.format(employee_filter=' AND od."opportunity_owner_employee_id" = :employee_id'))
            params['employee_id'] = employee_id
        else:
            sql = text(sql_base.format(employee_filter=''))
            
        rows = session.execute(sql, params).mappings().all()

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
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/performance', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_performance():
    session = SessionLocal()
    try:
        tenant_id     = str(g.tenant_id)  
        current_user  = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        is_admin      = _is_admin_from_db(current_user)
        _raw_emp      = getattr(current_user, 'employee_id', None)
        employee_id   = int(_raw_emp) if _raw_emp is not None else None

        empty_response = {
            'converted_count': 0,
            'renewed_count': 0,
            'renewed_directly_count': 0,
            'end_date_changed_count': 0,
            'priced_count': 0,
            'contacted_count': 0,
            'not_contacted_count': 0,
            'lost_count': 0,
            'success_rate': 0,
            'total_customers': 0,
        }

        if not is_admin and not employee_id:
            return jsonify(empty_response), 200

        sql_base = """
            SELECT LOWER(COALESCE(sm."stage_name", '')) AS stage_name, COUNT(*) AS lead_count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            WHERE od."tenant_id" = :tenant_id
            AND od."service_id" = :service_id
            AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
            {employee_filter}
            GROUP BY LOWER(COALESCE(sm."stage_name", ''))
        """
        params = {'tenant_id': tenant_id, 'service_id': service_id}

        if not is_admin:
            sql = text(sql_base.format(employee_filter="""
            AND od."opportunity_owner_employee_id" = :employee_id
            AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
            """))
            params['employee_id'] = employee_id
        else:
            sql = text(sql_base.format(employee_filter=''))

        rows = session.execute(sql, params).mappings().all()

        counts = dict(converted=0, renewed=0, renewed_directly=0, end_date_changed=0,
                      priced=0, in_progress=0, lost=0, not_contacted=0)

        for r in rows:
            stage = (r.get('stage_name') or '').lower()
            lead_count = int(r.get('lead_count') or 0)
            if stage in ['converted', 'won']:                                     counts['converted'] += lead_count
            elif stage in ['already renewed', 'renewed']:                         counts['renewed'] += lead_count
            elif stage == 'renewed directly':                                     counts['renewed_directly'] += lead_count
            elif stage == 'end date changed':                                     counts['end_date_changed'] += lead_count
            elif stage == 'priced':                                               counts['priced'] += lead_count
            elif stage in ['callback','not answered','broker in place',
                           'email only','complaint','incorrect supplier']:         counts['in_progress'] += lead_count
            elif stage in ['lost','lost cot','invalid number','meter de-energised']: counts['lost'] += lead_count
            else:                                                                 counts['not_contacted'] += lead_count

        total = sum(counts.values())
        success = round(
            (counts['converted'] + counts['renewed'] + counts['renewed_directly']) / total * 100, 1
        ) if total else 0

        return jsonify({
            'converted_count':        counts['converted'],
            'renewed_count':          counts['renewed'],
            'renewed_directly_count': counts['renewed_directly'],
            'end_date_changed_count': counts['end_date_changed'],
            'priced_count':           counts['priced'],
            'contacted_count':        counts['in_progress'],
            'not_contacted_count':    counts['not_contacted'],
            'lost_count':             counts['lost'],
            'success_rate':           success,
            'total_customers':        total,
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


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
    """
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        period, start_dt, end_dt, goal_multiplier = _staff_period_bounds(request.args.get('period', 'daily'))

        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        my_emp_id = getattr(current_user, 'employee_id', None)
        only_employee_id = request.args.get('employee_id', type=int)

        if not is_admin:
            if my_emp_id is None:
                return jsonify([]), 200
            only_employee_id = my_emp_id

        ts_expr = _resolve_opportunity_ts_expr(session)

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
            WHERE od."tenant_id" = :tenant_id
              AND em."tenant_id" = :tenant_id
              AND od."service_id" = :service_id
              AND od."opportunity_owner_employee_id" IS NOT NULL
              AND {ts_expr} >= :start_dt
              AND {ts_expr} < :end_dt
              AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
              {{employee_filter}}
            GROUP BY em."employee_id", em."employee_name", COALESCE(sm."stage_name", 'Unknown'), is_offshore
            ORDER BY em."employee_name" ASC
        '''
        params = {'tenant_id': tenant_id, 'service_id': service_id, 'start_dt': start_dt, 'end_dt': end_dt}
        
        if only_employee_id:
            sql = text(base_sql.format(employee_filter=' AND od."opportunity_owner_employee_id" = :employee_id'))
            params['employee_id'] = only_employee_id
        else:
            sql = text(base_sql.format(employee_filter=''))

        rows = session.execute(sql, params).mappings().all()

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
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/stats-by-employee', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats_by_employee():
    """
    GET /api/crm/leads/stats-by-employee
    Returns lead counts grouped by employee for the Team Overview panel.
    """
    try:
        tenant_id    = str(g.tenant_id)
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        employee_id   = getattr(current_user, 'employee_id', None)

        logger.warning(
            '🔍 stats-by-employee: tenant_id=%s service_id=%s employee_id=%s',
            tenant_id, service_id, employee_id
        )

        if not employee_id:
            return jsonify({'stats': []}), 200

        from backend.crm.supabase_client import get_supabase_client
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
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e), 'stats': []}), 500


@crm_bp.route('/leads/stats-by-employee-detailed', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats_by_employee_detailed():
    """
    GET /api/crm/leads/stats-by-employee-detailed
    Per-employee lead counts split by CRM stage.
    """
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        service_param = request.args.get('service', 'utilities')
        service_id = 2 if service_param.strip().lower() == 'water' else 1

        current_user = request.current_user
        is_admin = _is_admin_from_db(current_user)
        my_emp_id = getattr(current_user, 'employee_id', None)

        only_employee_id = request.args.get('employee_id', type=int)
        if not is_admin:
            if my_emp_id is None:
                return jsonify({'employees': []}), 200
            only_employee_id = my_emp_id

        base_where = '''
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = :tenant_id
            AND od."service_id" = :service_id
            AND od."opportunity_owner_employee_id" IS NOT NULL
            AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
        '''
        params = {'tenant_id': tenant_id, 'service_id': service_id}

        if only_employee_id:
            base_where += ' AND od."opportunity_owner_employee_id" = :employee_id'
            params['employee_id'] = only_employee_id

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

        rows = session.execute(text(query), params).mappings().all()

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
    finally:
        try: session.close()
        except Exception: pass


# ========================================
# LEADS IMPORT / EXPORT
# ========================================

@crm_bp.route('/leads/bulk-delete', methods=['POST'])
@token_required
@tenant_from_jwt
def bulk_delete_leads():
    """Bulk delete multiple leads"""
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


def recalculate_lead_display_order(session, tenant_id, employee_id=None):
    """
    Recalculate display_order starting from 1 PER EMPLOYEE.
    Uses ROW_NUMBER() OVER (PARTITION BY opportunity_owner_employee_id ORDER BY created_at)
    """
    tenant_id = str(tenant_id)  
    
    if employee_id:
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details" od
            SET display_order = sub.rn
            FROM (
                SELECT opportunity_id,
                       ROW_NUMBER() OVER (ORDER BY created_at ASC) AS rn
                FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE tenant_id = :tenant_id
                  AND opportunity_owner_employee_id = :employee_id
                  AND (is_allocated = FALSE OR is_allocated IS NULL)
            ) sub
            WHERE od.opportunity_id = sub.opportunity_id
        """), {'tenant_id': tenant_id, 'employee_id': employee_id})
    else:
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details" od
            SET display_order = sub.rn
            FROM (
                SELECT opportunity_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY opportunity_owner_employee_id
                           ORDER BY created_at ASC
                       ) AS rn
                FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE tenant_id = :tenant_id
                  AND (is_allocated = FALSE OR is_allocated IS NULL)
                  AND opportunity_owner_employee_id IS NOT NULL
            ) sub
            WHERE od.opportunity_id = sub.opportunity_id
        """), {'tenant_id': tenant_id})
    
    session.flush()
    logger.info(
        f"✅ Recalculated lead display_order per-employee "
        f"(tenant={tenant_id}, employee={employee_id or 'ALL'})"
    )


@crm_bp.route('/leads/import', methods=['POST'])
@token_required
@tenant_from_jwt
def import_leads():
    """
    ✅ FIXED: Ensures is_allocated = FALSE for imported leads + recalculates display_order
    """
    session = SessionLocal()
    try:
        tenant_id     = str(g.tenant_id)  
        service_param = request.args.get('service', 'electricity')
        service_id    = 2 if (service_param or '').strip().lower() == 'water' else 1
 
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided',
                            'total_rows': 0, 'successful': 0, 'failed': 1,
                            'errors': ['No file uploaded']}), 400
 
        file           = request.files.get('file')
        preview_result = crm_controller.crm_service.preview_lead_import(tenant_id, file)
 
        if not preview_result.get('success'):
            return jsonify({'success': False,
                            'message': preview_result.get('message', 'Validation failed'),
                            'total_rows': preview_result.get('total_rows', 0),
                            'successful': 0, 'failed': preview_result.get('total_rows', 1),
                            'errors': preview_result.get('errors', ['Validation failed'])}), 400
 
        if not preview_result.get('valid_rows', 0):
            return jsonify({'success': False, 'message': 'No valid rows to import',
                            'total_rows': preview_result.get('total_rows', 0),
                            'successful': 0, 'failed': preview_result.get('invalid_rows', 0),
                            'errors': preview_result.get('errors', ['No valid data found'])}), 400
 
        validated_data = [r['data'] for r in preview_result.get('rows', []) if r.get('is_valid')]
        created_by     = getattr(request.current_user, 'id', None)
        importing_employee_id = getattr(request.current_user, 'employee_id', None)
        
        confirm_result = crm_controller.crm_service.confirm_lead_import(
            tenant_id, validated_data, created_by, service_id)
 
        if 'success' in confirm_result and not confirm_result['success']:
            return jsonify({'success': False,
                            'message': confirm_result.get('message', 'Import failed'),
                            'total_rows': preview_result.get('total_rows', 0),
                            'successful': 0, 'failed': preview_result.get('total_rows', 0),
                            'errors': [confirm_result.get('error', 'Import failed')]}), 400
 
        inserted = confirm_result.get('inserted', 0)
        
        if inserted > 0:
            try:
                session.execute(text("""
                    UPDATE "StreemLyne_MT"."Opportunity_Details"
                    SET is_allocated = FALSE
                    WHERE tenant_id = :tenant_id
                      AND opportunity_owner_employee_id = :employee_id
                      AND created_at >= NOW() - INTERVAL '2 minutes'
                      AND (is_allocated IS NULL OR is_allocated = TRUE)
                """), {'tenant_id': tenant_id, 'employee_id': importing_employee_id})
                session.commit()
                logger.info(f'✅ Set is_allocated = FALSE for {inserted} imported leads')
                
                recalculate_lead_display_order(session, tenant_id, importing_employee_id)
                session.commit()
                logger.info(f'✅ Recalculated display_order after importing {inserted} leads')
            except Exception as e:
                logger.error(f'❌ Post-import fix error: {e}')
                session.rollback()
        
        return jsonify({
            'success': inserted > 0,
            'message': f"Successfully imported {inserted} lead(s)" if inserted else "No new leads imported",
            'total_rows': preview_result.get('total_rows', 0),
            'successful': inserted,
            'failed': confirm_result.get('skipped', 0),
            'errors': confirm_result.get('errors', [])
        }), 200
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': str(e), 'total_rows': 0,
                        'successful': 0, 'failed': 1, 'errors': [str(e)]}), 500
    finally:
        session.close()


@crm_bp.route('/leads/import/template', methods=['GET'])
def download_leads_template():
    try:
        from flask import send_file
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from io import BytesIO

        wb = Workbook()
        ws = wb.active
        ws.title = "Leads Import"
        
        headers = [
            'Business Name',      
            'Contact Person',       
            'Tel Number',         
            'Email',
            'MPAN_MPR',
            'Start Date',         
            'End Date',           
            'Annual Usage',
            'Address',
            'Site Address'
        ]
        ws.append(headers)
        
        ws.append([
            'Acme Corp',          
            'John Doe',            
            '02071234567',         
            'john@acme.com',       
            '1234567890123',       
            '01/01/2024',          
            '31/12/2024',          
            '50000',               
            '123 Main St, London', 
            '456 Business Park, London'  
        ])
        
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            adjusted_width = min(max_length + 2, 30)
            ws.column_dimensions[column].width = adjusted_width
        
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
        return jsonify({'error': str(e)}), 500


@crm_bp.route('/leads/customer-type', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_by_customer_type():
    return crm_controller.get_leads_by_customer_type()


# ========================================
# LEADS ALLOCATED / ARCHIVED / PRICED
# ========================================

@crm_bp.route('/leads/allocated', methods=['GET'])
@token_required
@tenant_from_jwt
def get_allocated_leads():
    session = SessionLocal()
    try:
        tenant_id     = str(g.tenant_id)
        current_user  = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        _raw_emp      = getattr(current_user, 'employee_id', None)
        employee_id   = int(_raw_emp) if _raw_emp is not None else None

        if not employee_id:
            return jsonify([]), 200

        rows = session.execute(text("""
            SELECT od.*, sm.stage_name,
                   em.employee_name AS assigned_to_name,
                   COALESCE(od.business_name, od.opportunity_title) AS business_name,
                   sup.supplier_company_name AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od.client_id   = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id   = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od.opportunity_owner_employee_id = em.employee_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
            WHERE od.tenant_id  = :tenant_id
            AND   od.service_id = :service_id
            AND   od.opportunity_owner_employee_id = :employee_id
            AND   od.is_allocated = TRUE
            AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
            ORDER BY od.created_at DESC
        """), {'tenant_id': tenant_id, 'service_id': service_id, 'employee_id': employee_id}).mappings().all()

        return jsonify(_rows_to_list(rows)), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/archives', methods=['GET'])
@token_required
@tenant_from_jwt
def get_archived_leads():
    return jsonify([]), 200


@crm_bp.route('/leads/priced', methods=['GET'])
@token_required
@tenant_from_jwt
def get_priced_leads():
    session = SessionLocal()
    try:
        tenant_id     = str(g.tenant_id)
        current_user  = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        is_admin      = _is_admin_from_db(current_user)
        _raw_emp      = getattr(current_user, 'employee_id', None)
        employee_id   = int(_raw_emp) if _raw_emp is not None else None
        salesperson   = request.args.get('salesperson')

        sql = """
            SELECT od.*, sm.stage_name,
                   em.employee_name AS assigned_to_name,
                   COALESCE(od.business_name, od.opportunity_title) AS business_name,
                   sup.supplier_company_name AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od.client_id   = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id   = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od.opportunity_owner_employee_id = em.employee_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
            WHERE od.tenant_id  = :tenant_id
            AND   od.service_id = :service_id
            AND   LOWER(sm.stage_name) = 'priced'
            AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
        """
        params = {'tenant_id': tenant_id, 'service_id': service_id}

        if is_admin and salesperson and salesperson != 'All':
            try:
                sql += ' AND od.opportunity_owner_employee_id = :salesperson'
                params['salesperson'] = int(salesperson)
            except ValueError:
                pass
        elif not is_admin and employee_id:
            sql += ' AND od.opportunity_owner_employee_id = :employee_id'
            params['employee_id'] = employee_id

        sql += ' ORDER BY od.created_at DESC'
        rows = session.execute(text(sql), params).mappings().all()
        return jsonify(_rows_to_list(rows)), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


# ========================================
# LEADS CALLBACK & HISTORY
# ========================================

@crm_bp.route('/leads/<int:opportunity_id>/callback', methods=['POST', 'OPTIONS'])
@token_required
@tenant_from_jwt
def leads_callback(opportunity_id):
    """
    POST /api/crm/leads/<opportunity_id>/callback
    Save a callback/status update for a lead.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        data      = request.get_json(force=True, silent=True) or {}
        status    = data.get('status')
        notes     = data.get('notes', '')
        callback_date = data.get('callback_date')
        called_date = data.get('called_date')
        is_sold = data.get('is_sold')
        stage_id = data.get('stage_id')
 
        logger.info(f"📥 Callback for lead {opportunity_id} — status: {status}")
 
        if not status:
            return jsonify({'error': 'Status is required'}), 400
 
        STATUS_CFG = {
            "Callback":           {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "Not Answered":       {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "Priced":             {"deletes_record": False, "requires_notes": False, "requires_sold": True},
            "Lost":               {"deletes_record": True,  "requires_notes": True,  "requires_sold": False},
            "Lost COT":           {"deletes_record": True,  "requires_notes": True,  "requires_sold": False},
            "Already Renewed":    {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "Invalid Number":     {"deletes_record": True,  "requires_notes": False, "requires_sold": False},
            "Meter De-energised": {"deletes_record": True,  "requires_notes": False, "requires_sold": False},
            "Broker in Place":    {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "End Date Changed":   {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "Complaint":          {"deletes_record": True,  "requires_notes": True,  "requires_sold": False},
            "Email Only":         {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "Renewed Directly":   {"deletes_record": False, "requires_notes": True,  "requires_sold": False},
            "Incorrect Supplier": {"deletes_record": True,  "requires_notes": True,  "requires_sold": False},
            "Won":                {"deletes_record": False, "requires_notes": False, "requires_sold": False},
            "Converted":          {"deletes_record": False, "requires_notes": False, "requires_sold": False},
        }
 
        if status not in STATUS_CFG:
            return jsonify({'error': f'Invalid status: {status}'}), 400

        stage_lookup_status = 'Converted' if status == 'Won' else status
 
        cfg = STATUS_CFG[status]
 
        if cfg['requires_notes'] and not (notes or '').strip():
            return jsonify({'error': 'Notes are required for this status'}), 400
        if cfg['requires_sold'] and is_sold is None:
            return jsonify({'error': 'Please select if the contract was sold'}), 400
        if status == 'Already Renewed' and not data.get('renewed_by'):
            return jsonify({'error': 'Please select if renewed by customer or agent'}), 400
 
        lead = session.execute(text("""
            SELECT opportunity_id, client_id FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :t
            AND (opportunity_id = :id OR tenant_lead_id = :id)
            ORDER BY CASE WHEN opportunity_id = :id THEN 0 ELSE 1 END
            LIMIT 1
        """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

        if not lead:
            return jsonify({'error': 'Lead not found'}), 404

        real_id = lead['opportunity_id']
        client_id = lead['client_id']

        if not client_id:
            try:
                client_id = ensure_lead_client_id(session, real_id, tenant_id)
                session.flush()
                logger.info(f"✅ Created client_id={client_id} for lead {real_id}")
            except Exception as e:
                logger.error(f"❌ ensure_lead_client_id failed for lead {real_id}: {e}")
                session.rollback()
                return jsonify({'error': f'Failed to create client record: {str(e)}'}), 500

        session.execute(text("""
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET client_id = :client_id
            WHERE opportunity_id = :real_id
              AND tenant_id = :tenant_id
              AND (client_id IS NULL OR client_id <> :client_id)
        """), {'client_id': client_id, 'real_id': real_id, 'tenant_id': tenant_id})
 
        if callback_date:
            deleted_count = session.execute(text("""
                DELETE FROM "StreemLyne_MT"."Client_Interactions"
                WHERE reminder_date IS NOT NULL
                  AND client_id IN (
                    SELECT DISTINCT od2."client_id"
                    FROM "StreemLyne_MT"."Opportunity_Details" od2
                    WHERE od2."tenant_id" = :tenant_id
                      AND od2."client_id" IS NOT NULL
                      AND (
                        od2."opportunity_id" = :real_id
                        OR od2."opportunity_id" = :request_id
                        OR od2."tenant_lead_id" = :request_id
                      )
                    UNION
                    SELECT :client_id
                  )
            """), {
                'client_id': client_id,
                'real_id': real_id,
                'request_id': opportunity_id,
                'tenant_id': tenant_id
            }).rowcount
            
            session.commit()
            logger.warning(f"🗑️ Deleted {deleted_count} old callback entries for client_id={client_id} before creating new {status}")
 
        if cfg['deletes_record']:
            try:
                CLEANSING_STATUSES = {"Invalid Number", "Incorrect Supplier"}
                is_cleansing = status in CLEANSING_STATUSES

                if not client_id:
                    try:
                        client_id = ensure_lead_client_id(session, real_id, tenant_id)
                        session.flush()
                    except Exception as e:
                        logger.error(f"❌ Could not ensure client_id for lead {real_id}: {e}")
                        return jsonify({'error': f'Could not create client record: {str(e)}'}), 500

                client_master = session.query(Client_Master).filter_by(client_id=client_id).first()

                if not client_master:
                    logger.error(f"❌ Client_Master not found for client_id={client_id}, lead={real_id}")
                    return jsonify({'error': 'Customer record not found'}), 404

                client_master.is_deleted = True
                client_master.deleted_at = datetime.utcnow()
                client_master.deleted_reason = status
                
                if hasattr(client_master, 'is_cleansing'):
                    client_master.is_cleansing = is_cleansing
                else:
                    session.execute(text("""
                        UPDATE "StreemLyne_MT"."Client_Master"
                        SET is_cleansing = :is_cleansing
                        WHERE client_id = :client_id
                    """), {'is_cleansing': is_cleansing, 'client_id': client_id})

                if not stage_id:
                    s = session.execute(text(
                        'SELECT stage_id FROM "StreemLyne_MT"."Stage_Master" '
                        'WHERE LOWER(stage_name) = :n LIMIT 1'
                    ), {'n': stage_lookup_status.lower()}).mappings().first()
                    stage_id = s['stage_id'] if s else None

                if stage_id:
                    session.execute(text(
                        'UPDATE "StreemLyne_MT"."Opportunity_Details" SET stage_id = :s '
                        'WHERE opportunity_id = :id AND tenant_id = :t'
                    ), {'s': stage_id, 'id': real_id, 't': tenant_id})

                formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
                from backend.db import safe_add_with_sequence_retry
                safe_add_with_sequence_retry(
                    session,
                    Client_Interactions(
                        client_id=client_id,
                        contact_date=datetime.strptime(called_date, '%Y-%m-%d').date() if called_date else datetime.utcnow().date(),
                        contact_method=1,
                        reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                        notes=formatted_notes,
                        next_steps=status,
                        created_at=datetime.utcnow()
                    ))

                session.commit()

                if is_cleansing:
                    logger.info(f"✅ Lead {real_id} moved to Cleansing ({status})")
                    return jsonify({
                        'success': True,
                        'message': f'Moved to Cleansing ({status})',
                        'moved_to_cleansing': True,
                        'moved_to_recycle_bin': False,
                    }), 200
                else:
                    logger.info(f"✅ Lead {real_id} moved to Recycle Bin ({status})")
                    return jsonify({
                        'success': True,
                        'message': f'Moved to recycle bin ({status})',
                        'moved_to_cleansing': False,
                        'moved_to_recycle_bin': True,
                    }), 200

            except Exception as e:
                session.rollback()
                logger.error(f"❌ Error during soft-delete for lead {real_id}: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Failed to move record: {str(e)}'}), 500
 
        if status in ('Converted', 'Won') and data.get('assigned_to'):
            new_employee_id = data.get('assigned_to')
            current_employee_id = request.current_user.employee_id if hasattr(request.current_user, 'employee_id') else None
            
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET opportunity_owner_employee_id = :new_emp,
                    is_allocated = CASE 
                        WHEN :new_emp != :current_emp THEN TRUE 
                        ELSE FALSE 
                    END,
                    stage_id = :stage_id
                WHERE opportunity_id = :id AND tenant_id = :t
            """), {
                'new_emp': new_employee_id,
                'current_emp': current_employee_id,
                'id': real_id,
                't': tenant_id,
                'stage_id': stage_id or 16
            })
            
            from backend.db import safe_add_with_sequence_retry
            safe_add_with_sequence_retry(
                session,
                Client_Interactions(
                    client_id=client_id,
                    contact_date=datetime.strptime(called_date, '%Y-%m-%d').date() if called_date else datetime.utcnow().date(),
                    contact_method=1,
                    notes=f'[{status}] {notes}' if notes else f'[{status}] Lead marked as converted',
                    next_steps=status,
                    created_at=datetime.utcnow()
                ))
            
            session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Lead converted and assigned',
                'allocated': new_employee_id != current_employee_id
            }), 200
 
        if status == 'Priced' and is_sold is False:
            session.execute(text(
                'UPDATE "StreemLyne_MT"."Opportunity_Details" SET stage_id = :s '
                'WHERE opportunity_id = :id AND tenant_id = :t'
            ), {'s': stage_id or 4, 'id': real_id, 't': tenant_id})
            
            from backend.db import safe_add_with_sequence_retry
            safe_add_with_sequence_retry(
                session,
                Client_Interactions(
                    client_id=client_id,
                    contact_date=datetime.strptime(called_date, '%Y-%m-%d').date() if called_date else datetime.utcnow().date(),
                    contact_method=1,
                    notes=f'[Priced] {notes}' if notes else '[Priced] Moved to priced page',
                    next_steps='Priced',
                    created_at=datetime.utcnow()
                ))
            
            session.commit()
            return jsonify({'success': True, 'moved_to_priced': True}), 200
 
        new_end = data.get('new_end_date')
        if new_end and status in ('End Date Changed', 'Already Renewed'):
            session.execute(text(
                'UPDATE "StreemLyne_MT"."Opportunity_Details" SET end_date = :d '
                'WHERE opportunity_id = :id AND tenant_id = :t'
            ), {'d': new_end, 'id': real_id, 't': tenant_id})
            
            log_lead_field_change(session, real_id, 'Contract End', 
                                  session.execute(text(
                                      'SELECT end_date FROM "StreemLyne_MT"."Opportunity_Details" '
                                      'WHERE opportunity_id = :id'
                                  ), {'id': real_id}).scalar(), 
                                  new_end, tenant_id)
 
        new_supplier = (data.get('new_supplier') or '').strip()
        if new_supplier:
            from backend.models import Supplier_Master
            sup = session.query(Supplier_Master).filter(
                func.lower(Supplier_Master.supplier_company_name) == new_supplier.lower()
            ).first()
            if sup:
                session.execute(text(
                    'UPDATE "StreemLyne_MT"."Opportunity_Details" SET supplier_id = :s '
                    'WHERE opportunity_id = :id AND tenant_id = :t'
                ), {'s': sup.supplier_id, 'id': real_id, 't': tenant_id})
 
        if stage_id:
            session.execute(text(
                'UPDATE "StreemLyne_MT"."Opportunity_Details" SET stage_id = :s '
                'WHERE opportunity_id = :id AND tenant_id = :t'
            ), {'s': stage_id, 'id': real_id, 't': tenant_id})
 
        formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
        from backend.db import safe_add_with_sequence_retry
        safe_add_with_sequence_retry(
            session,
            Client_Interactions(
                client_id=client_id,
                contact_date=datetime.strptime(called_date, '%Y-%m-%d').date() if called_date else datetime.utcnow().date(),
                contact_method=1,
                reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                notes=formatted_notes,
                next_steps=status,
                created_at=datetime.utcnow()
            ))
 
        session.commit()
        
        logger.info(f"✅ Callback saved for lead {real_id}, status: {status}")
        
        updated_lead = session.execute(text("""
            SELECT od.*, sm.stage_name,
                em.employee_name AS assigned_to_name,
                COALESCE(od.business_name, od.opportunity_title) AS business_name,
                sup.supplier_company_name AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od.opportunity_owner_employee_id = em.employee_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
            WHERE od.opportunity_id = :id AND od.tenant_id = :t
            LIMIT 1
        """), {'id': real_id, 't': tenant_id}).mappings().first()

        lead_data = {k: _serial(v) for k, v in dict(updated_lead).items()} if updated_lead else {}
        lead_data['stage_name'] = status
        lead_data['stage_id'] = stage_id
        lead_data['reminder_date'] = callback_date

        return jsonify({
            'success': True, 
            'message': 'Callback saved successfully', 
            'status': status,
            'lead': lead_data
        }), 200
 
    except Exception as e:
        session.rollback()
        import traceback; traceback.print_exc()
        logger.error(f"❌ Error saving callback for lead {opportunity_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try: session.close()
        except Exception: pass


@crm_bp.route('/leads/<int:opportunity_id>/history', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_lead_history(opportunity_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)

        lead = session.execute(text("""
            SELECT opportunity_id, client_id FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :t
            AND (opportunity_id = :id OR tenant_lead_id = :id)
            ORDER BY CASE WHEN opportunity_id = :id THEN 0 ELSE 1 END
            LIMIT 1
        """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

        if not lead:
            return jsonify({'error': 'Lead not found'}), 404

        real_id = lead['opportunity_id']
        client_id = lead['client_id']

        if not client_id:
            return jsonify({'interactions': []}), 200

        interactions = session.execute(text("""
            SELECT 
                interaction_id,
                CASE 
                    WHEN next_steps = 'Field Updated' THEN 'Field Updated'
                    WHEN next_steps = 'Assignment' THEN 'Assignment'
                    ELSE COALESCE(next_steps, 'Note')
                END as interaction_type,
                contact_date,
                reminder_date,
                notes,
                created_at
            FROM "StreemLyne_MT"."Client_Interactions"
            WHERE client_id = :client_id
            ORDER BY created_at DESC
        """), {'client_id': client_id}).mappings().all()

        return jsonify({
            'interactions': [{
                'interaction_id': i['interaction_id'],
                'interaction_type': i['interaction_type'] or 'Note',
                'contact_date': i['contact_date'].isoformat() if i['contact_date'] else None,
                'reminder_date': i['reminder_date'].isoformat() if i['reminder_date'] else None,
                'notes': i['notes'],
                'created_at': i['created_at'].isoformat() if i['created_at'] else None
            } for i in interactions]
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@crm_bp.route('/leads/<int:opportunity_id>/history/<int:interaction_id>', methods=['DELETE', 'OPTIONS'])
@token_required
@tenant_from_jwt
def delete_lead_interaction(opportunity_id, interaction_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)

        lead = session.execute(text("""
            SELECT opportunity_id, client_id FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :t
            AND (opportunity_id = :id OR tenant_lead_id = :id)
            ORDER BY CASE WHEN opportunity_id = :id THEN 0 ELSE 1 END
            LIMIT 1
        """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

        if not lead or not lead['client_id']:
            return jsonify({'error': 'Lead not found'}), 404
        
        session.execute(text("""
            DELETE FROM "StreemLyne_MT"."Client_Interactions"
            WHERE interaction_id = :int_id
            AND client_id = :client_id
        """), {'int_id': interaction_id, 'client_id': lead['client_id']})

        session.commit()
        return jsonify({'success': True, 'message': 'Interaction deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


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
# DEAL ROUTES
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
# SUPPORTING DATA
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
# DASHBOARD
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


# ========================================
# CLEANSING ROUTES
# ========================================

from backend.routes.cleansing_routes import (
    register_get_cleansing,
    register_lead_cleanse,
)

register_get_cleansing(crm_bp, token_required, tenant_from_jwt)
register_lead_cleanse(crm_bp, token_required, tenant_from_jwt)


# ========================================
# HEALTH CHECK
# ========================================

@crm_bp.route('/health', methods=['GET'])
def health_check():
    return {'success': True, 'module': 'CRM', 'status': 'operational'}, 200


@crm_bp.route('/debug/tenant/<int:tenant_id>', methods=['GET'])
def debug_tenant_lookup(tenant_id):
    try:
        from backend.crm.repositories.tenant_repository import TenantRepository
        repo = TenantRepository()
        tenant = repo.get_tenant_by_id(tenant_id)
        return {'success': bool(tenant), 'tenant_id_requested': tenant_id,
                'tenant_found': tenant is not None, 'tenant_data': tenant}, 200 if tenant else 404
    except Exception as e:
        import traceback
        return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}, 500