# backend/routes/async_bulk_routes.py
"""
Async Bulk Import Routes using Celery
Provides instant response, processes in background with progress tracking
"""
from flask import Blueprint, request, jsonify, current_app
from backend.routes.auth_helpers import token_required
from backend.tasks.bulk_operations import bulk_import_customers, bulk_assign_customers
from backend.celery_app import celery_app
from backend.routes.customer_routes import get_user_role_name
from backend.db import SessionLocal
from pathlib import Path
import os
import uuid
import logging

logger = logging.getLogger(__name__)

async_bulk_bp = Blueprint('async_bulk', __name__)


@async_bulk_bp.route('/import/energy-customers-async', methods=['POST', 'OPTIONS'])
@token_required
def async_import_energy_customers():
    """Start async bulk import task - Returns immediately with task_id"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        user = request.current_user
        tenant_id = getattr(user, 'tenant_id', None)
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # Get file
        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'No file provided'}), 400
        
        # Validate file extension
        if not file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({'error': 'Invalid file type. Please upload an Excel file (.xlsx or .xls)'}), 400
        
        assigned_employee_id = request.form.get('assigned_employee_id', type=int)
        service = request.args.get('service', 'utilities')
        
        # Map service to service_id
        service_id_map = {'utilities': 1, 'electricity': 1, 'gas': 2, 'water': 3}
        service_id = service_id_map.get(service.lower(), 1)
        
        # Create upload directory
        upload_dir = Path('/tmp/streemlyne_uploads')
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_id = str(uuid.uuid4())
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        safe_filename = f"{file_id}_{tenant_id}.{file_ext}"
        file_path = str(upload_dir / safe_filename)  
        
        file.save(file_path)
        logger.info(f"📁 Saved upload to: {file_path}")
        
        # Start Celery task
        task = bulk_import_customers.apply_async(
            args=[file_path, tenant_id, user.employee_id, assigned_employee_id, service_id],
            task_id=f"import_{file_id}"
        )
        
        logger.info(f"🚀 Started import task {task.id} for tenant {tenant_id}")
        
        return jsonify({
            'success': True,
            'task_id': task.id,
            'message': 'Import started in background. You can continue working.',
            'status_url': f'/api/task-status/{task.id}'
        }), 202  # 202 Accepted
        
    except Exception as e:
        logger.error(f"❌ Error starting import: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@async_bulk_bp.route('/bulk-assign-async', methods=['POST', 'OPTIONS'])
@token_required
def async_bulk_assign():
    """Start async bulk assignment task"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        user = request.current_user
        tenant_id = getattr(user, 'tenant_id', None)
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        data = request.get_json()
        client_ids = data.get('client_ids', [])
        employee_id = data.get('employee_id')
        
        if not client_ids:
            return jsonify({'error': 'No clients selected'}), 400
        
        if not employee_id:
            return jsonify({'error': 'Employee ID is required'}), 400
        
        # Check permissions
        session = SessionLocal()
        try:
            user_role = get_user_role_name(user, session)
            if user_role not in ['Platform Admin', 'Tenant Super Admin']:
                return jsonify({
                    'success': False,
                    'error': 'Only administrators can bulk assign clients'
                }), 403
        finally:
            session.close()
        
        # Start Celery task
        task_id = f"assign_{uuid.uuid4().hex[:8]}"
        task = bulk_assign_customers.apply_async(
            args=[client_ids, employee_id, tenant_id],
            task_id=task_id
        )
        
        logger.info(f"🚀 Started assign task {task.id} for {len(client_ids)} clients")
        
        return jsonify({
            'success': True,
            'task_id': task.id,
            'message': f'Assignment of {len(client_ids)} client(s) started in background.',
            'status_url': f'/api/task-status/{task.id}'
        }), 202
        
    except Exception as e:
        logger.error(f"❌ Error starting assignment: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@async_bulk_bp.route('/task-status/<task_id>', methods=['GET'])
@token_required
def get_task_status(task_id):
    """Check status of background task"""
    
    try:
        task = celery_app.AsyncResult(task_id)
        
        if task.state == 'PENDING':
            response = {
                'state': task.state,
                'status': 'Task is queued and will start shortly...',
                'progress': 0,
                'successful': 0,
                'errors': 0
            }
            
        elif task.state == 'PROGRESS':
            info = task.info or {}
            response = {
                'state': task.state,
                'status': info.get('status', 'Processing...'),
                'progress': info.get('progress', 0),
                'successful': info.get('successful', 0),
                'errors': info.get('errors', 0),
                'current_batch': info.get('current_batch'),
                'total_batches': info.get('total_batches'),
            }
            
        elif task.state == 'SUCCESS':
            result = task.result or {}
            response = {
                'state': task.state,
                'status': 'Completed successfully!',
                'progress': 100,
                'result': result
            }
            
        elif task.state == 'FAILURE':
            response = {
                'state': task.state,
                'status': 'Task failed',
                'progress': 0,
                'error': str(task.info) if task.info else 'Unknown error occurred'
            }
            
        else:
            response = {
                'state': task.state,
                'status': f'Task state: {task.state}',
                'progress': 0
            }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"❌ Error checking task status: {str(e)}")
        return jsonify({
            'state': 'ERROR',
            'error': str(e),
            'status': 'Failed to check task status'
        }), 500