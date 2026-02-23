from functools import wraps
from flask import request, jsonify, current_app, g
import jwt
# NOTE: authentication for CRM should use `UserMaster` (StreemLyne_MT.User_Master).
from ..models import UserMaster
from ..db import SessionLocal


def token_required(f):
    """Decorator to require valid JWT token (CRM-aware, uses UserMaster).

    Verifies the JWT signature and loads `UserMaster` by `employee_id` (or
    legacy `user_id` in payload). Compatible with the CRM tenant-scoped login flow.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Handle OPTIONS requests
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        local_session = SessionLocal()
        try:
            token = None
            
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
    
    return decorated

def get_tenant_id_from_user(user):
    """
    Extract tenant_id from authenticated user object
    
    Args:
        user: The authenticated user object from token_required decorator
        
    Returns:
        int: The tenant_id or None if not found
    """
    from ..db import SessionLocal
    from ..models import Employee_Master
    
    # First check if user has tenant_id directly (from JWT)
    if hasattr(user, 'tenant_id') and user.tenant_id is not None:
        return user.tenant_id
    
    # Fallback: Look up employee to get tenant_id
    if hasattr(user, 'employee_id') and user.employee_id is not None:
        session = SessionLocal()
        try:
            employee = session.query(Employee_Master).filter_by(
                employee_id=user.employee_id
            ).first()
            return employee.tenant_id if employee else None
        finally:
            session.close()
    
    return None