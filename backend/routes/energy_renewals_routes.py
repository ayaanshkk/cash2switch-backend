# backend/routes/energy_renewals_routes.py

from flask import Blueprint, jsonify, request, current_app
from datetime import datetime, timedelta
from sqlalchemy import text, func, case, and_
from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Opportunity_Details, Supplier_Master, Employee_Master,
    Client_Interactions
)
from ..db import SessionLocal
from .auth_helpers import token_required, get_tenant_id_from_user

renewals_bp = Blueprint("renewals", __name__)

@renewals_bp.route("/energy-renewals", methods=["GET"])
@token_required
def get_renewals():
    """
    Get all clients with energy contracts
    - Normal mode: Expiring in next 90 days
    - use_current_user mode: ALL contracts (no date filter)
    """
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        db = SessionLocal()
        
        # Get current date and 90 days from now
        today = datetime.now().date()
        ninety_days_later = today + timedelta(days=90)
        
        # Check if we should use current user
        use_current_user = request.args.get('use_current_user', 'false').lower() == 'true'
        
        if use_current_user:
            # Use current logged-in user's employee_id from JWT
            current_user = request.current_user
            
            if hasattr(current_user, 'id'):
                employee_id = current_user.id
            elif hasattr(current_user, 'employee_id'):
                employee_id = current_user.employee_id
            else:
                employee_id = None
            
            print(f"🔍 Using current user's employee_id: {employee_id}")
        else:
            # Use optional employee_id parameter (original behavior)
            employee_id = request.args.get('employee_id')
            print(f"🔍 Using employee_id parameter: {employee_id}")
        
        employee_filter = "AND od.opportunity_owner_employee_id = :employee_id" if employee_id else ""
        
        # ✅ CRITICAL FIX: Only filter by date if NOT using current user
        if use_current_user:
            date_filter = "AND ecm.contract_end_date IS NOT NULL"  # No 90-day limit
        else:
            date_filter = "AND ecm.contract_end_date BETWEEN :today AND :ninety_days_later"
        
        # Query using your actual schema structure with proper joins
        query = text(f"""
            SELECT 
                cm.client_id,
                cm.client_contact_name as contact_person,
                cm.client_company_name as business_name,
                cm.client_phone as phone,
                cm.client_email as email,
                sm.supplier_company_name as supplier_name,
                ecm.contract_end_date as end_date,
                pd."Misc_Col2" as annual_usage,
                (ecm.contract_end_date - CURRENT_DATE) as days_until_expiry,
                od."Misc_Col1" as status,
                em.employee_name as assigned_to_name,
                ecm.unit_rate,
                ecm.mpan_number
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od ON cm.client_id = od.client_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od.opportunity_owner_employee_id = em.employee_id
            WHERE cm.tenant_id = :tenant_id
            {date_filter}
            {employee_filter}
            ORDER BY ecm.contract_end_date ASC
        """)
        
        # Pass parameters
        params = {"tenant_id": tenant_id}
        
        # ✅ Only add date params if not using current user
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
                "email": row.email or "",
                "supplier_name": row.supplier_name or "Unknown",
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "annual_usage": float(row.annual_usage) if row.annual_usage else 0,
                "days_until_expiry": row.days_until_expiry,
                "status": row.status or "Pending",
                "assigned_to_name": row.assigned_to_name or "Unassigned",
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
    """Get renewal statistics - FILTERED BY EMPLOYEE"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # ✅ Optional employee filter for salespeople
        employee_id = request.args.get('employee_id', type=int)
        
        # ✅ DEBUG LOGGING
        print(f"\n{'='*60}")
        print(f"📊 STATS ENDPOINT CALLED")
        print(f"{'='*60}")
        print(f"   Tenant ID: {tenant_id}")
        print(f"   Employee Filter: {employee_id if employee_id else 'NONE (ADMIN VIEW)'}")
        print(f"   Filter Active: {employee_id is not None}")
        print(f"{'='*60}\n")
        
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        
        # Define date ranges
        days_30 = today + timedelta(days=30)
        days_60 = today + timedelta(days=60)
        days_90 = today + timedelta(days=90)
        days_180 = today + timedelta(days=180)
        
        # ✅ CRITICAL FIX: Build base query BEFORE filtering
        base_query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).join(
            Opportunity_Details, Client_Master.client_id == Opportunity_Details.client_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None)
        )
        
        # ✅ CRITICAL FIX: Apply employee filter BEFORE calling .all()
        if employee_id:
            print(f"🔍 Applying filter: opportunity_owner_employee_id = {employee_id}")
            base_query = base_query.filter(
                Opportunity_Details.opportunity_owner_employee_id == employee_id
            )
        else:
            print(f"🌍 NO FILTER - Returning ALL company data")
        
        # ✅ NOW get all results AFTER filter is applied
        all_results = base_query.all()
        
        print(f"📦 Query returned {len(all_results)} total records")
        
        # ✅ Calculate statistics from filtered records
        total_renewals_30_60_days = 0
        total_renewals_61_90_days = 0
        total_renewals_90_plus_days = 0
        expired_contracts = 0
        total_revenue_at_risk = 0
        total_aq = 0
        contacted_count = 0
        not_contacted_count = 0
        renewed_count = 0
        lost_count = 0
        
        for client, project, contract, opportunity in all_results:
            end_date = contract.contract_end_date
            
            # ✅ Total AQ - Add annual usage from Project_Details.Misc_Col2
            if project.Misc_Col2:
                total_aq += project.Misc_Col2
            
            # Skip if no end date
            if not end_date:
                continue
            
            # Calculate days until renewal
            days_until_renewal = (end_date - today).days
            
            # ✅ Count by period (including expired)
            if days_until_renewal < 0:
                expired_contracts += 1
            elif 30 <= days_until_renewal <= 60:
                total_renewals_30_60_days += 1
            elif 61 <= days_until_renewal <= 90:
                total_renewals_61_90_days += 1
            elif 91 <= days_until_renewal <= 180:
                total_renewals_90_plus_days += 1
            
            # ✅ Revenue at risk calculation
            if contract.unit_rate and project.Misc_Col2:
                annual_cost = (contract.unit_rate * project.Misc_Col2) / 100
                total_revenue_at_risk += annual_cost
            
            # ✅ Count by status
            status = opportunity.Misc_Col1
            if status:
                status_lower = status.lower()
                if status_lower == 'contacted' or status_lower == 'called':
                    contacted_count += 1
                elif status_lower == 'not_answered' or status_lower == 'not contacted':
                    not_contacted_count += 1
                elif status_lower in ['priced', 'renewed', 'already renewed', 'end date changed']:
                    renewed_count += 1
                elif status_lower == 'lost':
                    lost_count += 1
                else:
                    not_contacted_count += 1
            else:
                not_contacted_count += 1
        
        result = {
            'total_renewals_30_60_days': total_renewals_30_60_days,
            'total_renewals_61_90_days': total_renewals_61_90_days,
            'total_renewals_90_plus_days': total_renewals_90_plus_days,
            'expired_contracts': expired_contracts,
            'total_revenue_at_risk': total_revenue_at_risk,
            'total_aq': total_aq,
            'contacted_count': contacted_count,
            'not_contacted_count': not_contacted_count,
            'renewed_count': renewed_count,
            'lost_count': lost_count
        }
        
        print(f"\n✅ RETURNING STATS:")
        print(f"   30-60 days: {total_renewals_30_60_days}")
        print(f"   61-90 days: {total_renewals_61_90_days}")
        print(f"   91-180 days: {total_renewals_90_plus_days}")
        print(f"   Expired: {expired_contracts}")
        print(f"   Total AQ: {total_aq}")
        print(f"   Revenue: £{total_revenue_at_risk:,.2f}")
        print(f"{'='*60}\n")
        
        return jsonify(result)
        
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
    """Get supplier breakdown - FILTERED BY EMPLOYEE"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # ✅ Optional employee filter
        employee_id = request.args.get('employee_id', type=int)
        
        # ✅ Query suppliers with aggregated data
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
        ).join(
            Opportunity_Details,
            Client_Master.client_id == Opportunity_Details.client_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None)
        )
        
        # ✅ CRITICAL FIX: Apply employee filter
        if employee_id:
            query = query.filter(
                Opportunity_Details.opportunity_owner_employee_id == employee_id
            )
        
        # ✅ Group by supplier and order by total value
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
        
        print(f"✅ Supplier breakdown: {len(supplier_breakdown)} suppliers (employee_id={employee_id})")
        
        return jsonify(supplier_breakdown)
        
    except Exception as e:
        current_app.logger.error(f"Error getting supplier breakdown: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/period-breakdown', methods=['GET'])
@token_required
def get_period_breakdown():
    """
    Get detailed breakdown of renewals by period
    ✅ FILTERED BY EMPLOYEE for salespeople
    """
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # Required period filter
        period = request.args.get('period')  # '30-60', '61-90', '91-180', 'expired'
        
        # ✅ Optional employee filter
        employee_id = request.args.get('employee_id', type=int)
        
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        
        # ✅ Calculate date range based on period
        if period == 'expired':
            start_date = today - timedelta(days=365 * 5)
            end_date = today - timedelta(days=1)
        elif period == '30-60':
            start_days = 30
            end_days = 60
            start_date = today + timedelta(days=start_days)
            end_date = today + timedelta(days=end_days)
        elif period == '61-90':
            start_days = 61
            end_days = 90
            start_date = today + timedelta(days=start_days)
            end_date = today + timedelta(days=end_days)
        elif period == '91-180':
            start_days = 91
            end_days = 180
            start_date = today + timedelta(days=start_days)
            end_date = today + timedelta(days=end_days)
        else:
            return jsonify({'error': 'Invalid period parameter'}), 400
        
        # ✅ Query for detailed breakdown
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
            Opportunity_Details.Misc_Col1.label('status')
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).join(
            Opportunity_Details,
            Client_Master.client_id == Opportunity_Details.client_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.between(start_date, end_date)
        )
        
        # ✅ CRITICAL FIX: Apply employee filter for salespeople
        if employee_id:
            print(f"🔍 Period breakdown filtered by employee_id={employee_id}")
            query = query.filter(
                Opportunity_Details.opportunity_owner_employee_id == employee_id
            )
        
        # Order by end date
        results = query.order_by(Energy_Contract_Master.contract_end_date).all()
        
        breakdown = []
        for r in results:
            # Calculate revenue
            revenue = 0
            if r.unit_rate and r.annual_usage:
                revenue = (r.unit_rate * r.annual_usage) / 100
            
            # Calculate days until expiry
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
        
        print(f"✅ Period breakdown: {len(breakdown)} renewals (employee_id={employee_id})")
        
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
        print(f"Error getting period breakdown: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/salesperson-performance', methods=['GET'])
@token_required
def get_salesperson_performance():
    """Get detailed performance metrics - FILTERED BY EMPLOYEE"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # Optional filters
        employee_id = request.args.get('employee_id', type=int)
        period = request.args.get('period', 'month')  # 'week' or 'month'
        
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        
        # Calculate date range
        if period == 'week':
            start_date = today - timedelta(days=7)
            period_label = "This Week"
        else:  # month
            start_date = today - timedelta(days=30)
            period_label = "This Month"
        
        # Query for salesperson performance
        query = session.query(
            Employee_Master.employee_id,
            Employee_Master.employee_name,
            Client_Master.client_id,
            Client_Master.client_company_name,
            Client_Master.client_contact_name,
            Client_Master.client_phone,
            Client_Interactions.contact_date,
            Client_Interactions.notes,
            Opportunity_Details.Misc_Col1.label('status'),
            Energy_Contract_Master.contract_end_date,
            Project_Details.Misc_Col2.label('annual_usage'),
            Energy_Contract_Master.unit_rate,
            Supplier_Master.supplier_company_name
        ).join(
            Opportunity_Details,
            Employee_Master.employee_id == Opportunity_Details.opportunity_owner_employee_id
        ).join(
            Client_Master,
            Opportunity_Details.client_id == Client_Master.client_id
        ).join(
            Client_Interactions,
            and_(
                Client_Master.client_id == Client_Interactions.client_id,
                Client_Interactions.contact_date >= start_date
            )
        ).outerjoin(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).filter(
            Employee_Master.tenant_id == tenant_id
        )
        
        # ✅ CRITICAL FIX: Apply employee filter
        if employee_id:
            query = query.filter(Employee_Master.employee_id == employee_id)
        
        # Order by employee and contact date
        results = query.order_by(
            Employee_Master.employee_name,
            Client_Interactions.contact_date.desc()
        ).all()
        
        # Group results by employee
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
            
            # Calculate revenue
            revenue = 0
            if r.unit_rate and r.annual_usage:
                revenue = (r.unit_rate * r.annual_usage) / 100
            
            # Check if this customer is already in the list
            customer_exists = any(
                c['client_id'] == r.client_id 
                for c in performance_by_employee[emp_id]['customers_contacted']
            )
            
            if not customer_exists:
                performance_by_employee[emp_id]['total_contacts'] += 1
                performance_by_employee[emp_id]['total_value_touched'] += revenue
                
                # Check if converted
                if r.status and (r.status.lower() in ['priced', 'renewed']):
                    performance_by_employee[emp_id]['converted_count'] += 1
                
                # Add customer details
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
        
        # Calculate conversion rates
        performance_data = []
        for emp_data in performance_by_employee.values():
            conversion_rate = round(
                (emp_data['converted_count'] / emp_data['total_contacts'] * 100) 
                if emp_data['total_contacts'] > 0 else 0, 
                1
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
        
        # Sort by total value touched
        performance_data.sort(key=lambda x: x['total_value_touched'], reverse=True)
        
        print(f"✅ Performance data: {len(performance_data)} employees (employee_id={employee_id})")
        
        return jsonify({
            'period': period,
            'period_label': period_label,
            'start_date': start_date.isoformat(),
            'end_date': today.isoformat(),
            'performance': performance_data
        })
        
    except Exception as e:
        session.rollback()
        print(f"Error getting salesperson performance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@renewals_bp.route('/energy-renewals/aq-breakdown', methods=['GET'])
@token_required
def get_aq_breakdown():
    """Get AQ breakdown - FILTERED BY EMPLOYEE for salespeople"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # ✅ Optional employee filter
        employee_id = request.args.get('employee_id', type=int)
        
        print(f"\n{'='*60}")
        print(f"📊 AQ BREAKDOWN")
        print(f"{'='*60}")
        print(f"   Tenant ID: {tenant_id}")
        print(f"   Employee Filter: {employee_id if employee_id else 'NONE (ALL SALESPEOPLE)'}")
        print(f"{'='*60}\n")
        
        # Query AQ grouped by salesperson
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
            Opportunity_Details,
            Employee_Master.employee_id == Opportunity_Details.opportunity_owner_employee_id
        ).join(
            Client_Master,
            Opportunity_Details.client_id == Client_Master.client_id
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None),
            Project_Details.Misc_Col2.isnot(None),
            Employee_Master.tenant_id == tenant_id
        )
        
        # ✅ CRITICAL FIX: Apply employee filter for salespeople
        if employee_id:
            query = query.filter(Employee_Master.employee_id == employee_id)
        
        query = query.group_by(
            Employee_Master.employee_id,
            Employee_Master.employee_name
        ).order_by(
            func.sum(Project_Details.Misc_Col2).desc()
        )
        
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
        
        print(f"✅ AQ BREAKDOWN RESULTS:")
        print(f"   Employees: {len(breakdown)}")
        print(f"   Total AQ: {total_aq:,.0f} kWh")
        print(f"   Total Revenue: £{total_revenue:,.2f}")
        print(f"{'='*60}\n")
        
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
    """Test endpoint - no auth required"""
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
        
        sample_query = text("""
            SELECT 
                cm.client_company_name,
                ecm.contract_end_date,
                sm.supplier_company_name,
                (ecm.contract_end_date - CURRENT_DATE) as days_until_expiry
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            WHERE ecm.contract_end_date IS NOT NULL
            AND ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days'
            ORDER BY ecm.contract_end_date
            LIMIT 5
        """)
        
        sample_result = db.execute(sample_query)
        sample_data = []
        for row in sample_result:
            sample_data.append({
                "company": row.client_company_name,
                "end_date": row.contract_end_date.isoformat() if row.contract_end_date else None,
                "supplier": row.supplier_company_name,
                "days_until_expiry": row.days_until_expiry
            })
        
        response = {
            "status": "success",
            "schema": "StreemLyne_MT",
            "total_clients": result.total_clients,
            "total_contracts": result.total_contracts,
            "contracts_with_end_date": result.contracts_with_end_date,
            "renewals_due_90_days": result.renewals_due_90_days,
            "renewals_due_30_days": result.renewals_due_30_days,
            "sample_renewals": sample_data,
            "message": "Database connection successful! Schema verified."
        }
        
        print(f"✅ Test endpoint result: {response}")
        db.close()
        return jsonify(response), 200
        
    except Exception as e:
        print(f"❌ Test endpoint error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "error": str(e),
            "message": "Database connection failed. Check schema structure."
        }), 500

@renewals_bp.route('/energy-renewals/performance', methods=['GET'])
@token_required
def get_renewal_performance():
    """
    Get renewal performance metrics
    
    Two modes:
    1. Dashboard (optional employee_id): Can show ALL data for admin or filtered for salesperson
    2. Renewals page (no employee_id): Uses current logged-in user automatically
    
    Query params:
    - employee_id (optional): If provided, filter by this employee. If not provided, return ALL.
    - use_current_user (optional): If 'true', ignore employee_id and use current user from JWT
    """
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # ✅ Check if we should use current user (for renewals page)
        use_current_user = request.args.get('use_current_user', 'false').lower() == 'true'
        
        if use_current_user:
            # ✅ RENEWALS PAGE MODE: Always use current logged-in user
            current_user = request.current_user
            
            # Extract employee_id from the user object
            if hasattr(current_user, 'id'):
                employee_id = current_user.id
            elif hasattr(current_user, 'employee_id'):
                employee_id = current_user.employee_id
            else:
                return jsonify({'error': 'User employee_id not found'}), 400
            
            print(f"\n{'='*60}")
            print(f"📊 PERFORMANCE (RENEWALS PAGE - PERSONAL)")
            print(f"{'='*60}")
            print(f"   Mode: use_current_user=true")
            print(f"   Current User Employee ID: {employee_id}")
            print(f"   Showing: ONLY THIS USER'S PERFORMANCE")
            print(f"{'='*60}\n")
        else:
            # ✅ DASHBOARD MODE: Optional employee filter
            employee_id = request.args.get('employee_id', type=int)
            
            print(f"\n{'='*60}")
            print(f"📊 PERFORMANCE (DASHBOARD)")
            print(f"{'='*60}")
            print(f"   Mode: Dashboard (optional filter)")
            print(f"   Tenant ID: {tenant_id}")
            print(f"   Employee Filter: {employee_id if employee_id else 'NONE (ALL DATA)'}")
            print(f"   Showing: {'FILTERED DATA' if employee_id else 'ALL COMPANY DATA'}")
            print(f"{'='*60}\n")
        
        # ✅ Build base query
        base_query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).join(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).join(
            Opportunity_Details, Client_Master.client_id == Opportunity_Details.client_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.contract_end_date.isnot(None)
        )
        
        # ✅ Apply employee filter if provided (or if using current user)
        if employee_id:
            print(f"🔍 Filtering by employee_id={employee_id}")
            base_query = base_query.filter(
                Opportunity_Details.opportunity_owner_employee_id == employee_id
            )
        else:
            print(f"🌍 NO FILTER - Returning ALL company data")
        
        # ✅ Get all results
        all_results = base_query.all()
        
        print(f"📦 Query returned {len(all_results)} total records")
        
        # ✅ Calculate statistics
        renewed_count = 0
        contacted_count = 0
        not_contacted_count = 0
        lost_count = 0
        
        for client, project, contract, opportunity in all_results:
            status = opportunity.Misc_Col1
            
            if status:
                status_lower = status.lower()
                # ✅ FIX: Count 'Already Renewed' and 'End Date Changed' as renewed
                if status_lower in ['priced', 'renewed', 'already renewed', 'end date changed']:
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
        
        # ✅ Calculate success rate
        total_attempts = renewed_count + lost_count + contacted_count + not_contacted_count
        success_rate = round((renewed_count / total_attempts * 100), 1) if total_attempts > 0 else 0
        
        result = {
            'renewed_count': renewed_count,
            'contacted_count': contacted_count,
            'not_contacted_count': not_contacted_count,
            'lost_count': lost_count,
            'success_rate': success_rate,
            'total_customers': len(all_results),
            'employee_id': employee_id if employee_id else None  # Return for verification
        }
        
        print(f"\n✅ PERFORMANCE STATS:")
        print(f"   Employee ID: {employee_id if employee_id else 'ALL'}")
        print(f"   Renewed: {renewed_count}")
        print(f"   In Progress: {contacted_count}")
        print(f"   Not Contacted: {not_contacted_count}")
        print(f"   Lost: {lost_count}")
        print(f"   Success Rate: {success_rate}%")
        print(f"{'='*60}\n")
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error getting performance stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()