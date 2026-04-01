"""
Energy Tenant Customer Routes
Multi-table system integrating:
- Client_Master: Core client info
- Project_Details: Site addresses (Misc_Col2 = Annual Usage)
- Energy_Contract_Master: MPAN, Supplier, Contract dates
- Opportunity_Details: Sales pipeline, assigned employee
- Client_Interactions: Callback tracking
"""

from flask import Blueprint, request, jsonify, current_app
from .auth_helpers import token_required
from backend.crm.utils.role_helpers import is_admin_user
from datetime import datetime
from sqlalchemy import and_, or_, func, text 
from sqlalchemy.orm import aliased
from ..db import SessionLocal

# ✅ Import all models directly from backend.models
from backend.models import (
    UserMaster,
    Employee_Master,
    Client_Master,
    Project_Details,
    Energy_Contract_Master,
    Client_Interactions,
    Supplier_Master,
    Stage_Master,
    Role_Master
)

energy_customer_bp = Blueprint('energy_customers', __name__)
 
# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_tenant_id_from_user(user):
    """Get tenant_id from authenticated user"""
    # ✅ The JWT already contains tenant_id, attached to user object by auth_helpers
    if hasattr(user, 'tenant_id') and user.tenant_id:
        return user.tenant_id
    
    # Fallback: query Employee_Master if not in user object
    session = SessionLocal()
    try:
        employee = session.query(Employee_Master).filter_by(
            employee_id=user.employee_id
        ).first()
        return employee.tenant_id if employee else None
    finally:
        session.close()


def build_customer_response(client, project=None, contract=None, opportunity=None, interaction=None, supplier=None, employee=None, old_supplier=None, stage=None):
    def safe_date_to_iso(date_value):
        if date_value is None:
            return None
        if isinstance(date_value, str):
            return date_value
        if hasattr(date_value, 'isoformat'):
            return date_value.isoformat()
        return str(date_value)
 
    response = {
        # From Client_Master
        'id': client.tenant_client_id,
        'client_id': client.client_id,
        'tenant_client_id': client.tenant_client_id,
        'display_id': client.display_id if hasattr(client, 'display_id') else None,
        'display_order': getattr(client, 'display_order', None),
        'assigned_employee_id': client.assigned_employee_id if hasattr(client, 'assigned_employee_id') else None,
        'name': client.client_contact_name or '',
        'business_name': client.client_company_name or '',
        'contact_person': client.client_contact_name or '',
        'phone': client.client_phone or '',
        'mobile_no': client.client_mobile or '',
        'email': client.client_email or '',
        'address': client.address or '',
        'post_code': client.post_code or '',
        'website': client.client_website or '',
        'created_at': safe_date_to_iso(client.created_at),
        'position': getattr(client, 'position', None),
        'company_number': getattr(client, 'company_number', None),
        'date_of_birth': safe_date_to_iso(getattr(client, 'date_of_birth', None)),
        'charity_ltd_company_number': getattr(client, 'charity_ltd_company_number', None),
        'partner_details': getattr(client, 'partner_details', None),
        'home_door_number': getattr(client, 'home_door_number', None),
        'home_street': getattr(client, 'home_street', None),
        'home_post_code': getattr(client, 'home_post_code', None),
 
        # From Project_Details
        'project_id': project.project_id if project else None,
        'site_address': project.address if project else (client.address if client else None),
        'annual_usage': project.Misc_Col2 if project else None,
        'project_title': project.project_title if project else None,
        'site_name': getattr(project, 'site_name', None) if project else None,
        'month_sold': getattr(project, 'month_sold', None) if project else None,
        'house_name': getattr(project, 'house_name', None) if project else None,
        'house_number': getattr(project, 'house_number', None) if project else None,
 
        # Bank details
        'bank_name': getattr(client, 'bank_name', None),
        'account_number': getattr(client, 'account_number', None),
        'sort_code': getattr(client, 'sort_code', None),
 
        # From Energy_Contract_Master
        'contract_id': contract.energy_contract_master_id if contract else None,
        'mpan_mpr': contract.mpan_number if contract else '',
        'mpan_top': contract.mpan_number if contract else None,
        'mpan_bottom': contract.mpan_bottom if contract else None,
        'start_date': safe_date_to_iso(contract.contract_start_date if contract else None),
        'end_date': safe_date_to_iso(contract.contract_end_date if contract else None),
        'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
        'terms_of_sale': contract.terms_of_sale if contract else None,
        'standing_charge': contract.standing_charge if contract and hasattr(contract, 'standing_charge') else None,
        'aggregator': getattr(contract, 'aggregator', None) if contract else None,
        'rate_1': float(contract.rate_1) if contract and hasattr(contract, 'rate_1') and contract.rate_1 else None,
        'payment_type': getattr(contract, 'payment_type', None) if contract else None,
        'net_notch': float(contract.net_notch) if contract and hasattr(contract, 'net_notch') and contract.net_notch else None,
        'term_sold': getattr(contract, 'term_sold', None) if contract else None,
        'rate_2': float(contract.rate_2) if contract and hasattr(contract, 'rate_2') and contract.rate_2 else None,
        'rate_3': float(contract.rate_3) if contract and hasattr(contract, 'rate_3') and contract.rate_3 else None,
        'comms_paid': float(contract.comms_paid) if contract and hasattr(contract, 'comms_paid') and contract.comms_paid else None,
 
        # From Supplier_Master
        'supplier_id': (supplier.supplier_id if supplier else
                        (contract.supplier_id if contract and hasattr(contract, 'supplier_id') else None)),
        'supplier_name': supplier.supplier_company_name if supplier else '',
        'supplier_contact': supplier.supplier_contact_name if supplier else '',
        'supplier_provisions': supplier.supplier_provisions if supplier else None,
        'old_supplier_id': (old_supplier.supplier_id if old_supplier else
                            (contract.old_supplier_id if contract and hasattr(contract, 'old_supplier_id') else None)),
        'old_supplier_name': old_supplier.supplier_company_name if old_supplier else '',
 
        # ✅ Status and assignment now come from Project_Details
        'status': project.status if project else None,
        'stage_id': None,  # No longer tracked on renewals
        'opportunity_id': None,
        'opportunity_value': None,
        'opportunity_title': None,
 
        # From Employee_Master (via Project_Details.assigned_employee_id)
        'assigned_to_id': employee.employee_id if employee else None,
        'assigned_to_name': employee.employee_name if employee else '',
 
        # From Client_Interactions
        'callback_date': safe_date_to_iso(interaction.reminder_date if interaction else None),
        'last_contact_date': safe_date_to_iso(interaction.contact_date if interaction else None),
        'interaction_notes': interaction.notes if interaction else None,
        'is_allocated': getattr(client, 'is_allocated', False) or False,
    }
 
    return response


def get_user_role_name(user, session):
    """Get the role name for a user from User_Role_Mapping and Role_Master"""
    try:
        from backend.models import Role_Master
        
        # Query User_Role_Mapping to get role_id for this user
        result = session.execute(text("""
            SELECT rm.role_name
            FROM "StreemLyne_MT"."User_Role_Mapping" urm
            JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE urm.user_id = :user_id
            LIMIT 1
        """), {'user_id': user.user_id}).fetchone()
        
        if result:
            return result[0]  # Returns "Platform Admin" or "Salesperson" etc.
        
        return None
        
    except Exception as e:
        current_app.logger.error(f"Error getting user role: {e}")
        return None


def log_field_change(session, client_id: int, field_name: str, old_value, new_value, changed_by_employee_id: int = None):
    """
    Log a field change to the interaction history with old → new format
    """
    # Format values for display
    def format_value(val):
        if val is None or val == '':
            return "—"
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, datetime):
            return val.strftime('%d/%m/%Y')
        if hasattr(val, 'isoformat'):  # date objects
            return val.strftime('%d/%m/%Y')
        return str(val)
    
    old_formatted = format_value(old_value)
    new_formatted = format_value(new_value)
    
    # Skip logging if values are actually the same
    if old_formatted == new_formatted:
        return
    
    # Create change note with old → new format
    change_note = f"Changed {field_name}: '{old_formatted}' → '{new_formatted}'"
    
    # Add to Client_Interactions with special next_steps marker
    session.add(Client_Interactions(
        client_id=client_id,
        contact_date=datetime.utcnow().date(),
        contact_method=1,  # System/internal
        notes=change_note,
        next_steps='Field Updated',  # ✅ This is how frontend identifies it
        created_at=datetime.utcnow()
    ))

# ==========================================
# GET ALL CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
 
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
 
        _service_id = None
        service_param = request.args.get('service')
        if service_param and isinstance(service_param, str):
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
 
        latest_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )
        LatestInteraction = aliased(Client_Interactions)

        # ✅ EVERYONE (including admins) only sees their own NON-ALLOCATED contacts
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            LatestInteraction,
            Supplier_Master,
            Employee_Master,
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            latest_sq,
            Client_Master.client_id == latest_sq.c.client_id
        ).outerjoin(
            LatestInteraction,
            LatestInteraction.interaction_id == latest_sq.c.max_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_deleted == False,
                Client_Master.is_archived == False,
                # ✅ CRITICAL: Only show contacts assigned to THIS user
                Project_Details.assigned_employee_id == user.employee_id,
                # ✅ CRITICAL: Only show NON-ALLOCATED contacts (not reassigned)
                or_(
                    Client_Master.is_allocated == False,
                    Client_Master.is_allocated == None
                ),
                or_(
                    Project_Details.status == None,
                    ~func.lower(Project_Details.status).in_(['priced', 'lost', 'lost_cot', 'lost cot'])
                ),
                *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
            )
        ).order_by(Client_Master.created_at.desc())
 
        results = query.all()
 
        client_ids = list(set([client.client_id for client, *_ in results]))
        assignment_notes_map = {}
        if client_ids:
            try:
                assignment_notes_result = session.execute(text("""
                    SELECT DISTINCT ON (client_id) client_id, notes
                    FROM "StreemLyne_MT"."Client_Interactions"
                    WHERE client_id = ANY(:client_ids) AND next_steps = 'Assignment'
                    ORDER BY client_id, created_at DESC
                """), {'client_ids': client_ids})
                for row in assignment_notes_result:
                    if row.notes:
                        parts = row.notes.split(' - ', 1)
                        assignment_notes_map[row.client_id] = parts[1] if len(parts) > 1 else row.notes
            except Exception as notes_error:
                print(f"⚠️ Error loading assignment notes: {notes_error}")
 
        customers = []
        seen_clients = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
 
            customer_data = build_customer_response(
                client, project, contract, None, interaction, supplier, employee
            )
            customer_data['assignment_notes'] = assignment_notes_map.get(client.client_id)
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': 'Failed to fetch energy customers'}), 500
    finally:
        session.close()
 
# ==========================================
# GET SINGLE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)

        # Subquery: get only the latest interaction_id per client
        latest_interaction_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )

        LatestInteraction = aliased(Client_Interactions)

        result = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            LatestInteraction,
            Supplier_Master,
            Employee_Master
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            latest_interaction_sq,
            Client_Master.client_id == latest_interaction_sq.c.client_id
        ).outerjoin(
            LatestInteraction,
            LatestInteraction.interaction_id == latest_interaction_sq.c.max_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            )
        ).first()

        if not result:
            return jsonify({'error': 'Customer not found'}), 404

        client, project, contract, interaction, supplier, employee = result

        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()

        customer_data = build_customer_response(
            client, project, contract, None, interaction, supplier, employee, old_supplier
        )

        return jsonify(customer_data), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching energy customer {client_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500
    finally:
        session.close()

# ==========================================
# CREATE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients', methods=['POST'])
@token_required
def create_energy_customer():
    session = SessionLocal()
    try:
        data = request.get_json()
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        if not data.get('business_name') and not data.get('contact_person'):
            return jsonify({'error': 'Business name or contact person is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
 
        assigned_employee_id = data.get('assigned_to_id') or request.current_user.employee_id
        service_string = data.get('service', 'utilities')
        service_id = 1 if service_string == 'utilities' else 2
 
        should_archive, archive_reason = auto_archive_older_contracts(
            session=session,
            tenant_id=tenant_id,
            business_name=data.get('business_name', ''),
            mpan_top=data.get('mpan_top', ''),
            mpan_bottom=data.get('mpan_bottom', ''),
            new_end_date=data.get('end_date'),
            service_id=service_id
        )
 
        # 1. Create Client_Master
        new_client = Client_Master(
            tenant_id=tenant_id,
            assigned_employee_id=assigned_employee_id,
            client_company_name=data.get('business_name', ''),
            client_contact_name=data.get('contact_person', ''),
            address=data.get('address', ''),
            post_code=data.get('post_code', ''),
            client_phone=data.get('phone'),
            client_email=data.get('email', ''),
            client_website=data.get('website', ''),
            default_currency_id=data.get('currency_id', 1),
            is_archived=should_archive,
            archived_at=datetime.utcnow() if should_archive else None,
            archived_reason=archive_reason,
            created_at=datetime.utcnow()
        )
        session.add(new_client)
        session.flush()
        client_id = new_client.client_id

        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
            session.flush()
 
        # 2. Create Project_Details (with assigned_employee_id and status)
        project = Project_Details(
            client_id=client_id,
            project_title=f"Site - {data.get('business_name', 'Unknown')}",
            project_description='Primary site location',
            address=data.get('site_address') or data.get('address', ''),
            Misc_Col2=data.get('annual_usage'),
            employee_id=request.current_user.employee_id,
            assigned_employee_id=assigned_employee_id,
            status=None,                                 
            start_date=data.get('start_date'),
            created_at=datetime.utcnow()
        )
        session.add(project)
        session.flush()
 
        # 3. Create Energy_Contract_Master
        mpan_top = data.get('mpan_top', '').strip()
        mpan_bottom = data.get('mpan_bottom', '').strip()
 
        contract = Energy_Contract_Master(
            project_id=project.project_id,
            employee_id=request.current_user.employee_id,
            supplier_id=data.get('supplier_id'),
            mpan_number=mpan_top,
            mpan_bottom=mpan_bottom,
            contract_start_date=data.get('start_date'),
            contract_end_date=data.get('end_date'),
            unit_rate=data.get('unit_rate') or 0,
            currency_id=data.get('currency_id', 1),
            service_id=service_id,
            terms_of_sale=data.get('terms_of_sale', ''),
            created_at=datetime.utcnow()
        )
        session.add(contract)
        session.flush()
 
        # 4. Client_Interactions (optional)
        if data.get('callback_date'):
            interaction = Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=data.get('notes', 'Initial contact'),
                reminder_date=data.get('callback_date'),
                created_at=datetime.utcnow()
            )
            session.add(interaction)
 
        session.commit()
        session.refresh(new_client)
 
        response_data = build_customer_response(new_client, project, contract)
 
        return jsonify({
            'success': True,
            'message': 'Energy customer created successfully',
            'customer': response_data
        }), 201
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating energy customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close()
        
# ==========================================
# UPDATE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_energy_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        print(f"\n{'='*60}")
        print(f"🔧 UPDATE REQUEST for client {client_id}")
        print(f"   Data: {data}")
        print(f"   User: {request.current_user.employee_id}")
        
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id
        ).first()
        if not client:
            return jsonify({'error': 'Customer not found'}), 404

        # Resolve actual client_id for downstream use
        client_id = client.client_id
 
        # ✅ Get current employee ID for change logging
        current_employee_id = request.current_user.employee_id if hasattr(request.current_user, 'employee_id') else None
        
        # ✅ TRACK CHANGES - Client_Master fields
        CLIENT_FIELDS = {
            'business_name': ('client_company_name', 'Trading Name'),
            'contact_person': ('client_contact_name', 'Client Name'),
            'phone': ('client_phone', 'Tel Number'),
            'mobile_no': ('client_mobile', 'Mobile Number'),
            'email': ('client_email', 'Email'),
            'address': ('address', 'Street'),
            'post_code': ('post_code', 'Post Code'),
            'website': ('client_website', 'Website'),
            'position': ('position', 'Position'),
            'company_number': ('company_number', 'Company Number'),
            'date_of_birth': ('date_of_birth', 'Date of Birth'),
            'bank_name': ('bank_name', 'Bank Name'),
            'bank_account_number': ('account_number', 'Account Number'),
            'bank_sort_code': ('sort_code', 'Sort Code'),
            'charity_ltd_company_number': ('charity_ltd_company_number', 'Charity/Ltd Company Number'),
            'partner_details': ('partner_details', 'Partner Details'),
        }
        
        # Update Client_Master fields WITH CHANGE TRACKING
        for api_field, (db_field, display_name) in CLIENT_FIELDS.items():
            if api_field in data:
                old_value = getattr(client, db_field, None)
                new_value = data[api_field]
                
                if old_value != new_value:
                    log_field_change(session, client_id, display_name, old_value, new_value, current_employee_id)
                    setattr(client, db_field, new_value)

        # Update Project_Details
        project = session.query(Project_Details).filter_by(client_id=client_id).first()
        if project:
            # ✅ TRACK CHANGES - Project_Details fields
            PROJECT_FIELDS = {
                'site_address': ('address', 'Site Address'),
                'annual_usage': ('Misc_Col2', 'Annual Usage'),
                'site_name': ('site_name', 'Site Name'),
                'month_sold': ('month_sold', 'Month Sold'),
                'house_name': ('house_name', 'House Name'),
                'house_number': ('house_number', 'House Number'),
                'door_number': ('door_number', 'Door Number'),
                'town': ('town', 'Town'),
                'county': ('county', 'County'),
            }
            
            for api_field, (db_field, display_name) in PROJECT_FIELDS.items():
                if api_field in data:
                    old_value = getattr(project, db_field, None)
                    new_value = data[api_field]
                    
                    if old_value != new_value:
                        log_field_change(session, client_id, display_name, old_value, new_value, current_employee_id)
                        setattr(project, db_field, new_value)

            # ✅ Status tracking
            if 'status' in data:
                status_value = data['status']
                new_status = None if status_value in ['None', 'null', '', None] else status_value
                old_status = project.status
                
                if old_status != new_status:
                    log_field_change(session, client_id, 'Status', old_status, new_status, current_employee_id)
                    project.status = new_status

            # ✅ Assignment tracking (SEPARATE from change tracking)
            if 'assigned_to_id' in data:
                session.flush()
                fresh_project = session.query(Project_Details).filter_by(client_id=client_id).first()
                old_assigned_to = fresh_project.assigned_employee_id
                new_assigned_to = data['assigned_to_id']
                current_user_employee_id = request.current_user.employee_id
                assignment_notes = data.get('assignment_notes')
                
                print(f"\n📝 Assignment check:")
                print(f"   Old: {old_assigned_to}")
                print(f"   New: {new_assigned_to}")
                print(f"   Current user: {current_user_employee_id}")
                
                # Track assignment change with employee names
                if old_assigned_to != new_assigned_to:
                    old_emp = session.query(Employee_Master).filter_by(employee_id=old_assigned_to).first() if old_assigned_to else None
                    new_emp = session.query(Employee_Master).filter_by(employee_id=new_assigned_to).first() if new_assigned_to else None
                    
                    old_name = old_emp.employee_name if old_emp else "Unassigned"
                    new_name = new_emp.employee_name if new_emp else "Unassigned"
                    
                    log_field_change(session, client_id, 'Assigned To', old_name, new_name, current_employee_id)
                
                # Update assignment on BOTH tables
                project.assigned_employee_id = new_assigned_to
                project.updated_at = datetime.utcnow()
                client.assigned_employee_id = new_assigned_to
                
                # ✅ Determine is_allocated flag
                if new_assigned_to is None:
                    client.is_allocated = False
                    print(f"   ✅ Unassigned - is_allocated = False")
                elif old_assigned_to == new_assigned_to:
                    print(f"   ℹ️  No change in assignment")
                elif new_assigned_to == current_user_employee_id:
                    client.is_allocated = False
                    print(f"   ✅ Assigned to self - is_allocated = False")
                else:
                    client.is_allocated = True
                    print(f"   ✅ Assigned to someone else ({new_assigned_to}) - is_allocated = True")
            else:
                project.updated_at = datetime.utcnow()
                old_assigned_to = None
                new_assigned_to = None
                assignment_notes = None
 
        elif data.get('site_address') or data.get('annual_usage'):
            project = Project_Details(
                client_id=client_id,
                project_title=f"Site - {client.client_company_name}",
                address=data.get('site_address', ''),
                Misc_Col2=data.get('annual_usage'),
                employee_id=request.current_user.employee_id,
                assigned_employee_id=client.assigned_employee_id,
                created_at=datetime.utcnow()
            )
            session.add(project)
            session.flush()
            old_assigned_to = None
            new_assigned_to = None
            assignment_notes = None
        else:
            old_assigned_to = None
            new_assigned_to = None
            assignment_notes = None
 
        # ✅ Update Energy_Contract_Master WITH CHANGE TRACKING
        if project:
            contract = session.query(Energy_Contract_Master).filter_by(
                project_id=project.project_id
            ).first()
            if contract:
                # MPAN changes
                if 'mpan_mpr' in data or 'mpan_top' in data:
                    new_mpan = data.get('mpan_mpr') or data.get('mpan_top')
                    if contract.mpan_number != new_mpan:
                        log_field_change(session, client_id, 'MPAN Top', contract.mpan_number, new_mpan, current_employee_id)
                        contract.mpan_number = new_mpan
                
                if 'mpan_bottom' in data and contract.mpan_bottom != data['mpan_bottom']:
                    log_field_change(session, client_id, 'MPAN Bottom', contract.mpan_bottom, data['mpan_bottom'], current_employee_id)
                    contract.mpan_bottom = data['mpan_bottom']
                
                # Supplier changes - show names not IDs
                if 'supplier_id' in data:
                    new_supplier_id = data['supplier_id']
                    if contract.supplier_id != new_supplier_id:
                        old_supp = session.query(Supplier_Master).filter_by(supplier_id=contract.supplier_id).first() if contract.supplier_id else None
                        new_supp = session.query(Supplier_Master).filter_by(supplier_id=new_supplier_id).first() if new_supplier_id else None
                        
                        old_name = old_supp.supplier_company_name if old_supp else "—"
                        new_name = new_supp.supplier_company_name if new_supp else "—"
                        
                        log_field_change(session, client_id, 'New Supplier', old_name, new_name, current_employee_id)
                        contract.supplier_id = new_supplier_id
                
                if 'old_supplier_id' in data:
                    val = data['old_supplier_id']
                    new_old_supplier_id = None if (val is None or val == 0) else val
                    
                    if contract.old_supplier_id != new_old_supplier_id:
                        old_supp = session.query(Supplier_Master).filter_by(supplier_id=contract.old_supplier_id).first() if contract.old_supplier_id else None
                        new_supp = session.query(Supplier_Master).filter_by(supplier_id=new_old_supplier_id).first() if new_old_supplier_id else None
                        
                        old_name = old_supp.supplier_company_name if old_supp else "—"
                        new_name = new_supp.supplier_company_name if new_supp else "—"
                        
                        log_field_change(session, client_id, 'Old Supplier', old_name, new_name, current_employee_id)
                        contract.old_supplier_id = new_old_supplier_id
                
                # Standing charge
                if 'standing_charge' in data:
                    new_sc = str(data['standing_charge']) if data['standing_charge'] else None
                    if contract.standing_charge != new_sc:
                        log_field_change(session, client_id, 'Standing Charge', contract.standing_charge, new_sc, current_employee_id)
                        contract.standing_charge = new_sc
                
                # Contract dates
                if 'start_date' in data and data['start_date']:
                    new_start = datetime.fromisoformat(data['start_date'].replace('Z', '')).date() if isinstance(data['start_date'], str) else data['start_date']
                    if contract.contract_start_date != new_start:
                        log_field_change(session, client_id, 'Start Date', contract.contract_start_date, new_start, current_employee_id)
                        contract.contract_start_date = new_start
                
                if 'end_date' in data and data['end_date']:
                    new_end = datetime.fromisoformat(data['end_date'].replace('Z', '')).date() if isinstance(data['end_date'], str) else data['end_date']
                    if contract.contract_end_date != new_end:
                        log_field_change(session, client_id, 'Contract End', contract.contract_end_date, new_end, current_employee_id)
                        contract.contract_end_date = new_end
                
                # Rates and charges
                if 'unit_rate' in data and data['unit_rate'] is not None:
                    if contract.unit_rate != data['unit_rate']:
                        log_field_change(session, client_id, 'Rate 1', contract.unit_rate, data['unit_rate'], current_employee_id)
                        contract.unit_rate = data['unit_rate']
                
                if 'rate_2' in data and contract.rate_2 != data.get('rate_2'):
                    log_field_change(session, client_id, 'Rate 2', contract.rate_2, data['rate_2'], current_employee_id)
                    contract.rate_2 = data['rate_2']
                
                if 'rate_3' in data and contract.rate_3 != data.get('rate_3'):
                    log_field_change(session, client_id, 'Rate 3', contract.rate_3, data['rate_3'], current_employee_id)
                    contract.rate_3 = data['rate_3']
                
                if 'net_notch' in data and contract.net_notch != data.get('net_notch'):
                    log_field_change(session, client_id, 'Net Notch', contract.net_notch, data['net_notch'], current_employee_id)
                    contract.net_notch = data['net_notch']
                
                if 'term_sold' in data and contract.term_sold != data.get('term_sold'):
                    log_field_change(session, client_id, 'Term Sold', contract.term_sold, data['term_sold'], current_employee_id)
                    contract.term_sold = data['term_sold']
                
                if 'comms_paid' in data and contract.comms_paid != data.get('comms_paid'):
                    log_field_change(session, client_id, 'Comms Paid', contract.comms_paid, data['comms_paid'], current_employee_id)
                    contract.comms_paid = data['comms_paid']
                
                if 'terms_of_sale' in data and contract.terms_of_sale != data.get('terms_of_sale'):
                    log_field_change(session, client_id, 'Terms of Sale', contract.terms_of_sale, data['terms_of_sale'], current_employee_id)
                    contract.terms_of_sale = data['terms_of_sale']
                
                if 'payment_type' in data and contract.payment_type != data.get('payment_type'):
                    log_field_change(session, client_id, 'Payment Type', contract.payment_type, data['payment_type'], current_employee_id)
                    contract.payment_type = data['payment_type']
                
                # Handle new supplier by name
                if 'new_supplier' in data and data['new_supplier']:
                    new_supplier_name = data['new_supplier'].strip()
                    matched = session.query(Supplier_Master).filter(
                        Supplier_Master.supplier_company_name.ilike(f'%{new_supplier_name}%')
                    ).first()
                    if matched:
                        if contract.supplier_id and contract.supplier_id != matched.supplier_id:
                            contract.old_supplier_id = contract.supplier_id
                            log_field_change(session, client_id, 'New Supplier', 
                                           session.query(Supplier_Master).filter_by(supplier_id=contract.supplier_id).first().supplier_company_name if contract.supplier_id else "—",
                                           matched.supplier_company_name, current_employee_id)
                        contract.supplier_id = matched.supplier_id
                    else:
                        new_sup = Supplier_Master(
                            supplier_company_name=new_supplier_name,
                            supplier_contact_name='Auto-created',
                            supplier_provisions=3,
                            created_at=datetime.utcnow()
                        )
                        session.add(new_sup)
                        session.flush()
                        contract.old_supplier_id = contract.supplier_id
                        log_field_change(session, client_id, 'New Supplier', "—", new_supplier_name, current_employee_id)
                        contract.supplier_id = new_sup.supplier_id
                
                contract.updated_at = datetime.utcnow()
 
        # Create assignment interaction if assignment changed (SEPARATE from field change tracking)
        if 'assigned_to_id' in data and old_assigned_to != new_assigned_to:
            emp = session.query(Employee_Master).filter_by(employee_id=new_assigned_to).first() if new_assigned_to else None
            emp_name = emp.employee_name if emp else "Unassigned"
            note = f"Assigned to {emp_name}"
            if assignment_notes:
                note += f" - {assignment_notes}"
            session.add(Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=note,
                next_steps="Assignment",  # ✅ Keep only this
                created_at=datetime.utcnow()
            ))
 
        # Handle callback_date / interaction_notes
        if data.get('callback_date') or data.get('interaction_notes'):
            row = session.execute(text("""
                SELECT interaction_id FROM "StreemLyne_MT"."Client_Interactions"
                WHERE client_id = :cid ORDER BY created_at DESC LIMIT 1
            """), {'cid': client_id}).fetchone()
            if row:
                session.execute(text("""
                    UPDATE "StreemLyne_MT"."Client_Interactions"
                    SET reminder_date = :rd, notes = COALESCE(:n, notes), contact_date = CURRENT_DATE
                    WHERE interaction_id = :iid
                """), {'rd': data.get('callback_date'), 'n': data.get('interaction_notes'), 'iid': row[0]})
            else:
                session.execute(text("""
                    INSERT INTO "StreemLyne_MT"."Client_Interactions"
                    (client_id, contact_date, contact_method, notes, reminder_date, created_at)
                    VALUES (:cid, CURRENT_DATE, 1, :n, :rd, :ca)
                """), {'cid': client_id, 'n': data.get('interaction_notes', ''),
                       'rd': data.get('callback_date'), 'ca': datetime.utcnow()})
 
        session.commit()
        session.expire_all()
 
        # Fetch updated data
        latest_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )
        LatestInteraction = aliased(Client_Interactions)

        updated = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            LatestInteraction, Supplier_Master, Employee_Master
        ).outerjoin(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(latest_sq, Client_Master.client_id == latest_sq.c.client_id
        ).outerjoin(LatestInteraction, LatestInteraction.interaction_id == latest_sq.c.max_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(Client_Master.client_id == client_id).first()

        client, project, contract, interaction, supplier, employee = updated
 
        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()
 
        response_data = build_customer_response(
            client, project, contract, None, interaction, supplier, employee, old_supplier
        )
 
        return jsonify({'success': True, 'message': 'Customer updated successfully', 'customer': response_data}), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error updating energy customer {client_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close()

# ==========================================
# DELETE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_energy_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        # ✅ Try multiple ID fields (display_order, tenant_client_id, client_id)
        client = (
            session.query(Client_Master).filter(
                and_(
                    Client_Master.display_order == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            ).first() or
            session.query(Client_Master).filter(
                and_(
                    Client_Master.tenant_client_id == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            ).first() or
            session.query(Client_Master).filter(
                and_(
                    Client_Master.client_id == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            ).first()
        )
 
        if not client:
            current_app.logger.warning(f"Customer {client_id} not found for deletion")
            return jsonify({'error': 'Customer not found'}), 404
        
        # ✅ Soft delete the customer (move to recycle bin)
        actual_client_id = client.client_id
        
        # Get reason from request body if provided
        try:
            data = request.get_json(silent=True) or {}
            deletion_reason = data.get('reason', 'Manually deleted')
        except Exception:
            deletion_reason = 'Manually deleted'
        
        # Soft delete
        client.is_deleted = True
        client.deleted_at = datetime.utcnow()
        client.deleted_reason = deletion_reason

        session.commit()
        
        current_app.logger.info(f"✅ Soft deleted customer {actual_client_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer moved to recycle bin successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting customer {client_id}: {e}")
        return jsonify({'error': f'Failed to delete customer: {str(e)}'}), 500
    finally:
        session.close()

# ==========================================
# SEARCH CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients/search', methods=['GET', 'OPTIONS'])
@token_required
def search_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        if not query_param:
            return jsonify([]), 200
 
        results = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Client_Interactions,
            Supplier_Master,
            Employee_Master,
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_deleted == False,
                or_(
                    Client_Master.client_company_name.ilike(f'%{query_param}%'),
                    Client_Master.client_contact_name.ilike(f'%{query_param}%'),
                    Client_Master.client_phone.ilike(f'%{query_param}%'),
                    Client_Master.client_email.ilike(f'%{query_param}%'),
                    Client_Master.post_code.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_number.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_bottom.ilike(f'%{query_param}%'),
                    Project_Details.site_name.ilike(f'%{query_param}%'),
                    Supplier_Master.supplier_company_name.ilike(f'%{query_param}%')
                )
            )
        ).order_by(Client_Master.client_id.desc()).limit(50).all()
 
        customers = []
        seen_clients = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
 
            old_supplier = None
            if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
                old_supplier = session.query(Supplier_Master).filter_by(
                    supplier_id=contract.old_supplier_id
                ).first()
 
            customer_data = build_customer_response(
                client, project, contract, None, interaction, supplier, employee, old_supplier
            )
 
            if contract:
                customer_data['mpan_top'] = contract.mpan_number or ''
                customer_data['mpan_bottom'] = contract.mpan_bottom or ''
 
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error searching energy customers: {e}")
        return jsonify({'error': 'Failed to search customers'}), 500
    finally:
        session.close()

# ==========================================
# GET STATISTICS
# ==========================================

@energy_customer_bp.route('/energy-clients/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customer_stats():
    """Get customer statistics"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        # Total customers
        total = session.query(Client_Master).filter_by(tenant_id=tenant_id).count()
        
        stage_counts = {}
        
        # By supplier
        supplier_counts = dict(
            session.query(Supplier_Master.supplier_company_name, func.count(Energy_Contract_Master.energy_contract_master_id))
            .join(Energy_Contract_Master, Supplier_Master.supplier_id == Energy_Contract_Master.supplier_id)
            .join(Project_Details, Energy_Contract_Master.project_id == Project_Details.project_id)
            .join(Client_Master, Project_Details.client_id == Client_Master.client_id)
            .filter(Client_Master.tenant_id == tenant_id)
            .group_by(Supplier_Master.supplier_company_name)
            .all()
        )
        
        # Total annual usage
        total_usage = session.query(func.sum(Project_Details.Misc_Col2)).join(
            Client_Master
        ).filter(
            Client_Master.tenant_id == tenant_id
        ).scalar() or 0
        
        stats = {
            'total': total,
            'by_stage': stage_counts,
            'by_supplier': supplier_counts,
            'total_annual_usage': float(total_usage)
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching energy customer stats: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500
    finally:
        session.close()

# ==========================================
# HELPER ENDPOINTS
# ==========================================

@energy_customer_bp.route('/suppliers', methods=['GET'])
@token_required
def get_suppliers():
    """Get all energy suppliers"""
    session = SessionLocal()
    try:
        suppliers = session.query(Supplier_Master).all()
        result = [{
            'supplier_id': s.supplier_id,
            'supplier_name': s.supplier_company_name,
            'contact_name': s.supplier_contact_name,
            'provisions': s.supplier_provisions,
            'provisions_text': {
                0: 'Generic',
                1: 'Electricity Only',
                2: 'Gas Only',
                3: 'Electricity & Gas'
            }.get(s.supplier_provisions, 'Unknown')
        } for s in suppliers]
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching suppliers: {e}")
        return jsonify({'error': 'Failed to fetch suppliers'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/stages', methods=['GET'])
@token_required
def get_stages():
    """Get all opportunity stages"""
    session = SessionLocal()
    try:
        stages = session.query(Stage_Master).order_by(Stage_Master.stage_id).all()
        result = [{
            'stage_id': s.stage_id,
            'stage_name': s.stage_name,
            'description': s.stage_description
        } for s in stages]
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching stages: {e}")
        return jsonify({'error': 'Failed to fetch stages'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/employees', methods=['GET'])
@token_required
def get_employees():
    """Get all employees for assignment"""
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employees = session.query(Employee_Master).filter_by(tenant_id=tenant_id).all()
        
        result = [{
            'employee_id': e.employee_id,
            'employee_name': e.employee_name,
            'email': e.email
        } for e in employees]
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching employees: {e}")
        return jsonify({'error': 'Failed to fetch employees'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/reset-sequence', methods=['POST'])
@token_required
def reset_client_sequence():
    """Reset the client_id sequence to start from 1"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # ✅ FIX: Get user role from User_Role_Mapping
        user_role = get_user_role_name(request.current_user, session)
        
        # Check if user has permission (Platform Admin or Tenant Super Admin)
        if user_role not in ['Platform Admin', 'Tenant Super Admin']:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Get the maximum client_id for this tenant
        max_id = session.query(func.max(Client_Master.client_id)).filter(
            Client_Master.tenant_id == tenant_id
        ).scalar()
        
        # If no clients exist, reset to 1
        if max_id is None:
            max_id = 0
        
        # Reset the sequence
        session.execute(text(
            f'ALTER SEQUENCE "StreemLyne_MT"."Client_Master_client_id_seq" RESTART WITH {max_id + 1}'
        ))
        session.commit()
        
        return jsonify({
            'message': 'Sequence reset successfully',
            'next_id': max_id + 1
        })
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error resetting sequence: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/bulk-assign', methods=['POST', 'OPTIONS'])
@token_required
def bulk_assign_clients():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        data = request.get_json()
        client_ids = data.get('client_ids', [])
        employee_id = data.get('employee_id')
        assignment_notes = data.get('assignment_notes')
 
        if not client_ids or not employee_id:
            return jsonify({'error': 'client_ids and employee_id are required'}), 400
 
        employee = session.query(Employee_Master).filter(
            Employee_Master.employee_id == employee_id,
            Employee_Master.tenant_id == tenant_id
        ).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
 
        old_employee_ids = set()
        updated_count = 0
 
        for cid in client_ids:
            client = session.query(Client_Master).filter(
                Client_Master.client_id == cid,
                Client_Master.tenant_id == tenant_id
            ).first()
            if client:
                if client.assigned_employee_id and client.assigned_employee_id != employee_id:
                    old_employee_ids.add(client.assigned_employee_id)
                    client.is_allocated = True
                client.assigned_employee_id = employee_id
                updated_count += 1
 
            # ✅ Update Project_Details.assigned_employee_id
            projects = session.query(Project_Details).filter(
                Project_Details.client_id == cid
            ).all()
            for project in projects:
                project.assigned_employee_id = employee_id
 
            note = f"Assigned to {employee.employee_name}"
            if assignment_notes:
                note += f" - {assignment_notes}"
            session.add(Client_Interactions(
                client_id=cid,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=note,
                next_steps="Assignment",
                created_at=datetime.utcnow()
            ))
 
        session.commit()
 
        for old_emp_id in old_employee_ids:
            recalculate_display_order(session, tenant_id, old_emp_id)
        recalculate_display_order(session, tenant_id, employee_id)
        session.commit()
 
        return jsonify({
            'success': True,
            'message': f'Successfully assigned {len(client_ids)} clients to {employee.employee_name}',
            'updated_count': updated_count,
            'employee_name': employee.employee_name
        }), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error bulk assigning clients: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/search-all', methods=['GET', 'OPTIONS'])
@token_required
def search_all_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        service_param = request.args.get('service', 'utilities').strip().lower()
 
        if not query_param:
            return jsonify([]), 200
 
        service_id = {'utilities': 1, 'electricity': 1, 'water': 2, 'gas': 3}.get(service_param, 1)
 
        results = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Client_Interactions,
            Supplier_Master,
            Employee_Master,
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.is_deleted == False,
                or_(
                    Energy_Contract_Master.service_id == service_id,
                    Energy_Contract_Master.service_id == None
                ),
                or_(
                    Client_Master.client_company_name.ilike(f'%{query_param}%'),
                    Client_Master.client_contact_name.ilike(f'%{query_param}%'),
                    Client_Master.client_phone.ilike(f'%{query_param}%'),
                    Client_Master.client_email.ilike(f'%{query_param}%'),
                    Client_Master.post_code.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_number.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_bottom.ilike(f'%{query_param}%'),
                    Project_Details.site_name.ilike(f'%{query_param}%'),
                    Supplier_Master.supplier_company_name.ilike(f'%{query_param}%')
                )
            )
        ).order_by(Client_Master.client_id.desc()).limit(50).all()
 
        customers = []
        seen_clients = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
 
            old_supplier = None
            if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
                old_supplier = session.query(Supplier_Master).filter_by(
                    supplier_id=contract.old_supplier_id
                ).first()
 
            customer_data = {
                'id': client.client_id,
                'client_id': client.client_id,
                'display_id': client.tenant_client_id if hasattr(client, 'tenant_client_id') else None,
                'display_order': client.display_order,
                'name': client.client_contact_name or '',
                'business_name': client.client_company_name or '',
                'contact_person': client.client_contact_name or '',
                'phone': client.client_phone or '',
                'email': client.client_email or '',
                'address': client.address or '',
                'site_address': project.address if project else '',
                'mpan_mpr': contract.mpan_number if contract else '',
                'mpan_top': contract.mpan_number if contract else '',
                'mpan_bottom': contract.mpan_bottom if contract else '',
                'supplier_id': contract.supplier_id if contract else None,
                'supplier_name': supplier.supplier_company_name if supplier else '',
                'annual_usage': project.Misc_Col2 if project else None,
                'start_date': contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,
                'end_date': contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
                'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
                'status': project.status if project else None,  # ✅ from Project_Details
                'stage_id': None,
                'opportunity_id': None,
                'assigned_to_id': project.assigned_employee_id if project else client.assigned_employee_id,  # ✅
                'assigned_to_name': employee.employee_name if employee else None,
                'created_at': client.created_at.isoformat() if client.created_at else None,
                'is_archived': client.is_archived if hasattr(client, 'is_archived') else False,
                'position': getattr(client, 'position', None),
                'company_number': getattr(client, 'company_number', None),
                'site_name': project.site_name if project and hasattr(project, 'site_name') else None,
                'old_supplier_name': old_supplier.supplier_company_name if old_supplier else None,
            }
 
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error in cross-tenant search: {e}")
        return jsonify({'error': 'Failed to search customers'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/priced', methods=['GET', 'OPTIONS'])
@token_required
def get_priced_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
 
        _service_id = None
        service_param = request.args.get('service')
        if service_param:
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
 
        salesperson_param = request.args.get('salesperson')
 
        query = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            Client_Interactions, Supplier_Master, Employee_Master
        ).join(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(and_(
            Client_Master.tenant_id == tenant_id,
            func.lower(Project_Details.status) == 'priced',  # ✅ Changed
            *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
        ))
 
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
 
        if is_admin:
            if salesperson_param and salesperson_param != "All":
                try:
                    query = query.filter(
                        Project_Details.assigned_employee_id == int(salesperson_param)  # ✅ Changed
                    )
                except ValueError:
                    pass
        else:
            query = query.filter(
                Project_Details.assigned_employee_id == user.employee_id  # ✅ Changed
            )
 
        results = query.order_by(Client_Master.created_at.desc()).all()
 
        customers = []
        seen_clients = set()
        for client, project, contract, interaction, supplier, employee in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
            customers.append(build_customer_response(
                client, project, contract, None, interaction, supplier, employee
            ))
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching priced customers: {e}")
        return jsonify({'error': 'Failed to fetch priced customers'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/stats-by-employee', methods=['GET'])
@token_required
def get_stats_by_employee():
    """Get customer count per employee for Platform Admin"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # user_role = get_user_role_name(request.current_user, session)
        
        # if user_role not in ['Platform Admin', 'Tenant Super Admin']:
        #     return jsonify({'error': 'Unauthorized - Admin only'}), 403
        
        service_param = request.args.get('service', 'utilities')
        service_id_map = {'utilities': 1, 'water': 2, 'gas': 3}
        service_id = service_id_map.get(service_param.strip().lower(), 1)
        
        sql = text('''
            SELECT 
                em.employee_id,
                em.employee_name,
                COUNT(DISTINCT cm.client_id) as count
            FROM "StreemLyne_MT"."Employee_Master" em
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm 
                ON em.employee_id = cm.assigned_employee_id
                AND cm.tenant_id = :tenant_id
                AND cm.client_company_name != '[IMPORTED LEADS]'
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd 
                ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm 
                ON pd.project_id = ecm.project_id 
                AND ecm.service_id = :service_id
            WHERE em.tenant_id = :tenant_id
                AND ecm.energy_contract_master_id IS NOT NULL
            GROUP BY em.employee_id, em.employee_name
            HAVING COUNT(DISTINCT cm.client_id) > 0
            ORDER BY em.employee_name ASC
        ''')
        
        results = session.execute(sql, {
            'tenant_id': tenant_id,
            'service_id': service_id
        }).mappings().all()
        
        stats = [
            {
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'count': int(row['count']) if row['count'] else 0
            }
            for row in results
        ]
        
        return jsonify({'stats': stats}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching employee stats: {str(e)}")
        return jsonify({'error': str(e), 'stats': []}), 500
    finally:
        session.close()

# ==========================================
# RECYCLE BIN ENDPOINTS
# ==========================================

@energy_customer_bp.route('/energy-clients/recycle-bin', methods=['GET', 'OPTIONS'])
@token_required
def get_recycle_bin():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        service_param = request.args.get('service', 'utilities')
        service_id = {'utilities': 1, 'water': 2, 'gas': 3}.get(service_param.strip().lower(), 1)
        salesperson_param = request.args.get('salesperson')  # ✅ NEW

        query = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            Supplier_Master, Employee_Master
        ).join(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(and_(
            Client_Master.tenant_id == tenant_id,
            Client_Master.is_deleted == True,
            *([Energy_Contract_Master.service_id == service_id] if service_id is not None else [])
        ))

        # ✅ Admin sees all (with optional salesperson filter); non-admin sees only their own
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']

        if is_admin:
            if salesperson_param and salesperson_param != "All":
                try:
                    query = query.filter(
                        Project_Details.assigned_employee_id == int(salesperson_param)
                    )
                except ValueError:
                    pass
        else:
            query = query.filter(
                Project_Details.assigned_employee_id == user.employee_id
            )

        results = query.order_by(Client_Master.deleted_at.desc()).all()
        customers = []
        seen_clients = set()

        for client, project, contract, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            customer_data = build_customer_response(
                client, project, contract, None, None, supplier, employee
            )
            customer_data['is_deleted'] = True
            customer_data['deleted_at'] = client.deleted_at.isoformat() if client.deleted_at else None
            customer_data['deleted_reason'] = client.deleted_reason
            customers.append(customer_data)

        return jsonify(customers), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching recycle bin: {e}")
        return jsonify({'error': 'Failed to fetch recycle bin'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/restore', methods=['POST', 'OPTIONS'])
@token_required
def restore_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        client = (
            session.query(Client_Master).filter_by(display_order=client_id, tenant_id=tenant_id, is_deleted=True).first() or
            session.query(Client_Master).filter_by(tenant_client_id=client_id, tenant_id=tenant_id, is_deleted=True).first() or
            session.query(Client_Master).filter_by(client_id=client_id, tenant_id=tenant_id, is_deleted=True).first()
        )
        if client and not client.is_deleted:
            client = None
        if not client:
            return jsonify({'error': 'Customer not found in recycle bin'}), 404

        # Resolve actual client_id for downstream use
        actual_client_id = client.client_id

        assigned_employee_id = client.assigned_employee_id
        client.is_deleted = False
        client.deleted_at = None
        client.deleted_reason = None

        project = session.query(Project_Details).filter_by(client_id=actual_client_id).first()
        if project and project.status:
            project.status = None
 
        session.flush()
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        session.commit()
 
        return jsonify({'success': True, 'message': 'Customer restored successfully'}), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error restoring customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/permanent-delete', methods=['DELETE', 'OPTIONS'])
@token_required
def permanent_delete_customer(client_id):
    """
    Permanently delete a customer from recycle bin.
    HARD DELETE — only works on records already in recycle bin (is_deleted = TRUE).
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)

        client = (
            session.query(Client_Master).filter_by(display_order=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(tenant_client_id=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(client_id=client_id, tenant_id=tenant_id).first()
        )
        # For restore/permanent-delete, also verify the is_deleted flag:
        if client and not client.is_deleted:
            client = None

        if not client:
            return jsonify({'error': 'Customer not found in recycle bin'}), 404

        actual_client_id = client.client_id
        current_app.logger.info(f"🗑️ Permanently deleting customer {client_id}: {client.client_company_name}")

        # 1. Find project IDs
        projects = session.query(Project_Details).filter_by(client_id=client_id).all()
        project_ids = [p.project_id for p in projects]

        # 2. Delete Energy_Contract_Master
        contracts_deleted = 0
        if project_ids:
            contracts_deleted = session.query(Energy_Contract_Master).filter(
                Energy_Contract_Master.project_id.in_(project_ids)
            ).delete(synchronize_session=False)
            current_app.logger.info(f"   📋 Deleted {contracts_deleted} contracts")

        # 3. Delete Client_Interactions
        interactions_deleted = session.query(Client_Interactions).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {interactions_deleted} interactions")

        # 4. Delete Project_Details
        projects_deleted = session.query(Project_Details).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {projects_deleted} projects")

        # 5. Delete Client_Master
        session.delete(client)

        session.commit()

        current_app.logger.info(f"✅ Permanently deleted customer {client_id} from recycle bin")

        return jsonify({
            'success': True,
            'message': 'Customer permanently deleted',
            'deleted': {
                'contracts': contracts_deleted,
                'interactions': interactions_deleted,
                'projects': projects_deleted,
                'client': 1
            }
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error permanently deleting customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/archives', methods=['GET', 'OPTIONS'])
@token_required
def get_archived_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
 
        service_param = request.args.get('service', 'utilities')
        service_id = {'utilities': 1, 'water': 2, 'gas': 3}.get(service_param.strip().lower(), 1)
        salesperson_param = request.args.get('salesperson')
 
        query = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            Supplier_Master, Employee_Master
        ).join(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id  # ✅ Changed
        ).filter(and_(
            Client_Master.tenant_id == tenant_id,
            Client_Master.is_archived == True,
            *([Energy_Contract_Master.service_id == service_id] if service_id is not None else [])
        ))
 
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
 
        if is_admin:
            if salesperson_param and salesperson_param != "All":
                try:
                    query = query.filter(
                        Project_Details.assigned_employee_id == int(salesperson_param)  # ✅ Changed
                    )
                except ValueError:
                    pass
        else:
            query = query.filter(
                Project_Details.assigned_employee_id == user.employee_id  # ✅ Changed
            )
 
        results = query.order_by(Energy_Contract_Master.contract_end_date.desc()).all()
        customers = []
        seen_clients = set()
 
        for client, project, contract, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            customer_data = build_customer_response(
                client, project, contract, None, None, supplier, employee
            )
            customer_data['is_archived'] = True
            customer_data['archived_at'] = client.archived_at.isoformat() if client.archived_at else None
            customer_data['archived_reason'] = client.archived_reason
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching archives: {e}")
        return jsonify({'error': 'Failed to fetch archives'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/<int:client_id>/archive', methods=['POST', 'OPTIONS'])
@token_required
def archive_customer(client_id):
    """
    Archive a customer record
    Sets is_archived = TRUE and recalculates display_order
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the client
        client = (
            session.query(Client_Master).filter_by(display_order=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(tenant_client_id=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(client_id=client_id, tenant_id=tenant_id).first()
        )
        # Must not already be archived
        if client and client.is_archived:
            client = None

        if not client:
            return jsonify({'error': 'Customer not found'}), 404
        
        # ✅ Get employee_id BEFORE archiving (for display_order recalculation)
        assigned_employee_id = client.assigned_employee_id
        
        # Archive the customer
        client.is_archived = True
        client.archived_at = datetime.utcnow()
        
        # Get reason from request body if provided
        data = request.get_json() or {}
        client.archived_reason = data.get('reason', 'Manually archived')
        
        # Commit the archive change
        session.flush()
        
        # ✅ Recalculate display_order for the employee who lost this record
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        
        session.commit()
        
        current_app.logger.info(f"✅ Archived customer {client_id}")
        current_app.logger.info(f"✅ Recalculated display_order for employee_id={assigned_employee_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer archived successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error archiving customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/unarchive', methods=['POST', 'OPTIONS'])
@token_required
def unarchive_customer(client_id):
    """
    Restore a customer from archives
    Sets is_archived = FALSE, clears archive metadata, and recalculates display_order
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the archived client
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id,
            is_archived=True  # Must be in archives
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found in archives'}), 404
        
        # ✅ Get employee_id for display_order recalculation
        assigned_employee_id = client.assigned_employee_id
        
        # Restore the customer
        client.is_archived = False
        client.archived_at = None
        client.archived_reason = None
        
        # Commit the unarchive change
        session.flush()
        
        # ✅ Recalculate display_order for the employee who gained this record
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        
        session.commit()
        
        current_app.logger.info(f"✅ Restored customer {client_id} from archives")
        current_app.logger.info(f"✅ Recalculated display_order for employee_id={assigned_employee_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer restored from archives successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error restoring customer from archives: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def auto_archive_older_contracts(session, tenant_id, business_name, mpan_top, mpan_bottom, new_end_date, service_id, new_client_id=None):
    """
    Automatically archive older contracts when a newer one is created
    Returns: (should_archive_new, reason)
    """
    if not new_end_date:
        return False, None
    
    # Find existing records for this customer (by MPAN or business name)
    existing_query = session.query(
        Client_Master,
        Project_Details,
        Energy_Contract_Master
    ).join(
        Project_Details,
        Client_Master.client_id == Project_Details.client_id
    ).join(
        Energy_Contract_Master,
        Project_Details.project_id == Energy_Contract_Master.project_id
    ).filter(
        Client_Master.tenant_id == tenant_id,
        Energy_Contract_Master.service_id == service_id,
        Client_Master.is_deleted == False  # Don't consider deleted records
    )
    
    # Exclude the new client if it already exists (for updates)
    if new_client_id:
        existing_query = existing_query.filter(Client_Master.client_id != new_client_id)
    
    # Match by MPAN or business name
    if mpan_top or mpan_bottom:
        existing_query = existing_query.filter(
            or_(
                Energy_Contract_Master.mpan_number == mpan_top,
                Energy_Contract_Master.mpan_bottom == mpan_bottom
            )
        )
    elif business_name:
        existing_query = existing_query.filter(
            Client_Master.client_company_name == business_name
        )
    else:
        return False, None
    
    existing_records = existing_query.all()
    
    if not existing_records:
        return False, None
    
    # Convert new_end_date to date object if it's a string
    if isinstance(new_end_date, str):
        try:
            new_end_date = datetime.fromisoformat(new_end_date.replace('Z', '+00:00')).date()
        except:
            return False, None
    
    # Find the latest end date among existing records
    latest_end_date = None
    latest_client = None
    
    for client, project, contract in existing_records:
        if contract.contract_end_date:
            if latest_end_date is None or contract.contract_end_date > latest_end_date:
                latest_end_date = contract.contract_end_date
                latest_client = client
    
    if not latest_end_date:
        return False, None
    
    # If this NEW record's end date is OLDER than the latest existing, archive the NEW one
    if new_end_date < latest_end_date:
        current_app.logger.info(
            f"📦 Auto-archiving NEW record: {business_name} - "
            f"End date {new_end_date} is older than existing {latest_end_date}"
        )
        return True, f"Older contract - superseded by existing contract ending {latest_end_date}"
    
    # If this NEW record's end date is NEWER than existing, archive the OLD ones
    elif new_end_date > latest_end_date:
        archived_count = 0
        # ✅ Track employee IDs for display_order recalculation
        affected_employee_ids = set()
        
        for client, project, contract in existing_records:
            if not client.is_archived and contract.contract_end_date and contract.contract_end_date < new_end_date:
                # ✅ Track the employee ID before archiving
                if client.assigned_employee_id:
                    affected_employee_ids.add(client.assigned_employee_id)
                
                client.is_archived = True
                client.archived_at = datetime.utcnow()
                client.archived_reason = f"Superseded by newer contract ending {new_end_date}"
                archived_count += 1
                current_app.logger.info(
                    f"📦 Auto-archiving OLD record: {business_name} (ID: {client.client_id}) - "
                    f"Old end date {contract.contract_end_date} < New end date {new_end_date}"
                )
        
        if archived_count > 0:
            current_app.logger.info(f"✅ Archived {archived_count} older contract(s)")
            
            # ✅ Recalculate display_order for all affected employees
            session.flush()
            for employee_id in affected_employee_ids:
                recalculate_display_order(session, tenant_id, employee_id)
                current_app.logger.info(f"✅ Recalculated display_order for employee_id={employee_id} after auto-archive")
    
    return False, None

def recalculate_display_order(session, tenant_id, employee_id=None):
    """
    Recalculate display_order starting from 1 PER EMPLOYEE.
    Uses ROW_NUMBER() OVER (PARTITION BY assigned_employee_id ORDER BY created_at)
    so each salesperson's list always starts at 1.
    """
    if employee_id:
        # Recalculate only for this specific employee
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Client_Master" cm
            SET display_order = sub.rn
            FROM (
                SELECT client_id,
                       ROW_NUMBER() OVER (ORDER BY created_at ASC) AS rn
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                  AND assigned_employee_id = :employee_id
                  AND is_deleted = FALSE
                  AND is_archived = FALSE
            ) sub
            WHERE cm.client_id = sub.client_id
        """), {'tenant_id': tenant_id, 'employee_id': employee_id})
    else:
        # Recalculate for ALL employees at once using PARTITION BY
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Client_Master" cm
            SET display_order = sub.rn
            FROM (
                SELECT client_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY assigned_employee_id
                           ORDER BY created_at ASC
                       ) AS rn
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_archived = FALSE
            ) sub
            WHERE cm.client_id = sub.client_id
        """), {'tenant_id': tenant_id})
    
    session.flush()
    current_app.logger.info(
        f"✅ Recalculated display_order per-employee "
        f"(tenant={tenant_id}, employee={employee_id or 'ALL'})"
    )

@energy_customer_bp.route('/energy-clients/allocated', methods=['GET', 'OPTIONS'])
@token_required
def get_allocated_contacts():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
        
        _service_id = None
        service_param = request.args.get('service')
        if service_param and isinstance(service_param, str):
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
 
        latest_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )
        LatestInteraction = aliased(Client_Interactions)

        # ✅ Show contacts that are:
        # 1. Assigned to THIS user (Project_Details.assigned_employee_id)
        # 2. Marked as allocated (is_allocated = True)
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            LatestInteraction,
            Supplier_Master,
            Employee_Master
        ).join(
            Project_Details, 
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, 
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            latest_sq,
            Client_Master.client_id == latest_sq.c.client_id
        ).outerjoin(
            LatestInteraction,
            LatestInteraction.interaction_id == latest_sq.c.max_id
        ).outerjoin(
            Supplier_Master, 
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, 
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_deleted == False,
                Client_Master.is_archived == False,
                # ✅ Assigned to THIS user
                Project_Details.assigned_employee_id == user.employee_id,
                # ✅ Marked as allocated
                Client_Master.is_allocated == True,
                or_(
                    Project_Details.status == None,
                    ~func.lower(Project_Details.status).in_(['priced', 'lost', 'lost_cot', 'lost cot'])
                ),
                *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
            )
        ).order_by(Client_Master.display_order.asc())
 
        results = query.all()
        
        customers = []
        seen = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.tenant_client_id in seen:
                continue
            seen.add(client.tenant_client_id)
            customers.append(build_customer_response(
                client, project, contract, None, interaction, supplier, employee
            ))
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching allocated contacts: {e}")
        return jsonify({'error': 'Failed to fetch allocated contacts'}), 500
    finally:
        session.close()