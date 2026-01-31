# backend/routes/auth_helpers.py

from functools import wraps
from flask import request, jsonify, current_app, g
from backend.db import SessionLocal
import jwt
import logging

def token_required(f):
    """Decorator to require valid JWT token using UserMaster (CRM model)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Handle OPTIONS requests
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        local_session = SessionLocal()
        try:
            token = None
            
            # Get token from Authorization header
            if 'Authorization' in request.headers:
                auth_header = request.headers['Authorization']
                logging.info(f"🔑 Auth header received: {auth_header[:30]}...")
                
                try:
                    # Handle "Bearer TOKEN" format
                    if auth_header.startswith('Bearer '):
                        token = auth_header.split(" ")[1]
                    else:
                        token = auth_header
                except IndexError:
                    logging.warning("❌ Invalid token format")
                    return jsonify({'error': 'Invalid token format'}), 401
            
            if not token:
                logging.warning("❌ No token provided")
                return jsonify({'error': 'Token is missing'}), 401
            
            try:
                # Decode JWT token
                logging.info("🔓 Attempting to decode token...")
                payload = jwt.decode(
                    token, 
                    current_app.config['SECRET_KEY'], 
                    algorithms=['HS256']
                )
                
                logging.info(f"✅ Token decoded successfully")
                logging.info(f"📦 Payload: employee_id={payload.get('employee_id')}, tenant_id={payload.get('tenant_id')}, user_id={payload.get('user_id')}")
                
                # ✅ Get employee_id from payload (primary identifier in CRM)
                employee_id = payload.get('employee_id') or payload.get('user_id')
                
                if not employee_id:
                    logging.warning("❌ Token missing employee_id")
                    return jsonify({'error': 'Invalid token payload'}), 401
                
                logging.info(f"👤 Looking up user with employee_id: {employee_id}")
                
                # ✅ Import UserMaster from backend.models (not the shim)
                from backend.models import UserMaster
                
                # ✅ Get user by employee_id using filter_by (not get which uses primary key)
                user = local_session.query(UserMaster).filter_by(
                    employee_id=employee_id
                ).first()
                
                if not user:
                    logging.warning(f"❌ UserMaster not found for employee_id={employee_id}")
                    return jsonify({'error': 'User not found'}), 401
                
                # Check if user is active
                if hasattr(user, 'is_active') and not user.is_active:
                    logging.warning(f"❌ User {employee_id} is inactive")
                    return jsonify({'error': 'User account is inactive'}), 401
                
                # ✅ Attach tenant_id and employee_id from JWT to user object for easy access
                user.tenant_id = payload.get('tenant_id')
                user.employee_id = employee_id
                
                # Attach user to request and g
                request.current_user = user
                g.user = user
                
                logging.info(f"✅ User authenticated: employee_id={employee_id}, tenant_id={user.tenant_id}")
                
            except jwt.ExpiredSignatureError:
                logging.warning("❌ Token has expired")
                return jsonify({'error': 'Token has expired'}), 401
            except jwt.InvalidTokenError as e:
                logging.warning(f"❌ Invalid token: {str(e)}")
                return jsonify({'error': 'Token is invalid or expired'}), 401
            except Exception as e:
                logging.error(f"❌ Token validation error: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': 'Token validation failed'}), 401
            
            return f(*args, **kwargs)
            
        finally:
            local_session.close()
    
    return decorated


def admin_required(f):
    """Decorator to require Admin access"""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        # Check if user has Admin role
        # TODO: Implement proper role checking based on Employee_Master.role_ids
        # For now, this is a placeholder
        roles = []
        if hasattr(g.user, 'roles'):
            roles = g.user.roles or []
        elif hasattr(g.user, 'role'):
            roles = [g.user.role]
        
        if 'Admin' not in roles:
            logging.warning(f"❌ User {g.user.employee_id if hasattr(g.user, 'employee_id') else 'unknown'} attempted admin access without permission")
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated