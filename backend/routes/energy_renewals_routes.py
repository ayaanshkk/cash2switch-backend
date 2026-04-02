# backend/routes/energy_renewals_routes.py

from flask import Blueprint, jsonify, request, current_app
from datetime import datetime, timedelta
from sqlalchemy import text, func, case, and_
from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Supplier_Master, Employee_Master, Client_Interactions
)
from ..db import SessionLocal
from .auth_helpers import token_required, get_tenant_id_from_user

renewals_bp = Blueprint("renewals", __name__)

# ============================================================================
# ENERGY RENEWALS ENDPOINTS
# ============================================================================

@renewals_bp.route("/energy-renewals", methods=["GET"])
@token_required
def get_renewals():
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
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)
        today = datetime.utcnow().date()
        days_365_later = today + timedelta(days=365)

        base_query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
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

        for client, project, contract in all_results:
            end_date = contract.contract_end_date

            if project.Misc_Col2:
                total_aq += project.Misc_Col2

            if not end_date:
                continue

            days_until_renewal = (end_date - today).days

            if days_until_renewal > 365:
                not_due_contracts += 1
            elif days_until_renewal < 0:
                expired_contracts += 1
            elif 30 <= days_until_renewal <= 60:
                total_renewals_30_60_days += 1
            elif 61 <= days_until_renewal <= 90:
                total_renewals_61_90_days += 1
            elif 91 <= days_until_renewal <= 180:
                total_renewals_90_plus_days += 1

            if contract.unit_rate and project.Misc_Col2:
                annual_cost = (contract.unit_rate * project.Misc_Col2) / 100
                total_revenue_at_risk += annual_cost

            status = project.status
            if status:
                status_lower = status.lower()
                if status_lower in ['called', 'callback', 'contacted', 'not answered']:
                    contacted_count += 1
                elif status_lower in ['not contacted']:
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
                        (Energy_Contract_Master.unit_rate * Project_Details.Misc_Col2) / 100
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
                        (Energy_Contract_Master.unit_rate * Project_Details.Misc_Col2) / 100
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
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        period = request.args.get('period')
        employee_id = request.args.get('employee_id', type=int)
        today = datetime.utcnow().date()

        if period == 'not-due':
            start_date = today + timedelta(days=366)
            end_date = today + timedelta(days=365 * 10)
        elif period == 'expired':
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
            if r.unit_rate and r.annual_usage:
                revenue = (r.unit_rate * r.annual_usage) / 100

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
                'annual_usage': r.annual_usage,
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

            revenue = 0
            if r.unit_rate and r.annual_usage:
                revenue = (r.unit_rate * r.annual_usage) / 100

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
                    'annual_usage': r.annual_usage,
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
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        employee_id = request.args.get('employee_id', type=int)

        query = session.query(
            Employee_Master.employee_id,
            Employee_Master.employee_name,
            func.count(Client_Master.client_id).label('customer_count'),
            func.sum(Project_Details.Misc_Col2).label('total_aq'),
            func.sum(
                case(
                    (
                        and_(
                            Energy_Contract_Master.unit_rate.isnot(None),
                            Project_Details.Misc_Col2.isnot(None)
                        ),
                        (Energy_Contract_Master.unit_rate * Project_Details.Misc_Col2) / 100
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
        ).order_by(func.sum(Project_Details.Misc_Col2).desc())

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

        base_query = session.query(
            Project_Details,
            Energy_Contract_Master,
        ).join(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).join(
            Client_Master, Project_Details.client_id == Client_Master.client_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None)
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

        for project, contract in all_results:
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
                elif status_lower in ['called', 'callback', 'contacted', 'not answered']:
                    contacted_count += 1
                elif status_lower in ['lost', 'lost cot']:
                    lost_count += 1
                elif status_lower in ['not contacted']:
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
    """
    Returns status counts for all staff members, including those with 0 assignments.
    Excludes employees with role_ids containing '5' (leads-only salespeople).
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
 
        # Get ALL employees for this tenant, excluding those with role '5'
        all_employees_query = """
            SELECT DISTINCT
                em.employee_id,
                em.employee_name,
                em.role_ids
            FROM "StreemLyne_MT"."Employee_Master" em
            WHERE em.tenant_id = :tenant_id
            AND (em.role_ids IS NULL OR em.role_ids NOT LIKE '%5%')
            {employee_filter}
            ORDER BY em.employee_name
        """
 
        # Get project status counts
        project_stats_query = """
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
            AND (em.role_ids IS NULL OR em.role_ids NOT LIKE '%5%')
            {employee_filter}
            GROUP BY em.employee_id, em.employee_name, pd.status
            ORDER BY em.employee_name
        """
 
        params = {"tenant_id": tenant_id}
        
        # Get all employees (excluding those with role_id 5)
        if employee_id:
            all_emp_sql = all_employees_query.format(employee_filter="AND em.employee_id = :employee_id")
            params["employee_id"] = employee_id
        else:
            all_emp_sql = all_employees_query.format(employee_filter="")
 
        print(f"🔍 Executing query to get all employees for tenant {tenant_id}...")
        
        all_employees = session.execute(text(all_emp_sql), params).fetchall()
        
        print(f"✅ Found {len(all_employees)} employees")
        for emp in all_employees:
            print(f"  - {emp.employee_name} (ID: {emp.employee_id}, role_ids: '{emp.role_ids}')")
        
        # Initialize all employees with zero counts
        employees = {}
        for emp in all_employees:
            employees[emp.employee_id] = {
                'employee_id': emp.employee_id,
                'employee_name': emp.employee_name,
                'renewed': 0,
                'in_progress': 0,
                'not_contacted': 0,
                'lost': 0,
                'renewed_directly': 0,
                'end_date_changed': 0,
                'priced': 0,
                'total': 0,
            }
 
        # Get project stats
        if employee_id:
            stats_sql = project_stats_query.format(employee_filter="AND em.employee_id = :employee_id")
        else:
            stats_sql = project_stats_query.format(employee_filter="")
 
        print(f"🔍 Executing query to get project stats...")
        results = session.execute(text(stats_sql), params).fetchall()
        
        print(f"✅ Found {len(results)} project status records")
 
        # Update counts for employees with projects
        for r in results:
            eid = r.employee_id
            if eid in employees:
                count = r.count or 0
                s = (r.status or '').lower().strip()
                employees[eid]['total'] += count
                
                print(f"  - Employee {eid}: status='{r.status}' ({s}), count={count}")

                if s in ('renewed', 'already renewed'):
                    employees[eid]['renewed'] += count
                elif s in ('callback', 'called', 'contacted', 'not answered'):
                    employees[eid]['in_progress'] += count
                elif s in ('lost', 'lost cot'):
                    employees[eid]['lost'] += count
                elif s == 'renewed directly':
                    employees[eid]['renewed_directly'] += count
                elif s == 'end date changed':
                    employees[eid]['end_date_changed'] += count
                elif s == 'priced':
                    employees[eid]['priced'] += count
                elif s in ('email only', 'broker in place', 'complaint', 
                          'incorrect supplier', 'invalid number', 'meter de-energised'):
                    employees[eid]['not_contacted'] += count
                elif s == 'not contacted':
                    employees[eid]['not_contacted'] += count
                else:
                    # null/empty/unknown - default to not contacted
                    employees[eid]['not_contacted'] += count
                    print(f"    ⚠️  Unknown status '{s}' - defaulting to not_contacted")
 
        # Build output
        output = []
        for emp in employees.values():
            total = emp['total'] if emp['total'] > 0 else 1
            rate = round((emp['renewed'] / total) * 100) if emp['total'] > 0 else 0
            
            output.append({
                'employee_id': emp['employee_id'],
                'employee_name': emp['employee_name'],
                'total_contacts': emp['total'],
                'renewed_count': emp['renewed'],
                'in_progress_count': emp['in_progress'],
                'not_contacted_count': emp['not_contacted'],
                'lost_count': emp['lost'],
                'renewed_directly_count': emp['renewed_directly'],
                'end_date_changed_count': emp['end_date_changed'],
                'priced_count': emp['priced'],
                'conversion_rate': rate,
                'converted_count': emp['renewed'],
            })
 
        print(f"\n✅ FINAL OUTPUT: Returning {len(output)} staff members")
        for member in output:
            print(f"  - {member['employee_name']}: total={member['total_contacts']}, "
                  f"renewed={member['renewed_count']}, in_progress={member['in_progress_count']}, "
                  f"not_contacted={member['not_contacted_count']}, lost={member['lost_count']}, "
                  f"rate={member['conversion_rate']}%")
        
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


# ============================================================================
# LEADS ENDPOINTS (Merged from leads_routes.py)
# ============================================================================

@renewals_bp.route('/api/crm/leads/staff-performance', methods=['GET'])
@token_required
def get_leads_staff_performance():
    """
    Staff performance for leads - uses Opportunity_Details table
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
 
        # ✅ Get ALL salespeople - use role_ids column (contains '2', '3', or '5')
        all_employees_query = """
            SELECT DISTINCT
                em.employee_id,
                em.employee_name
            FROM "StreemLyne_MT"."Employee_Master" em
            WHERE em.tenant_id = :tenant_id
            AND (
                em.role_ids LIKE '%2%' OR 
                em.role_ids LIKE '%3%' OR 
                em.role_ids LIKE '%5%'
            )
            {employee_filter}
            ORDER BY em.employee_name
        """
 
        # Get lead status counts from Opportunity_Details + Stage_Master
        lead_stats_query = """
            SELECT
                em.employee_id,
                em.employee_name,
                sm.stage_name,
                COUNT(DISTINCT od.opportunity_id) as count
            FROM "StreemLyne_MT"."Employee_Master" em
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od
                ON em.employee_id = od.opportunity_owner_employee_id
                AND od.tenant_id = :tenant_id
                AND od.is_allocated = true
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od.stage_id = sm.stage_id
            WHERE em.tenant_id = :tenant_id
            AND (
                em.role_ids LIKE '%2%' OR 
                em.role_ids LIKE '%3%' OR 
                em.role_ids LIKE '%5%'
            )
            {employee_filter}
            GROUP BY em.employee_id, em.employee_name, sm.stage_name
            ORDER BY em.employee_name
        """
 
        params = {"tenant_id": tenant_id}
        
        # Apply employee filter if specified
        if employee_id:
            all_emp_sql = all_employees_query.format(employee_filter="AND em.employee_id = :employee_id")
            stats_sql = lead_stats_query.format(employee_filter="AND em.employee_id = :employee_id")
            params["employee_id"] = employee_id
        else:
            all_emp_sql = all_employees_query.format(employee_filter="")
            stats_sql = lead_stats_query.format(employee_filter="")
 
        # Get all employees
        all_employees = session.execute(text(all_emp_sql), params).fetchall()
        
        # Initialize all employees with zero counts
        employees = {}
        for emp in all_employees:
            employees[emp.employee_id] = {
                'employee_id': emp.employee_id,
                'employee_name': emp.employee_name,
                'total_leads': 0,
                'converted_leads': 0,
                'in_progress_leads': 0,
                'not_contacted_leads': 0,
                'lost_leads': 0,
                'by_stage': []
            }
 
        # Get lead stats
        results = session.execute(text(stats_sql), params).fetchall()
 
        # Update counts for employees with leads
        for r in results:
            eid = r.employee_id
            if eid in employees and r.stage_name:  # Skip NULL stages
                count = r.count or 0
                stage = (r.stage_name or '').lower().strip()
                employees[eid]['total_leads'] += count
                
                # Track by stage for debugging
                employees[eid]['by_stage'].append({
                    'stage_name': r.stage_name,
                    'count': count
                })
 
                # Categorize stages (adjust these based on your actual Stage_Master values)
                if stage in ('converted', 'won', 'renewed', 'signed', 'closed won'):
                    employees[eid]['converted_leads'] += count
                elif stage in ('callback', 'contacted', 'in progress', 'follow up', 'qualified', 'proposal sent', 'negotiation'):
                    employees[eid]['in_progress_leads'] += count
                elif stage in ('not contacted', 'new', 'unassigned', 'open'):
                    employees[eid]['not_contacted_leads'] += count
                elif stage in ('lost', 'rejected', 'not interested', 'closed lost'):
                    employees[eid]['lost_leads'] += count
                else:
                    # Default unknown stages to in_progress
                    employees[eid]['in_progress_leads'] += count
 
        # Build output matching StaffPerformanceGrid expectations
        output = []
        for emp in employees.values():
            total = emp['total_leads'] if emp['total_leads'] > 0 else 1
            rate = round((emp['converted_leads'] / total) * 100) if emp['total_leads'] > 0 else 0
            
            output.append({
                # Required fields for StaffPerformanceGrid
                'employee_id': emp['employee_id'],
                'employee_name': emp['employee_name'],
                'total_contacts': emp['total_leads'],
                'converted_count': emp['converted_leads'],
                'conversion_rate': rate,
                'renewed_count': emp['converted_leads'],  # For leads, "renewed" = "converted"
                'in_progress_count': emp['in_progress_leads'],
                'not_contacted_count': emp['not_contacted_leads'],
                'lost_count': emp['lost_leads'],
                
                # Additional compatibility fields
                'renewed_directly_count': 0,
                'end_date_changed_count': 0,
                'priced_count': 0,
                'total_value_touched': 0,
            })
 
        print(f"✅ Returning {len(output)} LEADS staff members (using Opportunity_Details)")
        return jsonify(output), 200
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
 
@renewals_bp.route('/api/crm/leads/stats', methods=['GET'])
@token_required
def get_leads_dashboard_stats():
    """
    Dashboard overview statistics for leads - uses Opportunity_Details table
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
 
        # Base WHERE clause
        base_conditions = """
            WHERE od.tenant_id = :tenant_id
        """
 
        params = {"tenant_id": tenant_id}
        
        # Add employee filter if specified
        if employee_id:
            base_conditions += " AND od.opportunity_owner_employee_id = :employee_id"
            params["employee_id"] = employee_id
 
        # Total leads
        total_leads_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
        """
        total_leads = session.execute(text(total_leads_query), params).scalar() or 0
 
        # Active leads (not Lost/Converted)
        active_leads_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
        """
        active_leads = session.execute(text(active_leads_query), params).scalar() or 0
 
        # Converted leads
        converted_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('converted', 'won', 'signed', 'renewed', 'closed won')
        """
        converted_leads = session.execute(text(converted_query), params).scalar() or 0
 
        # New/Uncontacted
        new_leads_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('new', 'not contacted', 'unassigned', 'open')
        """
        new_leads = session.execute(text(new_leads_query), params).scalar() or 0
 
        # In Progress
        in_progress_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('contacted', 'callback', 'in progress', 'follow up', 'qualified', 'proposal sent', 'negotiation')
        """
        in_progress = session.execute(text(in_progress_query), params).scalar() or 0
 
        # Lost leads
        lost_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('lost', 'rejected', 'not interested', 'closed lost')
        """
        lost_leads = session.execute(text(lost_query), params).scalar() or 0
 
        # Total estimated value (using opportunity_value column)
        total_value_query = f"""
            SELECT COALESCE(SUM(od.opportunity_value), 0)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
        """
        total_value = session.execute(text(total_value_query), params).scalar() or 0
 
        # Conversion rate
        conversion_rate = round((converted_leads / total_leads * 100), 1) if total_leads > 0 else 0.0
 
        # Recent activity (leads created in last 30 days)
        recent_leads_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
            AND od.created_at >= CURRENT_DATE - INTERVAL '30 days'
        """
        recent_leads = session.execute(text(recent_leads_query), params).scalar() or 0
 
        # Stage breakdown for charts/analytics
        stage_breakdown_query = f"""
            SELECT 
                COALESCE(sm.stage_name, 'Unknown') as stage_name, 
                COUNT(DISTINCT od.opportunity_id) as count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            GROUP BY sm.stage_name
            ORDER BY count DESC
        """
        stage_results = session.execute(text(stage_breakdown_query), params).fetchall()
        stages = {stage: count for stage, count in stage_results}
 
        # Allocated vs Unallocated
        allocated_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
            AND od.is_allocated = true
        """
        allocated_leads = session.execute(text(allocated_query), params).scalar() or 0
 
        unallocated_query = f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
            AND (od.is_allocated = false OR od.is_allocated IS NULL)
        """
        unallocated_leads = session.execute(text(unallocated_query), params).scalar() or 0
 
        return jsonify({
            # Core metrics
            'total_leads': total_leads,
            'active_leads': active_leads,
            'converted_leads': converted_leads,
            'new_leads': new_leads,
            'in_progress': in_progress,
            'lost_leads': lost_leads,
            'conversion_rate': conversion_rate,
            
            # Financial
            'total_value': float(total_value),
            
            # Time-based
            'recent_leads_30d': recent_leads,
            
            # Allocation
            'allocated_leads': allocated_leads,
            'unallocated_leads': unallocated_leads,
            
            # Breakdown for charts
            'stage_breakdown': stages,
        }), 200
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
 
@renewals_bp.route('/api/crm/leads/stage-breakdown', methods=['GET'])
@token_required
def get_leads_stage_breakdown():
    """
    Stage breakdown for leads pipeline - used by LeadsOverview component
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
 
        # Build query
        query = """
            SELECT 
                sm.stage_name,
                sm.stage_id,
                COUNT(DISTINCT od.opportunity_id) as count,
                COALESCE(SUM(od.opportunity_value), 0) as total_value
            FROM "StreemLyne_MT"."Stage_Master" sm
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od 
                ON sm.stage_id = od.stage_id
                AND od.tenant_id = :tenant_id
                {employee_filter}
            WHERE sm.stage_type = 1  -- Assuming 1 = leads stages
            GROUP BY sm.stage_id, sm.stage_name
            ORDER BY sm.stage_id
        """
 
        params = {"tenant_id": tenant_id}
        
        if employee_id:
            query = query.format(employee_filter="AND od.opportunity_owner_employee_id = :employee_id")
            params["employee_id"] = employee_id
        else:
            query = query.format(employee_filter="")
 
        results = session.execute(text(query), params).fetchall()
 
        breakdown = []
        for r in results:
            breakdown.append({
                'stage_id': r.stage_id,
                'stage_name': r.stage_name,
                'count': r.count or 0,
                'total_value': float(r.total_value or 0)
            })
 
        return jsonify(breakdown), 200
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@renewals_bp.route('/api/crm/leads/salesperson-breakdown', methods=['GET'])
@token_required
def get_leads_salesperson_breakdown():
    """
    Salesperson breakdown for leads - shows performance by salesperson
    Used by LeadsOverview component for admin view
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        # Get salesperson performance from Opportunity_Details
        query = """
            SELECT
                em.employee_id,
                em.employee_name,
                COUNT(DISTINCT od.opportunity_id) as total_leads,
                COUNT(DISTINCT CASE 
                    WHEN LOWER(COALESCE(sm.stage_name, '')) IN ('converted', 'won', 'signed', 'renewed', 'closed won')
                    THEN od.opportunity_id 
                END) as converted_count,
                COUNT(DISTINCT CASE 
                    WHEN LOWER(COALESCE(sm.stage_name, '')) IN ('contacted', 'callback', 'in progress', 'follow up', 'qualified', 'proposal sent', 'negotiation')
                    THEN od.opportunity_id 
                END) as in_progress_count,
                COUNT(DISTINCT CASE 
                    WHEN LOWER(COALESCE(sm.stage_name, '')) IN ('new', 'not contacted', 'unassigned', 'open')
                    THEN od.opportunity_id 
                END) as not_contacted_count,
                COUNT(DISTINCT CASE 
                    WHEN LOWER(COALESCE(sm.stage_name, '')) IN ('lost', 'rejected', 'not interested', 'closed lost')
                    THEN od.opportunity_id 
                END) as lost_count,
                COALESCE(SUM(od.opportunity_value), 0) as total_value
            FROM "StreemLyne_MT"."Employee_Master" em
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od
                ON em.employee_id = od.opportunity_owner_employee_id
                AND od.tenant_id = :tenant_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od.stage_id = sm.stage_id
            WHERE em.tenant_id = :tenant_id
            AND (
                em.role_ids LIKE '%2%' OR 
                em.role_ids LIKE '%3%' OR 
                em.role_ids LIKE '%5%'
            )
            GROUP BY em.employee_id, em.employee_name
            HAVING COUNT(DISTINCT od.opportunity_id) > 0
            ORDER BY total_value DESC
        """
 
        results = session.execute(text(query), {"tenant_id": tenant_id}).fetchall()
 
        breakdown = []
        for r in results:
            total = r.total_leads or 0
            converted = r.converted_count or 0
            conversion_rate = round((converted / total * 100), 1) if total > 0 else 0.0
 
            breakdown.append({
                'employee_id': r.employee_id,
                'employee_name': r.employee_name,
                'total_leads': total,
                'converted_count': converted,
                'in_progress_count': r.in_progress_count or 0,
                'not_contacted_count': r.not_contacted_count or 0,
                'lost_count': r.lost_count or 0,
                'conversion_rate': conversion_rate,
                'total_value': float(r.total_value or 0)
            })
 
        return jsonify(breakdown), 200
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@renewals_bp.route('/api/crm/leads/by-stage', methods=['GET'])
@token_required
def get_leads_by_stage_endpoint():
    """
    Get detailed leads for a specific stage/category
    Used by LeadsOverview modal to show lead details
    Integrates with your lead_repository.py
    """
    from backend.crm.repositories.lead_repository import LeadRepository
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        stage = request.args.get('stage')
        employee_id = request.args.get('employee_id', type=int)
 
        if not stage:
            return jsonify({'error': 'Stage parameter required'}), 400
 
        # Initialize repository
        lead_repo = LeadRepository()
 
        # For category-based queries (not direct stage IDs), we need custom SQL
        db = SessionLocal()
        
        try:
            # Map frontend stage categories to SQL filters
            if stage == 'all':
                stage_condition = ""
            elif stage == 'new':
                stage_condition = "AND LOWER(COALESCE(sm.stage_name, '')) IN ('new', 'not contacted', 'unassigned', 'open')"
            elif stage == 'in_progress':
                stage_condition = "AND LOWER(COALESCE(sm.stage_name, '')) IN ('contacted', 'callback', 'in progress', 'follow up', 'qualified', 'proposal sent', 'negotiation')"
            elif stage == 'converted':
                stage_condition = "AND LOWER(COALESCE(sm.stage_name, '')) IN ('converted', 'won', 'signed', 'renewed', 'closed won')"
            elif stage == 'lost':
                stage_condition = "AND LOWER(COALESCE(sm.stage_name, '')) IN ('lost', 'rejected', 'not interested', 'closed lost')"
            else:
                # Specific stage name provided - try to get stage_id first
                stage_query = text("""
                    SELECT stage_id FROM "StreemLyne_MT"."Stage_Master" 
                    WHERE LOWER(stage_name) = LOWER(:stage_name)
                """)
                stage_result = db.execute(stage_query, {"stage_name": stage}).first()
                
                if stage_result:
                    # Use existing repository method
                    leads_data = lead_repo.get_leads_by_stage(tenant_id, stage_result.stage_id)
                    
                    # Format for frontend
                    leads = []
                    for r in leads_data:
                        leads.append({
                            'opportunity_id': r.get('opportunity_id'),
                            'business_name': r.get('business_name') or 'Unknown',
                            'contact_person': r.get('contact_person') or 'N/A',
                            'tel_number': r.get('tel_number') or 'N/A',
                            'email': r.get('email') or 'N/A',
                            'stage_name': r.get('stage_name') or 'Unknown',
                            'opportunity_value': float(r.get('opportunity_value') or 0),
                            'assigned_to_name': r.get('assigned_to_name') or 'Unassigned',
                            'created_at': r.get('created_at'),
                            'annual_usage': float(r.get('annual_usage') or 0),
                            'service_name': r.get('service_name') or 'Energy'
                        })
                    
                    # Filter by employee if needed
                    if employee_id:
                        leads = [l for l in leads if l.get('assigned_to_id') == employee_id]
                    
                    return jsonify({
                        'stage': stage,
                        'total_count': len(leads),
                        'leads': leads
                    }), 200
                else:
                    stage_condition = ""
 
            # Build custom query for category-based filtering
            query = text("""
                SELECT 
                    od.opportunity_id,
                    od.business_name,
                    od.contact_person,
                    od.tel_number,
                    od.email,
                    sm.stage_name,
                    od.opportunity_value,
                    em.employee_name as assigned_to_name,
                    od.opportunity_owner_employee_id as assigned_to_id,
                    od.created_at,
                    od.annual_usage,
                    srv.service_title as service_name
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
                LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od.opportunity_owner_employee_id = em.employee_id
                LEFT JOIN "StreemLyne_MT"."Services_Master" srv ON od.service_id = srv.service_id
                WHERE od.tenant_id = :tenant_id
                {stage_condition}
                {employee_filter}
                ORDER BY od.created_at DESC
            """.format(
                stage_condition=stage_condition,
                employee_filter="AND od.opportunity_owner_employee_id = :employee_id" if employee_id else ""
            ))
 
            params = {"tenant_id": tenant_id}
            if employee_id:
                params["employee_id"] = employee_id
 
            results = db.execute(query, params).fetchall()
 
            leads = []
            for r in results:
                leads.append({
                    'opportunity_id': r.opportunity_id,
                    'business_name': r.business_name or 'Unknown',
                    'contact_person': r.contact_person or 'N/A',
                    'tel_number': r.tel_number or 'N/A',
                    'email': r.email or 'N/A',
                    'stage_name': r.stage_name or 'Unknown',
                    'opportunity_value': float(r.opportunity_value or 0),
                    'assigned_to_name': r.assigned_to_name or 'Unassigned',
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                    'annual_usage': float(r.annual_usage or 0),
                    'service_name': r.service_name or 'Energy'
                })
 
            return jsonify({
                'stage': stage,
                'total_count': len(leads),
                'leads': leads
            }), 200
 
        finally:
            db.close()
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500