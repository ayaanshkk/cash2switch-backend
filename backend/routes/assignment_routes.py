"""
Simplified Assignment Routes for Forklift Academy CRM
Updated for Admin/Staff roles and simplified Job model
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from ..models import User, Assignment, Job, Customer
from .auth_helpers import token_required
from ..db import SessionLocal

assignment_bp = Blueprint('assignments', __name__)

# ✅ VALID ASSIGNMENT FIELDS
VALID_ASSIGNMENT_FIELDS = [
    'type', 'title', 'date', 'start_date', 'end_date', 'customer_name',
    'user_id', 'team_member', 'job_id', 'customer_id',
    'start_time', 'end_time', 'estimated_hours',
    'notes', 'priority', 'status'
]


def filter_assignment_data(data):
    """Filter request data to only include valid Assignment fields"""
    filtered = {}
    for key in VALID_ASSIGNMENT_FIELDS:
        if key in data:
            filtered[key] = data[key]
    return filtered


@assignment_bp.route('/assignments', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_assignments():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    current_user = request.current_user
    
    if request.method == 'POST':
        session = SessionLocal()
        
        try:
            data = request.json
            current_app.logger.info(f"📥 RAW data received: {data}")
            
            # ✅ Filter out invalid fields
            data = filter_assignment_data(data)
            current_app.logger.info(f"📥 Creating assignment with filtered data: {data}")
            
            # ✅ PARSE DATE FIELDS
            date_value = None
            start_date_value = None
            end_date_value = None
            
            if data.get('start_date'):
                try:
                    start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                    date_value = start_date_value
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing start_date: {e}")
                    return jsonify({'error': 'Invalid start_date format'}), 400
            elif data.get('date'):
                try:
                    date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
                    start_date_value = date_value
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing date: {e}")
                    return jsonify({'error': 'Invalid date format'}), 400
            else:
                return jsonify({'error': 'start_date or date is required'}), 400
            
            if data.get('end_date'):
                try:
                    end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing end_date: {e}")
                    return jsonify({'error': 'Invalid end_date format'}), 400
            else:
                end_date_value = start_date_value
            
            # ✅ GET CUSTOMER NAME
            customer_name = data.get('customer_name')
            customer_id = data.get('customer_id')
            if customer_id and not customer_name:
                customer = session.query(Customer).filter_by(id=customer_id).first()
                if customer:
                    customer_name = customer.name
            
            # Parse times if provided
            start_time = None
            end_time = None
            if data.get('start_time'):
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time format: {data['start_time']}")
            
            if data.get('end_time'):
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time format: {data['end_time']}")
            
            # Calculate hours
            estimated_hours = data.get('estimated_hours')
            if isinstance(estimated_hours, str):
                try:
                    estimated_hours = float(estimated_hours) if estimated_hours else None
                except ValueError:
                    estimated_hours = None

            # Get assigned user info
            user_id = data.get('user_id')
            team_member_name = data.get('team_member')
            
            if user_id and not team_member_name:
                assigned_user = session.get(User, user_id) 
                if assigned_user:
                    team_member_name = assigned_user.full_name
                else:
                    current_app.logger.warning(f"User {user_id} not found")
            
            # Get creator info
            creator = session.get(User, current_user.id)
            created_by_name = creator.full_name if creator else None
                
            # ✅ Create assignment
            assignment = Assignment(
                type=data.get('type', 'job'),
                title=data.get('title', ''),
                date=date_value,
                start_date=start_date_value,
                end_date=end_date_value,
                customer_name=customer_name,
                user_id=user_id,
                team_member=team_member_name,
                created_by=current_user.id,
                job_id=data.get('job_id'),
                customer_id=customer_id,
                start_time=start_time,
                end_time=end_time,
                estimated_hours=estimated_hours,
                notes=data.get('notes', ''),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled')
            )
            
            session.add(assignment)
            session.commit()
            session.refresh(assignment)

            current_app.logger.info(f"✅ Assignment created: {assignment.id}")

            # Build response dict
            result = assignment.to_dict()
            
            # Add creator name if not already present
            if 'created_by_name' not in result or not result['created_by_name']:
                result['created_by_name'] = created_by_name

            return jsonify({
                'message': 'Assignment created successfully',
                'assignment': result
            }), 201

        except KeyError as e:
            session.rollback()
            current_app.logger.error(f"Missing required field: {e}")
            return jsonify({'error': f'Missing required field: {str(e)}'}), 400
        except TypeError as e:
            session.rollback()
            current_app.logger.error(f"❌ TypeError (invalid field): {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Invalid field in request: {str(e)}'}), 400
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error creating assignment: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()
    
    # ✅ GET - All users see all assignments
    if request.method == 'GET':
        session = SessionLocal()
        try:
            current_app.logger.info(f"📋 Fetching assignments for user: {current_user.full_name} (role: {current_user.role})")
            
            # ✅ Everyone sees ALL assignments
            assignments = session.query(Assignment).order_by(Assignment.date.desc()).all()
            
            current_app.logger.info(f"✅ Returning all {len(assignments)} assignments to {current_user.role}")

            result = []
            for a in assignments:
                try:
                    assignment_dict = a.to_dict()
                    
                    # Ensure creator and updater names are included
                    if a.created_by and ('created_by_name' not in assignment_dict or not assignment_dict['created_by_name']):
                        creator = session.get(User, a.created_by)
                        if creator:
                            assignment_dict['created_by_name'] = creator.full_name
                    
                    if a.updated_by and ('updated_by_name' not in assignment_dict or not assignment_dict['updated_by_name']):
                        updater = session.get(User, a.updated_by)
                        if updater:
                            assignment_dict['updated_by_name'] = updater.full_name
                    
                    result.append(assignment_dict)
                except Exception as dict_error:
                    current_app.logger.error(f"Error converting assignment {a.id} to dict: {dict_error}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            return jsonify(result), 200
        except Exception as e:
            current_app.logger.error(f"Error in GET assignments: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()


@assignment_bp.route('/assignments/<string:assignment_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_assignment(assignment_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    current_user = request.current_user
    
    session = SessionLocal()
    try:
        assignment = session.get(Assignment, assignment_id) 
        
        if not assignment:
            current_app.logger.error(f"❌ Assignment {assignment_id} not found")
            return jsonify({'error': 'Assignment not found'}), 404
        
        # ✅ Authorization: Admin can do everything, Staff can manage their own or unassigned
        if request.method in ['PUT', 'DELETE']:
            is_admin = current_user.role == 'Admin'
            is_assigned_user = assignment.user_id == current_user.id
            is_creator = assignment.created_by == current_user.id
            is_unassigned = not assignment.user_id
            
            # Allow if: Admin, assigned user, creator, or task is unassigned
            if not (is_admin or is_assigned_user or is_creator or is_unassigned):
                return jsonify({'error': 'Unauthorized access to assignment'}), 403
        
        # GET
        if request.method == 'GET':
            result = assignment.to_dict()
            
            # Add user names if not present
            if assignment.created_by and ('created_by_name' not in result or not result['created_by_name']):
                creator = session.get(User, assignment.created_by)
                if creator:
                    result['created_by_name'] = creator.full_name
            
            if assignment.updated_by and ('updated_by_name' not in result or not result['updated_by_name']):
                updater = session.get(User, assignment.updated_by)
                if updater:
                    result['updated_by_name'] = updater.full_name
            
            return jsonify(result), 200
        
        # ✅ PUT - Update assignment
        elif request.method == 'PUT':
            data = request.json
            current_app.logger.info(f"📝 RAW update data received: {data}")
            
            # ✅ Filter out invalid fields
            data = filter_assignment_data(data)
            current_app.logger.info(f"📝 Updating assignment {assignment_id} with filtered data: {data}")
            
            if 'type' in data:
                assignment.type = data['type']
            if 'title' in data:
                assignment.title = data['title']
            
            # ✅ Handle date updates for drag and drop
            if 'start_date' in data and data['start_date']:
                assignment.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                assignment.date = assignment.start_date
                current_app.logger.info(f"📅 Updated start_date to: {assignment.start_date}")
            elif 'date' in data and data['date']:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
                if not hasattr(assignment, 'start_date') or not assignment.start_date:
                    assignment.start_date = assignment.date
                current_app.logger.info(f"📅 Updated date to: {assignment.date}")
            
            if 'end_date' in data and data['end_date']:
                assignment.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                current_app.logger.info(f"📅 Updated end_date to: {assignment.end_date}")
            elif 'start_date' in data and not ('end_date' in data):
                assignment.end_date = assignment.start_date
                current_app.logger.info(f"📅 Set end_date same as start_date: {assignment.end_date}")
            
            if 'start_time' in data:
                try:
                    assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time() if data['start_time'] else None
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time: {data['start_time']}")
            if 'end_time' in data:
                try:
                    assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time() if data['end_time'] else None
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time: {data['end_time']}")
            if 'estimated_hours' in data:
                estimated_hours = data['estimated_hours']
                try:
                    assignment.estimated_hours = float(estimated_hours) if isinstance(estimated_hours, str) else estimated_hours
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Invalid estimated_hours: {estimated_hours}")
            if 'notes' in data:
                assignment.notes = data['notes']
            if 'priority' in data:
                assignment.priority = data['priority']
            if 'status' in data:
                assignment.status = data['status']
            if 'job_id' in data:
                assignment.job_id = data['job_id']
            
            # ✅ Update customer
            if 'customer_id' in data:
                assignment.customer_id = data['customer_id']
                if data['customer_id']:
                    customer = session.query(Customer).filter_by(id=data['customer_id']).first()
                    if customer:
                        if hasattr(assignment, 'customer_name'):
                            assignment.customer_name = customer.name
            
            if 'customer_name' in data:
                assignment.customer_name = data['customer_name']
            
            if 'user_id' in data:
                assignment.user_id = data['user_id']
                new_user = session.get(User, data['user_id'])
                if new_user:
                    assignment.team_member = new_user.full_name
            if 'team_member' in data:
                assignment.team_member = data['team_member']
                
            assignment.updated_by = current_user.id
            assignment.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(assignment)
            
            current_app.logger.info(f"✅ Assignment {assignment_id} updated successfully")
            
            result = assignment.to_dict()
            
            # Add updater name
            updater = session.get(User, current_user.id)
            if updater:
                result['updated_by_name'] = updater.full_name
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': result
            }), 200
            
        # ✅ DELETE
        elif request.method == 'DELETE':
            current_app.logger.info(f"🗑️ Deleting assignment {assignment_id}")
            session.delete(assignment)
            session.commit()
            current_app.logger.info(f"✅ Assignment {assignment_id} deleted")
            
            return jsonify({
                'message': 'Assignment deleted successfully',
                'id': assignment_id
            }), 200
        
    except TypeError as e:
        session.rollback()
        current_app.logger.error(f"❌ TypeError (invalid field): {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Invalid field in request: {str(e)}'}), 400
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_single_assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/assignments/by-date-range', methods=['GET', 'OPTIONS'])
@token_required 
def get_assignments_by_date_range():
    """Get assignments within a date range"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    current_user = request.current_user
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({'error': 'start_date and end_date are required'}), 400
    
    session = SessionLocal()
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        current_app.logger.info(f"📅 Fetching assignments from {start} to {end}")
        
        # ✅ Everyone sees all assignments in date range
        assignments = session.query(Assignment).filter(
            Assignment.date >= start,
            Assignment.date <= end
        ).order_by(Assignment.date).all()
        
        current_app.logger.info(f"✅ Found {len(assignments)} assignments in date range")
        
        result = []
        for a in assignments:
            try:
                assignment_dict = a.to_dict()
                
                # Add user names
                if a.created_by:
                    creator = session.get(User, a.created_by)
                    if creator:
                        assignment_dict['created_by_name'] = creator.full_name
                
                if a.updated_by:
                    updater = session.get(User, a.updated_by)
                    if updater:
                        assignment_dict['updated_by_name'] = updater.full_name
                
                result.append(assignment_dict)
            except Exception as e:
                current_app.logger.error(f"Error processing assignment {a.id}: {e}")
                continue
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"Error in get_assignments_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400
    finally:
        session.close()


@assignment_bp.route('/jobs/available', methods=['GET', 'OPTIONS'])
@token_required 
def get_available_jobs():
    """Get jobs that are available for assignment"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching available jobs for scheduling...")
        
        # ✅ Get all non-completed jobs
        jobs = session.query(Job).filter(
            Job.status.notin_(['Completed', 'Cancelled'])
        ).order_by(Job.created_at.desc()).all()
        
        current_app.logger.info(f"✅ Found {len(jobs)} available jobs")
        
        result = []
        for j in jobs:
            try:
                customer_name = 'Unknown'
                customer_id = None
                
                # Get customer info
                if hasattr(j, 'customer') and j.customer:
                    customer_name = j.customer.name
                    customer_id = j.customer.id
                elif j.customer_id:
                    customer_id = j.customer_id
                    customer = session.get(Customer, j.customer_id)
                    if customer:
                        customer_name = customer.name
                
                result.append({
                    'id': j.id,
                    'job_number': j.job_number,
                    'description': j.description or '',
                    'customer_name': customer_name,
                    'customer_id': customer_id,
                    'status': j.status,
                    'start_date': j.start_date.isoformat() if j.start_date else None,
                    'end_date': j.end_date.isoformat() if j.end_date else None
                })
            except Exception as job_error:
                current_app.logger.error(f"Error processing job {j.id}: {job_error}")
                import traceback
                traceback.print_exc()
                continue
        
        current_app.logger.info(f"✅ Returning {len(result)} jobs")
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_available_jobs: {e}")
        import traceback
        traceback.print_exc()
        # Return empty array to allow graceful degradation
        current_app.logger.info("⚠️ Returning empty jobs array due to error")
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/clients/active', methods=['GET', 'OPTIONS'])
@token_required 
def get_active_customers():
    """Get active customers for assignments"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching active customers...")
        
        # Get all customers
        customers = session.query(Customer).order_by(Customer.name).all()
        
        current_app.logger.info(f"✅ Found {len(customers)} customers")
        
        result = []
        for c in customers:
            try:
                result.append({
                    'id': c.id,
                    'name': c.name,
                    'address': c.address or '',
                    'phone': c.phone or '',
                    'email': c.email or '',
                    'sales_stage': c.sales_stage or 'Enquiry',
                    'training_stage': c.training_stage,
                    'pipeline_type': c.pipeline_type or 'sales'
                })
            except Exception as customer_error:
                current_app.logger.error(f"Error processing customer {c.id}: {customer_error}")
                import traceback
                traceback.print_exc()
                continue
        
        current_app.logger.info(f"✅ Returning {len(result)} customers")
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_active_customers: {e}")
        import traceback
        traceback.print_exc()
        # Return empty array to allow graceful degradation
        current_app.logger.info("⚠️ Returning empty customers array due to error")
        return jsonify([]), 200
    finally:
        session.close()