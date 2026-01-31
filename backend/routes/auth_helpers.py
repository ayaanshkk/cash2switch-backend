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
                
                # Get user_id or employee_id from payload
                user_id = payload.get('employee_id') or payload.get('user_id')
                if not user_id:
                    logging.warning("❌ Token missing user identifier")
                    return jsonify({'error': 'Invalid token payload'}), 401
                
                logging.info(f"👤 Looking up user with employee_id: {user_id}")
                
                # Import UserMaster (CRM model)
                from backend.crm.models.user_master import UserMaster
                
                # Get user from database
                user = local_session.get(UserMaster, user_id)
                
                if not user:
                    logging.warning(f"❌ UserMaster not found for employee_id={user_id}")
                    return jsonify({'error': 'User not found'}), 401
                
                # Check if user is active
                if hasattr(user, 'is_active') and not user.is_active:
                    logging.warning(f"❌ User {user_id} is inactive")
                    return jsonify({'error': 'User account is inactive'}), 401
                
                # Attach user to request and g
                request.current_user = user
                g.user = user
                
                logging.info(f"✅ User authenticated: employee_id={user_id}")
                
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
        roles = []
        if hasattr(g.user, 'roles'):
            roles = g.user.roles or []
        elif hasattr(g.user, 'role'):
            roles = [g.user.role]
        
        if 'Admin' not in roles:
            logging.warning(f"❌ User {g.user.id if hasattr(g.user, 'id') else 'unknown'} attempted admin access without permission")
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated