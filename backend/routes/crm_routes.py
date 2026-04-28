# -*- coding: utf-8 -*-
"""
CRM Routes Blueprint — uses SessionLocal (same connection as renewals).
All raw SQL queries use SQLAlchemy text() via SessionLocal so leads and
renewals always hit the same database connection.
"""
from datetime import datetime

from backend.models import Client_Interactions, Client_Master
from flask import Blueprint, request, g, jsonify
from functools import wraps
from sqlalchemy import text, func
from backend.db import SessionLocal
from backend.crm.controllers.crm_controller import CRMController
from backend.crm.middleware.tenant_middleware import require_tenant
from .auth_helpers import token_required
import logging

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
        role = result[0] if result else None
        return role in ['Platform Admin', 'Tenant Super Admin']
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


# ── Blueprint ─────────────────────────────────────────────────────────────────

crm_bp = Blueprint('crm', __name__, url_prefix='/api/crm')
crm_controller = CRMController()


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
    """
    import logging
    logger = logging.getLogger(__name__)
    
    session = SessionLocal()
    try:
        tenant_id    = str(g.tenant_id)  # ✅ CHANGED: Cast to string immediately
        current_user = request.current_user
        service_param = request.args.get('service', 'utilities')
        service_id    = 2 if service_param.strip().lower() == 'water' else 1
        exclude_stage = request.args.get('exclude_stage', '')
        employee_id   = getattr(current_user, 'employee_id', None)

        logger.warning(
            '🔍 get_leads: employee_id=%s tenant=%s service=%s',
            employee_id, tenant_id, service_param
        )

        if not employee_id:
            logger.warning('⚠️ No employee_id - returning empty')
            return jsonify({'data': [], 'team_stats': []}), 200

        # ✅ Determine if admin
        is_admin = _is_admin_from_db(current_user)
        
        # ================================================================
        # 1. RECALCULATE DISPLAY_ORDER (per employee, starting from 1)
        # ================================================================
        try:
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
                  AND od.tenant_id = :tenant_id
            """), {'tenant_id': tenant_id})
            session.commit()
            logger.warning('✅ Recalculated display_order for all employees')
        except Exception as e:
            session.rollback()
            logger.error(f'❌ Error recalculating display_order: {e}')

        # ================================================================
        # 2. TEAM STATS QUERY - ✅ FIXED: tenant_id as string
        # ================================================================
        team_stats_rows = []
        
        if is_admin:
            # Admin: Show ALL employees in tenant with their lead counts (including 0)
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
                WHERE em."tenant_id" = :tenant_id
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

        # ================================================================
        # 3. MAIN LEADS QUERY - ✅ Fixed tenant_id as string
        # ================================================================
        query = """
            SELECT
                od.*,
                od.display_order,
                sm."stage_name",
                em."employee_name" AS assigned_to_name,
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                sup."supplier_company_name" AS supplier_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od."client_id"   = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od."stage_id"    = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id"  = sup."supplier_id"
            WHERE od."tenant_id" = :tenant_id
            AND od."service_id" = :service_id
            AND od."opportunity_owner_employee_id" = :employee_id
            AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)
            AND (cm."is_deleted" IS NULL OR cm."is_deleted" = FALSE)
        """
        params = {'tenant_id': tenant_id, 'service_id': service_id, 'employee_id': employee_id}

        if exclude_stage:
            query += ' AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") != LOWER(:exclude_stage))'
            params['exclude_stage'] = exclude_stage

        query += ' ORDER BY od."display_order" ASC'

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
        session.close()

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
            text(sql + ' AND od.tenant_lead_id = :id LIMIT 1'),
            {'tenant_id': tenant_id, 'id': opportunity_id}
        ).mappings().first()

        if not row:
            row = session.execute(
                text(sql + ' AND od.opportunity_id = :id LIMIT 1'),
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
                AND (tenant_lead_id = :id OR opportunity_id = :id)
                LIMIT 1
            """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

            if not current:
                return jsonify({'error': 'Lead not found'}), 404

            real_id = current['opportunity_id']
            
            # ✅ Track changes for supplier_id with name resolution
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
            
            # ✅ Track assignment changes with employee names
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
            
            # ✅ Track all other field changes
            for field, new_value in fields.items():
                if field in ['supplier_id', 'opportunity_owner_employee_id']:
                    continue  # Already handled above
                
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

        sql = """
            SELECT sm.stage_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            WHERE od.tenant_id  = :tenant_id
            AND   od.service_id = :service_id
        """
        params = {'tenant_id': tenant_id, 'service_id': service_id}

        # ✅ FIX: Non-admin should only see own performance
        if employee_id:
            sql += ' AND od.opportunity_owner_employee_id = :employee_id'
            params['employee_id'] = employee_id

        rows = session.execute(text(sql), params).mappings().all()

        counts = dict(converted=0, renewed=0, renewed_directly=0, end_date_changed=0,
                      priced=0, in_progress=0, lost=0, not_contacted=0)

        for r in rows:
            stage = (r.get('stage_name') or '').lower()
            if stage == 'converted':                                              counts['converted'] += 1
            elif stage in ['already renewed', 'renewed']:                         counts['renewed'] += 1
            elif stage == 'renewed directly':                                     counts['renewed_directly'] += 1
            elif stage == 'end date changed':                                     counts['end_date_changed'] += 1
            elif stage == 'priced':                                               counts['priced'] += 1
            elif stage in ['callback','not answered','broker in place',
                           'email only','complaint','incorrect supplier']:         counts['in_progress'] += 1
            elif stage in ['lost','lost cot','invalid number','meter de-energised']: counts['lost'] += 1
            else:                                                                 counts['not_contacted'] += 1

        total = len(rows)
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


@crm_bp.route('/leads/stats-by-employee', methods=['GET'])
@token_required
@tenant_from_jwt
def get_leads_stats_by_employee():
    from backend.crm.supabase_client import get_supabase_client
    import logging
    logger = logging.getLogger(__name__)

    try:
        tenant_id    = str(g.tenant_id)  # ✅ CHANGED: Cast to string
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

        db = get_supabase_client()

        # ✅ Everyone sees only their own count (mirrors renewals stats-by-employee)
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
    so each salesperson's list always starts at 1.
    
    Args:
        session: SQLAlchemy session
        tenant_id: Tenant ID (will be cast to string)
        employee_id: Optional - recalculate only for this employee
    """
    tenant_id = str(tenant_id)  
    
    if employee_id:
        # Recalculate only for this specific employee
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
        # Recalculate for ALL employees at once using PARTITION BY
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
    logging.getLogger(__name__).info(
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
                # Update all recently created leads by this employee
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
                
                # Recalculate display_order
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
        
        # Style the header row
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


@crm_bp.route('/leads/<int:opportunity_id>/callback', methods=['POST', 'OPTIONS'])
@token_required
@tenant_from_jwt
def leads_callback(opportunity_id):
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
 
        # ✅ CHANGED: Incorrect Supplier now deletes to Cleansing
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
            "Converted":          {"deletes_record": False, "requires_notes": False, "requires_sold": False},
        }
 
        if status not in STATUS_CFG:
            return jsonify({'error': f'Invalid status: {status}'}), 400
 
        cfg = STATUS_CFG[status]
 
        if cfg['requires_notes'] and not (notes or '').strip():
            return jsonify({'error': 'Notes are required for this status'}), 400
        if cfg['requires_sold'] and is_sold is None:
            return jsonify({'error': 'Please select if the contract was sold'}), 400
        if status == 'Already Renewed' and not data.get('renewed_by'):
            return jsonify({'error': 'Please select if renewed by customer or agent'}), 400
 
        # Find the lead
        lead = session.execute(text("""
            SELECT opportunity_id, client_id FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :t
            AND (tenant_lead_id = :id OR opportunity_id = :id)
            LIMIT 1
        """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

        if not lead:
            return jsonify({'error': 'Lead not found'}), 404

        real_id = lead['opportunity_id']
        client_id = lead['client_id']

        # ✅ Always ensure client_id exists (needed for interactions + soft-delete)
        if not client_id:
            try:
                client_id = ensure_lead_client_id(session, real_id, tenant_id)
                session.flush()
                logger.info(f"✅ Created client_id={client_id} for lead {real_id}")
            except Exception as e:
                logger.error(f"❌ ensure_lead_client_id failed for lead {real_id}: {e}")
                session.rollback()
                return jsonify({'error': f'Failed to create client record: {str(e)}'}), 500
 
        # ✅✅✅ CRITICAL FIX: DELETE ALL OLD CALLBACKS FOR THIS LEAD (removes stale calendar entries)
        CALLBACK_STATUSES = ['Callback', 'Not Answered', 'Broker in Place', 'Email Only', 'End Date Changed', 'Already Renewed', 'Voicemail']
        
        if status in CALLBACK_STATUSES:
            # Delete ALL previous callback-type interactions for this client (not just future ones)
            deleted_count = session.execute(text("""
                DELETE FROM "StreemLyne_MT"."Client_Interactions"
                WHERE client_id = :client_id
                AND next_steps IN ('Callback', 'Not Answered', 'Broker in Place', 'Email Only', 'End Date Changed', 'Already Renewed', 'Voicemail')
                AND reminder_date IS NOT NULL
            """), {'client_id': client_id}).rowcount
            
            session.commit()  # ✅ CRITICAL: Commit deletion immediately
            logger.warning(f"🗑️ Deleted {deleted_count} old callback entries for client_id={client_id} before creating new {status}")
 
        # ──────────────────────────────────────────────────────────────────
        # ✅ SOFT-DELETE: Cleansing OR Recycle Bin (mirrors renewals pattern)
        # ──────────────────────────────────────────────────────────────────
        if cfg['deletes_record']:
            try:
                CLEANSING_STATUSES = {"Invalid Number", "Incorrect Supplier"}
                is_cleansing = status in CLEANSING_STATUSES

                # ✅ Ensure client_id exists before soft-deleting
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
                    return jsonify({'error': 'Customer record not found — could not move to bin/cleansing'}), 404

                # Soft delete
                client_master.is_deleted = True
                client_master.deleted_at = datetime.utcnow()
                client_master.deleted_reason = status
                
                # ✅ CRITICAL: Set is_cleansing flag (mirrors renewals)
                if hasattr(client_master, 'is_cleansing'):
                    client_master.is_cleansing = is_cleansing
                else:
                    # Fallback: use raw SQL if attribute doesn't exist
                    session.execute(text("""
                        UPDATE "StreemLyne_MT"."Client_Master"
                        SET is_cleansing = :is_cleansing
                        WHERE client_id = :client_id
                    """), {'is_cleansing': is_cleansing, 'client_id': client_id})

                # Resolve stage_id for the status
                if not stage_id:
                    s = session.execute(text(
                        'SELECT stage_id FROM "StreemLyne_MT"."Stage_Master" '
                        'WHERE LOWER(stage_name) = :n LIMIT 1'
                    ), {'n': status.lower()}).mappings().first()
                    stage_id = s['stage_id'] if s else None

                # ✅ Update stage on Opportunity_Details (not Project_Details for leads)
                if stage_id:
                    session.execute(text(
                        'UPDATE "StreemLyne_MT"."Opportunity_Details" SET stage_id = :s '
                        'WHERE opportunity_id = :id AND tenant_id = :t'
                    ), {'s': stage_id, 'id': real_id, 't': tenant_id})

                # Log interaction
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
 
        # ──────────────────────────────────────────────────────────────────
        # Handle "Converted" with assignment
        # ──────────────────────────────────────────────────────────────────
        if status == 'Converted' and data.get('assigned_to'):
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
                    notes=f'[Converted] {notes}' if notes else '[Converted] Lead marked as converted',
                    next_steps='Converted',
                    created_at=datetime.utcnow()
                ))
            
            session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Lead converted and assigned',
                'allocated': new_employee_id != current_employee_id
            }), 200
 
        # ──────────────────────────────────────────────────────────────────
        # Handle "Priced" with no sale
        # ──────────────────────────────────────────────────────────────────
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
 
        # ──────────────────────────────────────────────────────────────────
        # Handle "End Date Changed" and "Already Renewed" - UPDATE end_date
        # ──────────────────────────────────────────────────────────────────
        new_end = data.get('new_end_date')
        if new_end and status in ('End Date Changed', 'Already Renewed'):
            session.execute(text(
                'UPDATE "StreemLyne_MT"."Opportunity_Details" SET end_date = :d '
                'WHERE opportunity_id = :id AND tenant_id = :t'
            ), {'d': new_end, 'id': real_id, 't': tenant_id})
            
            # Log the end date change
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
 
        # Update stage_id
        if stage_id:
            session.execute(text(
                'UPDATE "StreemLyne_MT"."Opportunity_Details" SET stage_id = :s '
                'WHERE opportunity_id = :id AND tenant_id = :t'
            ), {'s': stage_id, 'id': real_id, 't': tenant_id})
 
        # ──────────────────────────────────────────────────────────────────
        # CREATE NEW HISTORY INTERACTION (All other statuses)
        # ──────────────────────────────────────────────────────────────────
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
        
        # Return the updated lead data
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

        # ✅ Force the correct stage_name from the status parameter
        lead_data = {k: _serial(v) for k, v in dict(updated_lead).items()} if updated_lead else {}
        lead_data['stage_name'] = status  # ✅ Override with the correct status
        lead_data['stage_id'] = stage_id  # ✅ Override with the correct stage_id

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


from backend.routes.cleansing_routes import (
    register_get_cleansing,
    register_lead_cleanse,
)

# Register cleansing routes
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
    
@crm_bp.route('/leads/<int:opportunity_id>/history', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_lead_history(opportunity_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)

        # ✅ Get client_id from opportunity_id
        lead = session.execute(text("""
            SELECT opportunity_id, client_id FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE tenant_id = :t
            AND (tenant_lead_id = :id OR opportunity_id = :id)
            LIMIT 1
        """), {'t': tenant_id, 'id': opportunity_id}).mappings().first()

        if not lead:
            return jsonify({'error': 'Lead not found'}), 404

        real_id = lead['opportunity_id']
        client_id = lead['client_id']

        if not client_id:
            # No client_id = no interactions yet
            return jsonify({'interactions': []}), 200

        # ✅ Fetch from Client_Interactions (same table as renewals)
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
            AND (tenant_lead_id = :id OR opportunity_id = :id)
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