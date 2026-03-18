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


def build_customer_response(client, project=None, contract=None, opportunity=None, interaction=None, supplier=None, employee=None, old_supplier=None, stage=None):
    """Build unified customer response from multiple tables"""
    
    # Helper function to safely convert dates to ISO format
    def safe_date_to_iso(date_value):
        """Convert date to ISO string, handling both date objects and strings"""
        if date_value is None:
            return None
        if isinstance(date_value, str):
            return date_value  # Already a string
        if hasattr(date_value, 'isoformat'):
            return date_value.isoformat()  # datetime/date object
        return str(date_value)  # Fallback
    
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
        'created_at': safe_date_to_iso(client.created_at),
        
        # ✅ NEW: Client_Master fields
        'position': getattr(client, 'position', None),
        'company_number': getattr(client, 'company_number', None),
        'date_of_birth': safe_date_to_iso(getattr(client, 'date_of_birth', None)),
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
        
        # From Energy_Contract_Master - ✅ FIX: Use safe_date_to_iso
        'contract_id': contract.energy_contract_master_id if contract else None,
        'mpan_mpr': contract.mpan_number if contract else '',
        'start_date': safe_date_to_iso(contract.contract_start_date if contract else None),
        'end_date': safe_date_to_iso(contract.contract_end_date if contract else None),
        'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
        'terms_of_sale': contract.terms_of_sale if contract else None,

        # ✅ ADD THESE CONTRACT FIELDS:
        'standing_charge': float(contract.standing_charge) if contract and hasattr(contract, 'standing_charge') and contract.standing_charge else None,
        'aggregator': getattr(contract, 'aggregator', None) if contract else None,
        'rate_1': float(contract.rate_1) if contract and hasattr(contract, 'rate_1') and contract.rate_1 else None,
        'payment_type': getattr(contract, 'payment_type', None) if contract else None,  
        
        # ✅ NEW: Energy_Contract_Master fields
        'net_notch': float(contract.net_notch) if contract and hasattr(contract, 'net_notch') and contract.net_notch else None,
        'term_sold': getattr(contract, 'term_sold', None) if contract else None,
        'rate_2': float(contract.rate_2) if contract and hasattr(contract, 'rate_2') and contract.rate_2 else None,
        'rate_3': float(contract.rate_3) if contract and hasattr(contract, 'rate_3') and contract.rate_3 else None,
        'comms_paid': float(contract.comms_paid) if contract and hasattr(contract, 'comms_paid') and contract.comms_paid else None,

        'mpan_top': contract.mpan_number if contract else None,
        'mpan_bottom': contract.mpan_bottom if contract else None,
        'mpan_mpr': contract.mpan_number if contract else None,
        
        # From Supplier_Master (via Energy_Contract_Master)
        'supplier_id': (supplier.supplier_id if supplier else 
                        (contract.supplier_id if contract and hasattr(contract, 'supplier_id') else None)),
        'supplier_name': supplier.supplier_company_name if supplier else '',
        'supplier_contact': supplier.supplier_contact_name if supplier else '',
        'supplier_provisions': supplier.supplier_provisions if supplier else None,
        
        # ✅ NEW: Old Supplier
        'old_supplier_id': (old_supplier.supplier_id if old_supplier else 
                    (contract.old_supplier_id if contract and hasattr(contract, 'old_supplier_id') else None)),
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
        
        # From Client_Interactions - ✅ FIX: Use safe_date_to_iso
        'callback_date': safe_date_to_iso(interaction.reminder_date if interaction else None),
        'last_contact_date': safe_date_to_iso(interaction.contact_date if interaction else None),
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
    
    print("\n" + "="*80)
    print("🚀 GET /energy-clients CALLED - CODE IS RUNNING")
    print("="*80 + "\n")
    
    if request.method == 'OPTIONS':
        print("⚠️ OPTIONS request - returning early")
        return jsonify({}), 200
    
    print("✅ Past OPTIONS check")
    
    session = SessionLocal()
    try:
        print("✅ Session created")
        
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        print(f"✅ Tenant ID: {tenant_id}, Employee ID: {user.employee_id}")
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        # Service filter
        _service_id = None
        service_param = request.args.get('service')
        if service_param and isinstance(service_param, str):
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
        
        print(f"✅ Service ID: {_service_id}")
        
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
                Client_Master.is_deleted == False,
                Client_Master.is_archived == False,
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

        print("✅ About to execute query")
        
        results = query.all()
        
        print(f"🔍 QUERY RETURNED {len(results)} TOTAL RESULTS")
        
        # ✅ NEW: Fetch assignment notes for all customers
        client_ids = list(set([client.client_id for client, _, _, _, _, _, _, _ in results]))
        assignment_notes_map = {}
        
        if client_ids:
            print(f"📝 Fetching assignment notes for {len(client_ids)} clients")
            
            # Get latest assignment note for each client
            assignment_notes_query = text("""
                SELECT DISTINCT ON (client_id)
                    client_id,
                    notes
                FROM "StreemLyne_MT"."Client_Interactions"
                WHERE client_id = ANY(:client_ids)
                AND next_steps = 'Assignment'
                ORDER BY client_id, created_at DESC
            """)
            
            try:
                assignment_notes_result = session.execute(
                    assignment_notes_query,
                    {'client_ids': client_ids}
                )
                
                # Extract just the note part (after "Assigned to [Name] - ")
                for row in assignment_notes_result:
                    if row.notes:
                        # Remove the "Assigned to [Name] - " prefix
                        note_parts = row.notes.split(' - ', 1)
                        if len(note_parts) > 1:
                            assignment_notes_map[row.client_id] = note_parts[1]
                        else:
                            assignment_notes_map[row.client_id] = row.notes
                
                print(f"✅ Loaded {len(assignment_notes_map)} assignment notes")
                
            except Exception as notes_error:
                print(f"⚠️ Error loading assignment notes: {notes_error}")
                # Continue without notes if there's an error
        
        # Build response
        customers = []
        seen_clients = set()

        for client, project, contract, opportunity, interaction, supplier, employee, stage in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
            
            print(f"🔍 Processing customer tenant_client_id={client.tenant_client_id}, client_id={client.client_id}")
            
            customer_data = build_customer_response(
                client, project, contract, opportunity, interaction, supplier, employee, None, stage
            )

            print(f"   - opportunity exists: {opportunity is not None}")
            if opportunity:
                print(f"   - opportunity.Misc_Col1: '{opportunity.Misc_Col1}'")
                print(f"   - opportunity.stage_id: {opportunity.stage_id}")
            print(f"   - customer_data['status'] BEFORE override: {customer_data['status']}")

            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
                print(f"   - customer_data['status'] AFTER override: '{customer_data['status']}'")
            else:
                print(f"   - ⚠️ NO OVERRIDE - opportunity.Misc_Col1 is NULL or opportunity is None")

            # ✅ NEW: Add assignment notes to customer data
            customer_data['assignment_notes'] = assignment_notes_map.get(client.client_id)
            
            customers.append(customer_data)
        
        print(f"✅ Returning {len(customers)} renewals for employee_id={user.employee_id}")
        
        return jsonify(customers), 200

    except Exception as e:
        print(f"❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
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

        # Fetch old supplier
        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()

        stage = None
        if opportunity and opportunity.stage_id:
            stage = session.query(Stage_Master).filter_by(stage_id=opportunity.stage_id).first()

        customer_data = build_customer_response(
            client, project, contract, opportunity, interaction, supplier, employee, old_supplier, stage
        )

        if opportunity and opportunity.Misc_Col1:
            customer_data['status'] = opportunity.Misc_Col1

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
        current_app.logger.info(f"📝 Received data: {data}")  # ✅ Debug log

        assigned_employee_id = data.get('assigned_to_id') or request.current_user.employee_id

        # ✅ Map service string to service_id
        service_string = data.get('service', 'utilities')
        service_id = 1 if service_string == 'utilities' else 2
        
        # ✅ Auto-archive logic
        should_archive, archive_reason = auto_archive_older_contracts(
            session=session,
            tenant_id=tenant_id,
            business_name=data.get('business_name', ''),
            mpan_top=data.get('mpan_top', ''),  # ✅ Use mpan_top
            mpan_bottom=data.get('mpan_bottom', ''),
            new_end_date=data.get('end_date'),
            service_id=service_id
        )
        
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
            default_currency_id=data.get('currency_id', 1),
            is_archived=should_archive,
            archived_at=datetime.utcnow() if should_archive else None,
            archived_reason=archive_reason,
            created_at=datetime.utcnow()
        )
        session.add(new_client)
        session.flush()
        
        client_id = new_client.client_id
        current_app.logger.info(f"✅ Created Client_Master: {client_id}")
        
        # 2. Get default stage for opportunity
        default_stage_query = session.query(Stage_Master).order_by(Stage_Master.stage_id).first()
        default_stage_id = default_stage_query.stage_id if default_stage_query else 1
        
        # 3. Create Opportunity_Details
        opportunity = Opportunity_Details(
            client_id=client_id,
            opportunity_title=f"Energy Renewal - {data.get('business_name', 'Unknown')}",
            opportunity_description=f"Energy contract renewal for {data.get('business_name', 'Unknown')}",
            opportunity_owner_employee_id=assigned_employee_id,
            stage_id=default_stage_id,
            created_at=datetime.utcnow()
        )
        session.add(opportunity)
        session.flush()
        current_app.logger.info(f"✅ Created Opportunity_Details: {opportunity.opportunity_id}")
        
        # ✅ 4. ALWAYS create Project_Details (not conditional)
        project = Project_Details(
            client_id=client_id,
            opportunity_id=opportunity.opportunity_id,
            project_title=f"Site - {data.get('business_name', 'Unknown')}",
            project_description='Primary site location',
            address=data.get('site_address') or data.get('address', ''),
            Misc_Col2=data.get('annual_usage'),  # Annual Usage in kWh
            employee_id=request.current_user.employee_id,
            start_date=data.get('start_date'),
            created_at=datetime.utcnow()
        )
        session.add(project)
        session.flush()
        current_app.logger.info(f"✅ Created Project_Details: {project.project_id}")
        
        # ✅ 5. ALWAYS create Energy_Contract_Master (not conditional)
        mpan_top = data.get('mpan_top', '').strip()
        mpan_bottom = data.get('mpan_bottom', '').strip()
        
        current_app.logger.info(f"📋 MPAN fields - Top: '{mpan_top}', Bottom: '{mpan_bottom}'")
        
        contract = Energy_Contract_Master(
            project_id=project.project_id,
            employee_id=request.current_user.employee_id,
            supplier_id=data.get('supplier_id'),
            mpan_number=mpan_top,  # ✅ Store MPAN top as main number
            mpan_bottom=mpan_bottom,  # ✅ Store MPAN bottom separately
            contract_start_date=data.get('start_date'),
            contract_end_date=data.get('end_date'),
            unit_rate=data.get('unit_rate'),
            currency_id=data.get('currency_id', 1),
            service_id=service_id,  # ✅ Use mapped service_id
            terms_of_sale=data.get('terms_of_sale', ''),
            created_at=datetime.utcnow()
        )
        session.add(contract)
        session.flush()
        current_app.logger.info(f"✅ Created Energy_Contract_Master: {contract.energy_contract_master_id}")
        
        # 6. Create Client_Interactions (if callback date provided)
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
            current_app.logger.info(f"✅ Created Client_Interactions")
        
        session.commit()
        
        # Fetch complete customer data
        session.refresh(new_client)
        
        # Build response with opportunity
        response_data = build_customer_response(
            new_client, project, contract, opportunity, None, None, None, None, None
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
            if 'site_name' in data:
                project.site_name = data['site_name']
            if 'month_sold' in data:
                project.month_sold = data['month_sold']
            if 'house_name' in data:
                project.house_name = data['house_name']
            if 'house_number' in data:
                project.house_number = data['house_number']
            if 'door_number' in data:
                project.door_number = data['door_number']
            if 'town' in data:
                project.town = data['town']
            if 'county' in data:
                project.county = data['county']
            project.updated_at = datetime.utcnow()
        elif data.get('site_address') or data.get('annual_usage'):
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
                if 'old_supplier_id' in data:
                    val = data['old_supplier_id']
                    contract.old_supplier_id = None if (val is None or val == 0) else val
                if 'start_date' in data and data['start_date']:
                    if isinstance(data['start_date'], str):
                        contract.contract_start_date = datetime.fromisoformat(data['start_date'].replace('Z', '')).date()
                    else:
                        contract.contract_start_date = data['start_date']
                if 'end_date' in data and data['end_date']:
                    if isinstance(data['end_date'], str):
                        contract.contract_end_date = datetime.fromisoformat(data['end_date'].replace('Z', '')).date()
                    else:
                        contract.contract_end_date = data['end_date']
                if 'unit_rate' in data and data['unit_rate'] is not None:
                    contract.unit_rate = data['unit_rate']
                if 'terms_of_sale' in data:
                    contract.terms_of_sale = data['terms_of_sale']
                if 'payment_type' in data:
                    contract.payment_type = data['payment_type']
                contract.updated_at = datetime.utcnow()
                
            elif data.get('mpan_mpr') or data.get('supplier_id'):
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
        
        # Track assignment changes for interaction logging
        old_assigned_to = None
        new_assigned_to = None
        assignment_notes = data.get('assignment_notes')
        
        # Update Opportunity_Details
        opportunity = session.query(Opportunity_Details).filter_by(client_id=client_id).first()
        if opportunity:
            if 'stage_id' in data:
                opportunity.stage_id = data['stage_id']
            if 'status' in data:
                status_value = data['status']
                if status_value in ['None', 'null', '', None]:
                    opportunity.Misc_Col1 = None
                else:
                    opportunity.Misc_Col1 = status_value
            if 'assigned_to_id' in data:
                old_assigned_to = opportunity.opportunity_owner_employee_id
                new_assigned_to = data['assigned_to_id']
                opportunity.opportunity_owner_employee_id = new_assigned_to
                current_app.logger.info(f"✅ Updated assignment from {old_assigned_to} to {new_assigned_to}")
            if 'opportunity_value' in data:
                opportunity.opportunity_value = data['opportunity_value']
        
        # Create interaction for assignment change with notes
        if old_assigned_to != new_assigned_to and 'assigned_to_id' in data:
            if new_assigned_to:
                employee = session.query(Employee_Master).filter_by(
                    employee_id=new_assigned_to
                ).first()
                employee_name = employee.employee_name if employee else "Unknown"
            else:
                employee_name = "Unassigned"
            
            interaction_notes = f"Assigned to {employee_name}"
            if assignment_notes:
                interaction_notes += f" - {assignment_notes}"
            
            assignment_interaction = Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=interaction_notes,
                next_steps="Assignment",
                created_at=datetime.utcnow()
            )
            session.add(assignment_interaction)
            current_app.logger.info(f"✅ Created assignment interaction: {interaction_notes}")
        
        # Handle callback_date and interaction_notes
        if data.get('callback_date') or data.get('interaction_notes'):
            interaction_check = session.execute(text("""
                SELECT interaction_id 
                FROM "StreemLyne_MT"."Client_Interactions"
                WHERE client_id = :client_id
                ORDER BY created_at DESC
                LIMIT 1
            """), {'client_id': client_id}).fetchone()
            
            if interaction_check:
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
            Employee_Master,
            Stage_Master
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
        ).outerjoin(
            Stage_Master, Opportunity_Details.stage_id == Stage_Master.stage_id
        ).filter(
            Client_Master.client_id == client_id
        ).first()
        
        client, project, contract, opportunity, interaction, supplier, employee, stage = updated_result

        # ✅ Fetch old supplier for the response
        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()

        response_data = build_customer_response(
            client, project, contract, opportunity, interaction, supplier, employee, old_supplier, stage
        )
        
        if opportunity and opportunity.Misc_Col1:
            response_data['status'] = opportunity.Misc_Col1

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
        
        # ✅ Get employee_id BEFORE deletion for display_order recalculation
        assigned_employee_id = client.assigned_employee_id
        
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
        session.flush()
        
        # ✅ Recalculate display_order for the employee who lost this record
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        
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
        current_app.logger.info(f"✅ Recalculated display_order for employee_id={assigned_employee_id}")
        
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
    """Search energy customers - returns ALL results regardless of assignment"""

    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        if not query_param:
            return jsonify([]), 200
        
        # ✅ COMPLETE QUERY: Search across ALL customers with full data
        results = session.query(
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
        
        # ✅ Build complete response
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, interaction, supplier, employee, stage in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            
            # ✅ Fetch old supplier if exists
            old_supplier = None
            if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
                old_supplier = session.query(Supplier_Master).filter_by(
                    supplier_id=contract.old_supplier_id
                ).first()
            
            # ✅ Use build_customer_response for consistency
            customer_data = build_customer_response(
                client, project, contract, opportunity, interaction, supplier, employee, old_supplier, stage
            )
            
            # ✅ Ensure these fields are explicitly set (redundant but safe)
            if contract:
                customer_data['mpan_top'] = contract.mpan_number or ''
                customer_data['mpan_bottom'] = contract.mpan_bottom or ''
                customer_data['start_date'] = contract.contract_start_date.isoformat() if contract.contract_start_date else None
                customer_data['end_date'] = contract.contract_end_date.isoformat() if contract.contract_end_date else None
            
            if client:
                customer_data['phone'] = client.client_phone or ''
            
            # ✅ Prioritize Misc_Col1 if it exists
            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
            
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

@energy_customer_bp.route('/energy-clients/bulk-assign', methods=['POST', 'OPTIONS'])
@token_required
def bulk_assign_clients():
    """Bulk assign multiple clients to a salesperson"""
    
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
        
        # Verify employee exists and belongs to tenant
        employee = session.query(Employee_Master).filter(
            Employee_Master.employee_id == employee_id,
            Employee_Master.tenant_id == tenant_id
        ).first()
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        # ✅ Track old employee IDs for display_order recalculation
        old_employee_ids = set()
        
        # ✅ Update BOTH tables + create interactions
        updated_count = 0
        for client_id in client_ids:
            # 1. Update Client_Master.assigned_employee_id
            client = session.query(Client_Master).filter(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            ).first()
            
            if client:
                # ✅ Track the old employee ID
                if client.assigned_employee_id:
                    old_employee_ids.add(client.assigned_employee_id)
                
                client.assigned_employee_id = employee_id
                updated_count += 1
            
            # 2. Update Opportunity_Details
            opportunities = session.query(Opportunity_Details).filter(
                Opportunity_Details.client_id == client_id
            ).all()
            
            for opportunity in opportunities:
                opportunity.opportunity_owner_employee_id = employee_id
            
            # ✅ 3. Create interaction for assignment with notes
            interaction_notes = f"Assigned to {employee.employee_name}"
            if assignment_notes:
                interaction_notes += f" - {assignment_notes}"
            
            assignment_interaction = Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,  # Internal note
                notes=interaction_notes,
                next_steps="Assignment",
                created_at=datetime.utcnow()
            )
            session.add(assignment_interaction)
        
        # ✅ Commit the changes first
        session.commit()
        
        # ✅ Recalculate display_order for all affected employees
        # Recalculate for the old employees (records were removed from their list)
        for old_emp_id in old_employee_ids:
            recalculate_display_order(session, tenant_id, old_emp_id)
        
        # Recalculate for the new employee (records were added to their list)
        recalculate_display_order(session, tenant_id, employee_id)
        
        # ✅ Commit the display_order changes
        session.commit()
        
        current_app.logger.info(f"✅ Bulk assigned {len(client_ids)} clients to {employee.employee_name} (ID: {employee_id})")
        current_app.logger.info(f"✅ Recalculated display_order for {len(old_employee_ids) + 1} employees")
        
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
    """
    Search energy customers across ALL tenants (for cross-tenant search)
    Returns COMPLETE data including MPAN, phone, dates, etc.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        service_param = request.args.get('service', 'utilities').strip().lower()
        
        if not query_param:
            return jsonify([]), 200
        
        # ✅ Map service to service_id
        service_id_map = {
            'utilities': 1,
            'electricity': 1,
            'water': 2,
            'gas': 3
        }
        service_id = service_id_map.get(service_param, 1)
        
        current_app.logger.info(f"🔍 Cross-tenant search for '{query_param}' (service: {service_param})")
        
        # ✅ CROSS-TENANT SEARCH: No tenant filter, but filter by service
        results = session.query(
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
            Client_Master.assigned_employee_id == Employee_Master.employee_id
        ).outerjoin(
            Stage_Master,
            Opportunity_Details.stage_id == Stage_Master.stage_id
        ).filter(
            and_(
                Client_Master.is_deleted == False,
                or_(
                    Energy_Contract_Master.service_id == service_id,
                    Energy_Contract_Master.service_id == None  # Include records without contracts
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
        
        # ✅ Build complete response with ALL fields
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, interaction, supplier, employee, stage in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            
            # ✅ Fetch old supplier if exists
            old_supplier = None
            if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
                old_supplier = session.query(Supplier_Master).filter_by(
                    supplier_id=contract.old_supplier_id
                ).first()
            
            # ✅ Build COMPLETE customer response - EVERY field must be included
            customer_data = {
                'id': client.client_id,
                'client_id': client.client_id,
                'display_id': client.tenant_client_id if hasattr(client, 'tenant_client_id') else None,
                'display_order': client.display_order,
                'name': client.client_contact_name or '',
                'business_name': client.client_company_name or '',
                'contact_person': client.client_contact_name or '',
                'phone': client.client_phone or '',  # ✅ CRITICAL
                'email': client.client_email or '',
                'address': client.address or '',
                'site_address': project.address if project else '',
                
                # ✅ Energy specific fields - MUST include ALL of these
                'mpan_mpr': contract.mpan_number if contract else '',
                'mpan_top': contract.mpan_number if contract else '',  # ✅ CRITICAL
                'mpan_bottom': contract.mpan_bottom if contract else '',  # ✅ CRITICAL
                'supplier_id': contract.supplier_id if contract else None,
                'supplier_name': supplier.supplier_company_name if supplier else '',
                'annual_usage': project.Misc_Col2 if project and hasattr(project, 'Misc_Col2') else None,
                'start_date': contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,  # ✅ CRITICAL
                'end_date': contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
                'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
                
                # Pipeline fields
                'status': opportunity.Misc_Col1 if opportunity and opportunity.Misc_Col1 else (stage.stage_name if stage else None),
                'stage_id': opportunity.stage_id if opportunity else None,
                'opportunity_id': opportunity.opportunity_id if opportunity else None,
                
                # ✅ Assignment - show who owns the record
                'assigned_to_id': client.assigned_employee_id,
                'assigned_to_name': employee.employee_name if employee else None,
                'assignment_notes': client.assignment_notes if hasattr(client, 'assignment_notes') else None,
                
                'created_at': client.created_at.isoformat() if client.created_at else None,
                
                # ✅ Archive status
                'is_archived': client.is_archived if hasattr(client, 'is_archived') else False,
                
                # ✅ Additional fields
                'position': client.position if hasattr(client, 'position') else None,
                'company_number': client.company_number if hasattr(client, 'company_number') else None,
                'site_name': project.site_name if project and hasattr(project, 'site_name') else None,
                'old_supplier_name': old_supplier.supplier_company_name if old_supplier else None,
            }
            
            customers.append(customer_data)
        
        current_app.logger.info(f"🔍 Cross-tenant search for '{query_param}' returned {len(customers)} results")
        
        return jsonify(customers), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error in cross-tenant search: {e}")
        return jsonify({'error': 'Failed to search customers'}), 500
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
        
        # ✅ Get salesperson filter (optional, admin only)
        salesperson_param = request.args.get('salesperson')
        
        # ✅ DEBUG LOG
        current_app.logger.info(f"🔍 Priced request - salesperson_param: {salesperson_param}")
        
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

        # ✅ CRITICAL FIX: Apply employee filter based on role BEFORE order_by
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
        
        if is_admin:
            # ✅ Admin: Optional filter by salesperson
            if salesperson_param and salesperson_param != "All":
                try:
                    salesperson_id = int(salesperson_param)
                    query = query.filter(
                        Opportunity_Details.opportunity_owner_employee_id == salesperson_id
                    )
                    current_app.logger.info(f"✅ Admin filtering priced by salesperson_id={salesperson_id}")
                except ValueError:
                    current_app.logger.warning(f"⚠️ Invalid salesperson_id: {salesperson_param}")
            else:
                current_app.logger.info(f"ℹ️ Admin viewing all priced leads (no filter)")
        else:
            # ✅ Salesperson: Only see their own priced leads
            query = query.filter(
                Opportunity_Details.opportunity_owner_employee_id == user.employee_id
            )
            current_app.logger.info(f"ℹ️ Salesperson viewing own priced leads (employee_id={user.employee_id})")

        # ✅ Sort AFTER applying filters
        query = query.order_by(Client_Master.created_at.desc())

        results = query.all()
        
        # ✅ DEBUG LOG
        current_app.logger.info(f"📊 Query returned {len(results)} priced leads")
        
        # Build response
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, interaction, supplier, employee, stage in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
            
            customer_data = build_customer_response(
                client, project, contract, opportunity, interaction, supplier, employee, None, stage
            )
            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
            
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} priced leads (admin={is_admin}, filter={salesperson_param or 'none'})")
        
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
    """
    Get all soft-deleted customers from recycle bin
    Shows only deleted records (is_deleted = TRUE)
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        # Service filter
        service_param = request.args.get('service', 'utilities')
        service_id_map = {'utilities': 1, 'water': 2, 'gas': 3}
        service_id = service_id_map.get(service_param.strip().lower(), 1)
        
        # Base query - ONLY get deleted records
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details,
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
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_deleted == True,  # ✅ Only deleted records
                *([Energy_Contract_Master.service_id == service_id] if service_id is not None else [])
            )
        )

        # Sort by most recently deleted first
        query = query.order_by(Client_Master.deleted_at.desc())

        # Filter by employee (each user sees their own deleted records)
        query = query.filter(
            Opportunity_Details.opportunity_owner_employee_id == user.employee_id
        )

        results = query.all()
        
        # Build response
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            
            stage = None
            if opportunity and opportunity.stage_id:
                stage = session.query(Stage_Master).filter_by(stage_id=opportunity.stage_id).first()

            customer_data = build_customer_response(
                client, project, contract, opportunity, None, supplier, employee, None, stage
            )

            # ✅ Prioritize Misc_Col1
            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
            
            # ✅ Add deletion metadata
            customer_data['is_deleted'] = True
            customer_data['deleted_at'] = client.deleted_at.isoformat() if client.deleted_at else None
            customer_data['deleted_reason'] = client.deleted_reason
            
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} deleted records for employee_id={user.employee_id}")
        
        return jsonify(customers), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching recycle bin: {e}")
        return jsonify({'error': 'Failed to fetch recycle bin'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/restore', methods=['POST', 'OPTIONS'])
@token_required
def restore_customer(client_id):
    """
    Restore a customer from recycle bin
    Sets is_deleted = FALSE, clears deletion metadata, and recalculates display_order
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the deleted client
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id,
            is_deleted=True  # Must be in recycle bin
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found in recycle bin'}), 404
        
        # Get employee_id for display_order recalculation
        assigned_employee_id = client.assigned_employee_id
        
        # Restore the customer
        client.is_deleted = False
        client.deleted_at = None
        client.deleted_reason = None
        
        # Clear Opportunity status
        opportunity = session.query(Opportunity_Details).filter_by(client_id=client_id).first()
        if opportunity and opportunity.Misc_Col1:
            # Clear the deletion status (lost_cot, invalid_number, meter_de-energised)
            # if opportunity.Misc_Col1.lower() in ['lost_cot', 'invalid_number', 'meter_de-energised']:
            opportunity.Misc_Col1 = None
        
        # Commit the restore change
        session.flush()
        
        # ✅ Recalculate display_order for the employee who gained this record
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        
        session.commit()
        
        current_app.logger.info(f"✅ Restored customer {client_id} from recycle bin")
        current_app.logger.info(f"✅ Recalculated display_order for employee_id={assigned_employee_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer restored successfully'
        }), 200
        
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
    Permanently delete a customer from recycle bin
    This is a HARD DELETE - removes from database completely
    Can only delete records that are already in recycle bin (is_deleted = TRUE)
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the client - MUST be in recycle bin
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id,
            is_deleted=True  # ✅ Only allow permanent delete from recycle bin
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found in recycle bin'}), 404
        
        current_app.logger.info(f"🗑️ Permanently deleting customer {client_id}: {client.client_company_name}")
        
        # ============================================
        # HARD DELETE: Delete in correct order (child → parent)
        # ============================================
        
        # 1. Find all projects for this client
        projects = session.query(Project_Details).filter_by(client_id=client_id).all()
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
            client_id=client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {interactions_deleted} interactions")
        
        # 4. Delete Invoice_Details and Invoice_Master
        invoice_ids = [inv.invoice_id for inv in session.query(Invoice_Master).filter_by(client_id=client_id).all()]
        invoices_deleted = 0
        if invoice_ids:
            session.query(Invoice_Details).filter(Invoice_Details.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
            invoices_deleted = session.query(Invoice_Master).filter_by(client_id=client_id).delete(synchronize_session=False)
            current_app.logger.info(f"   📋 Deleted {invoices_deleted} invoices")
        
        # 5. Delete Proposal_Details and Proposal_Master
        proposal_ids = [prop.proposal_id for prop in session.query(Proposal_Master).filter_by(client_id=client_id).all()]
        proposals_deleted = 0
        if proposal_ids:
            session.query(Proposal_Details).filter(Proposal_Details.proposal_id.in_(proposal_ids)).delete(synchronize_session=False)
            proposals_deleted = session.query(Proposal_Master).filter_by(client_id=client_id).delete(synchronize_session=False)
            current_app.logger.info(f"   📋 Deleted {proposals_deleted} proposals")
        
        # 6. Delete Opportunity_Details (references client_id)
        opportunities_deleted = session.query(Opportunity_Details).filter_by(
            client_id=client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {opportunities_deleted} opportunities")
        
        # 7. Delete Project_Details (references client_id and opportunity_id)
        projects_deleted = session.query(Project_Details).filter_by(
            client_id=client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {projects_deleted} projects")
        
        # 8. Finally delete Client_Master
        session.delete(client)
        
        # Commit all deletions
        session.commit()
        
        current_app.logger.info(f"✅ Permanently deleted customer {client_id} from recycle bin")
        
        return jsonify({
            'success': True,
            'message': 'Customer permanently deleted',
            'deleted': {
                'contracts': contracts_deleted,
                'interactions': interactions_deleted,
                'invoices': invoices_deleted,
                'proposals': proposals_deleted,
                'opportunities': opportunities_deleted,
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
    """
    Get all archived customers
    Shows historical records that have been superseded by newer contracts
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        # Service filter
        service_param = request.args.get('service', 'utilities')
        service_id_map = {'utilities': 1, 'water': 2, 'gas': 3}
        service_id = service_id_map.get(service_param.strip().lower(), 1)
        
        # ✅ Get salesperson filter (optional, admin only)
        salesperson_param = request.args.get('salesperson')
        
        # ✅ DEBUG LOG
        current_app.logger.info(f"🔍 Archives request - salesperson_param: {salesperson_param}")
        
        # Base query - ONLY get archived records
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Opportunity_Details,
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
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Opportunity_Details.opportunity_owner_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_archived == True,  # ✅ Only archived records
                *([Energy_Contract_Master.service_id == service_id] if service_id is not None else [])
            )
        )

        # ✅ CRITICAL FIX: Apply employee filter BEFORE order_by
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
        
        if is_admin:
            # ✅ Admin: Optional filter by salesperson
            if salesperson_param and salesperson_param != "All":
                try:
                    salesperson_id = int(salesperson_param)
                    query = query.filter(
                        Opportunity_Details.opportunity_owner_employee_id == salesperson_id
                    )
                    current_app.logger.info(f"✅ Admin filtering archives by salesperson_id={salesperson_id}")
                except ValueError:
                    current_app.logger.warning(f"⚠️ Invalid salesperson_id: {salesperson_param}")
            else:
                current_app.logger.info(f"ℹ️ Admin viewing all archived records (no filter)")
        else:
            # ✅ Salesperson: Only see their own archived records
            query = query.filter(
                Opportunity_Details.opportunity_owner_employee_id == user.employee_id
            )
            current_app.logger.info(f"ℹ️ Salesperson viewing own archives (employee_id={user.employee_id})")

        # ✅ Sort AFTER applying filters
        query = query.order_by(Energy_Contract_Master.contract_end_date.desc())

        results = query.all()
        
        # ✅ DEBUG LOG
        current_app.logger.info(f"📊 Query returned {len(results)} archived records")
        
        # Build response
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            
            stage = None
            if opportunity and opportunity.stage_id:
                stage = session.query(Stage_Master).filter_by(stage_id=opportunity.stage_id).first()

            customer_data = build_customer_response(
                client, project, contract, opportunity, None, supplier, employee, None, stage
            )

            # ✅ Prioritize Misc_Col1
            if opportunity and opportunity.Misc_Col1:
                customer_data['status'] = opportunity.Misc_Col1
            
            # ✅ Add archive metadata
            customer_data['is_archived'] = True
            customer_data['archived_at'] = client.archived_at.isoformat() if client.archived_at else None
            customer_data['archived_reason'] = client.archived_reason
            
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} archived records (admin={is_admin}, filter={salesperson_param or 'none'})")
        
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
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id,
            is_archived=False  # Must not already be archived
        ).first()
        
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
    Recalculate display_order for all active (non-archived, non-deleted) records
    If employee_id is provided, only recalculate for that employee's records
    Otherwise, recalculate for all records in the tenant
    """
    from sqlalchemy import and_
    
    query = session.query(Client_Master).filter(
        and_(
            Client_Master.tenant_id == tenant_id,
            Client_Master.is_deleted == False,
            Client_Master.is_archived == False
        )
    )
    
    if employee_id:
        query = query.filter(Client_Master.assigned_employee_id == employee_id)
    
    # Order by created_at (oldest first)
    clients = query.order_by(Client_Master.created_at.asc()).all()
    
    # Assign sequential display_order
    for idx, client in enumerate(clients, start=1):
        client.display_order = idx
    
    session.flush()
    current_app.logger.info(f"✅ Recalculated display_order for {len(clients)} clients (tenant={tenant_id}, employee={employee_id})")