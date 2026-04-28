# backend/routes/energy_renewals_routes.py

from flask import Blueprint, jsonify, request, current_app
from datetime import datetime, timedelta, date
from sqlalchemy import text, func, case, and_, cast, Float, String, exists
from ..numeric_parse import safe_float
from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Supplier_Master, Employee_Master, Client_Interactions
)
from ..db import SessionLocal
from .auth_helpers import token_required, get_tenant_id_from_user
from ..dummy_local_dashboard_data import (
    dummy_aq_breakdown,
    dummy_energy_renewals_list,
    dummy_period_breakdown,
    dummy_renewal_performance,
    dummy_renewal_stats,
    dummy_salesperson_performance,
    dummy_staff_status_counts,
    dummy_supplier_breakdown,
    local_demo_dashboard_enabled,
)

renewals_bp = Blueprint("renewals", __name__)


def _as_calendar_date(val):
    """Database may return date or datetime — subtracting datetime from date raises TypeError."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return val


def _misc_col2_sql_float():
    """Annual usage may be varchar in DB; use for SQL aggregates and arithmetic."""
    trimmed = func.replace(func.trim(cast(Project_Details.Misc_Col2, String)), ",", "")
    return cast(func.nullif(trimmed, ""), Float)


def _period_bounds(period: str):
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
        # Project_Details timestamps rarely fall in a single calendar day; a 1-day window
        # makes team performance / staff charts look empty. Use a rolling 14-day window.
        end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
        multiplier = 1
    return key, start, end, multiplier


def _resolve_project_timestamp_expr(session):
    """Pick the best timestamp column available in Project_Details for period filters."""
    rows = session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
              AND table_name = 'Project_Details'
            """
        )
    ).fetchall()
    columns = {r[0] for r in rows}
    if "updated_at" in columns:
        return 'pd."updated_at"'
    if "modified_at" in columns:
        return 'pd."modified_at"'
    if "created_at" in columns:
        return 'pd."created_at"'
    return "NOW()"

@renewals_bp.route("/energy-renewals", methods=["GET"])
@token_required
def get_renewals():
    if local_demo_dashboard_enabled():
        return jsonify(dummy_energy_renewals_list()), 200
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        db = SessionLocal()
        today = datetime.now().date()
        ninety_days_later = today + timedelta(days=90)

        use_current_user = request.args.get('use_current_user', 'false').lower() == 'true'

        if use_current_user:
            current_user = request.current_user
            if hasattr(current_user, 'id'):
                employee_id = current_user.id
            elif hasattr(current_user, 'employee_id'):
                employee_id = current_user.employee_id
            else:
                employee_id = None
        else:
            employee_id = request.args.get('employee_id')

        employee_filter = "AND pd.assigned_employee_id = :employee_id" if employee_id else ""

        if use_current_user:
            date_filter = "AND ecm.contract_end_date IS NOT NULL"
        else:
            date_filter = "AND ecm.contract_end_date BETWEEN :today AND :ninety_days_later"

        query = text(f"""
            SELECT
                cm.client_id,
                cm.client_contact_name as contact_person,
                cm.client_company_name as business_name,
                cm.client_phone as phone,
                cm.client_mobile as mobile_no,
                cm.client_email as email,
                sm.supplier_company_name as supplier_name,
                ecm.contract_end_date as end_date,
                ecm.contract_start_date as start_date,
                pd."Misc_Col2" as annual_usage,
                (ecm.contract_end_date - CURRENT_DATE) as days_until_expiry,
                pd.status as status,
                em.employee_name as assigned_to_name,
                pd.assigned_employee_id as assigned_to_id,
                ecm.unit_rate,
                ecm.mpan_number
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON pd.assigned_employee_id = em.employee_id
            WHERE cm.tenant_id = :tenant_id
            AND cm.is_deleted = false
            {date_filter}
            {employee_filter}
            ORDER BY ecm.contract_end_date ASC
        """)

        params = {"tenant_id": tenant_id}
        if not use_current_user:
            params["today"] = today
            params["ninety_days_later"] = ninety_days_later
        if employee_id:
            params['employee_id'] = int(employee_id)

        result = db.execute(query, params)

        renewals = []
        for row in result:
            renewals.append({
                "client_id": row.client_id,
                "contact_person": row.contact_person or "Unknown",
                "business_name": row.business_name or "",
                "phone": row.phone or "",
                "mobile_no": row.mobile_no or "",
                "email": row.email or "",
                "supplier_name": row.supplier_name or "Unknown",
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "annual_usage": float(row.annual_usage) if row.annual_usage else 0,
                "days_until_expiry": row.days_until_expiry,
                "status": row.status or "Pending",
                "assigned_to_name": row.assigned_to_name or "Unassigned",
                "assigned_to_id": row.assigned_to_id,
                "mpan_number": row.mpan_number or ""
            })

        db.close()
        print(f"✅ Found {len(renewals)} renewals (use_current_user={use_current_user}, employee_id={employee_id})")
        return jsonify(renewals), 200

    except Exception as e:
        print(f"❌ Error fetching renewals: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@renewals_bp.route('/energy-renewals/stats', methods=['GET'])
@token_required
def get_renewal_stats():
    if local_demo_dashboard_enabled():
        return jsonify(dummy_renewal_stats()), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)
        today = datetime.utcnow().date()

        # Select only columns used below. Loading full Energy_Contract_Master rows can fail when
        # DB types diverge from the ORM (e.g. varchar stored in Numeric-typed columns → psycopg "Unknown PG numeric type: 1043").
        base_query = session.query(
            Project_Details.Misc_Col2,
            Project_Details.status,
            Energy_Contract_Master.contract_end_date,
            cast(Energy_Contract_Master.unit_rate, String),
        ).join(
            Client_Master, Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).filter(
            cast(Client_Master.tenant_id, String) == str(tenant_id),
            Energy_Contract_Master.contract_end_date.isnot(None)
        )

        if employee_id:
            base_query = base_query.filter(
                Project_Details.assigned_employee_id == employee_id
            )

        all_results = base_query.all()

        total_renewals_30_60_days = 0
        total_renewals_61_90_days = 0
        total_renewals_90_plus_days = 0
        expired_contracts = 0
        not_due_contracts = 0
        total_revenue_at_risk = 0
        total_aq = 0
        contacted_count = 0
        not_contacted_count = 0
        renewed_count = 0
        lost_count = 0

        for misc_col2, status_raw, end_raw, unit_rate_raw in all_results:
            end_date = _as_calendar_date(end_raw)
            aq = safe_float(misc_col2)
            if aq:
                total_aq += aq

            if not end_date:
                continue

            days_until_renewal = (end_date - today).days

            if days_until_renewal < 0:
                expired_contracts += 1
            # Buckets align with dashboard cards: "Due in 30/60/90 days" (0–30, 31–60, 61–90).
            elif 0 <= days_until_renewal <= 30:
                total_renewals_30_60_days += 1
            elif 31 <= days_until_renewal <= 60:
                total_renewals_61_90_days += 1
            elif 61 <= days_until_renewal <= 90:
                total_renewals_90_plus_days += 1
            elif days_until_renewal >= 365:
                not_due_contracts += 1

            ur = safe_float(unit_rate_raw)
            if ur and aq:
                annual_cost = (ur * aq) / 100
                total_revenue_at_risk += annual_cost

            status = status_raw
            if status:
                status_lower = str(status).strip().lower()
                if status_lower in ['called', 'callback', 'contacted']:
                    contacted_count += 1
                elif status_lower in ('not_answered', 'not answered', 'not contacted'):
                    not_contacted_count += 1
                elif status_lower in ['priced', 'renewed', 'already renewed', 'end date changed']:
                    renewed_count += 1
                elif status_lower == 'lost':
                    lost_count += 1
                else:
                    not_contacted_count += 1
            else:
                not_contacted_count += 1

        return jsonify({
            'total_renewals_30_60_days': total_renewals_30_60_days,
            'total_renewals_61_90_days': total_renewals_61_90_days,
            'total_renewals_90_plus_days': total_renewals_90_plus_days,
            'expired_contracts': expired_contracts,
            'not_due_contracts': not_due_contracts,
            'total_revenue_at_risk': total_revenue_at_risk,
            'total_aq': total_aq,
            'contacted_count': contacted_count,
            'not_contacted_count': not_contacted_count,
            'renewed_count': renewed_count,
            'lost_count': lost_count
        })

    except Exception as e:
        current_app.logger.error(f"Error getting renewal stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/supplier-breakdown', methods=['GET'])
@token_required
def get_supplier_breakdown():
    if local_demo_dashboard_enabled():
        return jsonify(dummy_supplier_breakdown()), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)

        query = session.query(
            Supplier_Master.supplier_company_name,
            func.count(Energy_Contract_Master.energy_contract_master_id).label('renewal_count'),
            func.sum(
                case(
                    (
                        and_(
                            Energy_Contract_Master.unit_rate.isnot(None),
                            Project_Details.Misc_Col2.isnot(None)
                        ),
                        (Energy_Contract_Master.unit_rate * _misc_col2_sql_float()) / 100
                    ),
                    else_=0
                )
            ).label('total_value')
        ).join(
            Energy_Contract_Master,
            Supplier_Master.supplier_id == Energy_Contract_Master.supplier_id
        ).join(
            Project_Details,
            Energy_Contract_Master.project_id == Project_Details.project_id
        ).join(
            Client_Master,
            Project_Details.client_id == Client_Master.client_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None)
        )

        if employee_id:
            query = query.filter(Project_Details.assigned_employee_id == employee_id)

        results = query.group_by(
            Supplier_Master.supplier_company_name
        ).order_by(
            func.sum(
                case(
                    (
                        and_(
                            Energy_Contract_Master.unit_rate.isnot(None),
                            Project_Details.Misc_Col2.isnot(None)
                        ),
                        (Energy_Contract_Master.unit_rate * _misc_col2_sql_float()) / 100
                    ),
                    else_=0
                )
            ).desc()
        ).all()

        supplier_breakdown = [
            {
                'supplier_name': r[0],
                'renewal_count': r[1],
                'total_value': float(r[2] or 0)
            }
            for r in results
        ]

        return jsonify(supplier_breakdown)

    except Exception as e:
        current_app.logger.error(f"Error getting supplier breakdown: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/period-breakdown', methods=['GET'])
@token_required
def get_period_breakdown():
    if local_demo_dashboard_enabled():
        period = request.args.get('period')
        return jsonify(dummy_period_breakdown(period)), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        period = request.args.get('period')
        employee_id = request.args.get('employee_id', type=int)
        today = datetime.utcnow().date()

        if period == 'expired':
            start_date = today - timedelta(days=365 * 5)
            end_date = today - timedelta(days=1)
        elif period == '30-60':
            start_date = today + timedelta(days=30)
            end_date = today + timedelta(days=60)
        elif period == '61-90':
            start_date = today + timedelta(days=61)
            end_date = today + timedelta(days=90)
        elif period == '91-180':
            start_date = today + timedelta(days=91)
            end_date = today + timedelta(days=180)
        elif period == 'not-due':
            start_date = today + timedelta(days=365)
            end_date = today + timedelta(days=365 * 20)
        else:
            return jsonify({'error': 'Invalid period parameter'}), 400

        query = session.query(
            Client_Master.client_id,
            Client_Master.client_company_name,
            Client_Master.client_contact_name,
            Client_Master.client_phone,
            Client_Master.client_email,
            Supplier_Master.supplier_company_name,
            Energy_Contract_Master.contract_end_date,
            Energy_Contract_Master.mpan_number,
            Project_Details.Misc_Col2.label('annual_usage'),
            Energy_Contract_Master.unit_rate,
            Employee_Master.employee_name,
            Project_Details.status.label('status')
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.between(start_date, end_date)
        )

        if employee_id:
            query = query.filter(Project_Details.assigned_employee_id == employee_id)

        results = query.order_by(Energy_Contract_Master.contract_end_date).all()

        breakdown = []
        for r in results:
            revenue = 0
            ur = safe_float(r.unit_rate)
            usage = safe_float(r.annual_usage)
            if ur and usage:
                revenue = (ur * usage) / 100

            days_until_expiry = (r.contract_end_date - today).days if r.contract_end_date else 0

            breakdown.append({
                'client_id': r.client_id,
                'business_name': r.client_company_name,
                'contact_person': r.client_contact_name,
                'phone': r.client_phone,
                'email': r.client_email,
                'supplier_name': r.supplier_company_name,
                'contract_end_date': r.contract_end_date.isoformat() if r.contract_end_date else None,
                'days_until_expiry': days_until_expiry,
                'mpan_number': r.mpan_number,
                'annual_usage': usage,
                'estimated_revenue': round(revenue, 2),
                'assigned_to': r.employee_name or 'Unassigned',
                'status': r.status or 'Pending'
            })

        return jsonify({
            'period': period,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_count': len(breakdown),
            'total_revenue': sum(item['estimated_revenue'] for item in breakdown),
            'renewals': breakdown
        })

    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/salesperson-performance', methods=['GET'])
@token_required
def get_salesperson_performance():
    if local_demo_dashboard_enabled():
        period = request.args.get('period', 'month')
        return jsonify(dummy_salesperson_performance(period)), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)
        period = request.args.get('period', 'month')
        today = datetime.utcnow().date()

        if period == 'week':
            start_date = today - timedelta(days=7)
            period_label = "This Week"
        else:
            start_date = today - timedelta(days=30)
            period_label = "This Month"

        query = session.query(
            Employee_Master.employee_id,
            Employee_Master.employee_name,
            Client_Master.client_id,
            Client_Master.client_company_name,
            Client_Master.client_contact_name,
            Client_Master.client_phone,
            Client_Interactions.contact_date,
            Client_Interactions.notes,
            Project_Details.status.label('status'),
            Energy_Contract_Master.contract_end_date,
            Project_Details.Misc_Col2.label('annual_usage'),
            Energy_Contract_Master.unit_rate,
            Supplier_Master.supplier_company_name
        ).join(
            Project_Details,
            Employee_Master.employee_id == Project_Details.assigned_employee_id
        ).join(
            Client_Master,
            Project_Details.client_id == Client_Master.client_id
        ).join(
            Client_Interactions,
            and_(
                Client_Master.client_id == Client_Interactions.client_id,
                Client_Interactions.contact_date >= start_date
            )
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).filter(
            Employee_Master.tenant_id == tenant_id
        )

        if employee_id:
            query = query.filter(Employee_Master.employee_id == employee_id)

        results = query.order_by(
            Employee_Master.employee_name,
            Client_Interactions.contact_date.desc()
        ).all()

        performance_by_employee = {}

        for r in results:
            emp_id = r.employee_id
            emp_name = r.employee_name

            if emp_id not in performance_by_employee:
                performance_by_employee[emp_id] = {
                    'employee_id': emp_id,
                    'employee_name': emp_name,
                    'total_contacts': 0,
                    'converted_count': 0,
                    'total_value_touched': 0,
                    'customers_contacted': []
                }

            ur = safe_float(r.unit_rate)
            usage = safe_float(r.annual_usage)
            revenue = 0
            if ur and usage:
                revenue = (ur * usage) / 100

            customer_exists = any(
                c['client_id'] == r.client_id
                for c in performance_by_employee[emp_id]['customers_contacted']
            )

            if not customer_exists:
                performance_by_employee[emp_id]['total_contacts'] += 1
                performance_by_employee[emp_id]['total_value_touched'] += revenue

                if r.status and r.status.lower() in ['priced', 'renewed']:
                    performance_by_employee[emp_id]['converted_count'] += 1

                performance_by_employee[emp_id]['customers_contacted'].append({
                    'client_id': r.client_id,
                    'business_name': r.client_company_name,
                    'contact_person': r.client_contact_name,
                    'phone': r.client_phone,
                    'contact_date': r.contact_date.isoformat() if r.contact_date else None,
                    'notes': r.notes,
                    'status': r.status,
                    'supplier': r.supplier_company_name,
                    'contract_end_date': r.contract_end_date.isoformat() if r.contract_end_date else None,
                    'annual_usage': usage,
                    'estimated_revenue': round(revenue, 2)
                })

        performance_data = []
        for emp_data in performance_by_employee.values():
            conversion_rate = round(
                (emp_data['converted_count'] / emp_data['total_contacts'] * 100)
                if emp_data['total_contacts'] > 0 else 0, 1
            )
            performance_data.append({
                'employee_id': emp_data['employee_id'],
                'employee_name': emp_data['employee_name'],
                'total_contacts': emp_data['total_contacts'],
                'converted_count': emp_data['converted_count'],
                'total_value_touched': round(emp_data['total_value_touched'], 2),
                'conversion_rate': conversion_rate,
                'customers_contacted': sorted(
                    emp_data['customers_contacted'],
                    key=lambda x: x['contact_date'] or '',
                    reverse=True
                )
            })

        performance_data.sort(key=lambda x: x['total_value_touched'], reverse=True)

        return jsonify({
            'period': period,
            'period_label': period_label,
            'start_date': start_date.isoformat(),
            'end_date': today.isoformat(),
            'performance': performance_data
        })

    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/aq-breakdown', methods=['GET'])
@token_required
def get_aq_breakdown():
    if local_demo_dashboard_enabled():
        return jsonify(dummy_aq_breakdown()), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)

        misc_sq = _misc_col2_sql_float()
        query = session.query(
            Employee_Master.employee_id,
            Employee_Master.employee_name,
            func.count(Client_Master.client_id).label('customer_count'),
            func.sum(misc_sq).label('total_aq'),
            func.sum(
                case(
                    (
                        and_(
                            Energy_Contract_Master.unit_rate.isnot(None),
                            Project_Details.Misc_Col2.isnot(None)
                        ),
                        (Energy_Contract_Master.unit_rate * misc_sq) / 100
                    ),
                    else_=0
                )
            ).label('total_revenue')
        ).join(
            Project_Details,
            Employee_Master.employee_id == Project_Details.assigned_employee_id
        ).join(
            Client_Master,
            Project_Details.client_id == Client_Master.client_id
        ).join(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None),
            Project_Details.Misc_Col2.isnot(None),
            Employee_Master.tenant_id == tenant_id
        )

        if employee_id:
            query = query.filter(Employee_Master.employee_id == employee_id)

        query = query.group_by(
            Employee_Master.employee_id,
            Employee_Master.employee_name
        ).order_by(func.sum(misc_sq).desc())

        results = query.all()

        breakdown = []
        total_aq = 0
        total_revenue = 0
        total_customers = 0

        for r in results:
            aq = float(r.total_aq or 0)
            revenue = float(r.total_revenue or 0)
            customers = r.customer_count or 0

            total_aq += aq
            total_revenue += revenue
            total_customers += customers

            breakdown.append({
                'employee_id': r.employee_id,
                'employee_name': r.employee_name,
                'customer_count': customers,
                'total_aq': aq,
                'total_revenue': round(revenue, 2),
                'average_aq_per_customer': round(aq / customers, 2) if customers > 0 else 0
            })

        return jsonify({
            'total_aq': total_aq,
            'total_revenue': round(total_revenue, 2),
            'total_customers': total_customers,
            'salesperson_count': len(breakdown),
            'breakdown': breakdown
        })

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error getting AQ breakdown: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route("/energy-renewals/test", methods=["GET"])
def test_renewals_endpoint():
    try:
        db = SessionLocal()
        test_query = text("""
            SELECT
                COUNT(DISTINCT cm.client_id) as total_clients,
                COUNT(DISTINCT ecm.energy_contract_master_id) as total_contracts,
                COUNT(CASE WHEN ecm.contract_end_date IS NOT NULL THEN 1 END) as contracts_with_end_date,
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days' THEN 1 END) as renewals_due_90_days,
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days' THEN 1 END) as renewals_due_30_days
            FROM "StreemLyne_MT"."Client_Master" cm
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
        """)
        result = db.execute(test_query).first()
        db.close()
        return jsonify({
            "status": "success",
            "total_clients": result.total_clients,
            "total_contracts": result.total_contracts,
            "contracts_with_end_date": result.contracts_with_end_date,
            "renewals_due_90_days": result.renewals_due_90_days,
            "renewals_due_30_days": result.renewals_due_30_days,
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500


@renewals_bp.route('/energy-renewals/performance', methods=['GET'])
@token_required
def get_renewal_performance():
    if local_demo_dashboard_enabled():
        return jsonify(dummy_renewal_performance()), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        use_current_user = request.args.get('use_current_user', 'false').lower() == 'true'

        if use_current_user:
            current_user = request.current_user
            if hasattr(current_user, 'id'):
                employee_id = current_user.id
            elif hasattr(current_user, 'employee_id'):
                employee_id = current_user.employee_id
            else:
                return jsonify({'error': 'User employee_id not found'}), 400
        else:
            employee_id = request.args.get('employee_id', type=int)

        # Avoid loading Energy_Contract_Master ORM rows (varchar-as-numeric causes psycopg 1043).
        base_query = session.query(Project_Details).join(
            Client_Master, Project_Details.client_id == Client_Master.client_id
        ).filter(
            cast(Client_Master.tenant_id, String) == str(tenant_id),
            exists().where(
                and_(
                    Energy_Contract_Master.project_id == Project_Details.project_id,
                    Energy_Contract_Master.contract_end_date.isnot(None),
                )
            ),
        )

        if employee_id:
            base_query = base_query.filter(
                Project_Details.assigned_employee_id == employee_id
            )

        all_results = base_query.all()

        renewed_count = 0
        contacted_count = 0
        not_contacted_count = 0
        lost_count = 0
        renewed_directly_count = 0
        end_date_changed_count = 0
        priced_count = 0

        for project in all_results:
            status = project.status

            if status:
                status_lower = status.lower()
                if status_lower == 'renewed directly':
                    renewed_directly_count += 1
                elif status_lower == 'end date changed':
                    end_date_changed_count += 1
                elif status_lower == 'priced':
                    priced_count += 1
                elif status_lower in ['renewed', 'already renewed']:
                    renewed_count += 1
                elif status_lower in ['called', 'callback', 'contacted']:
                    contacted_count += 1
                elif status_lower in ['lost', 'lost cot']:
                    lost_count += 1
                elif status_lower in ['not answered', 'not contacted']:
                    not_contacted_count += 1
                else:
                    not_contacted_count += 1
            else:
                not_contacted_count += 1

        total_attempts = renewed_count + lost_count + contacted_count + not_contacted_count
        success_rate = round((renewed_count / total_attempts * 100), 1) if total_attempts > 0 else 0

        return jsonify({
            'renewed_count': renewed_count,
            'contacted_count': contacted_count,
            'not_contacted_count': not_contacted_count,
            'lost_count': lost_count,
            'success_rate': success_rate,
            'total_customers': len(all_results),
            'employee_id': employee_id if employee_id else None,
            'renewed_directly_count': renewed_directly_count,
            'end_date_changed_count': end_date_changed_count,
            'priced_count': priced_count,
        })

    except Exception as e:
        current_app.logger.error(f"Error getting performance stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@renewals_bp.route('/energy-renewals/staff-status-counts', methods=['GET'])
@token_required
def get_staff_status_counts():
    if local_demo_dashboard_enabled():
        period = request.args.get('period', 'daily')
        return jsonify(dummy_staff_status_counts(period)), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)
        period, start_dt, end_dt, goal_multiplier = _period_bounds(request.args.get('period', 'daily'))
        ts_expr = _resolve_project_timestamp_expr(session)

        # Exclude offshore / leads-only users (CRM role_id 5) from renewals team performance
        base_sql = f"""
            SELECT
                em.employee_id,
                em.employee_name,
                pd.status,
                COUNT(DISTINCT pd.project_id) as count
            FROM "StreemLyne_MT"."Employee_Master" em
            JOIN "StreemLyne_MT"."Project_Details" pd
                ON em.employee_id = pd.assigned_employee_id
            JOIN "StreemLyne_MT"."Client_Master" cm
                ON pd.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm
                ON pd.project_id = ecm.project_id
            WHERE cm.tenant_id = :tenant_id
            AND em.tenant_id = :tenant_id
            AND {ts_expr} >= :start_dt
            AND {ts_expr} < :end_dt
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."User_Master" um_r5
                INNER JOIN "StreemLyne_MT"."User_Role_Mapping" urm_r5
                    ON urm_r5.user_id = um_r5.user_id
                    AND urm_r5.role_id = 5
                WHERE um_r5.employee_id = em.employee_id
            )
            {{employee_filter}}
            GROUP BY em.employee_id, em.employee_name, pd.status
            ORDER BY em.employee_name
        """

        params = {
            "tenant_id": tenant_id,
            "start_dt": start_dt,
            "end_dt": end_dt,
        }
        if employee_id:
            sql = base_sql.format(employee_filter="AND em.employee_id = :employee_id")
            params["employee_id"] = employee_id
        else:
            sql = base_sql.format(employee_filter="")

        results = session.execute(text(sql), params).fetchall()

        employees = {}
        for r in results:
            eid = r.employee_id
            if eid not in employees:
                employees[eid] = {
                    'employee_id': eid,
                    'employee_name': r.employee_name,
                    'renewed': 0,
                    'in_progress': 0,
                    'not_contacted': 0,
                    'lost': 0,
                    'renewed_directly': 0,
                    'end_date_changed': 0,
                    'priced': 0,
                    'total': 0,
                }
            count = r.count or 0
            s = (r.status or '').lower().strip()
            employees[eid]['total'] += count

            if s in ('renewed', 'already renewed'):
                employees[eid]['renewed'] += count
            elif s in ('callback', 'called', 'contacted'):
                employees[eid]['in_progress'] += count
            elif s in ('lost', 'lost cot'):
                employees[eid]['lost'] += count
            elif s == 'renewed directly':
                employees[eid]['renewed_directly'] += count
            elif s == 'end date changed':
                employees[eid]['end_date_changed'] += count
            elif s == 'priced':
                employees[eid]['priced'] += count
            elif s in ('not answered', 'email only', 'broker in place', 
                    'complaint', 'incorrect supplier', 'invalid number',
                    'meter de-energised'):
                employees[eid]['not_contacted'] += count
            else:
                # null/empty/unknown
                employees[eid]['not_contacted'] += count
        output = []
        for emp in employees.values():
            total = emp['total'] or 1
            rate = round((emp['renewed'] / total) * 100)
            goal_target = 25 * goal_multiplier
            goal_achieved = emp['renewed']
            goal_progress_pct = round((goal_achieved / goal_target) * 100, 1) if goal_target > 0 else 0
            output.append({
                'employee_id': emp['employee_id'],
                'employee_name': emp['employee_name'],
                'total_contacts': emp['total'],
                'renewed_count': emp['renewed'],
                'converted_count': emp['renewed'],
                'in_progress_count': emp['in_progress'],
                'not_contacted_count': emp['not_contacted'],
                'lost_count': emp['lost'],
                'renewed_directly_count': emp['renewed_directly'],
                'end_date_changed_count': emp['end_date_changed'],
                'priced_count': emp['priced'],
                'conversion_rate': rate,
                'goal_target': goal_target,
                'goal_achieved': goal_achieved,
                'goal_progress_pct': min(100, max(0, goal_progress_pct)),
                'goal_hit': goal_achieved >= goal_target,
                'period': period,
            })

        return jsonify(output), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@renewals_bp.route('/energy-renewals/debug-statuses', methods=['GET'])
@token_required
def debug_statuses():
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        results = session.execute(text("""
            SELECT 
                em.employee_name,
                pd.status,
                COUNT(*) as count
            FROM "StreemLyne_MT"."Employee_Master" em
            JOIN "StreemLyne_MT"."Project_Details" pd 
                ON em.employee_id = pd.assigned_employee_id
            JOIN "StreemLyne_MT"."Client_Master" cm 
                ON pd.client_id = cm.client_id
            JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm 
                ON pd.project_id = ecm.project_id
            WHERE cm.tenant_id = :tenant_id
            AND em.tenant_id = :tenant_id
            GROUP BY em.employee_name, pd.status
            ORDER BY em.employee_name, count DESC
        """), {"tenant_id": tenant_id}).fetchall()

        output = {}
        for row in results:
            name = row.employee_name
            if name not in output:
                output[name] = []
            output[name].append({"status": row.status, "count": row.count})

        return jsonify(output), 200
    finally:
        session.close()
