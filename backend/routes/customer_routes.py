"""
Simplified Customer Routes for Forklift Academy CRM
Only includes Customer model with dual pipeline system
Removed: Project, CustomerFormData, DrawingDocument, FormDocument, ProductionNotification
"""

from flask import Blueprint, request, jsonify, current_app
from ..models import Customer, User
from .auth_helpers import token_required
import uuid
from datetime import datetime

from ..db import SessionLocal

customer_bp = Blueprint('customers', __name__)


# ==========================================
# CUSTOMER ENDPOINTS
# ==========================================

@customer_bp.route('/clients', methods=['GET', 'OPTIONS'])
@token_required
def get_customers():
    """Get all customers with their pipeline information"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Get all customers
        customers = session.query(Customer).all()
        
        current_app.logger.info(f"📊 Fetching {len(customers)} customers")
        
        result = []
        for customer in customers:
            customer_data = customer.to_dict()
            result.append(customer_data)

        current_app.logger.info(f"✅ Returning {len(result)} customers")
        
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customers: {e}")
        return jsonify({'error': 'Failed to fetch customers'}), 500
    finally:
        session.close()


@customer_bp.route('/clients', methods=['POST'])
@token_required
def create_customer():
    """Create a new customer and automatically create a lead in CRM"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
        
        # Create new customer in local database
        new_customer = Customer(
            id=str(uuid.uuid4()),
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email', ''),
            address=data.get('address', ''),
            salesperson=data.get('salesperson', ''),
            marketing_opt_in=data.get('marketing_opt_in', False),
            notes=data.get('notes', ''),
            contact_made=data.get('contact_made', 'No'),
            preferred_contact_method=data.get('preferred_contact_method', 'Phone'),
            sales_stage='Enquiry',  # Default to first stage in sales pipeline
            pipeline_type='sales',   # Default to sales pipeline
            status='Active',
            created_at=datetime.utcnow(),
            created_by=str(request.current_user.id) if hasattr(request.current_user, 'id') else None
        )
        
        session.add(new_customer)
        session.commit()
        session.refresh(new_customer)
        
        current_app.logger.info(f"✅ Customer {new_customer.id} created by user {request.current_user.id}")
        
        # ✅ NEW: Create lead/opportunity in StreemLyne CRM
        try:
            from backend.crm.repositories.lead_repository import LeadRepository
            lead_repo = LeadRepository()
            
            # Create lead in CRM with tenant ID 1 (default tenant for demo)
            lead_data = {
                'client_id': 1,  # Using default client for now
                'opportunity_title': f"Lead: {new_customer.name}",
                'opportunity_description': f"Phone: {new_customer.phone}\nEmail: {new_customer.email}\nAddress: {new_customer.address}\nNotes: {new_customer.notes}",
                'stage_id': 1,  # Default to first stage
                'opportunity_value': 0,
                'opportunity_owner_employee_id': request.current_user.id if hasattr(request.current_user, 'id') else 1
            }
            
            created_lead = lead_repo.create_lead(1, lead_data)  # Tenant ID 1
            
            if created_lead:
                current_app.logger.info(f"✅ Lead created in CRM for customer {new_customer.id}")
            else:
                current_app.logger.warning(f"⚠️  Could not create lead in CRM for customer {new_customer.id}")
        except Exception as crm_error:
            # Log but don't fail - customer was created successfully
            current_app.logger.warning(f"⚠️  CRM lead creation failed (non-critical): {crm_error}")
        
        return jsonify({
            'success': True,
            'message': 'Customer created successfully and added to leads',
            'customer': new_customer.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/clients/<string:customer_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer(customer_id):
    """Get a single customer by ID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # ✅ Staff can only view customers they created or are assigned to
        if request.current_user.role == 'Staff':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        
        return jsonify(customer.to_dict()), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500
    finally:
        session.close()


@customer_bp.route('/clients/<string:customer_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_customer(customer_id):
    """Update a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions - Staff can only edit their own customers
        if request.current_user.role == 'Staff':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to edit this customer'}), 403
        
        data = request.get_json()
        
        # Update allowed fields
        if 'name' in data:
            customer.name = data['name']
        if 'phone' in data:
            customer.phone = data['phone']
        if 'email' in data:
            customer.email = data['email']
        if 'address' in data:
            customer.address = data['address']
        if 'contact_made' in data:
            customer.contact_made = data['contact_made']
        if 'preferred_contact_method' in data:
            customer.preferred_contact_method = data['preferred_contact_method']
        if 'marketing_opt_in' in data:
            customer.marketing_opt_in = data['marketing_opt_in']
        if 'notes' in data:
            customer.notes = data['notes']
        if 'salesperson' in data:
            customer.salesperson = data['salesperson']
        if 'status' in data:
            customer.status = data['status']
        
        customer.updated_by = str(request.current_user.id) if hasattr(request.current_user, 'id') else None
        customer.updated_at = datetime.utcnow()
        
        session.commit()
        session.refresh(customer)
        
        current_app.logger.info(f"✅ Customer {customer_id} updated")
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully',
            'customer': customer.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error updating customer {customer_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/clients/<string:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(customer_id):
    """
    Update customer stage in pipeline
    Handles auto-transition from Sales to Training pipeline
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        data = request.get_json()
        new_stage = data.get('stage')
        pipeline_type = data.get('pipeline_type', customer.pipeline_type)
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        current_app.logger.info(f"🔄 Updating customer {customer_id} to stage: {new_stage}, pipeline: {pipeline_type}")
        
        old_stage = customer.sales_stage if pipeline_type == 'sales' else customer.training_stage
        old_pipeline = customer.pipeline_type
        
        # ✅ Update the appropriate stage based on pipeline type
        if pipeline_type == 'sales':
            customer.sales_stage = new_stage
            customer.pipeline_type = 'sales'
            
            # ✅ AUTO-TRANSITION: When reaching "Converted", move to Training pipeline
            if new_stage == 'Converted':
                customer.pipeline_type = 'training'
                customer.training_stage = 'Training Scheduled'
                current_app.logger.info(f"✅ Auto-transitioned customer {customer_id} to Training pipeline")
                
        elif pipeline_type == 'training':
            customer.training_stage = new_stage
            customer.pipeline_type = 'training'
        
        customer.updated_by = str(request.current_user.id) if hasattr(request.current_user, 'id') else None
        customer.updated_at = datetime.utcnow()
        
        # Add note about stage change
        stage_change_note = f"\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] Stage changed: {old_stage} → {new_stage} ({pipeline_type} pipeline)"
        if customer.notes:
            customer.notes += stage_change_note
        else:
            customer.notes = stage_change_note.strip()
        
        session.commit()
        session.refresh(customer)
        
        current_app.logger.info(f"✅ Customer stage updated: {old_stage} → {new_stage}")
        
        return jsonify({
            'success': True,
            'customer_id': customer.id,
            'old_stage': old_stage,
            'new_stage': new_stage,
            'old_pipeline': old_pipeline,
            'new_pipeline': customer.pipeline_type,
            'auto_transitioned': new_stage == 'Converted' and pipeline_type == 'sales'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer stage: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/clients/<string:customer_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer(customer_id):
    """Delete a customer (Admin only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Only Admin can delete
        if request.current_user.role != 'Admin':
            return jsonify({'error': 'You do not have permission to delete customers'}), 403
        
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check if customer has associated jobs
        from ..models import Job
        job_count = session.query(Job).filter(Job.customer_id == customer_id).count()
        
        if job_count > 0:
            return jsonify({
                'error': f'Cannot delete customer with {job_count} job(s). Delete jobs first.'
            }), 400
        
        # Check if customer has assignments
        from ..models import Assignment
        assignment_count = session.query(Assignment).filter(Assignment.customer_id == customer_id).count()
        
        if assignment_count > 0:
            return jsonify({
                'error': f'Cannot delete customer with {assignment_count} assignment(s). Delete assignments first.'
            }), 400
        
        session.delete(customer)
        session.commit()
        
        current_app.logger.info(f"✅ Customer {customer_id} deleted by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to delete customer'}), 500
    finally:
        session.close()


@customer_bp.route('/clients/search', methods=['GET', 'OPTIONS'])
@token_required
def search_customers():
    """Search customers by name, email, or phone"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        
        if not query_param:
            return jsonify([]), 200
        
        # Search by name, email, or phone
        customers = session.query(Customer).filter(
            (Customer.name.ilike(f'%{query_param}%')) |
            (Customer.email.ilike(f'%{query_param}%')) |
            (Customer.phone.ilike(f'%{query_param}%'))
        ).limit(20).all()
        
        result = [customer.to_dict() for customer in customers]
        
        current_app.logger.info(f"🔍 Search for '{query_param}' returned {len(result)} results")
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error searching customers: {e}")
        return jsonify({'error': 'Failed to search customers'}), 500
    finally:
        session.close()


@customer_bp.route('/clients/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_stats():
    """Get customer statistics"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        from sqlalchemy import func
        
        # Total customers
        total = session.query(Customer).count()
        
        # By pipeline type
        pipeline_counts = dict(
            session.query(Customer.pipeline_type, func.count(Customer.id))
            .group_by(Customer.pipeline_type)
            .all()
        )
        
        # By sales stage
        sales_stage_counts = dict(
            session.query(Customer.sales_stage, func.count(Customer.id))
            .filter(Customer.pipeline_type == 'sales')
            .group_by(Customer.sales_stage)
            .all()
        )
        
        # By training stage
        training_stage_counts = dict(
            session.query(Customer.training_stage, func.count(Customer.id))
            .filter(Customer.pipeline_type == 'training')
            .group_by(Customer.training_stage)
            .all()
        )
        
        # By status
        status_counts = dict(
            session.query(Customer.status, func.count(Customer.id))
            .group_by(Customer.status)
            .all()
        )
        
        stats = {
            'total': total,
            'by_pipeline': pipeline_counts,
            'sales_stages': sales_stage_counts,
            'training_stages': training_stage_counts,
            'by_status': status_counts
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customer stats: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500
    finally:
        session.close()