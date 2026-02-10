import os
import uuid
from typing import Optional
from flask import Blueprint, request, jsonify, current_app
import json
from datetime import datetime, date
from ..db import SessionLocal
from ..models import (
    User, Customer, UserMaster
)
from .auth_helpers import token_required

db_bp = Blueprint('database', __name__)

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
# CUSTOMERS (Legacy - Minimal)
# ----------------------------------

@db_bp.route('/legacy-customers', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_legacy_customers():
    """Legacy customer endpoints (use /clients for CRM customers)"""
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
                address=data.get('address')
            )
            
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
        current_app.logger.error(f"Error handling legacy customers: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/legacy-customers/<string:customer_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_legacy_customer(customer_id):
    """Legacy customer endpoints (use /clients for CRM customers)"""
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
        current_app.logger.error(f"Error handling legacy customer {customer_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ----------------------------------
# HEALTH CHECK
# ----------------------------------

@db_bp.route('/db/health', methods=['GET', 'OPTIONS'])
def db_health_check():
    """Database health check"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Try to query User table
        user_count = session.query(User).count()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'user_count': user_count
        }), 200
    
    except Exception as e:
        current_app.logger.error(f"Database health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500
    finally:
        session.close()