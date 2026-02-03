# backend/routes/auth_helpers.py

from functools import wraps
from flask import request, jsonify, current_app, g
<<<<<<< HEAD
import jwt
# NOTE: authentication for CRM should use `UserMaster` (StreemLyne_MT.User_Master).
from ..models import UserMaster
from ..db import SessionLocal


def token_required(f):
    """Decorator to require valid JWT token (CRM-aware, uses UserMaster).

    Verifies the JWT signature and loads `UserMaster` by `employee_id` (or
    legacy `user_id` in payload). Compatible with the CRM tenant-scoped login flow.
    """
=======
from backend.db import SessionLocal
import jwt
import logging

def token_required(f):
    """Decorator to require valid JWT token using UserMaster (CRM model)"""
>>>>>>> dd9cd99 (fixing errors backend errors)
    @wraps(f)
    def decorated(*args, **kwargs):
        # Handle OPTIONS requests
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        local_session = SessionLocal()
        try:
            token = None
            
<<<<<<< HEAD
            if 'Authorization' in request.headers:
                auth_header = request.headers['Authorization']
                try:
                    token = auth_header.split(" ")[1]
                except IndexError:
                    return jsonify({'error': 'Invalid token format'}), 401
            
            if not token:
                return jsonify({'error': 'Token is missing'}), 401
            
            try:
                secret_key = current_app.config['SECRET_KEY']
                current_app.logger.info(f"🔐 Decoding JWT with secret (first 10 chars): {secret_key[:10]}...")
                payload = jwt.decode(token, secret_key, algorithms=['HS256'])
                current_app.logger.info(f"✅ JWT decoded successfully. Payload keys: {list(payload.keys())}")

                # Get user_id from JWT - this is the User_Master.user_id (primary key)
                # employee_id in JWT is for Employee_Master reference, not for loading UserMaster
                user_id = payload.get('user_id')
                if user_id is None:
                    current_app.logger.warning("token missing user_id")
                    return jsonify({'error': 'Invalid token payload'}), 401

                user = local_session.get(UserMaster, user_id)

                if not user:
                    current_app.logger.warning(f"Auth token valid but UserMaster not found (id={user_id})")
                    return jsonify({'error': 'User not found'}), 401

                if not getattr(user, 'is_active', True):
                    return jsonify({'error': 'User not active'}), 401

                # Attach tenant_id from JWT to user object (single source of truth)
                user.tenant_id = payload.get('tenant_id')

                # Attach user to request and g (for compatibility with both patterns)
                g.user = user
                request.current_user = user

            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError as e:
                current_app.logger.error(f"Invalid token: {e}")
                return jsonify({'error': 'Token is invalid or expired'}), 401
            except Exception as e:
                current_app.logger.error(f"Token verification failed: {e}")
                return jsonify({'error': 'Token verification failed'}), 401
            
            return f(*args, **kwargs)
        finally:
            local_session.close()
=======
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
>>>>>>> dd9cd99 (fixing errors backend errors)
    
    return decorated