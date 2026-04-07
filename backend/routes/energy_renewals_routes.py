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
        service_param = request.args.get('service', 'utilities')
        service_id = {'utilities': 1, 'water': 2, 'gas': 3}.get(service_param.strip().lower(), 1)

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

        today = datetime.utcnow().date()

        base_query = session.query(
            Project_Details,
            Energy_Contract_Master,
        ).join(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).join(
            Client_Master, Project_Details.client_id == Client_Master.client_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None),
            Energy_Contract_Master.service_id == service_id
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
        not_due_count = 0

        for project, contract in all_results:
            # ✅ Calculate days until renewal
            days_until_renewal = (contract.contract_end_date - today).days
            
            # ✅ Count not_due (365+ days) FIRST
            if days_until_renewal > 365:
                not_due_count += 1
                continue  # Don't count in other categories
            
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
            'not_due': not_due_count,
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
    Staff performance for renewals - role_id 2, 3 only
    Returns 4 categories: Renewed, In Progress, Not Contacted, Lost
    Each category is separate and NOT combined
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
        
        print(f"\n{'='*80}")
        print(f"🔍 RENEWALS STAFF PERFORMANCE REQUEST")
        print(f"{'='*80}")
        print(f"Tenant ID: {tenant_id}")
        print(f"Employee ID filter: {employee_id}")
        print(f"{'='*80}\n")
 
        employee_filter = ""
        if employee_id:
            employee_filter = " AND em.employee_id = :employee_id "
        
        # Get employees with role 2, 3
        all_emp_sql = """
            SELECT DISTINCT
                em.employee_id,
                em.employee_name
            FROM "StreemLyne_MT"."Employee_Master" em
            INNER JOIN "StreemLyne_MT"."User_Master" um
                ON em.employee_id = um.employee_id
            INNER JOIN "StreemLyne_MT"."User_Role_Mapping" urm
                ON um.user_id = urm.user_id
            WHERE em.tenant_id = :tenant_id
            AND urm.role_id IN (2, 3)
        """ + employee_filter + """
            ORDER BY em.employee_name
        """
        
        params = {'tenant_id': tenant_id}
        if employee_id:
            params['employee_id'] = employee_id
            
        all_employees = session.execute(text(all_emp_sql), params).fetchall()
        
        print(f"✅ Found {len(all_employees)} employees with roles 2, 3\n")
        
        results = []
        for emp in all_employees:
            emp_id = emp.employee_id
            emp_name = emp.employee_name
            
            # ✅ SEPARATE BREAKDOWN - DO NOT COMBINE
            stats_query = """
                SELECT 
                    COUNT(*) as total_contacts,
                    
                    -- Renewed: ONLY "Already Renewed" (not including other success statuses)
                    SUM(CASE 
                        WHEN pd.status = 'Already Renewed'
                        THEN 1 ELSE 0 
                    END) as renewed_count,
                    
                    -- In Progress: Callback, Called, Contacted, Not Answered
                    SUM(CASE 
                        WHEN pd.status IN ('Callback', 'Called', 'Contacted', 'Not Answered')
                        THEN 1 ELSE 0 
                    END) as in_progress_count,
                    
                    -- Not Contacted: NULL status only
                    SUM(CASE 
                        WHEN pd.status IS NULL
                        THEN 1 ELSE 0 
                    END) as not_contacted_count,
                    
                    -- Lost: ONLY "Lost COT" (not including Meter De-energised)
                    SUM(CASE 
                        WHEN pd.status = 'Lost COT'
                        THEN 1 ELSE 0 
                    END) as lost_count
                    
                FROM "StreemLyne_MT"."Client_Master" cm
                INNER JOIN "StreemLyne_MT"."Project_Details" pd 
                    ON cm.client_id = pd.client_id
                INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm 
                    ON pd.project_id = ecm.project_id
                WHERE cm.tenant_id = :tenant_id
                AND pd.assigned_employee_id = :emp_id
                AND ecm.contract_end_date IS NOT NULL
            """
            
            stats_result = session.execute(
                text(stats_query), 
                {'tenant_id': tenant_id, 'emp_id': emp_id}
            ).fetchone()
            
            total = stats_result.total_contacts or 0
            renewed = stats_result.renewed_count or 0
            in_progress = stats_result.in_progress_count or 0
            not_contacted = stats_result.not_contacted_count or 0
            lost = stats_result.lost_count or 0
            
            # Conversion = Renewed / Total (only counting "Already Renewed")
            conversion_rate = round((renewed / total * 100), 1) if total > 0 else 0
            
            print(f"   📊 {emp_name}:")
            print(f"      Total: {total}")
            print(f"      Renewed: {renewed} ({conversion_rate}%)")
            print(f"      In Progress: {in_progress}")
            print(f"      Not Contacted: {not_contacted}")
            print(f"      Lost: {lost}")
            
            results.append({
                'employee_id': emp_id,
                'employee_name': emp_name,
                'total_contacts': total,
                'renewed_count': renewed,
                'conversion_rate': conversion_rate,
                'in_progress_count': in_progress,
                'not_contacted_count': not_contacted,
                'lost_count': lost,
                'total_value_touched': 0,
                'renewed_directly_count': 0,
                'end_date_changed_count': 0,
                'priced_count': 0,
            })
        
        print(f"\n✅ Returning {len(results)} staff performance records\n")
        return jsonify(results)
        
    except Exception as e:
        print(f"❌ Error in staff status counts: {e}")
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
    Leads staff performance - role_id 2, 3, 5 (local + offshore)
    Returns 4 categories: Converted, In Progress, Not Contacted, Lost
    Uses exact stage names from database
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
        
        print(f"\n{'='*80}")
        print(f"🔍 LEADS STAFF PERFORMANCE REQUEST")
        print(f"{'='*80}")
        print(f"Tenant ID: {tenant_id}")
        print(f"Employee ID filter: {employee_id}")
        print(f"{'='*80}\n")
 
        employee_filter = ""
        if employee_id:
            employee_filter = " AND em.employee_id = :employee_id "
        
        # Get employees with role 2, 3, 5 (includes offshore)
        all_emp_sql = """
            SELECT DISTINCT
                em.employee_id,
                em.employee_name
            FROM "StreemLyne_MT"."Employee_Master" em
            INNER JOIN "StreemLyne_MT"."User_Master" um
                ON em.employee_id = um.employee_id
            INNER JOIN "StreemLyne_MT"."User_Role_Mapping" urm
                ON um.user_id = urm.user_id
            WHERE em.tenant_id = :tenant_id
            AND urm.role_id IN (2, 3, 5)
        """ + employee_filter + """
            ORDER BY em.employee_name
        """
        
        params = {'tenant_id': tenant_id}
        if employee_id:
            params['employee_id'] = employee_id
            
        all_employees = session.execute(text(all_emp_sql), params).fetchall()
        
        print(f"✅ Found {len(all_employees)} employees with roles 2, 3, 5\n")
        
        results = []
        for emp in all_employees:
            emp_id = emp.employee_id
            emp_name = emp.employee_name
            
            # ✅ Using EXACT stage names from your database
            stats_query = """
                SELECT 
                    COUNT(*) as total_contacts,
                    
                    -- Converted: All success outcomes
                    SUM(CASE 
                        WHEN sm.stage_name IN (
                            'Already Renewed',
                            'Renewed Directly',
                            'End Date Changed',
                            'Won',
                            'Priced'
                        )
                        THEN 1 ELSE 0 
                    END) as converted_count,
                    
                    -- In Progress: Active engagement
                    SUM(CASE 
                        WHEN sm.stage_name IN (
                            'Callback',
                            'Not Answered',
                            'Email Only'
                        )
                        THEN 1 ELSE 0 
                    END) as in_progress_count,
                    
                    -- Not Contacted: Never reached out or just imported
                    SUM(CASE 
                        WHEN sm.stage_name IN ('Not Called', 'Lead') OR sm.stage_name IS NULL
                        THEN 1 ELSE 0 
                    END) as not_contacted_count,
                    
                    -- Lost: All failure outcomes
                    SUM(CASE 
                        WHEN sm.stage_name IN (
                            'Lost',
                            'Lost COT',
                            'Broker in Place',
                            'Invalid Number',
                            'Incorrect Supplier'
                        )
                        THEN 1 ELSE 0 
                    END) as lost_count
                    
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
                WHERE od.tenant_id = :tenant_id
                AND od.opportunity_owner_employee_id = :emp_id
                AND (sm.stage_type = 1 OR sm.stage_type IS NULL)
            """
            
            stats_result = session.execute(
                text(stats_query), 
                {'tenant_id': tenant_id, 'emp_id': emp_id}
            ).fetchone()
            
            total = stats_result.total_contacts or 0
            converted = stats_result.converted_count or 0
            in_progress = stats_result.in_progress_count or 0
            not_contacted = stats_result.not_contacted_count or 0
            lost = stats_result.lost_count or 0
            
            # ✅ FIX: Conversion = Converted / Total (with proper decimal handling)
            conversion_rate = round((converted / total * 100), 1) if total > 0 else 0.0
            
            print(f"   📊 {emp_name}:")
            print(f"      Total: {total}")
            print(f"      Converted: {converted} ({conversion_rate}%)")
            print(f"      In Progress: {in_progress}")
            print(f"      Not Contacted: {not_contacted}")
            print(f"      Lost: {lost}")
            
            results.append({
                'employee_id': emp_id,
                'employee_name': emp_name,
                'total_contacts': total,
                'converted_count': converted,
                'renewed_count': converted,  # Frontend uses 'renewed_count'
                'conversion_rate': conversion_rate,
                'in_progress_count': in_progress,
                'not_contacted_count': not_contacted,
                'lost_count': lost,
                'total_value_touched': 0,
                'renewed_directly_count': 0,
                'end_date_changed_count': 0,
                'priced_count': 0,
            })
        
        print(f"\n✅ Returning {len(results)} leads performance records\n")
        return jsonify(results)
        
    except Exception as e:
        print(f"❌ Error in leads staff performance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
@renewals_bp.route('/api/crm/leads/stats', methods=['GET'])
@token_required
def get_leads_dashboard_stats():
    """
    Dashboard overview statistics for leads
    ✅ FIXED: Uses end_date column + tenant_id casting
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
        today = datetime.utcnow().date()
 
        print(f"\n{'='*80}")
        print(f"📊 LEADS STATS REQUEST")
        print(f"{'='*80}")
        print(f"Tenant ID: {tenant_id}")
        print(f"Employee ID: {employee_id}")
        print(f"Today: {today}")
        print(f"{'='*80}\n")
 
        # Base WHERE clause - ✅ CAST tenant_id
        base_conditions = "WHERE od.tenant_id = CAST(:tenant_id AS VARCHAR)"
        params = {"tenant_id": str(tenant_id)}
        
        if employee_id:
            base_conditions += " AND od.opportunity_owner_employee_id = :employee_id"
            params["employee_id"] = employee_id
 
        # ===== PERIOD-BASED COUNTS (Using end_date) =====
        
        # 30-60 Days
        query_30_60 = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND od.end_date IS NOT NULL
            AND od.end_date BETWEEN :start_30 AND :end_60
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
        """)
        
        params_30_60 = {
            **params,
            "start_30": today + timedelta(days=30),
            "end_60": today + timedelta(days=60)
        }
        leads_30_60_days = session.execute(query_30_60, params_30_60).scalar() or 0
        print(f"✅ 30-60 Days: {leads_30_60_days}")
        
        # 61-90 Days
        query_61_90 = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND od.end_date IS NOT NULL
            AND od.end_date BETWEEN :start_61 AND :end_90
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
        """)
        
        params_61_90 = {
            **params,
            "start_61": today + timedelta(days=61),
            "end_90": today + timedelta(days=90)
        }
        leads_61_90_days = session.execute(query_61_90, params_61_90).scalar() or 0
        print(f"✅ 61-90 Days: {leads_61_90_days}")
        
        # 91-180 Days
        query_91_180 = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND od.end_date IS NOT NULL
            AND od.end_date BETWEEN :start_91 AND :end_180
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
        """)
        
        params_91_180 = {
            **params,
            "start_91": today + timedelta(days=91),
            "end_180": today + timedelta(days=180)
        }
        leads_91_180_days = session.execute(query_91_180, params_91_180).scalar() or 0
        print(f"✅ 91-180 Days: {leads_91_180_days}")
        
        # Not Due (365+ days)
        query_not_due = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND od.end_date IS NOT NULL
            AND od.end_date > :future_365
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
        """)
        
        params_not_due = {**params, "future_365": today + timedelta(days=365)}
        not_due_leads = session.execute(query_not_due, params_not_due).scalar() or 0
        print(f"✅ Not Due: {not_due_leads}")
        
        # Total Annual Usage
        query_usage = text(f"""
            SELECT COALESCE(SUM(od.annual_usage), 0)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
        """)
        total_annual_usage = session.execute(query_usage, params).scalar() or 0
        print(f"✅ Total Usage: {total_annual_usage}")
         
        # Total leads
        query_total = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
        """)
        total_leads = session.execute(query_total, params).scalar() or 0
 
        # Active leads
        query_active = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
        """)
        active_leads = session.execute(query_active, params).scalar() or 0
 
        # Converted leads
        query_converted = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('converted', 'won', 'signed', 'renewed', 'closed won')
        """)
        converted_leads = session.execute(query_converted, params).scalar() or 0
 
        # New/Uncontacted
        query_new = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('new', 'not contacted', 'unassigned', 'open', 'lead')
        """)
        new_leads = session.execute(query_new, params).scalar() or 0
 
        # In Progress
        query_progress = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('contacted', 'callback', 'in progress', 'follow up', 'qualified', 'proposal sent', 'negotiation', 'not answered', 'email only')
        """)
        in_progress = session.execute(query_progress, params).scalar() or 0
 
        # Lost leads
        query_lost = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            AND LOWER(COALESCE(sm.stage_name, '')) IN ('lost', 'rejected', 'not interested', 'closed lost', 'lost cot', 'invalid number')
        """)
        lost_leads = session.execute(query_lost, params).scalar() or 0
 
        # Total value
        query_value = text(f"""
            SELECT COALESCE(SUM(od.opportunity_value), 0)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
        """)
        total_value = session.execute(query_value, params).scalar() or 0
 
        # Conversion rate
        conversion_rate = round((converted_leads / total_leads * 100), 1) if total_leads > 0 else 0.0
 
        # Recent leads (30 days)
        query_recent = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
            AND od.created_at >= CURRENT_DATE - INTERVAL '30 days'
        """)
        recent_leads = session.execute(query_recent, params).scalar() or 0
 
        # Stage breakdown
        query_stages = text(f"""
            SELECT 
                COALESCE(sm.stage_name, 'Unknown') as stage_name, 
                COUNT(DISTINCT od.opportunity_id) as count
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            {base_conditions}
            GROUP BY sm.stage_name
            ORDER BY count DESC
        """)
        stage_results = session.execute(query_stages, params).fetchall()
        stages = {stage: count for stage, count in stage_results}
 
        # Allocated vs Unallocated
        query_allocated = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
            AND od.is_allocated = true
        """)
        allocated_leads = session.execute(query_allocated, params).scalar() or 0
 
        query_unallocated = text(f"""
            SELECT COUNT(DISTINCT od.opportunity_id)
            FROM "StreemLyne_MT"."Opportunity_Details" od
            {base_conditions}
            AND (od.is_allocated = false OR od.is_allocated IS NULL)
        """)
        unallocated_leads = session.execute(query_unallocated, params).scalar() or 0
 
        result = {
            'total_leads': total_leads,
            'active_leads': active_leads,
            'converted_leads': converted_leads,
            'new_leads': new_leads,
            'in_progress': in_progress,
            'lost_leads': lost_leads,
            'conversion_rate': conversion_rate,
            'total_value': float(total_value),
            'recent_leads_30d': recent_leads,
            'allocated_leads': allocated_leads,
            'unallocated_leads': unallocated_leads,
            'stage_breakdown': stages,
            'leads_30_60_days': leads_30_60_days,
            'leads_61_90_days': leads_61_90_days,
            'leads_91_180_days': leads_91_180_days,
            'not_due_leads': not_due_leads,
            'total_annual_usage': float(total_annual_usage),
        }
        
        print(f"\n✅ Returning stats: {result}\n")
        return jsonify(result), 200
 
    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        print(f"\n❌ ERROR: {str(e)}\n")
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

@renewals_bp.route('/api/crm/leads/supplier-breakdown', methods=['GET'])
@token_required
def get_leads_supplier_breakdown():
    """
    ✅ FIXED: Proper tenant_id casting for leads supplier breakdown
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        employee_id = request.args.get('employee_id', type=int)
        
        # ✅ Build query with proper CAST and string conversion
        query = """
            SELECT 
                COALESCE(sm.supplier_company_name, 'Unknown') as supplier_name,
                COUNT(DISTINCT od.opportunity_id) as lead_count,
                COALESCE(SUM(od.opportunity_value), 0) as total_value
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm 
                ON od.supplier_id = sm.supplier_id
            WHERE od.tenant_id = CAST(:tenant_id AS VARCHAR)
            {employee_filter}
            GROUP BY sm.supplier_company_name
            ORDER BY total_value DESC
        """
 
        params = {"tenant_id": str(tenant_id)}
        
        if employee_id:
            query = query.format(employee_filter="AND od.opportunity_owner_employee_id = :employee_id")
            params["employee_id"] = employee_id
        else:
            query = query.format(employee_filter="")
 
        results = session.execute(text(query), params).fetchall()
 
        supplier_breakdown = [
            {
                'supplier_name': r.supplier_name or 'Unknown',
                'lead_count': r.lead_count or 0,
                'total_value': float(r.total_value or 0)
            }
            for r in results
        ]
 
        return jsonify(supplier_breakdown), 200
 
    except Exception as e:
        current_app.logger.error(f"Error getting leads supplier breakdown: {e}")
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

@renewals_bp.route('/api/crm/leads/period-breakdown', methods=['GET'])
@token_required
def get_leads_period_breakdown():
    """
    Get leads grouped by time period until end_date
    Uses end_date column from Opportunity_Details
    """
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        period = request.args.get('period')
        employee_id = request.args.get('employee_id', type=int)
        today = datetime.utcnow().date()

        # Define date ranges based on period
        if period == 'not-due':
            start_date = today + timedelta(days=366)
            end_date = today + timedelta(days=365 * 10)
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
                srv.service_title as service_name,
                od.end_date,
                (od.end_date - CURRENT_DATE) as days_until_due
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od.opportunity_owner_employee_id = em.employee_id
            LEFT JOIN "StreemLyne_MT"."Services_Master" srv ON od.service_id = srv.service_id
            WHERE od.tenant_id = :tenant_id
            AND od.end_date BETWEEN :start_date AND :end_date
            AND LOWER(COALESCE(sm.stage_name, '')) NOT IN ('lost', 'converted', 'won', 'rejected', 'not interested', 'closed lost')
            {employee_filter}
            ORDER BY od.end_date ASC
        """.format(
            employee_filter="AND od.opportunity_owner_employee_id = :employee_id" if employee_id else ""
        ))

        params = {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }
        if employee_id:
            params["employee_id"] = employee_id

        results = session.execute(query, params).fetchall()

        leads = []
        total_usage = 0
        for r in results:
            usage = float(r.annual_usage or 0)
            total_usage += usage
            
            leads.append({
                'opportunity_id': r.opportunity_id,
                'business_name': r.business_name or 'Unknown',
                'contact_person': r.contact_person or 'N/A',
                'tel_number': r.tel_number or 'N/A',
                'email': r.email or 'N/A',
                'stage_name': r.stage_name or 'Unknown',
                'opportunity_value': float(r.opportunity_value or 0),
                'assigned_to_name': r.assigned_to_name or 'Unassigned',
                'assigned_to_id': r.assigned_to_id,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'annual_usage': usage,
                'service_name': r.service_name or 'Energy',
                'end_date': r.end_date.isoformat() if r.end_date else None,
                'days_until_due': r.days_until_due
            })

        return jsonify({
            'period': period,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'total_count': len(leads),
            'total_annual_usage': round(total_usage, 2),
            'leads': leads
        }), 200

    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()