import os
import uuid
from typing import Optional
from flask import Blueprint, request, jsonify, current_app
import json
from datetime import datetime, date
from ..db import SessionLocal
from ..models import (
    User, Assignment, Customer, Proposal,
    AuditLog, ActionItem, DataImport
)
from .auth_helpers import token_required
from sqlalchemy.orm import selectinload

db_bp = Blueprint('database', __name__)

# Pipeline Stage Orders
SALES_PIPELINE_STAGES = ["Enquiry", "Proposal", "Converted"]
TRAINING_PIPELINE_STAGES = [
    "Training Scheduled", "Training Conducted", "Training Completed",
    "PTI Created", "Certificates Created", "Certificates Dispatched"
]

# Helper function to get current user's email safely
def get_current_user_email(data=None):
    if hasattr(request, 'current_user') and hasattr(request.current_user, 'email'):
        return request.current_user.email
    return data.get('created_by', 'System') if isinstance(data, dict) else 'System'


# ----------------------------------
# USERS
# ----------------------------------

@db_bp.route('/users', methods=['GET', 'POST'])
@token_required
def handle_users():
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            user = User(
                email=data['email'],
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
                role=data.get('role', 'user'),
                phone=data.get('phone'),
                department=data.get('department')
            )
            if data.get('password'):
                user.set_password(data['password'])
            
            session.add(user)
            session.commit()
            return jsonify({'id': user.id, 'message': 'User created successfully'}), 201
        
        users = session.query(User).all()
        return jsonify([u.to_dict() for u in users])
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling users: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/users/<int:user_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_single_user(user_id):
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if request.method == 'GET':
            return jsonify(user.to_dict())
        
        elif request.method == 'PUT':
            data = request.json
            user.email = data.get('email', user.email)
            user.first_name = data.get('first_name', user.first_name)
            user.last_name = data.get('last_name', user.last_name)
            user.phone = data.get('phone', user.phone)
            user.role = data.get('role', user.role)
            user.department = data.get('department', user.department)
            user.is_active = data.get('is_active', user.is_active)
            
            if data.get('password'):
                user.set_password(data['password'])
            
            session.commit()
            return jsonify({'message': 'User updated successfully'})
        
        elif request.method == 'DELETE':
            session.delete(user)
            session.commit()
            return jsonify({'message': 'User deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling user {user_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ----------------------------------
# CUSTOMERS
# ----------------------------------

def _extract_stage_from_payload(data: dict, pipeline_type: str = 'sales') -> Optional[str]:
    """Extract stage from payload based on pipeline type"""
    if not isinstance(data, dict):
        return None

    # Determine valid stages based on pipeline type
    valid_stages = SALES_PIPELINE_STAGES if pipeline_type == 'sales' else TRAINING_PIPELINE_STAGES
    
    # Check for direct 'stage' field
    stage = data.get('stage') or data.get('sales_stage') or data.get('training_stage')
    if stage and isinstance(stage, str):
        stage = stage.strip()
        if stage in valid_stages:
            return stage
    
    # Check for object format
    if isinstance(stage, dict):
        for key in ('value', 'label', 'stage'):
            inner = stage.get(key)
            if isinstance(inner, str) and inner.strip() in valid_stages:
                return inner.strip()
    
    # Check alternative field names
    for field in ('target_stage', 'targetStage', 'new_stage', 'newStage'):
        alt_stage = data.get(field)
        if alt_stage and isinstance(alt_stage, str):
            alt_stage = alt_stage.strip()
            if alt_stage in valid_stages:
                return alt_stage
    
    return None


@db_bp.route('/clients', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            
            customer = Customer(
                name=data.get('name', ''),
                phone=data.get('phone'),
                email=data.get('email'),
                address=data.get('address'),
                # NO POSTCODE - removed for India
                salesperson=data.get('salesperson'),
                contact_made=data.get('contact_made', 'Unknown'),
                preferred_contact_method=data.get('preferred_contact_method', 'Phone'),
                marketing_opt_in=data.get('marketing_opt_in', False),
                notes=data.get('notes'),
                sales_stage=data.get('sales_stage', 'Enquiry'),
                pipeline_type=data.get('pipeline_type', 'sales'),
                status=data.get('status', 'Active'),
                project_types=data.get('project_types', []),
                created_by=get_current_user_email(data)
            )
            
            if data.get('date_of_measure') and hasattr(customer, 'date_of_measure'):
                customer.date_of_measure = datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date()
            
            session.add(customer)
            session.commit()
            session.refresh(customer)
            
            return jsonify({
                'id': customer.id,
                'message': 'Customer created successfully',
                'customer': customer.to_dict()
            }), 201
        
        # GET
        customers = session.query(Customer).order_by(Customer.created_at.desc()).all()
        return jsonify([c.to_dict() for c in customers])
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling customers: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/clients/<string:customer_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_customer(customer_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        if request.method == 'GET':
            return jsonify(customer.to_dict())
        
        elif request.method == 'PUT':
            data = request.json
            
            customer.name = data.get('name', customer.name)
            customer.phone = data.get('phone', customer.phone)
            customer.email = data.get('email', customer.email)
            customer.address = data.get('address', customer.address)
            # NO POSTCODE - removed for India
            customer.salesperson = data.get('salesperson', customer.salesperson)
            customer.contact_made = data.get('contact_made', customer.contact_made)
            customer.preferred_contact_method = data.get('preferred_contact_method', customer.preferred_contact_method)
            customer.marketing_opt_in = data.get('marketing_opt_in', customer.marketing_opt_in)
            customer.notes = data.get('notes', customer.notes)
            customer.sales_stage = data.get('sales_stage', customer.sales_stage)
            customer.training_stage = data.get('training_stage', customer.training_stage)
            customer.pipeline_type = data.get('pipeline_type', customer.pipeline_type)
            customer.status = data.get('status', customer.status)
            customer.project_types = data.get('project_types', customer.project_types)
            customer.updated_by = get_current_user_email(data)
            
            if 'date_of_measure' in data and data['date_of_measure'] and hasattr(customer, 'date_of_measure'):
                customer.date_of_measure = datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date()
            
            session.commit()
            session.refresh(customer)
            
            return jsonify({
                'message': 'Customer updated successfully',
                'customer': customer.to_dict()
            })
        
        elif request.method == 'DELETE':
            session.delete(customer)
            session.commit()
            return jsonify({'message': 'Customer deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling customer {customer_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/clients/<string:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(customer_id):
    """Update customer stage (supports both sales and training pipelines)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        data = request.json
        pipeline_type = data.get('pipeline_type', customer.pipeline_type or 'sales')
        updated_by_user = get_current_user_email(data)
        new_stage = _extract_stage_from_payload(data, pipeline_type)
        reason = data.get('reason', 'Stage updated')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        # Validate stage based on pipeline type
        valid_stages = SALES_PIPELINE_STAGES if pipeline_type == 'sales' else TRAINING_PIPELINE_STAGES
        if new_stage not in valid_stages:
            return jsonify({'error': f'Invalid stage for {pipeline_type} pipeline: {new_stage}'}), 400

        # Get old stage based on pipeline type
        old_stage = customer.sales_stage if pipeline_type == 'sales' else customer.training_stage
        
        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed', 
                'stage_updated': False,
                'customer_id': customer.id,
                'new_stage': new_stage,
                'old_stage': old_stage,
                'pipeline_type': pipeline_type
            }), 200

        # Update the appropriate stage
        if pipeline_type == 'sales':
            customer.sales_stage = new_stage
            # When converting to training pipeline
            if new_stage == 'Converted':
                customer.pipeline_type = 'training'
                customer.training_stage = 'Training Scheduled'
        else:
            customer.training_stage = new_stage
        
        customer.updated_by = updated_by_user
        customer.updated_at = datetime.utcnow()
        
        note_entry = f"\n[{datetime.utcnow().isoformat()}] {pipeline_type.title()} stage changed from {old_stage} to {new_stage}. Reason: {reason}"
        customer.notes = (customer.notes or '') + note_entry
        
        session.commit()
        
        return jsonify({
            'message': 'Stage updated successfully',
            'customer_id': customer.id,
            'old_stage': old_stage,
            'new_stage': new_stage,
            'pipeline_type': pipeline_type,
            'stage_updated': True
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating customer stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ----------------------------------
# PIPELINE
# ----------------------------------

@db_bp.route('/pipeline/<string:pipeline_type>', methods=['GET', 'OPTIONS'])
@token_required
def get_pipeline_data(pipeline_type):
    """Get pipeline data for sales or training pipeline"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    if pipeline_type not in ['sales', 'training']:
        return jsonify({'error': 'Invalid pipeline type. Must be "sales" or "training"'}), 400
    
    session = SessionLocal()
    try:
        # Get customers based on pipeline type
        if pipeline_type == 'sales':
            customers = session.query(Customer).filter(
                Customer.pipeline_type == 'sales'
            ).all()
            stage_field = 'sales_stage'
        else:
            customers = session.query(Customer).filter(
                Customer.pipeline_type == 'training'
            ).all()
            stage_field = 'training_stage'
        
        pipeline_items = []
        for customer in customers:
            stage = getattr(customer, stage_field)
            
            item = {
                'id': f'customer-{customer.id}',
                'type': 'customer',
                'customer': customer.to_dict(),
                'stage': stage or ('Enquiry' if pipeline_type == 'sales' else 'Training Scheduled'),
                'pipeline_type': pipeline_type
            }
            pipeline_items.append(item)
        
        return jsonify(pipeline_items), 200
    
    except Exception as e:
        current_app.logger.error(f"Error fetching pipeline: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ----------------------------------
# ASSIGNMENTS
# ----------------------------------

@db_bp.route('/assignments', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_assignments():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            
            # Parse dates
            date_value = None
            start_date_value = None
            end_date_value = None
            
            if data.get('start_date'):
                start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                date_value = start_date_value
            elif data.get('date'):
                date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
                start_date_value = date_value
            else:
                return jsonify({'error': 'start_date or date is required'}), 400
            
            if data.get('end_date'):
                end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            else:
                end_date_value = start_date_value
            
            # Get customer name
            customer_name = None
            customer_id = data.get('customer_id')
            if customer_id:
                customer = session.query(Customer).filter_by(id=customer_id).first()
                if customer:
                    customer_name = customer.name
            
            # Parse times
            start_time_value = None
            end_time_value = None
            
            if data.get('start_time'):
                start_time_value = datetime.strptime(data['start_time'], '%H:%M').time()
            
            if data.get('end_time'):
                end_time_value = datetime.strptime(data['end_time'], '%H:%M').time()
            
            # Create assignment
            assignment = Assignment(
                title=data.get('title', ''),
                notes=data.get('notes', ''),
                type=data.get('type', 'job'),
                date=date_value,
                start_date=start_date_value,
                end_date=end_date_value,
                customer_name=customer_name,
                user_id=data.get('user_id'),
                team_member=data.get('team_member'),
                customer_id=customer_id,
                start_time=start_time_value,
                end_time=end_time_value,
                estimated_hours=data.get('estimated_hours'),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled'),
                created_by=request.current_user.id if hasattr(request, 'current_user') else None
            )
            
            session.add(assignment)
            session.commit()
            session.refresh(assignment)
            
            return jsonify({
                'id': assignment.id,
                'message': 'Assignment created successfully',
                'assignment': assignment.to_dict()
            }), 201

        # GET
        if request.method == 'GET':
            assignments = session.query(Assignment).order_by(Assignment.date.asc()).all()
            return jsonify([a.to_dict() for a in assignments])
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /assignments: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/assignments/<string:assignment_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_assignment(assignment_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        assignment = session.query(Assignment).filter_by(id=assignment_id).first()
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        if request.method == 'GET':
            return jsonify(assignment.to_dict())
        
        elif request.method == 'PUT':
            data = request.json
            
            # Update fields
            if 'title' in data:
                assignment.title = data['title']
            if 'notes' in data:
                assignment.notes = data['notes']
            if 'type' in data:
                assignment.type = data['type']
            if 'team_member' in data:
                assignment.team_member = data['team_member']
            if 'priority' in data:
                assignment.priority = data['priority']
            if 'status' in data:
                assignment.status = data['status']
            if 'estimated_hours' in data:
                assignment.estimated_hours = data['estimated_hours']
            
            # Update dates
            if 'start_date' in data and data['start_date']:
                assignment.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                assignment.date = assignment.start_date
            elif 'date' in data and data['date']:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
                if not assignment.start_date:
                    assignment.start_date = assignment.date
            
            if 'end_date' in data and data['end_date']:
                assignment.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            elif 'start_date' in data and not ('end_date' in data):
                assignment.end_date = assignment.start_date
            
            # Update times
            if 'start_time' in data and data['start_time']:
                assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            if 'end_time' in data and data['end_time']:
                assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            
            # Update customer
            if 'customer_id' in data:
                assignment.customer_id = data['customer_id']
                if data['customer_id']:
                    customer = session.query(Customer).filter_by(id=data['customer_id']).first()
                    if customer:
                        assignment.customer_name = customer.name
            
            assignment.updated_by = request.current_user.id if hasattr(request, 'current_user') else None
            assignment.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(assignment)
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': assignment.to_dict()
            })
        
        elif request.method == 'DELETE':
            session.delete(assignment)
            session.commit()
            
            return jsonify({
                'message': 'Assignment deleted successfully',
                'id': assignment_id
            }), 200
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling assignment {assignment_id}: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ----------------------------------
# AUDIT LOGS
# ----------------------------------

@db_bp.route('/audit-logs', methods=['GET', 'OPTIONS'])
@token_required
def get_audit_logs():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Optional filters
        entity_type = request.args.get('entity_type')
        entity_id = request.args.get('entity_id')
        action = request.args.get('action')
        
        query = session.query(AuditLog)
        
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if entity_id:
            query = query.filter(AuditLog.entity_id == entity_id)
        if action:
            query = query.filter(AuditLog.action == action)
        
        logs = query.order_by(AuditLog.changed_at.desc()).limit(100).all()
        
        return jsonify([log.to_dict() for log in logs])
    
    except Exception as e:
        current_app.logger.error(f"Error fetching audit logs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ----------------------------------
# ACTION ITEMS
# ----------------------------------

@db_bp.route('/action-items', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_action_items():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            
            action_item = ActionItem(
                customer_id=data['customer_id'],
                stage=data['stage'],
                priority=data.get('priority', 'High'),
                completed=data.get('completed', False)
            )
            
            session.add(action_item)
            session.commit()
            session.refresh(action_item)
            
            return jsonify({
                'id': action_item.id,
                'message': 'Action item created successfully',
                'action_item': action_item.to_dict()
            }), 201
        
        # GET
        customer_id = request.args.get('customer_id')
        completed = request.args.get('completed')
        
        query = session.query(ActionItem)
        
        if customer_id:
            query = query.filter(ActionItem.customer_id == customer_id)
        if completed is not None:
            query = query.filter(ActionItem.completed == (completed.lower() == 'true'))
        
        action_items = query.order_by(ActionItem.created_at.desc()).all()
        return jsonify([item.to_dict() for item in action_items])
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling action items: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/action-items/<string:item_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_action_item(item_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        action_item = session.query(ActionItem).filter_by(id=item_id).first()
        if not action_item:
            return jsonify({'error': 'Action item not found'}), 404
        
        if request.method == 'GET':
            return jsonify(action_item.to_dict())
        
        elif request.method == 'PUT':
            data = request.json
            
            action_item.stage = data.get('stage', action_item.stage)
            action_item.priority = data.get('priority', action_item.priority)
            action_item.completed = data.get('completed', action_item.completed)
            
            if data.get('completed') and not action_item.completed_at:
                action_item.completed_at = datetime.utcnow()
            elif not data.get('completed'):
                action_item.completed_at = None
            
            session.commit()
            return jsonify({'message': 'Action item updated successfully'})
        
        elif request.method == 'DELETE':
            session.delete(action_item)
            session.commit()
            return jsonify({'message': 'Action item deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling action item {item_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ----------------------------------
# DATA IMPORTS
# ----------------------------------

@db_bp.route('/data-imports', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_data_imports():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            
            data_import = DataImport(
                filename=data['filename'],
                import_type=data['import_type'],
                status=data.get('status', 'processing'),
                records_processed=data.get('records_processed', 0),
                records_failed=data.get('records_failed', 0),
                error_log=data.get('error_log'),
                imported_by=get_current_user_email(data)
            )
            
            session.add(data_import)
            session.commit()
            session.refresh(data_import)
            
            return jsonify({
                'id': data_import.id,
                'message': 'Data import record created successfully',
                'data_import': data_import.to_dict()
            }), 201
        
        # GET
        imports = session.query(DataImport).order_by(DataImport.created_at.desc()).all()
        return jsonify([i.to_dict() for i in imports])
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling data imports: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/data-imports/<int:import_id>', methods=['GET', 'PUT', 'OPTIONS'])
@token_required
def handle_single_data_import(import_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        data_import = session.query(DataImport).filter_by(id=import_id).first()
        if not data_import:
            return jsonify({'error': 'Data import not found'}), 404
        
        if request.method == 'GET':
            return jsonify(data_import.to_dict())
        
        elif request.method == 'PUT':
            data = request.json
            
            data_import.status = data.get('status', data_import.status)
            data_import.records_processed = data.get('records_processed', data_import.records_processed)
            data_import.records_failed = data.get('records_failed', data_import.records_failed)
            data_import.error_log = data.get('error_log', data_import.error_log)
            
            if data.get('status') in ['completed', 'failed'] and not data_import.completed_at:
                data_import.completed_at = datetime.utcnow()
            
            session.commit()
            return jsonify({'message': 'Data import updated successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling data import {import_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()