# -*- coding: utf-8 -*-
"""
Calendar Routes
API endpoints for contract calendar view
"""
from flask import Blueprint, g, jsonify
from backend.routes.auth_helpers import token_required
from backend.routes.crm_routes import tenant_from_jwt
from backend.crm.repositories.tenant_repository import TenantRepository

calendar_bp = Blueprint('calendar', __name__, url_prefix='/api/calendar')


@calendar_bp.route('/renewals', methods=['GET'])
@token_required
@tenant_from_jwt
def get_renewals_calendar():
    """Get all renewals for calendar view - shows contract end dates AND callback dates"""
    try:
        tenant_id = g.tenant_id
        repo = TenantRepository()
        
        import logging
        logging.info(f"🔍 Fetching renewals for tenant_id: {tenant_id}")
        
        # ✅ Query contract end dates AND callback dates
        query = '''
            SELECT 
                cm.client_id,
                COALESCE(NULLIF(TRIM(cm.client_company_name), ''), cm.client_contact_name, 'Unknown') as name,
                ecm.mpan_number as mpan,
                sm.supplier_company_name as supplier,
                ecm.contract_end_date,
                ecm.contract_start_date,
                (ecm.contract_end_date - INTERVAL '365 days')::date as reminder_date,
                cm.address,
                cm.post_code as postcode,
                cm.client_contact_name as contact,
                cm.client_email as email,
                cm.client_phone as phone,
                ecm.terms_of_sale as contract_notes,
                srv.service_title,
                ecm.unit_rate as rates,
                ci.reminder_date as callback_date,
                ci.notes as callback_notes,
                od."Misc_Col1" as status
            FROM "StreemLyne_MT"."Client_Master" cm
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Services_Master" srv ON ecm.service_id = srv.service_id
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od ON cm.client_id = od.client_id
            LEFT JOIN "StreemLyne_MT"."Client_Interactions" ci ON cm.client_id = ci.client_id
            WHERE cm.tenant_id = %s
            AND (ecm.contract_end_date IS NOT NULL OR ci.reminder_date IS NOT NULL)
            ORDER BY cm.client_id
        '''
        
        logging.info(f"📊 Executing query...")
        renewals = repo.db.execute_query(query, (tenant_id,))
        logging.info(f"✅ Found {len(renewals)} renewals")
        
        if renewals:
            logging.info(f"📝 First renewal: {renewals[0]}")
        
        # Transform to calendar events - create separate events for contract end and callbacks
        events = []
        for renewal in renewals:
            business_name = renewal.get('name') or renewal.get('contact') or 'Unknown'
            
            # ✅ Add contract end date event
            if renewal.get('contract_end_date'):
                event = {
                    'id': f"contract-{renewal['client_id']}",
                    'customer_id': renewal['client_id'],
                    'type': 'contract_end',
                    'title': f"{business_name} - Contract End",
                    'name': business_name,
                    'mpan': renewal.get('mpan'),
                    'supplier': renewal.get('supplier'),
                    'contract_start_date': str(renewal['contract_start_date']) if renewal.get('contract_start_date') else None,
                    'contract_end_date': str(renewal['contract_end_date']) if renewal.get('contract_end_date') else None,
                    'reminder_date': str(renewal['reminder_date']) if renewal.get('reminder_date') else None,
                    'address': renewal.get('address'),
                    'postcode': renewal.get('postcode'),
                    'contact': renewal.get('contact'),
                    'email': renewal.get('email'),
                    'phone': renewal.get('phone'),
                    'service_title': renewal.get('service_title'),
                    'rates': str(renewal.get('rates')) if renewal.get('rates') else None,
                    'notes': renewal.get('contract_notes'),
                    'display_date': str(renewal['contract_end_date']),
                    'display_type': 'Contract End',
                    'status': renewal.get('status') or 'Active',
                }
                events.append(event)
                logging.info(f"📅 Added contract end event for {event['name']} on {event['display_date']}")
            
            # ✅ Add callback date event
            if renewal.get('callback_date'):
                event = {
                    'id': f"callback-{renewal['client_id']}",
                    'customer_id': renewal['client_id'],
                    'type': 'callback',
                    'title': f"{business_name} - Callback",
                    'name': business_name,
                    'mpan': renewal.get('mpan'),
                    'supplier': renewal.get('supplier'),
                    'contract_start_date': str(renewal['contract_start_date']) if renewal.get('contract_start_date') else None,
                    'contract_end_date': str(renewal['contract_end_date']) if renewal.get('contract_end_date') else None,
                    'reminder_date': str(renewal['callback_date']) if renewal.get('callback_date') else None,
                    'address': renewal.get('address'),
                    'postcode': renewal.get('postcode'),
                    'contact': renewal.get('contact'),
                    'email': renewal.get('email'),
                    'phone': renewal.get('phone'),
                    'service_title': renewal.get('service_title'),
                    'rates': str(renewal.get('rates')) if renewal.get('rates') else None,
                    'notes': renewal.get('callback_notes'),
                    'display_date': str(renewal['callback_date']),
                    'display_type': 'Callback',
                    'status': renewal.get('status') or 'Active',
                }
                events.append(event)
                logging.info(f"📞 Added callback event for {event['name']} on {event['display_date']}")
        
        logging.info(f"✅ Returning {len(events)} events")
        
        return jsonify({
            'success': True,
            'data': events,
            'count': len(events)
        }), 200
        
    except Exception as e:
        import logging
        logging.exception("Error fetching renewals calendar")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch calendar',
            'message': str(e)
        }), 500

@calendar_bp.route('/contracts', methods=['GET'])
@token_required
@tenant_from_jwt
def get_contract_schedule():
    """Get all energy contracts for calendar view"""
    try:
        tenant_id = g.tenant_id
        repo = TenantRepository()
        
        # ✅ Query with correct schema (StreemLyne_MT) and exact table names from your schema
        query = '''
            SELECT 
                cm.client_id,
                COALESCE(NULLIF(TRIM(cm.client_company_name), ''), cm.client_contact_name, 'Unknown') as name,
                ecm.mpan_number as mpan,
                sm.supplier_company_name as supplier,
                ecm.contract_end_date,
                ecm.contract_start_date,
                (ecm.contract_end_date - INTERVAL '365 days')::date as reminder_date,
                cm.address,
                cm.post_code as postcode,
                cm.client_contact_name as contact,
                cm.client_email as email,
                cm.client_phone as phone,
                ecm.terms_of_sale as contract_notes,
                srv.service_title,
                ecm.unit_rate as rates,
                ci.reminder_date as callback_date,
                ci.notes as callback_notes,
                od."Misc_Col1" as status
            FROM "StreemLyne_MT"."Client_Master" cm
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Services_Master" srv ON ecm.service_id = srv.service_id
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od ON cm.client_id = od.client_id
            LEFT JOIN "StreemLyne_MT"."Client_Interactions" ci ON cm.client_id = ci.client_id
            WHERE cm.tenant_id = %s
            AND (ecm.contract_end_date IS NOT NULL OR ci.reminder_date IS NOT NULL)
            ORDER BY cm.client_id
        '''
        
        contracts = repo.db.execute_query(query, (tenant_id,))
        
        # Transform to calendar events
        events = []
        for contract in contracts:
            if not contract.get('client_name'):
                continue
                
            events.append({
                'id': str(contract['id']),
                'type': 'contract',
                'title': f"{contract['client_name']} - {contract.get('supplier_name', 'Unknown')}",
                'client_id': contract.get('client_id'),
                'client_name': contract.get('client_name'),
                'client_contact': contract.get('client_contact_name'),
                'client_phone': contract.get('client_phone'),
                'client_email': contract.get('client_email'),
                'start_date': str(contract['start_date']) if contract.get('start_date') else None,
                'end_date': str(contract['end_date']) if contract.get('end_date') else None,
                'employee_id': contract.get('employee_id'),
                'assigned_to': contract.get('assigned_to'),
                'supplier_name': contract.get('supplier_name'),
                'supplier_id': contract.get('supplier_id'),
                'service_title': contract.get('service_title'),
                'mpan_number': contract.get('mpan_number'),
                'unit_rate': float(contract['unit_rate']) if contract.get('unit_rate') else None,
                'currency_code': contract.get('currency_code'),
                'terms_of_sale': contract.get('terms_of_sale'),
                'notes': contract.get('terms_of_sale'),
                'status': 'Active',
                'created_at': str(contract['created_at']) if contract.get('created_at') else None,
            })
        
        return jsonify({
            'success': True,
            'data': events,
            'count': len(events)
        }), 200
        
    except Exception as e:
        import logging
        logging.exception("Error fetching contract calendar")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch calendar',
            'message': str(e)
        }), 500


@calendar_bp.route('/clients', methods=['GET'])
@token_required
@tenant_from_jwt
def get_clients():
    """Get all clients for dropdown"""
    try:
        tenant_id = g.tenant_id
        repo = TenantRepository()
        
        query = '''
            SELECT 
                client_id as id,
                client_company_name as name,
                client_contact_name,
                client_phone,
                client_email,
                address,
                post_code
            FROM "StreemLyne_MT"."Client_Master"
            WHERE tenant_id = %s
            ORDER BY client_company_name
        '''
        
        clients = repo.db.execute_query(query, (tenant_id,))
        
        return jsonify({
            'success': True,
            'data': clients
        }), 200
        
    except Exception as e:
        import logging
        logging.exception("Error fetching clients")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch clients',
            'message': str(e)
        }), 500


@calendar_bp.route('/employees', methods=['GET'])
@token_required
@tenant_from_jwt
def get_employees():
    """Get all employees for assignment"""
    try:
        tenant_id = g.tenant_id
        repo = TenantRepository()
        
        query = '''
            SELECT 
                employee_id as id,
                employee_name as full_name,
                email,
                phone,
                dm.designation_description as role
            FROM "StreemLyne_MT"."Employee_Master" em
            LEFT JOIN "StreemLyne_MT"."Designation_Master" dm ON em.employee_designation_id = dm.designation_id
            WHERE em.tenant_id = %s
            ORDER BY employee_name
        '''
        
        employees = repo.db.execute_query(query, (tenant_id,))
        
        return jsonify({
            'success': True,
            'data': employees
        }), 200
        
    except Exception as e:
        import logging
        logging.exception("Error fetching employees")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch employees',
            'message': str(e)
        }), 500