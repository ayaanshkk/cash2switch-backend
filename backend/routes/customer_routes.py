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

from ..db import SessionLocal

# ✅ Import all models directly from backend.models
from backend.models import (
    UserMaster,
    Employee_Master,
    Client_Master,
    Project_Details,
    Energy_Contract_Master,
    Opportunity_Details,
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


def build_customer_response(client, project=None, contract=None, opportunity=None, interaction=None, supplier=None, employee=None, old_supplier=None):
    """Build unified customer response from multiple tables"""
    response = {
        # From Client_Master
        'id': client.tenant_client_id,
        'client_id': client.client_id,
        'tenant_client_id': client.tenant_client_id,
        'display_id': client.display_id if hasattr(client, 'display_id') else None, 
        'assigned_employee_id': client.assigned_employee_id if hasattr(client, 'assigned_employee_id') else None,
        'name': client.client_contact_name or '',
        'business_name': client.client_company_name or '',
        'contact_person': client.client_contact_name or '',
        'phone': client.client_phone or '',
        'email': client.client_email or '',
        'address': client.address or '',
        'post_code': client.post_code or '',
        'website': client.client_website or '',
        'created_at': client.created_at.isoformat() if client.created_at else None,
        
        # ✅ NEW: Client_Master fields
        'position': getattr(client, 'position', None),
        'company_number': getattr(client, 'company_number', None),
        'date_of_birth': client.date_of_birth.isoformat() if hasattr(client, 'date_of_birth') and client.date_of_birth else None,
        'charity_ltd_company_number': getattr(client, 'charity_ltd_company_number', None),
        'partner_details': getattr(client, 'partner_details', None),
        'home_door_number': getattr(client, 'home_door_number', None),
        'home_street': getattr(client, 'home_street', None),
        'home_post_code': getattr(client, 'home_post_code', None),
        
        # From Project_Details (Site address & Annual Usage)
        'project_id': project.project_id if project else None,
        'site_address': project.address if project else client.address,
        'annual_usage': project.Misc_Col2 if project else None,
        'project_title': project.project_title if project else None,
        
        # ✅ NEW: Project_Details fields
        'site_name': getattr(project, 'site_name', None) if project else None,
        'month_sold': getattr(project, 'month_sold', None) if project else None,
        'house_name': getattr(project, 'house_name', None) if project else None,
        'house_number': getattr(project, 'house_number', None) if project else None,

        # ✅ ADD BANK DETAILS from Client_Master:
        'bank_name': getattr(client, 'bank_name', None),
        'account_number': getattr(client, 'account_number', None),
        'sort_code': getattr(client, 'sort_code', None),
        
        # From Energy_Contract_Master
        'contract_id': contract.energy_contract_master_id if contract else None,
        'mpan_mpr': contract.mpan_number if contract else '',
        'start_date': contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,
        'end_date': contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
        'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
        'terms_of_sale': contract.terms_of_sale if contract else None,

        # ✅ ADD THESE CONTRACT FIELDS:
        'standing_charge': float(contract.standing_charge) if contract and hasattr(contract, 'standing_charge') and contract.standing_charge else None,
        'aggregator': getattr(contract, 'aggregator', None) if contract else None,
        'rate_1': float(contract.rate_1) if contract and hasattr(contract, 'rate_1') and contract.rate_1 else None,
        
        # ✅ NEW: Energy_Contract_Master fields
        'net_notch': float(contract.net_notch) if contract and hasattr(contract, 'net_notch') and contract.net_notch else None,
        'term_sold': getattr(contract, 'term_sold', None) if contract else None,
        'rate_2': float(contract.rate_2) if contract and hasattr(contract, 'rate_2') and contract.rate_2 else None,
        'rate_3': float(contract.rate_3) if contract and hasattr(contract, 'rate_3') and contract.rate_3 else None,
        'comms_paid': float(contract.comms_paid) if contract and hasattr(contract, 'comms_paid') and contract.comms_paid else None,
        
        # From Supplier_Master (via Energy_Contract_Master)
        'supplier_id': supplier.supplier_id if supplier else None,
        'supplier_name': supplier.supplier_company_name if supplier else '',
        'supplier_contact': supplier.supplier_contact_name if supplier else '',
        'supplier_provisions': supplier.supplier_provisions if supplier else None,
        
        # ✅ NEW: Old Supplier
        'old_supplier_id': old_supplier.supplier_id if old_supplier else None,
        'old_supplier_name': old_supplier.supplier_company_name if old_supplier else '',
        
        # From Opportunity_Details
        'opportunity_id': opportunity.opportunity_id if opportunity else None,
        'status': None,  # Will map from stage_id
        'stage_id': opportunity.stage_id if opportunity else None,
        'opportunity_value': opportunity.opportunity_value if opportunity else None,
        'opportunity_title': opportunity.opportunity_title if opportunity else None,
        
        # From Employee_Master (Assigned To)
        'assigned_to_id': employee.employee_id if employee else None,
        'assigned_to_name': employee.employee_name if employee else '',
        
        # From Client_Interactions
        'callback_date': interaction.reminder_date.isoformat() if interaction and interaction.reminder_date else None,
        'last_contact_date': interaction.contact_date.isoformat() if interaction and interaction.contact_date else None,
        'interaction_notes': interaction.notes if interaction else None,
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

# ==========================================
# GET ALL CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customers():
    """Get all energy customers EXCLUDING priced/lost statuses, filtered by assigned employee"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        # Service filter
        _service_id = None
        service_param = request.args.get('service')
        if service_param and isinstance(service_param, str):
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
        
        # Base query with joins
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details,
            Client_Interactions,
            Supplier_Master,
            Employee_Master,
            Stage_Master
        ).outerjoin(
            Project_Details, 
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Opportunity_Details,
            Client_Master.client_id == Opportunity_Details.client_id
        ).outerjoin(
            Client_Interactions,
            Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).outerjoin(
            Stage_Master,
            Opportunity_Details.stage_id == Stage_Master.stage_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.client_company_name != '[IMPORTED LEADS]',
                or_(
                    Opportunity_Details.Misc_Col1 == None,
                    ~func.lower(Opportunity_Details.Misc_Col1).in_(['priced', 'lost', 'lost_cot', 'lost cot'])
                ),
                or_(
                    Stage_Master.stage_name == None,
                    func.lower(Stage_Master.stage_name) != 'lost'
                ),
                *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
            )
        )

        query = query.order_by(Client_Master.created_at.desc())

        # ✅ CRITICAL: Filter by assigned employee for ALL users (admin and non-admin)
        # Each user only sees their own assigned customers
        query = query.filter(
            Opportunity_Details.opportunity_owner_employee_id == user.employee_id
        )

        results = query.all()
        
        # Build response
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, interaction, supplier, employee, stage in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
            
            customer_data = build_customer_response(
                client, project, contract, opportunity, interaction, supplier, employee
            )
            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
            
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} renewals for employee_id={user.employee_id}")
        
        return jsonify(customers), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching energy customers: {e}")
        return jsonify({'error': 'Failed to fetch energy customers'}), 500
    finally:
        session.close()

# ==========================================
# GET SINGLE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customer(client_id):
    """Get single customer with all related data"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Query with all joins + old supplier
        result = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details,
            Client_Interactions,
            Supplier_Master,
            Employee_Master
        ).outerjoin(
            Project_Details, 
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Opportunity_Details,
            Client_Master.client_id == Opportunity_Details.client_id
        ).outerjoin(
            Client_Interactions,
            Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            )
        ).first()
        
        if not result:
            return jsonify({'error': 'Customer not found'}), 404
        
        client, project, contract, opportunity, interaction, supplier, employee = result
        
        # ✅ Fetch old supplier if old_supplier_id exists
        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()
        
        customer_data = build_customer_response(
            client, project, contract, opportunity, interaction, supplier, employee, old_supplier
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
    """Create new energy customer across multiple tables"""

    session = SessionLocal()
    try:
        data = request.get_json()
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # Validate required fields
        if not data.get('business_name') and not data.get('contact_person'):
            return jsonify({'error': 'Business name or contact person is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
        
        current_app.logger.info(f"🆕 Creating new energy customer for tenant {tenant_id}")

        assigned_employee_id = data.get('assigned_to_id') or request.current_user.employee_id
        
        # 1. Create Client_Master entry
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
            default_currency_id=data.get('currency_id', 1),  # Default GBP
            created_at=datetime.utcnow()
        )
        session.add(new_client)
        session.flush()  # Get client_id
        
        client_id = new_client.client_id
        current_app.logger.info(f"✅ Created Client_Master: {client_id}")
        
        # 2. Create Project_Details (Site Address)
        project = None
        if data.get('site_address') or data.get('annual_usage'):
            project = Project_Details(
                client_id=client_id,
                project_title=f"Site - {data.get('business_name', 'Unknown')}",
                project_description='Primary site location',
                address=data.get('site_address', data.get('address', '')),
                Misc_Col2=data.get('annual_usage'),  # Annual Usage in kWh
                employee_id=request.current_user.employee_id,
                start_date=data.get('start_date'),
                created_at=datetime.utcnow()
            )
            session.add(project)
            session.flush()
            current_app.logger.info(f"✅ Created Project_Details: {project.project_id}")
        
        # 3. Create Energy_Contract_Master
        contract = None
        if project and (data.get('mpan_mpr') or data.get('supplier_id')):
            contract = Energy_Contract_Master(
                project_id=project.project_id,
                employee_id=request.current_user.employee_id,
                supplier_id=data.get('supplier_id'),
                mpan_number=data.get('mpan_mpr', ''),
                contract_start_date=data.get('start_date'),
                contract_end_date=data.get('end_date'),
                unit_rate=data.get('unit_rate'),
                currency_id=data.get('currency_id', 1),
                service_id=data.get('service_id'),  # Energy supplier rate
                terms_of_sale=data.get('terms_of_sale', ''),
                created_at=datetime.utcnow()
            )
            session.add(contract)
            session.flush()
            current_app.logger.info(f"✅ Created Energy_Contract_Master: {contract.energy_contract_master_id}")
        
        # 4. ✅ REMOVED: Opportunity_Details creation (was creating duplicate leads)
        # Renewals page (Client_Master) is now separate from Leads page (Opportunity_Details)
        
        # 5. Create Client_Interactions (if callback date provided)
        if data.get('callback_date'):
            interaction = Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,  # Phone by default
                notes=data.get('interaction_notes', 'Initial contact'),
                reminder_date=data.get('callback_date'),
                created_at=datetime.utcnow()
            )
            session.add(interaction)
            current_app.logger.info(f"✅ Created Client_Interactions")
        
        session.commit()
        
        # Fetch complete customer data
        session.refresh(new_client)
        
        # Build response (no opportunity parameter since we don't create it)
        response_data = build_customer_response(
            new_client, project, contract, None, None, None, None
        )
        
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
    """Update energy customer across multiple tables"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        data = request.get_json() or {}
        
        # Fetch client
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found'}), 404

        # Admin-only: assignment change
        user_role = get_user_role_name(request.current_user, session)
        if data and 'assigned_to_id' in data and user_role != 'Platform Admin':
            return jsonify({
                'error': 'permission_denied',
                'message': 'Only administrators can assign'
            }), 403
        
        current_app.logger.info(f"🔄 Updating energy customer {client_id}")
        
        # Update Client_Master
        if 'business_name' in data:
            client.client_company_name = data['business_name']
        if 'contact_person' in data:
            client.client_contact_name = data['contact_person']
        if 'phone' in data:
            client.client_phone = data['phone']
        if 'email' in data:
            client.client_email = data['email']
        if 'address' in data:
            client.address = data['address']
        if 'post_code' in data:
            client.post_code = data['post_code']
        if 'website' in data:
            client.client_website = data['website']
        
        # Update Project_Details
        project = session.query(Project_Details).filter_by(client_id=client_id).first()
        if project:
            if 'site_address' in data:
                project.address = data['site_address']
            if 'annual_usage' in data:
                project.Misc_Col2 = data['annual_usage']
            project.updated_at = datetime.utcnow()
        elif data.get('site_address') or data.get('annual_usage'):
            # Create project if it doesn't exist
            project = Project_Details(
                client_id=client_id,
                project_title=f"Site - {client.client_company_name}",
                address=data.get('site_address', ''),
                Misc_Col2=data.get('annual_usage'),
                employee_id=request.current_user.employee_id,
                created_at=datetime.utcnow()
            )
            session.add(project)
            session.flush()
        
        # Update Energy_Contract_Master
        if project:
            contract = session.query(Energy_Contract_Master).filter_by(
                project_id=project.project_id
            ).first()
            
            if contract:
                if 'mpan_mpr' in data:
                    contract.mpan_number = data['mpan_mpr']
                if 'supplier_id' in data:
                    contract.supplier_id = data['supplier_id']
                if 'start_date' in data:
                    contract.contract_start_date = data['start_date']
                if 'end_date' in data:
                    contract.contract_end_date = data['end_date']
                if 'unit_rate' in data:
                    contract.unit_rate = data['unit_rate']
                if 'terms_of_sale' in data:
                    contract.terms_of_sale = data['terms_of_sale']
                contract.updated_at = datetime.utcnow()
            elif data.get('mpan_mpr') or data.get('supplier_id'):
                # Create contract if it doesn't exist
                contract = Energy_Contract_Master(
                    project_id=project.project_id,
                    employee_id=request.current_user.employee_id,
                    supplier_id=data.get('supplier_id'),
                    mpan_number=data.get('mpan_mpr', ''),
                    contract_start_date=data.get('start_date'),
                    contract_end_date=data.get('end_date'),
                    unit_rate=data.get('unit_rate'),
                    created_at=datetime.utcnow()
                )
                session.add(contract)
        
        # Update Opportunity_Details
        opportunity = session.query(Opportunity_Details).filter_by(client_id=client_id).first()
        if opportunity:
            if 'stage_id' in data:
                opportunity.stage_id = data['stage_id']
            
            if 'status' in data:
                status_value = data['status']
                if status_value is None or status_value == '' or status_value == 'null':
                    opportunity.Misc_Col1 = None  # Clear the status
                    print(f"✅ Clearing status for client {client_id}")
                else:
                    opportunity.Misc_Col1 = status_value
                    print(f"✅ Setting status to '{status_value}' for client {client_id}")
            
            if 'assigned_to_id' in data:
                opportunity.opportunity_owner_employee_id = data['assigned_to_id']
            if 'opportunity_value' in data:
                opportunity.opportunity_value = data['opportunity_value']
        
        # ✅ UPDATE: Handle callback_date and interaction_notes
        if data.get('callback_date') or data.get('interaction_notes'):
            # Check if interaction exists
            interaction_check = session.execute(text("""
                SELECT interaction_id 
                FROM "StreemLyne_MT"."Client_Interactions"
                WHERE client_id = :client_id
                ORDER BY created_at DESC
                LIMIT 1
            """), {'client_id': client_id}).fetchone()
            
            if interaction_check:
                # Update existing interaction
                update_query = text("""
                    UPDATE "StreemLyne_MT"."Client_Interactions"
                    SET 
                        reminder_date = :reminder_date,
                        notes = COALESCE(:notes, notes),
                        contact_date = CURRENT_DATE
                    WHERE interaction_id = :interaction_id
                """)
                session.execute(update_query, {
                    'reminder_date': data.get('callback_date'),
                    'notes': data.get('interaction_notes'),
                    'interaction_id': interaction_check[0]
                })
            else:
                # Create new interaction with raw SQL
                insert_query = text("""
                    INSERT INTO "StreemLyne_MT"."Client_Interactions" 
                    (client_id, contact_date, contact_method, notes, reminder_date, created_at)
                    VALUES (:client_id, CURRENT_DATE, 1, :notes, :reminder_date, :created_at)
                """)
                session.execute(insert_query, {
                    'client_id': client_id,
                    'notes': data.get('interaction_notes', ''),
                    'reminder_date': data.get('callback_date'),
                    'created_at': datetime.utcnow()
                })
        
        session.commit()
        
        # Fetch updated data
        updated_result = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details,
            Client_Interactions,
            Supplier_Master,
            Employee_Master
        ).outerjoin(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Opportunity_Details, Client_Master.client_id == Opportunity_Details.client_id
        ).outerjoin(
            Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).filter(
            Client_Master.client_id == client_id
        ).first()
        
        client, project, contract, opportunity, interaction, supplier, employee = updated_result
        
        response_data = build_customer_response(
            client, project, contract, opportunity, interaction, supplier, employee
        )
        
        current_app.logger.info(f"✅ Energy customer {client_id} updated")
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully',
            'customer': response_data
        }), 200
        
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
    """Delete customer and all related records (Admin only)"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the client
        client = session.query(Client_Master).filter(
            and_(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            )
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found'}), 404
        
        actual_client_id = client.client_id
        
        current_app.logger.info(f"🗑️ Deleting customer {actual_client_id}: {client.client_company_name}")
        
        # ============================================
        # CRITICAL: Delete in correct order (child → parent)
        # ============================================
        
        # 0. ✅ DELETE Customer_Auth FIRST (references client_id)
        auth_deleted = session.execute(text("""
            DELETE FROM "StreemLyne_MT"."Customer_Auth"
            WHERE client_id = :client_id
        """), {'client_id': actual_client_id}).rowcount
        current_app.logger.info(f"   🔐 Deleted {auth_deleted} auth records")
        
        # 1. Find all projects for this client
        projects = session.query(Project_Details).filter_by(client_id=actual_client_id).all()
        project_ids = [p.project_id for p in projects]
        
        contracts_deleted = 0
        if project_ids:
            # 2. Delete Energy_Contract_Master (references project_id)
            contracts_deleted = session.query(Energy_Contract_Master).filter(
                Energy_Contract_Master.project_id.in_(project_ids)
            ).delete(synchronize_session=False)
            current_app.logger.info(f"   📋 Deleted {contracts_deleted} contracts")
        
        # 3. Delete Client_Interactions (references client_id)
        interactions_deleted = session.query(Client_Interactions).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {interactions_deleted} interactions")
        
        # 4. Delete Opportunity_Details (references client_id)
        opportunities_deleted = session.query(Opportunity_Details).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {opportunities_deleted} opportunities")
        
        # 5. Delete Project_Details (references client_id and opportunity_id)
        projects_deleted = session.query(Project_Details).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {projects_deleted} projects")
        
        # 6. Finally delete Client_Master
        session.delete(client)
        
        # Commit all deletions
        session.commit()
        
        # ============================================
        # RESET SEQUENCES AFTER DELETION
        # ============================================
        try:
            current_app.logger.info("🔄 Resetting sequences after deletion...")
            
            # Get max IDs for this tenant
            max_client_id = session.query(func.max(Client_Master.client_id)).filter(
                Client_Master.tenant_id == tenant_id
            ).scalar() or 0
            
            max_project_id = session.query(func.max(Project_Details.project_id)).join(
                Client_Master, Project_Details.client_id == Client_Master.client_id
            ).filter(
                Client_Master.tenant_id == tenant_id
            ).scalar() or 0
            
            max_opportunity_id = session.query(func.max(Opportunity_Details.opportunity_id)).join(
                Client_Master, Opportunity_Details.client_id == Client_Master.client_id
            ).filter(
                Client_Master.tenant_id == tenant_id
            ).scalar() or 0
            
            max_contract_id = session.query(func.max(Energy_Contract_Master.ecm_id)).join(
                Project_Details, Energy_Contract_Master.project_id == Project_Details.project_id
            ).join(
                Client_Master, Project_Details.client_id == Client_Master.client_id
            ).filter(
                Client_Master.tenant_id == tenant_id
            ).scalar() or 0
            
            # Reset sequences to max+1 (or 1 if no records)
            session.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('"StreemLyne_MT"."Client_Master"', 'client_id'),
                    {max_client_id + 1},
                    false
                )
            """))
            
            session.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('"StreemLyne_MT"."Project_Details"', 'project_id'),
                    {max_project_id + 1},
                    false
                )
            """))
            
            session.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('"StreemLyne_MT"."Opportunity_Details"', 'opportunity_id'),
                    {max_opportunity_id + 1},
                    false
                )
            """))
            
            session.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('"StreemLyne_MT"."Energy_Contract_Master"', 'ecm_id'),
                    {max_contract_id + 1},
                    false
                )
            """))
            
            session.commit()
            current_app.logger.info(f"✅ Sequences reset - next IDs: Client={max_client_id + 1}, Project={max_project_id + 1}, Opportunity={max_opportunity_id + 1}, Contract={max_contract_id + 1}")
            
        except Exception as seq_error:
            current_app.logger.warning(f"⚠️ Could not reset sequences: {seq_error}")
        
        current_app.logger.info(f"✅ Successfully deleted customer {actual_client_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer deleted successfully',
            'deleted': {
                'auth': auth_deleted,
                'contracts': contracts_deleted,
                'interactions': interactions_deleted,
                'opportunities': opportunities_deleted,
                'projects': projects_deleted,
                'client': 1
            }
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error deleting customer {client_id}: {str(e)}")
        return jsonify({'error': f'Failed to delete customer: {str(e)}'}), 500
    finally:
        session.close()

# ==========================================
# SEARCH CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients/search', methods=['GET', 'OPTIONS'])
@token_required
def search_energy_customers():
    """Search energy customers"""

    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        if not query_param:
            return jsonify([]), 200
        
        # Search across multiple fields
        results = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Supplier_Master
        ).outerjoin(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                or_(
                    Client_Master.client_company_name.ilike(f'%{query_param}%'),
                    Client_Master.client_contact_name.ilike(f'%{query_param}%'),
                    Client_Master.client_phone.ilike(f'%{query_param}%'),
                    Client_Master.client_email.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_number.ilike(f'%{query_param}%')
                )
            )
        ).limit(20).all()
        
        customers = []
        for client, project, contract, supplier in results:
            customer_data = build_customer_response(client, project, contract, None, None, supplier, None)
            customers.append(customer_data)
        
        current_app.logger.info(f"🔍 Search for '{query_param}' returned {len(customers)} results")
        
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
        
        # By stage
        stage_counts = dict(
            session.query(Stage_Master.stage_name, func.count(Opportunity_Details.opportunity_id))
            .join(Opportunity_Details, Stage_Master.stage_id == Opportunity_Details.stage_id)
            .join(Client_Master, Opportunity_Details.client_id == Client_Master.client_id)
            .filter(Client_Master.tenant_id == tenant_id)
            .group_by(Stage_Master.stage_name)
            .all()
        )
        
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

@energy_customer_bp.route('/energy-clients/bulk-assign', methods=['POST'])
@token_required
def bulk_assign_clients():
    """Bulk assign multiple clients to a salesperson"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        data = request.get_json()
        client_ids = data.get('client_ids', [])
        employee_id = data.get('employee_id')
        
        if not client_ids or not employee_id:
            return jsonify({'error': 'client_ids and employee_id are required'}), 400
        
        user_role = get_user_role_name(request.current_user, session)
        
        # Check permissions - only Platform Admin and Tenant Super Admin
        if user_role not in ['Platform Admin', 'Tenant Super Admin']:
            return jsonify({'error': 'Only administrators can bulk assign clients'}), 403
        
        # Verify employee exists and belongs to tenant
        employee = session.query(Employee_Master).filter(
            Employee_Master.employee_id == employee_id,
            Employee_Master.tenant_id == tenant_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        # ✅ FIX: Update BOTH tables
        updated_count = 0
        for client_id in client_ids:
            # ✅ 1. Update Client_Master.assigned_employee_id
            client = session.query(Client_Master).filter(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            ).first()
            
            if client:
                client.assigned_employee_id = employee_id
                updated_count += 1
            
            # ✅ 2. Update Opportunity_Details
            opportunities = session.query(Opportunity_Details).filter(
                Opportunity_Details.client_id == client_id
            ).all()
            
            for opportunity in opportunities:
                opportunity.opportunity_owner_employee_id = employee_id
        
        session.commit()
        
        current_app.logger.info(f"✅ Bulk assigned {len(client_ids)} clients to {employee.employee_name} (ID: {employee_id})")
        
        return jsonify({
            'message': f'Successfully assigned {len(client_ids)} clients to {employee.employee_name}',
            'updated_count': updated_count,
            'employee_name': employee.employee_name
        })
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error bulk assigning clients: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/search-all', methods=['GET'])
@token_required
def search_all_energy_clients():
    """
    Search across ALL energy clients regardless of assignment
    Used by salespeople to help customers assigned to other team members
    """
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # Get search query
        search_query = request.args.get('q', '').strip()
        service = request.args.get('service', 'utilities')
        
        if not search_query or len(search_query) < 2:
            return jsonify([])  # Return empty if search too short
        
        # Map service to service_id
        service_id_map = {
            'utilities': 1,
            'electricity': 1,
            'gas': 2,
            'water': 3
        }
        service_id = service_id_map.get(service.lower(), 1)
        
        # Build query - search across ALL customers in tenant
        query = session.query(
            Client_Master.client_id,
            Client_Master.client_company_name,
            Client_Master.client_contact_name,
            Client_Master.client_phone,
            Client_Master.client_email,
            Client_Master.address,
            Client_Master.post_code,
            Energy_Contract_Master.mpan_number,
            Energy_Contract_Master.contract_end_date,
            Energy_Contract_Master.unit_rate,
            Supplier_Master.supplier_company_name,
            Project_Details.Misc_Col2.label('annual_usage'),
            Project_Details.address.label('site_address'),
            Opportunity_Details.opportunity_owner_employee_id,
            Employee_Master.employee_name.label('assigned_to_name'),
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
        ).outerjoin(
            Opportunity_Details,
            Client_Master.client_id == Opportunity_Details.client_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).filter(
            Client_Master.tenant_id == tenant_id,
            Energy_Contract_Master.service_id == service_id,
            # Exclude lost and priced
            or_(
                Opportunity_Details.Misc_Col1.is_(None),
                and_(
                    Opportunity_Details.Misc_Col1.isnot(None),
                    ~func.lower(Opportunity_Details.Misc_Col1).in_(['lost', 'lost_cot', 'priced'])
                )
            ),
            # Exclude [IMPORTED LEADS]
            Client_Master.client_company_name != '[IMPORTED LEADS]'
        )
        
        # Apply search filter - search across multiple fields
        search_term = f"%{search_query.lower()}%"
        query = query.filter(
            or_(
                func.lower(Client_Master.client_company_name).like(search_term),
                func.lower(Client_Master.client_contact_name).like(search_term),
                func.lower(Client_Master.client_phone).like(search_term),
                func.lower(Client_Master.client_email).like(search_term),
                func.lower(Energy_Contract_Master.mpan_number).like(search_term),
                func.lower(Supplier_Master.supplier_company_name).like(search_term)
            )
        )
        
        # Limit results to prevent overwhelming response
        results = query.limit(50).all()
        
        # Format results
        customers = []
        for r in results:
            customers.append({
                'id': r.client_id,
                'client_id': r.client_id,
                'business_name': r.client_company_name,
                'contact_person': r.client_contact_name,
                'phone': r.client_phone,
                'email': r.client_email,
                'address': r.address,
                'site_address': r.site_address,
                'post_code': r.post_code,
                'mpan_mpr': r.mpan_number,
                'supplier_name': r.supplier_company_name,
                'annual_usage': r.annual_usage,
                'end_date': r.contract_end_date.isoformat() if r.contract_end_date else None,
                'unit_rate': float(r.unit_rate) if r.unit_rate else None,
                'assigned_to_id': r.opportunity_owner_employee_id,
                'assigned_to_name': r.assigned_to_name,
                'status': r.status,
                'is_assigned_to_others': True  # Flag to show it's from search
            })
        
        return jsonify(customers)
        
    except Exception as e:
        current_app.logger.error(f"Error searching all clients: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/priced', methods=['GET', 'OPTIONS'])
@token_required
def get_priced_customers():
    """Get ONLY priced customers"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        service_param = request.args.get('service')
        _service_id = None
        if service_param and isinstance(service_param, str):
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
        
        # Base query with joins
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details,
            Client_Interactions,
            Supplier_Master,
            Employee_Master,
            Stage_Master
        ).outerjoin(
            Project_Details, 
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Opportunity_Details,
            Client_Master.client_id == Opportunity_Details.client_id
        ).outerjoin(
            Client_Interactions,
            Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).outerjoin(
            Stage_Master,
            Opportunity_Details.stage_id == Stage_Master.stage_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.client_company_name != '[IMPORTED LEADS]',
                # ✅ ONLY priced status
                func.lower(Opportunity_Details.Misc_Col1) == 'priced',
                # Service filter
                *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
            )
        )

        query = query.order_by(Client_Master.created_at.desc())

        # Filter by assigned employee
        query = query.filter(
            Opportunity_Details.opportunity_owner_employee_id == user.employee_id
        )

        results = query.all()
        
        # Build response
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, interaction, supplier, employee, stage in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
            
            customer_data = build_customer_response(
                client, project, contract, opportunity, interaction, supplier, employee
            )
            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
            
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} priced leads for employee_id={user.employee_id}")
        
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
        
        user_role = get_user_role_name(request.current_user, session)
        
        if user_role not in ['Platform Admin', 'Tenant Super Admin']:
            return jsonify({'error': 'Unauthorized - Admin only'}), 403
        
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