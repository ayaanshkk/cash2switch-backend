# -*- coding: utf-8 -*-
"""
Calendar Routes - FIXED VERSION with Customer Details Sync
Syncs with renewals page AND customer details page (callbacks)
"""
from flask import Blueprint, g, jsonify, request
from backend.routes.auth_helpers import token_required
from backend.routes.crm_routes import tenant_from_jwt
from backend.crm.repositories.tenant_repository import TenantRepository
from backend.crm.utils.role_helpers import is_crm_leads_admin_role
import logging

calendar_bp = Blueprint('calendar', __name__, url_prefix='/api/calendar')

# ✅ Add CORS support for all calendar routes
@calendar_bp.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Tenant-ID')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@calendar_bp.route('/renewals', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_renewals_calendar():
    """Get all renewals for calendar view - FIXED VERSION"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    from backend.db import SessionLocal
    from sqlalchemy import text
    
    session = SessionLocal()
    
    try:
        tenant_id = g.tenant_id
        
        logging.info(f"🔍 Fetching renewals for tenant_id: {tenant_id}")
        
        # Get current user and check if admin
        current_user = request.current_user
        from backend.routes.customer_routes import get_user_role_name
        
        user_role = get_user_role_name(current_user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
        logging.info(f"👤 User role: {user_role}, is_admin: {is_admin}")
        
        # Get employee_id filter from query params
        filter_employee_id = request.args.get('employee_id', type=int)
        
        # Build employee filter
        if is_admin and filter_employee_id:
            employee_filter = f"AND pd.assigned_employee_id = {filter_employee_id}"
            callback_employee_filter = f"AND pd2.assigned_employee_id = {filter_employee_id}"
        elif is_admin:
            employee_filter = ""
            callback_employee_filter = ""
        else:
            employee_filter = f"AND pd.assigned_employee_id = {current_user.employee_id}"
            callback_employee_filter = f"AND pd2.assigned_employee_id = {current_user.employee_id}"
        
        # PART 1: Get contract end dates
        contract_query = text(f'''
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
                pd.status as status,
                em.employee_name as assigned_to,
                'contract_end' as event_type
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Services_Master" srv ON ecm.service_id = srv.service_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON pd.assigned_employee_id = em.employee_id
            WHERE cm.tenant_id = CAST(:tenant_id AS VARCHAR)
            AND cm.client_company_name != '[IMPORTED LEADS]'
            AND ecm.contract_end_date IS NOT NULL
            AND (pd.status IS NULL OR LOWER(pd.status) NOT IN ('priced', 'lost'))
            {employee_filter}
        ''')
        
        # PART 2: Get callback dates
        callback_query = text(f'''
            SELECT 
                cm.client_id,
                COALESCE(NULLIF(TRIM(cm.client_company_name), ''), cm.client_contact_name, 'Unknown') as name,
                ecm.mpan_number as mpan,
                sm.supplier_company_name as supplier,
                ecm.contract_end_date,
                ecm.contract_start_date,
                ci.reminder_date as callback_date,
                ci.next_steps as interaction_status,
                cm.address,
                cm.post_code as postcode,
                cm.client_contact_name as contact,
                cm.client_email as email,
                cm.client_phone as phone,
                ci.notes as callback_notes,
                srv.service_title,
                ecm.unit_rate as rates,
                pd2.status as status,
                em2.employee_name as assigned_to,
                'callback' as event_type
            FROM "StreemLyne_MT"."Client_Interactions" ci
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON ci.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Services_Master" srv ON ecm.service_id = srv.service_id
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd2 ON cm.client_id = pd2.client_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em2 ON pd2.assigned_employee_id = em2.employee_id
            WHERE cm.tenant_id = CAST(:tenant_id AS VARCHAR)
            AND cm.client_company_name != '[IMPORTED LEADS]'
            AND ci.reminder_date IS NOT NULL
            AND ci.reminder_date >= CURRENT_DATE
            AND (pd2.status IS NULL OR LOWER(pd2.status) NOT IN ('priced', 'lost'))
            {callback_employee_filter}
            ORDER BY cm.client_id, ci.reminder_date DESC
        ''')
        
        logging.info(f"📊 Executing contract query")
        contract_result = session.execute(contract_query, {'tenant_id': tenant_id})
        contracts = [dict(row._mapping) for row in contract_result]
        logging.info(f"✅ Found {len(contracts)} contract renewals")
        
        logging.info(f"📊 Executing callback query")
        callback_result = session.execute(callback_query, {'tenant_id': tenant_id})
        callbacks = [dict(row._mapping) for row in callback_result]
        logging.info(f"✅ Found {len(callbacks)} callbacks")
        
        # Transform to calendar events
        events = []
        
        # Add contract end date events
        for renewal in contracts:
            business_name = renewal.get('name') or renewal.get('contact') or 'Unknown'
            
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
                'assigned_to': renewal.get('assigned_to'),
            }
            events.append(event)
        
        # Add callback events (deduplicate by client_id)
        seen_clients = set()
        for callback in callbacks:
            client_id = callback['client_id']
            
            if client_id in seen_clients:
                continue
            seen_clients.add(client_id)
            
            business_name = callback.get('name') or callback.get('contact') or 'Unknown'

            interaction_status = callback.get('interaction_status') or 'Callback'
                        
            event = {
                'id': f"callback-{client_id}",
                'customer_id': client_id,
                'type': 'callback',
                'title': f"{business_name} - {interaction_status}",
                'name': business_name,
                'mpan': callback.get('mpan'),
                'supplier': callback.get('supplier'),
                'contract_start_date': str(callback['contract_start_date']) if callback.get('contract_start_date') else None,
                'contract_end_date': str(callback['contract_end_date']) if callback.get('contract_end_date') else None,
                'reminder_date': str(callback['callback_date']) if callback.get('callback_date') else None,
                'address': callback.get('address'),
                'postcode': callback.get('postcode'),
                'contact': callback.get('contact'),
                'email': callback.get('email'),
                'phone': callback.get('phone'),
                'service_title': callback.get('service_title'),
                'rates': str(callback.get('rates')) if callback.get('rates') else None,
                'notes': callback.get('callback_notes'),
                'display_date': str(callback['callback_date']),
                'display_type': interaction_status,
                'status': callback.get('status') or 'Active',
                'assigned_to': callback.get('assigned_to'),
            }
            events.append(event)
        
        logging.info(f"✅ Returning {len(events)} total events ({len(contracts)} contracts + {len(seen_clients)} callbacks)")
        
        return jsonify({
            'success': True,
            'data': events,
            'count': len(events)
        }), 200
        
    except Exception as e:
        logging.exception("❌ Error fetching renewals calendar")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch calendar',
            'message': str(e)
        }), 500
    finally:
        session.close()

@calendar_bp.route('/leads', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_leads_calendar():
    """
    Get callback events from Leads (Opportunity_Details)
    ✅ FIXED: Shows all future callbacks, not just the latest one
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    from backend.db import SessionLocal
    from sqlalchemy import text

    session = SessionLocal()
    try:
        tenant_id = str(g.tenant_id)
        current_user = request.current_user

        service_param = (request.args.get('service') or 'utilities').strip().lower()
        service_id = 2 if service_param == 'water' else 1

        user_role = getattr(current_user, 'role', None)
        is_admin = is_crm_leads_admin_role(user_role)
        current_employee_id = getattr(current_user, 'employee_id', None)
        filter_employee_id = request.args.get('employee_id', type=int)

        if is_admin and filter_employee_id:
            employee_filter = "AND od.\"opportunity_owner_employee_id\" = :employee_id"
            query_params = {'tenant_id': tenant_id, 'service_id': service_id, 'employee_id': filter_employee_id}
        elif is_admin:
            employee_filter = ""
            query_params = {'tenant_id': tenant_id, 'service_id': service_id}
        elif current_employee_id:
            employee_filter = "AND od.\"opportunity_owner_employee_id\" = :employee_id"
            query_params = {'tenant_id': tenant_id, 'service_id': service_id, 'employee_id': current_employee_id}
        else:
            return jsonify({'success': True, 'data': [], 'count': 0}), 200

        logging.info(
            "📅 leads calendar: tenant=%s service=%s service_id=%s is_admin=%s employee_filter=%s",
            tenant_id, service_param, service_id, is_admin, query_params.get('employee_id')
        )

        # ✅ FIXED: Get ALL callbacks for each lead, not just the latest one
        query = text(f'''
            SELECT
                od."opportunity_id",
                od."tenant_lead_id",
                COALESCE(NULLIF(TRIM(od."business_name"), ''), NULLIF(TRIM(od."opportunity_title"), ''), 'Unknown') AS name,
                od."contact_person",
                od."tel_number",
                od."email",
                od."postcode",
                od."address",
                od."mpan_mpr",
                od."start_date",
                od."end_date",
                sm."stage_name",
                em."employee_name" AS assigned_to,
                srv."service_title",
                sup."supplier_company_name" AS supplier,
                ci."reminder_date" AS callback_date,
                ci."next_steps" AS callback_status,
                ci."notes" AS callback_notes,
                ci."interaction_id",
                ci."contact_date" AS called_date
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm
                ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm
                ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em
                ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Services_Master" srv
                ON od."service_id" = srv."service_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup
                ON od."supplier_id" = sup."supplier_id"
            INNER JOIN "StreemLyne_MT"."Client_Interactions" ci
                ON ci."client_id" = od."client_id"
            WHERE (od."tenant_id" = CAST(:tenant_id AS VARCHAR) OR (od."client_id" IS NOT NULL AND cm."tenant_id" = CAST(:tenant_id AS VARCHAR)))
              AND od."service_id" = :service_id
              AND NOT EXISTS (
                    SELECT 1
                    FROM "StreemLyne_MT"."Project_Details" pd
                    WHERE pd."opportunity_id" = od."opportunity_id"
                )
              AND (sm."stage_name" IS NULL OR LOWER(sm."stage_name") NOT IN ('priced', 'lost'))
              AND ci."reminder_date" IS NOT NULL
              AND ci."reminder_date" >= CURRENT_DATE
              AND ci."next_steps" IN ('Callback', 'Not Answered', 'Broker in Place', 'Already Renewed', 'End Date Changed', 'Email Only', 'Complaint')
              {employee_filter}
            ORDER BY ci."reminder_date" ASC, od."opportunity_id" ASC
        ''')

        rows = session.execute(query, query_params)
        lead_rows = [dict(row._mapping) for row in rows]

        logging.info(f"✅ Found {len(lead_rows)} lead callbacks")

        events = []
        for lead in lead_rows:
            callback_date = lead.get('callback_date')
            if callback_date is None:
                continue

            callback_type = lead.get('callback_status') or 'Callback'
            notes = lead.get('callback_notes')
            lead_name = lead.get('name') or 'Unknown'
            open_id = lead.get('tenant_lead_id') or lead.get('opportunity_id')

            events.append({
                'id': f"lead-callback-{lead.get('interaction_id')}",
                'customer_id': open_id,
                'type': 'callback',
                'title': f"{lead_name} - {callback_type}",
                'name': lead_name,
                'mpan': lead.get('mpan_mpr'),
                'supplier': lead.get('supplier'),
                'contract_start_date': str(lead['start_date']) if lead.get('start_date') else None,
                'contract_end_date': str(lead['end_date']) if lead.get('end_date') else None,
                'reminder_date': str(callback_date),
                'address': lead.get('address'),
                'postcode': lead.get('postcode'),
                'contact': lead.get('contact_person'),
                'email': lead.get('email'),
                'phone': str(lead.get('tel_number')) if lead.get('tel_number') is not None else None,
                'service_title': lead.get('service_title') or service_param.title(),
                'rates': None,
                'notes': notes,
                'display_date': str(callback_date),
                'display_type': callback_type,
                'status': lead.get('stage_name') or 'Active',
                'assigned_to': lead.get('assigned_to'),
            })

        logging.info(f"✅ Returning {len(events)} lead callback events")

        return jsonify({'success': True, 'data': events, 'count': len(events)}), 200

    except Exception as e:
        logging.exception("❌ Error fetching leads calendar")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch leads calendar',
            'message': str(e),
        }), 500
    finally:
        session.close()

@calendar_bp.route('/contracts', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_contract_schedule():
    """Get all energy contracts for calendar view"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        tenant_id = g.tenant_id
        repo = TenantRepository()
        
        # ✅ Query with status filter to exclude priced/lost
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
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Client_Interactions" ci ON cm.client_id = ci.client_id
            WHERE cm.tenant_id = %s
            AND (ecm.contract_end_date IS NOT NULL OR ci.reminder_date IS NOT NULL)
            AND (pd.status IS NULL OR LOWER(pd.status) NOT IN ('priced', 'lost'))
            ORDER BY cm.client_id
        '''
        
        contracts = repo.db.execute_query(query, (tenant_id,))
        
        # Transform to calendar events
        events = []
        for contract in contracts:
            if not contract.get('name'):
                continue
                
            events.append({
                'id': str(contract['client_id']),
                'type': 'contract',
                'title': f"{contract['name']} - {contract.get('supplier', 'Unknown')}",
                'client_id': contract.get('client_id'),
                'client_name': contract.get('name'),
                'client_contact': contract.get('contact'),
                'client_phone': contract.get('phone'),
                'client_email': contract.get('email'),
                'start_date': str(contract['contract_start_date']) if contract.get('contract_start_date') else None,
                'end_date': str(contract['contract_end_date']) if contract.get('contract_end_date') else None,
                'supplier_name': contract.get('supplier'),
                'service_title': contract.get('service_title'),
                'mpan_number': contract.get('mpan'),
                'unit_rate': float(contract['rates']) if contract.get('rates') else None,
                'terms_of_sale': contract.get('contract_notes'),
                'notes': contract.get('contract_notes'),
                'status': 'Active',
            })
        
        return jsonify({
            'success': True,
            'data': events,
            'count': len(events)
        }), 200
        
    except Exception as e:
        logging.exception("❌ Error fetching contract calendar")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch calendar',
            'message': str(e)
        }), 500


@calendar_bp.route('/clients', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_clients():
    """Get all clients for dropdown"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
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
        logging.exception("❌ Error fetching clients")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch clients',
            'message': str(e)
        }), 500


@calendar_bp.route('/employees', methods=['GET', 'OPTIONS'])
@token_required
@tenant_from_jwt
def get_employees():
    """Get all employees for assignment - FIXED VERSION"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    from backend.db import SessionLocal
    from sqlalchemy import text
    
    session = SessionLocal()
    
    try:
        tenant_id = g.tenant_id
        
        logging.info(f"📊 Fetching employees for tenant_id: {tenant_id}")
        
        query = text('''
            SELECT 
                employee_id as id,
                employee_name as full_name,
                email,
                phone,
                dm.designation_description as role
            FROM "StreemLyne_MT"."Employee_Master" em
            LEFT JOIN "StreemLyne_MT"."Designation_Master" dm 
                ON em.employee_designation_id = dm.designation_id
            WHERE em.tenant_id = CAST(:tenant_id AS VARCHAR)
            ORDER BY employee_name
        ''')
        
        result = session.execute(query, {'tenant_id': tenant_id})
        employees = [dict(row._mapping) for row in result]
        
        logging.info(f"✅ Found {len(employees)} employees for tenant_id {tenant_id}")
        
        return jsonify({
            'success': True,
            'data': employees
        }), 200
        
    except Exception as e:
        logging.exception("❌ Error fetching employees")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch employees',
            'message': str(e)   
        }), 500
    finally:
        session.close()