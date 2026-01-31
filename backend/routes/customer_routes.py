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
from datetime import datetime
from sqlalchemy import and_, or_, func

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
    Stage_Master
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


def build_customer_response(client, project=None, contract=None, opportunity=None, interaction=None, supplier=None, employee=None):
    """Build unified customer response from multiple tables"""
    response = {
        # From Client_Master
        'id': client.client_id,
        'client_id': client.client_id,
        'name': client.client_contact_name or '',
        'business_name': client.client_company_name or '',
        'contact_person': client.client_contact_name or '',
        'phone': client.client_phone or '',
        'email': client.client_email or '',
        'address': client.address or '',
        'post_code': client.post_code or '',
        'website': client.client_website or '',
        'created_at': client.created_at.isoformat() if client.created_at else None,
        
        # From Project_Details (Site address & Annual Usage)
        'project_id': project.project_id if project else None,
        'site_address': project.address if project else client.address,
        'annual_usage': project.Misc_Col2 if project else None,
        'project_title': project.project_title if project else None,
        
        # From Energy_Contract_Master
        'contract_id': contract.energy_contract_master_id if contract else None,
        'mpan_mpr': contract.mpan_number if contract else '',
        'start_date': contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,
        'end_date': contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
        'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
        'terms_of_sale': contract.terms_of_sale if contract else None,
        
        # From Supplier_Master (via Energy_Contract_Master)
        'supplier_id': supplier.supplier_id if supplier else None,
        'supplier_name': supplier.supplier_company_name if supplier else '',
        'supplier_contact': supplier.supplier_contact_name if supplier else '',
        'supplier_provisions': supplier.supplier_provisions if supplier else None,
        
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


# ==========================================
# GET ALL CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customers():
    """Get all energy customers with joined data"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # ✅ Debug logging
        current_app.logger.info(f"🔍 Current user: employee_id={request.current_user.employee_id if hasattr(request.current_user, 'employee_id') else 'N/A'}")
        
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        current_app.logger.info(f"🏢 Tenant ID resolved: {tenant_id}")
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
        
        # Complex query joining all relevant tables
        query = session.query(
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
            Client_Master.tenant_id == tenant_id
        ).order_by(
            Client_Master.created_at.desc()
        )
        
        # ✅ Apply role-based filtering (TODO: implement proper role checking)
        # Note: UserMaster doesn't have a 'role' field directly
        # Will need to check Employee_Master.role_ids or implement custom role logic
        
        results = query.all()
        
        current_app.logger.info(f"📊 Fetching {len(results)} energy customers for tenant {tenant_id}")
        
        # Build response for each customer
        customers = []
        seen_clients = set()
        
        for client, project, contract, opportunity, interaction, supplier, employee in results:
            # Avoid duplicates if a client has multiple projects/contracts
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            
            customer_data = build_customer_response(
                client, project, contract, opportunity, interaction, supplier, employee
            )
            customers.append(customer_data)
        
        current_app.logger.info(f"✅ Returning {len(customers)} unique energy customers")
        
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
        
        # Query with all joins
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
        
        # TODO: Permission check for Staff role
        
        customer_data = build_customer_response(
            client, project, contract, opportunity, interaction, supplier, employee
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
        
        # 1. Create Client_Master entry
        new_client = Client_Master(
            tenant_id=tenant_id,
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
        
        # 4. Create Opportunity_Details (Sales Pipeline)
        opportunity = Opportunity_Details(
            client_id=client_id,
            opportunity_title=f"Opportunity - {data.get('business_name', 'Unknown')}",
            opportunity_description='Energy supply opportunity',
            opportunity_date=datetime.utcnow().date(),
            opportunity_owner_employee_id=data.get('assigned_to_id', request.current_user.employee_id),
            stage_id=data.get('stage_id', 1),  # Default to first stage
            opportunity_value=data.get('opportunity_value', 0),
            currency_id=data.get('currency_id', 1),
            created_at=datetime.utcnow()
        )
        session.add(opportunity)
        session.flush()
        current_app.logger.info(f"✅ Created Opportunity_Details: {opportunity.opportunity_id}")
        
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
        
        # Build response
        response_data = build_customer_response(
            new_client, project, contract, opportunity, None, None, None
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
        data = request.get_json()
        
        # Fetch client
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found'}), 404
        
        # TODO: Permission check for Staff role
        
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
            if 'assigned_to_id' in data:
                opportunity.opportunity_owner_employee_id = data['assigned_to_id']
            if 'opportunity_value' in data:
                opportunity.opportunity_value = data['opportunity_value']
        
        # Update Client_Interactions
        if data.get('callback_date'):
            interaction = session.query(Client_Interactions).filter_by(
                client_id=client_id
            ).order_by(Client_Interactions.created_at.desc()).first()
            
            if interaction:
                interaction.reminder_date = data['callback_date']
                if data.get('interaction_notes'):
                    interaction.notes = data['interaction_notes']
            else:
                interaction = Client_Interactions(
                    client_id=client_id,
                    contact_date=datetime.utcnow().date(),
                    reminder_date=data['callback_date'],
                    notes=data.get('interaction_notes', ''),
                    created_at=datetime.utcnow()
                )
                session.add(interaction)
        
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
        # TODO: Only Admin can delete - implement proper role checking
        
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found'}), 404
        
        current_app.logger.info(f"🗑️ Deleting energy customer {client_id} and all related records")
        
        # Delete in reverse order of dependencies
        
        # 1. Delete Client_Interactions
        session.query(Client_Interactions).filter_by(client_id=client_id).delete()
        
        # 2. Delete Energy_Contract_Master (via projects)
        projects = session.query(Project_Details).filter_by(client_id=client_id).all()
        for project in projects:
            session.query(Energy_Contract_Master).filter_by(project_id=project.project_id).delete()
        
        # 3. Delete Opportunity_Details
        session.query(Opportunity_Details).filter_by(client_id=client_id).delete()
        
        # 4. Delete Project_Details
        session.query(Project_Details).filter_by(client_id=client_id).delete()
        
        # 5. Delete Client_Master
        session.delete(client)
        
        session.commit()
        
        current_app.logger.info(f"✅ Energy customer {client_id} deleted successfully")
        
        return jsonify({
            'success': True,
            'message': 'Customer and all related records deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting energy customer {client_id}: {e}")
        return jsonify({'error': 'Failed to delete customer'}), 500
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