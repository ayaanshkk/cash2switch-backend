from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid
import traceback
import logging
from ..models import Job, Customer, Assignment
from ..db import SessionLocal
from .auth_helpers import token_required
from sqlalchemy import func

job_bp = Blueprint('jobs', __name__)


def generate_job_reference(session):
    """Generate sequential job reference like FAI-JOB001"""
    # Get the count of existing jobs
    job_count = session.query(Job).count()
    
    # Generate reference with zero-padded number
    reference_number = job_count + 1
    job_reference = f"FAI-JOB{reference_number:03d}"
    
    # Ensure uniqueness (in case of deletions)
    while session.query(Job).filter(Job.job_number == job_reference).first():
        reference_number += 1
        job_reference = f"FAI-JOB{reference_number:03d}"
    
    return job_reference


def serialize_job(job):
    """Serialize job object to dictionary"""
    return {
        'id': job.id,
        'customer_id': job.customer_id,
        'job_number': job.job_number,
        'description': job.description,
        'status': job.status,
        'start_date': job.start_date.isoformat() if job.start_date else None,
        'end_date': job.end_date.isoformat() if job.end_date else None,
        'notes': job.notes,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
        # Include customer info if available
        'customer_name': job.customer.name if job.customer else None,
    }


@job_bp.route('/jobs', methods=['GET', 'OPTIONS'])
@token_required
def get_jobs():
    """Get all jobs with optional filtering"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        customer_id = request.args.get('customer_id')
        status = request.args.get('status')
        
        query = session.query(Job)
        
        if customer_id:
            query = query.filter(Job.customer_id == customer_id)
        if status:
            query = query.filter(Job.status == status)
        
        jobs = query.order_by(Job.created_at.desc()).all()
        
        return jsonify([serialize_job(job) for job in jobs]), 200
    except Exception as e:
        logging.error("Error fetching jobs: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_job(job_id):
    """Get a specific job by ID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify(serialize_job(job)), 200
    except Exception as e:
        logging.error("Error fetching job %s: %s", job_id, e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs', methods=['POST'])
@token_required
def create_job():
    """Create a new job"""
    session = SessionLocal()
    try:
        data = request.get_json()
        logging.info("Received data: %s", data)
        
        # Validate required fields
        if not data.get('customer_id'):
            return jsonify({'error': 'customer_id is required'}), 400
        
        # Validate customer exists
        customer = session.query(Customer).filter(Customer.id == data['customer_id']).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Generate sequential job reference
        job_number = data.get('job_number') or generate_job_reference(session)
        logging.info("Generated job number: %s", job_number)
        
        # Parse dates safely
        def parse_date(date_str):
            if date_str:
                try:
                    # Handle both ISO format and date-only format
                    if 'T' in date_str:
                        return datetime.strptime(date_str.split('T')[0], '%Y-%m-%d').date()
                    return datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    logging.warning("Invalid date format: %s", date_str)
                    return None
            return None
        
        # Create job
        job = Job(
            customer_id=data['customer_id'],
            job_number=job_number,
            description=data.get('description', ''),
            status=data.get('status', 'Pending'),
            start_date=parse_date(data.get('start_date')),
            end_date=parse_date(data.get('end_date')),
            notes=data.get('notes', ''),
        )
        
        session.add(job)
        session.flush()
        
        logging.info("Created job with ID: %s, Number: %s", job.id, job_number)
        
        session.commit()
        
        return jsonify(serialize_job(job)), 201
        
    except Exception as e:
        logging.error("Error creating job: %s", e)
        traceback.print_exc()
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_job(job_id):
    """Update an existing job"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        def parse_date(date_str):
            if date_str:
                try:
                    if 'T' in date_str:
                        return datetime.strptime(date_str.split('T')[0], '%Y-%m-%d').date()
                    return datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    return None
            return None
        
        # Update allowed fields
        if 'description' in data:
            job.description = data['description']
        if 'status' in data:
            job.status = data['status']
        if 'notes' in data:
            job.notes = data['notes']
        if 'start_date' in data:
            job.start_date = parse_date(data['start_date'])
        if 'end_date' in data:
            job.end_date = parse_date(data['end_date'])
        
        job.updated_at = datetime.utcnow()
        
        session.commit()
        
        logging.info("Updated job %s", job_id)
        
        return jsonify(serialize_job(job)), 200
    except Exception as e:
        logging.error("Error updating job %s: %s", job_id, e)
        traceback.print_exc()
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_job(job_id):
    """Delete a job and its dependent records"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        logging.info("Attempting to delete job %s and its dependencies.", job_id)

        # Delete dependent assignments
        session.query(Assignment).filter(Assignment.job_id == job_id).delete(synchronize_session='fetch')
        session.flush()
        
        # Delete the job
        session.delete(job)
        session.commit()
        
        logging.info("Successfully deleted job %s.", job_id)
        return jsonify({'message': 'Job deleted successfully'}), 200
        
    except Exception as e:
        traceback.print_exc()
        logging.error("Error deleting job %s: %s", job_id, e)
        session.rollback()
        return jsonify({'error': f"Failed to delete job: {str(e)}"}), 500
    finally:
        session.close()


@job_bp.route('/jobs/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_job_stats():
    """Get job statistics"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        stats = {
            'total_jobs': session.query(Job).count(),
            'by_status': {},
        }
        
        # Count by status
        status_counts = session.query(
            Job.status, 
            func.count(Job.id)
        ).group_by(Job.status).all()
        
        for status, count in status_counts:
            stats['by_status'][status or 'Unknown'] = count
        
        return jsonify(stats), 200
    except Exception as e:
        logging.error("Error fetching job stats: %s", e)
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@job_bp.route('/jobs/<int:job_id>/status', methods=['PATCH', 'OPTIONS'])
@token_required
def update_job_status(job_id):
    """Update job status"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        if not data.get('status'):
            return jsonify({'error': 'Status is required'}), 400
        
        old_status = job.status
        job.status = data['status']
        job.updated_at = datetime.utcnow()
        
        # Optionally add a note about status change
        if data.get('add_note') and job.notes:
            job.notes += f"\n\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] Status changed from '{old_status}' to '{data['status']}'"
        elif data.get('add_note'):
            job.notes = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] Status changed from '{old_status}' to '{data['status']}'"
        
        session.commit()
        
        logging.info("Updated job %s status: %s -> %s", job_id, old_status, data['status'])
        
        return jsonify(serialize_job(job)), 200
    except Exception as e:
        logging.error("Error updating status for job %s: %s", job_id, e)
        traceback.print_exc()
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()