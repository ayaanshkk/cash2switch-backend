from flask import Blueprint, request, jsonify, current_app, g
from backend.models import UserMaster
from .auth_helpers import token_required
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import secrets
import re
import jwt
import os

from ..db import SessionLocal

auth_bp = Blueprint('auth', __name__)

# --- Configuration and Helpers ---

def get_client_ip():
    """Get client IP address"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "Password is valid"

def check_rate_limit(email, max_attempts=5, window_minutes=15):
    """Check if user has exceeded login attempts"""
    session = SessionLocal()
    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=window_minutes)
        
        recent_attempts = session.query(LoginAttempt).filter(
            LoginAttempt.email == email,
            LoginAttempt.attempted_at > cutoff_time,
            LoginAttempt.success == False
        ).count()
        
        return recent_attempts < max_attempts
    except Exception as e:
        current_app.logger.warning(f"Could not check rate limit: {e}")
        return True
    finally:
        session.close()


def log_login_attempt(email, ip_address, success):
    """Log login attempt"""
    session = SessionLocal()
    try:
        attempt = LoginAttempt(
            email=email,
            ip_address=ip_address,
            success=success
        )
        session.add(attempt)
        session.commit()
    except Exception as e:
        session.rollback()
        current_app.logger.warning(f"Could not log login attempt: {e}")
    finally:
        session.close()

# --- Decorators ---

def token_required(f):
    """Decorator to require valid JWT token (stateless).

    Verifies the JWT signature and loads `UserMaster` by `employee_id` (or
    legacy `user_id` in payload). Does NOT rely on `user_sessions` table.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        local_session = SessionLocal()
        try:
            token = None
            if 'Authorization' in request.headers:
                try:
                    token = request.headers['Authorization'].split(" ")[1]
                except IndexError:
                    return jsonify({'error': 'Invalid token format'}), 401

            if not token:
                return jsonify({'error': 'Token is missing'}), 401

            try:
                payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])

                user_id = payload.get('employee_id') or payload.get('user_id')
                if user_id is None:
                    current_app.logger.warning("token missing user identifier")
                    return jsonify({'error': 'Invalid token payload'}), 401

                # ✅ FIX: Look up by employee_id, not by primary key
                user = local_session.query(UserMaster).filter_by(employee_id=user_id).first()

                if not user:
                    current_app.logger.warning(f"Auth token valid but UserMaster not found (id={user_id})")
                    return jsonify({'error': 'User not found'}), 401

                if not getattr(user, 'is_active', True):
                    return jsonify({'error': 'User not active'}), 401

                g.user = user
                request.current_user = user

            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid token'}), 401

            return f(*args, **kwargs)
        finally:
            local_session.close()
    return decorated

def admin_required(f):
    """Decorator to require Admin access (checks CRM `role_ids` / roles)."""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        # `roles` helper on UserMaster returns a list; fall back to legacy `role` if present
        roles = []
        if hasattr(g.user, 'roles'):
            roles = g.user.roles or []
        elif hasattr(g.user, 'role'):
            roles = [g.user.role]

        if 'Admin' not in roles:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

# --- Routes ---

@auth_bp.route('/health', methods=['GET'])
def health_check():
    return {
        'status': 'ok', 
        'message': 'Forklift Academy Backend is running!'
    }, 200

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user (handles both regular registration and invitation completion)"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}

        # Check if this is completing an invitation
        invitation_token = data.get('invitation_token')
        
        if invitation_token:
            # INVITATION COMPLETION FLOW
            user = session.query(User).filter_by(invitation_token=invitation_token).first()
            
            if not user or not user.is_invited:
                return jsonify({'error': 'Invalid or expired invitation token'}), 400
            
            password = data.get('password')
            if not password:
                return jsonify({'error': 'Password is required'}), 400
            
            is_valid, message = validate_password(password)
            if not is_valid:
                return jsonify({'error': message}), 400
            
            user.set_password(password)
            user.is_invited = False
            user.invitation_token = None
            user.is_active = True
            user.is_verified = True
            user.updated_at = datetime.utcnow()
            
            session.commit()
            
            # Try to include tenant_id when the invited user is tenant-scoped
            tenant_id = None
            if hasattr(user, 'tenant_id') and getattr(user, 'tenant_id') is not None:
                tenant_id = getattr(user, 'tenant_id')
            elif hasattr(user, 'employee_id') and getattr(user, 'employee_id') is not None:
                emp = session.execute(
                    text('SELECT tenant_id FROM "StreemLyne_MT"."Employee_Master" WHERE employee_id = :id'),
                    {'id': user.employee_id}
                ).mappings().first()
                tenant_id = emp.get('tenant_id') if emp else None

            payload = {
                'user_id': user.id,
                'employee_id': getattr(user, 'employee_id', None),
                'tenant_id': tenant_id,
                'exp': datetime.utcnow() + timedelta(days=7),
                'iat': datetime.utcnow()
            }
            # strip None values
            payload = {k: v for k, v in payload.items() if v is not None}
            token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

            session_record = Session(
                user_id=user.id,
                session_token=token,
                ip_address=get_client_ip(),
                user_agent=request.headers.get('User-Agent', '')[:255],
                expires_at=datetime.utcnow() + timedelta(days=7)
            )
            session.add(session_record)
            session.commit()

            log_login_attempt(user.email, get_client_ip(), True)

            current_app.logger.info(f"✅ Invitation registration completed: {user.email} as {user.role}")

            return jsonify({
                'success': True,
                'message': 'Registration completed successfully',
                'token': token,
                'user': user.to_dict()
            }), 200
        
        # REGULAR REGISTRATION FLOW
        required_fields = ['email', 'password', 'first_name', 'last_name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400

        email = data['email'].lower().strip()
        password = data['password']
        first_name = data['first_name'].strip()
        last_name = data['last_name'].strip()
        role = data.get('role', 'Staff').strip()

        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400

        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400

        # ✨ UPDATED: Only Admin and Staff roles for Forklift Academy
        ALLOWED_ROLES = ['Admin', 'Staff']
        if role not in ALLOWED_ROLES:
            role = 'Staff'

        if session.query(User).filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 409

        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=True,
            is_verified=True,
            is_invited=False
        )
        user.set_password(password)
        
        if hasattr(user, 'generate_verification_token'):
            user.generate_verification_token()

        session.add(user)
        session.commit()

        log_login_attempt(email, get_client_ip(), True)
        
        current_app.logger.info(f"✅ User registered: {email} as {role}")

        return jsonify({
            'success': True,
            'message': 'User registered successfully',
            'user': user.to_dict()
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Registration error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/login', methods=['POST'])
def login():
    """Tenant-resolved username login against StreemLyne_MT CRM tables.

    - Accepts JSON: { "username", "password" }
    - The tenant_id is resolved from the joined Employee_Master row (not supplied by client).
    - Returns 401 "Invalid username or password" when credentials are incorrect or the username is not found
    - If `is_active` column exists and is False → 403
    - Returns JWT: { user_id, employee_id, tenant_id, user_name, role }
    """
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        if not data.get('username') or not data.get('password'):
            return jsonify({'error': 'username and password required'}), 400

        username = data['username'].strip()
        input_password = data['password']

        # ✅ UPDATED: JOIN with User_Role_Mapping and Role_Master to get role
        sql = text('''
            SELECT
                u.user_id,
                u.user_name,
                u.password,
                e.employee_id,
                e.tenant_id,
                e.employee_name,
                e.email,
                e.phone,
                rm.role_name,
                rm.role_id
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            LEFT JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE u.user_name = :username
            LIMIT 1;
        ''')

        row = session.execute(sql, {'username': username}).mappings().first()

        if not row:
            current_app.logger.warning(f"Login failed: no matching username (user_name={username})")
            return jsonify({'error': 'Invalid username or password'}), 401

        db_password = row.get('password')
        if db_password != input_password:
            current_app.logger.warning(f"Login failed (bad password) for user_name={username} employee_id={row.get('employee_id')}")
            return jsonify({'error': 'Invalid username or password'}), 401

        # If the employee has an is_active column and it's explicitly False -> forbid
        if 'is_active' in row.keys() and row.get('is_active') is False:
            current_app.logger.info(f"Login blocked: inactive employee_id={row.get('employee_id')}")
            return jsonify({'error': 'Account disabled'}), 403

        # ✅ UPDATED: Include role in JWT payload
        payload = {
            'user_id': row.get('user_id'),
            'employee_id': row.get('employee_id'),
            'tenant_id': row.get('tenant_id'),
            'user_name': row.get('user_name'),
            'role': row.get('role_name'),  # ✅ Add role to JWT
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        
        current_app.logger.info(f"🎫 Generating JWT for user_id={payload['user_id']}, tenant_id={payload['tenant_id']}, role={payload.get('role')}")
        
        token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

        # ✅ UPDATED: Include role in user response
        user = {
            'employee_id': row.get('employee_id'),
            'id': row.get('employee_id'),
            'name': (row.get('employee_name') or row.get('user_name')),
            'email': row.get('email'),
            'phone': row.get('phone'),
            'username': row.get('user_name'),
            'role': row.get('role_name'),  
            'role_id': row.get('role_id'),
            'tenant_id': row.get('tenant_id')
        }

        current_app.logger.info(f"✅ Tenant login successful: employee_id={row.get('employee_id')} user_name={username} tenant_id={row.get('tenant_id')} role={row.get('role_name')}")
        return jsonify({'success': True, 'token': token, 'user': user}), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Login error (tenant-aware): {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        session.close()


@auth_bp.route('/signup', methods=['POST'])
def signup():
    """Create CRM user: insert into Employee_Master then User_Master and return JWT.

    Expected JSON: {
      "tenant_id": <int>,
      "employee_name": "...",
      "email": "...",
      "phone": "...",           # optional
      "username": "...",
      "password": "..."
    }

    - username must be unique in User_Master
    - email must be unique in Employee_Master
    - uses plain-text password (per spec)
    """
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        required = ['tenant_id', 'employee_name', 'email', 'username', 'password']
        for f in required:
            if not data.get(f):
                return jsonify({'error': f'{f} is required'}), 400

        tenant_id = data.get('tenant_id')
        employee_name = data.get('employee_name').strip()
        email = data.get('email').strip()
        phone = data.get('phone')
        username = data.get('username').strip()
        password = data.get('password')

        # Uniqueness checks
        q_user_exists = text('SELECT 1 FROM "StreemLyne_MT"."User_Master" WHERE user_name = :username LIMIT 1')
        if session.execute(q_user_exists, {'username': username}).first():
            return jsonify({'error': 'username already exists'}), 400

        q_email_exists = text('SELECT 1 FROM "StreemLyne_MT"."Employee_Master" WHERE email = :email LIMIT 1')
        if session.execute(q_email_exists, {'email': email}).first():
            return jsonify({'error': 'email already exists'}), 400

        # Insert employee
        insert_emp = text('''
            INSERT INTO "StreemLyne_MT"."Employee_Master" (tenant_id, employee_name, email, phone)
            VALUES (:tenant_id, :employee_name, :email, :phone)
            RETURNING employee_id
        ''')
        emp_row = session.execute(insert_emp, {
            'tenant_id': tenant_id,
            'employee_name': employee_name,
            'email': email,
            'phone': phone
        }).mappings().first()

        if not emp_row or not emp_row.get('employee_id'):
            session.rollback()
            current_app.logger.error('Failed to create Employee_Master row')
            return jsonify({'error': 'Could not create employee'}), 500

        employee_id = emp_row.get('employee_id')

        # Insert user
        insert_user = text('''
            INSERT INTO "StreemLyne_MT"."User_Master" (employee_id, user_name, password)
            VALUES (:employee_id, :user_name, :password)
            RETURNING user_id
        ''')
        user_row = session.execute(insert_user, {
            'employee_id': employee_id,
            'user_name': username,
            'password': password
        }).mappings().first()

        if not user_row or not user_row.get('user_id'):
            session.rollback()
            current_app.logger.error('Failed to create User_Master row')
            return jsonify({'error': 'Could not create user'}), 500

        user_id = user_row.get('user_id')

        session.commit()

        # Build JWT per spec
        payload = {
            'user_id': user_id,
            'employee_id': employee_id,
            'tenant_id': tenant_id,
            'user_name': username,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

        user_out = {
            'user_id': user_id,
            'employee_id': employee_id,
            'user_name': username,
            'tenant_id': tenant_id
        }

        current_app.logger.info(f"✅ CRM signup successful: user_id={user_id} user_name={username} tenant_id={tenant_id}")
        return jsonify({'success': True, 'message': 'Signup successful', 'token': token, 'user': user_out}), 201

    except IntegrityError as ie:
        session.rollback()
        # Handle rare race where uniqueness check passed but insert violated constraint
        msg = str(ie.orig) if hasattr(ie, 'orig') else 'Integrity error'
        current_app.logger.warning(f"Signup integrity error: {msg}")
        return jsonify({'error': 'username or email already exists'}), 400
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Signup error (User_Master flow): {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        session.close()

@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout():
    """Stateless logout: token is JWT-only so simply acknowledge the request.

    (If you need server-side revocation later, add a token blacklist table/Redis.)
    """
    try:
        # token validity already enforced by token_required
        return jsonify({'message': 'Logged out successfully'}), 200
    except Exception as e:
        current_app.logger.exception(f"Error during logout: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current CRM user information (UserMaster-aware)"""
    try:
        if hasattr(g.user, 'to_dict'):
            return jsonify({'user': g.user.to_dict()}), 200

        # legacy fallback
        user_data = {
            'id': getattr(g.user, 'id', None),
            'email': getattr(g.user, 'email', None),
            'first_name': getattr(g.user, 'first_name', None),
            'last_name': getattr(g.user, 'last_name', None),
            'role': getattr(g.user, 'role', None),
        }
        return jsonify({'user': user_data}), 200
    except Exception as e:
        current_app.logger.exception(f"Error in /auth/me: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    
@auth_bp.route('/users/staff', methods=['GET'])
@admin_required
def get_staff_users():
    """Get all staff users"""
    session = SessionLocal()
    try:
        staff_roles = ['Staff']
        staff_users = session.query(User).filter(
            User.role.in_(staff_roles)
        ).order_by(User.first_name).all()
        
        return jsonify({
            'users': [user.to_dict() for user in staff_users]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/refresh', methods=['POST'])
@token_required
def refresh_token():
    """Refresh JWT token"""
    session = SessionLocal()
    try:
        user = g.user

        # Preserve tenant and identity claims from the incoming token when present.
        # Prefer claims from the incoming token (so refresh is idempotent),
        # but fall back to attributes on the loaded user.
        old_token = request.headers.get('Authorization').split(" ")[1]
        old_payload = {}
        try:
            # decode without enforcing expiry so we can copy claims from an expired token
            old_payload = jwt.decode(old_token, current_app.config['SECRET_KEY'], algorithms=['HS256'], options={'verify_exp': False})
        except Exception:
            old_payload = {}

        employee_id = getattr(user, 'id', None) or old_payload.get('employee_id') or old_payload.get('user_id')
        tenant_id = old_payload.get('tenant_id') or getattr(user, 'tenant_id', None)
        user_name = old_payload.get('user_name') or getattr(user, 'user_name', None)

        payload = {
            'user_id': employee_id,
            'employee_id': employee_id,
            'user_name': user_name,
            'tenant_id': tenant_id,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        # keep token compact by removing None values
        payload = {k: v for k, v in payload.items() if v is not None}
        new_token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

        old_token = old_token
        session_record = session.query(Session).filter_by(session_token=old_token).first()

        if session_record:
            session_record.session_token = new_token
            session_record.expires_at = datetime.utcnow() + timedelta(days=7)
            session.commit()
        
        return jsonify({
            'token': new_token,
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error refreshing token: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Request password reset"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        if not data.get('email'):
            return jsonify({'error': 'Email is required'}), 400
        
        email = data['email'].lower().strip()
        user = session.query(User).filter_by(email=email).first()
        
        if user:
            reset_token = user.generate_reset_token()
            session.add(user)
            session.commit()
            current_app.logger.info(f"Password reset token for {email}: {reset_token}")
        
        return jsonify({
            'message': 'If the email exists, a password reset link has been sent.'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error requesting password reset: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password with token"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        required_fields = ['token', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        token = data['token']
        password = data['password']
        
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        user = session.query(User).filter(
            User.reset_token == token,
            User.reset_token_expires > datetime.utcnow()
        ).first()
        
        if not user:
            return jsonify({'error': 'Invalid or expired reset token'}), 400
        
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        
        session.add(user)
        session.commit()
        
        return jsonify({'message': 'Password reset successful'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error resetting password: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users"""
    session = SessionLocal()
    try:
        users = session.query(User).order_by(User.created_at.desc()).all()
        
        return jsonify({
            'users': [user.to_dict() for user in users]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/users/me', methods=['GET', 'OPTIONS'])
@token_required
def get_user_me():
    """Get current user information - alternative endpoint"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        return jsonify({
            'id': g.user.id,
            'name': g.user.full_name if hasattr(g.user, 'full_name') else f"{g.user.first_name} {g.user.last_name}",
            'email': g.user.email,
            'role': g.user.role,
            'username': g.user.username if hasattr(g.user, 'username') else g.user.email
        }), 200
    except Exception as e:
        current_app.logger.exception(f"Error fetching current user: {e}")
        return jsonify({'error': 'Failed to fetch user information'}), 500

@auth_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Toggle user active status"""
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        if 'is_active' in data:
            user.is_active = data['is_active']
        else:
            user.is_active = not user.is_active
            
        user.updated_at = datetime.utcnow()
        
        session.commit()
        
        return jsonify({
            'message': f'User {"activated" if user.is_active else "deactivated"} successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error toggling user status: {e}")
        return jsonify({'error': 'Failed to toggle user status'}), 500
    finally:
        session.close()

def get_tenant_id_from_token():
    """Read tenant_id directly from the JWT — most reliable source."""
    try:
        token = request.headers.get('Authorization', '').split(' ')[1]
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload.get('tenant_id')
    except Exception:
        return None

@auth_bp.route('/invite-user', methods=['POST'])
@admin_required
def invite_user():
    """Create an invitation for a new user"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        required_fields = ['first_name', 'last_name', 'email', 'role']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        email = data['email'].lower().strip()
        first_name = data['first_name'].strip()
        last_name = data['last_name'].strip()
        role = data['role'].strip()
        
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # ✨ UPDATED: Only Admin and Staff roles for Forklift Academy
        ALLOWED_ROLES = ['Admin', 'Staff']
        if role not in ALLOWED_ROLES:
            return jsonify({'error': f'Role must be one of: {", ".join(ALLOWED_ROLES)}'}), 400
        
        existing_user = session.query(User).filter_by(email=email).first()
        if existing_user:
            return jsonify({'error': 'A user with this email already exists'}), 400
        
        invitation_token = secrets.token_urlsafe(32)
        
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=role,
            is_active=False,
            is_invited=True,
            invitation_token=invitation_token,
            invited_at=datetime.utcnow()
        )
        
        session.add(new_user)
        session.commit()
        
        current_app.logger.info(f"✅ Invitation created for: {email} as {role}")
        
        return jsonify({
            'success': True,
            'message': 'Invitation created successfully',
            'invitation_token': invitation_token,
            'user': new_user.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Invitation creation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/resend-invitation/<int:user_id>', methods=['POST'])
@admin_required
def resend_invitation(user_id):
    """Generate a new invitation token for a user"""
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not user.is_invited:
            return jsonify({'error': 'User has already completed registration'}), 400
        
        user.invitation_token = secrets.token_urlsafe(32)
        user.invited_at = datetime.utcnow()
        
        session.commit()
        
        current_app.logger.info(f"✅ Invitation resent for: {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'New invitation link generated',
            'invitation_token': user.invitation_token
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Resend invitation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update user details"""
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        
        if 'first_name' in data:
            user.first_name = data['first_name'].strip()
        
        if 'last_name' in data:
            user.last_name = data['last_name'].strip()
        
        if 'email' in data:
            new_email = data['email'].lower().strip()
            existing = session.query(User).filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                return jsonify({'error': 'Email already in use'}), 400
            
            if not validate_email(new_email):
                return jsonify({'error': 'Invalid email format'}), 400
            
            user.email = new_email
        
        if 'role' in data:
            role = data['role'].strip()
            # ✨ UPDATED: Only Admin and Staff roles for Forklift Academy
            ALLOWED_ROLES = ['Admin', 'Staff']
            if role not in ALLOWED_ROLES:
                return jsonify({'error': f'Role must be one of: {", ".join(ALLOWED_ROLES)}'}), 400
            user.role = role
        
        user.updated_at = datetime.utcnow()
        
        session.commit()
        
        current_app.logger.info(f"✅ User updated: {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'User updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Update user error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user"""
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        current_user = g.user
        if hasattr(current_user, 'id') and user.id == current_user.id:
            return jsonify({'error': 'You cannot delete your own account'}), 400
        
        email = user.email
        
        session.delete(user)
        session.commit()
        
        current_app.logger.info(f"✅ User deleted: {email}")
        
        return jsonify({
            'success': True,
            'message': 'User deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Delete user error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/settings/company', methods=['PUT'])
@admin_required
def update_company_settings():
    """Update company settings"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        # TODO: Implement actual company settings storage in database
        
        current_app.logger.info(f"✅ Company settings update requested: {data}")
        
        return jsonify({
            'success': True,
            'message': 'Company settings updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Company settings update error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/validate-invitation', methods=['POST'])
def validate_invitation():
    """Validate an invitation token and return user info"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        
        invitation_token = data.get('invitation_token')
        if not invitation_token:
            return jsonify({'error': 'Invitation token is required'}), 400
        
        user = session.query(User).filter_by(
            invitation_token=invitation_token,
            is_invited=True
        ).first()
        
        if not user:
            return jsonify({'error': 'Invalid or expired invitation token'}), 400
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"❌ Validate invitation error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    """Change user password by username (plain text storage per StreemLyne spec)"""
    session = SessionLocal()
    
    try:
        data = request.get_json()
        username = data.get('username')
        new_password = data.get('new_password')
        
        if not username or not new_password:
            return jsonify({'error': 'Username and new password are required'}), 400
        
        if len(new_password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters long'}), 400
        
        # ✅ Query User_Master table (not User_Credentials)
        sql = text('''
            SELECT user_id, user_name 
            FROM "StreemLyne_MT"."User_Master" 
            WHERE user_name = :username 
            LIMIT 1
        ''')
        
        row = session.execute(sql, {'username': username}).mappings().first()
        
        if not row:
            return jsonify({'error': 'User not found'}), 404
        
        user_id = row.get('user_id')
        
        # ✅ Update password (plain text as per StreemLyne spec)
        update_sql = text('''
            UPDATE "StreemLyne_MT"."User_Master"
            SET password = :password
            WHERE user_id = :user_id
        ''')
        
        session.execute(update_sql, {
            'password': new_password,
            'user_id': user_id
        })
        
        session.commit()
        
        current_app.logger.info(f"✅ Password changed successfully for user: {username}")
        
        return jsonify({
            'message': 'Password changed successfully',
            'username': username
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error changing password: {str(e)}")
        return jsonify({'error': 'Failed to change password'}), 500
        
    finally:
        session.close()

# ==========================================
# INVITE SYSTEM FOR STREEMLYN MT
# ==========================================

def platform_admin_required(f):
    """Decorator: only Platform Admin can access"""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        session = SessionLocal()
        try:
            user = request.current_user
            result = session.execute(text("""
                SELECT rm.role_name
                FROM "StreemLyne_MT"."User_Role_Mapping" urm
                JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
                WHERE urm.user_id = :user_id
                LIMIT 1
            """), {'user_id': user.user_id}).fetchone()

            role = result[0] if result else None
            if role not in ['Platform Admin', 'Tenant Super Admin']:
                return jsonify({'error': 'Platform Admin access required'}), 403

            return f(*args, **kwargs)
        finally:
            session.close()
    return decorated


@auth_bp.route('/invite/create', methods=['POST', 'OPTIONS'])
@platform_admin_required
def create_team_invite():
    """
    Platform Admin creates a team member invite.
    Creates Employee_Master + User_Master rows with a token.
    Team member uses the token to set their password.

    Expected JSON: {
        "employee_name": "...",
        "email": "...",          # optional
        "phone": "...",          # optional
        "username": "...",
        "role_id": <int>         # from Role_Master
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json() or {}
        user = request.current_user

        # Get tenant_id from the inviting admin
        tenant_id = get_tenant_id_from_token()
        if not tenant_id:
            return jsonify({'error': 'Could not determine tenant from token'}), 400

        # Validate required fields
        if not data.get('employee_name'):
            return jsonify({'error': 'employee_name is required'}), 400
        if not data.get('username'):
            return jsonify({'error': 'username is required'}), 400
        if not data.get('role_id'):
            return jsonify({'error': 'role_id is required'}), 400

        username = data['username'].strip()
        employee_name = data['employee_name'].strip()
        email = data.get('email', '').strip() or None
        phone = data.get('phone', '').strip() or None
        role_id = int(data['role_id'])

        # Check username uniqueness
        existing_user = session.execute(text("""
            SELECT 1 FROM "StreemLyne_MT"."User_Master"
            WHERE user_name = :username LIMIT 1
        """), {'username': username}).first()

        if existing_user:
            return jsonify({'error': 'Username already exists'}), 400

        # Check email uniqueness if provided
        if email:
            existing_email = session.execute(text("""
                SELECT 1 FROM "StreemLyne_MT"."Employee_Master"
                WHERE email = :email LIMIT 1
            """), {'email': email}).first()
            if existing_email:
                return jsonify({'error': 'Email already exists'}), 400

        # Verify role_id exists
        role_row = session.execute(text("""
            SELECT role_name FROM "StreemLyne_MT"."Role_Master"
            WHERE role_id = :role_id LIMIT 1
        """), {'role_id': role_id}).mappings().first()

        if not role_row:
            return jsonify({'error': 'Invalid role_id'}), 400

        # Generate invite token (used as temp password placeholder)
        invite_token = secrets.token_urlsafe(32)

        # 1. Create Employee_Master row
        emp_row = session.execute(text("""
            INSERT INTO "StreemLyne_MT"."Employee_Master"
                (tenant_id, employee_name, email, phone)
            VALUES (:tenant_id, :employee_name, :email, :phone)
            RETURNING employee_id
        """), {
            'tenant_id': tenant_id,
            'employee_name': employee_name,
            'email': email,
            'phone': phone
        }).mappings().first()

        if not emp_row:
            session.rollback()
            return jsonify({'error': 'Failed to create employee'}), 500

        employee_id = emp_row['employee_id']

        # 2. Create User_Master row
        # Store invite_token in password field temporarily — team member will replace it
        user_row = session.execute(text("""
            INSERT INTO "StreemLyne_MT"."User_Master"
                (employee_id, user_name, password, invite_token, is_invite_pending)
            VALUES (:employee_id, :user_name, :password, :invite_token, TRUE)
            RETURNING user_id
        """), {
            'employee_id': employee_id,
            'user_name': username,
            'password': invite_token,  # placeholder until they set real password
            'invite_token': invite_token
        }).mappings().first()

        if not user_row:
            session.rollback()
            return jsonify({'error': 'Failed to create user'}), 500

        user_id = user_row['user_id']

        # 3. Assign role via User_Role_Mapping
        session.execute(text("""
            INSERT INTO "StreemLyne_MT"."User_Role_Mapping" (user_id, role_id)
            VALUES (:user_id, :role_id)
        """), {'user_id': user_id, 'role_id': role_id})

        session.commit()

        # Build invite link (frontend handles this URL)
        base_url = request.headers.get('Origin', 'https://your-app.vercel.app')
        invite_link = f"{base_url}/accept-invite?token={invite_token}"

        current_app.logger.info(
            f"✅ Invite created: employee_id={employee_id} user_id={user_id} "
            f"username={username} role={role_row['role_name']} tenant_id={tenant_id}"
        )

        return jsonify({
            'success': True,
            'message': 'Invite created successfully',
            'invite': {
                'employee_id': employee_id,
                'user_id': user_id,
                'employee_name': employee_name,
                'username': username,
                'role': role_row['role_name'],
                'invite_token': invite_token,
                'invite_link': invite_link,
            }
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating invite: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/invite/validate/<token>', methods=['GET', 'OPTIONS'])
def validate_invite_token(token):
    """
    Public endpoint — validate an invite token.
    Frontend calls this when team member lands on /accept-invite?token=...
    Returns the username and employee name so the page can greet them.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(text("""
            SELECT
                u.user_id,
                u.user_name,
                u.is_invite_pending,
                e.employee_name,
                e.email,
                rm.role_name
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            LEFT JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE u.invite_token = :token
            LIMIT 1
        """), {'token': token}).mappings().first()

        if not row:
            return jsonify({'valid': False, 'error': 'Invalid invite link'}), 404

        if not row['is_invite_pending']:
            return jsonify({'valid': False, 'error': 'Invite already used'}), 400

        return jsonify({
            'valid': True,
            'employee_name': row['employee_name'],
            'username': row['user_name'],
            'email': row['email'],
            'role': row['role_name'],
        }), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error validating invite token: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/invite/accept', methods=['POST', 'OPTIONS'])
def accept_invite():
    """
    Public endpoint — team member sets their password using the invite token.
    After this, they can log in normally via /login.

    Expected JSON: {
        "token": "...",
        "password": "..."
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        data = request.get_json() or {}
        token = data.get('token')
        password = data.get('password')

        if not token or not password:
            return jsonify({'error': 'token and password are required'}), 400

        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400

        row = session.execute(text("""
            SELECT u.user_id, u.user_name, u.is_invite_pending, e.employee_id, e.tenant_id, e.employee_name
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            WHERE u.invite_token = :token
            LIMIT 1
        """), {'token': token}).mappings().first()

        if not row:
            return jsonify({'error': 'Invalid invite token'}), 404

        if not row['is_invite_pending']:
            return jsonify({'error': 'Invite already used. Please log in.'}), 400

        # Set real password, clear token, mark invite as complete
        session.execute(text("""
            UPDATE "StreemLyne_MT"."User_Master"
            SET password = :password,
                invite_token = NULL,
                is_invite_pending = FALSE
            WHERE user_id = :user_id
        """), {
            'password': password,
            'user_id': row['user_id']
        })

        session.commit()

        current_app.logger.info(
            f"✅ Invite accepted: user_id={row['user_id']} username={row['user_name']}"
        )

        return jsonify({
            'success': True,
            'message': 'Password set successfully. You can now log in.',
            'username': row['user_name'],
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error accepting invite: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/invite/list', methods=['GET', 'OPTIONS'])
@platform_admin_required
def list_invites():
    """
    Platform Admin — list all team members (both pending and active) for their tenant.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        user = request.current_user

        tenant_id = get_tenant_id_from_token()
        if not tenant_id:
            return jsonify({'error': 'Tenant not found in token'}), 400

        current_app.logger.info(f"📋 list_invites: tenant_id={tenant_id}")

        rows = session.execute(text("""
            SELECT
                e.employee_id,
                e.employee_name,
                e.email,
                e.phone,
                u.user_id,
                u.user_name,
                u.is_invite_pending,
                u.invite_token,
                rm.role_name,
                rm.role_id
            FROM "StreemLyne_MT"."Employee_Master" e
            LEFT JOIN "StreemLyne_MT"."User_Master" u ON e.employee_id = u.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            LEFT JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE e.tenant_id = :tenant_id
            ORDER BY e.employee_name ASC
        """), {'tenant_id': tenant_id}).mappings().all()

        base_url = request.headers.get('Origin', 'https://your-app.vercel.app')

        members = []
        for r in rows:
            member = {
                'employee_id': r['employee_id'],
                'employee_name': r['employee_name'],
                'email': r['email'],
                'phone': r['phone'],
                'user_id': r['user_id'],
                'username': r['user_name'],
                'role': r['role_name'],
                'role_id': r['role_id'],
                'is_invite_pending': r['is_invite_pending'],
                'invite_link': (
                    f"{base_url}/accept-invite?token={r['invite_token']}"
                    if r['is_invite_pending'] and r['invite_token']
                    else None
                ),
            }
            members.append(member)

        return jsonify({'members': members}), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error listing invites: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@auth_bp.route('/invite/resend/<int:user_id>', methods=['POST', 'OPTIONS'])
@platform_admin_required
def resend_invite(user_id):
    """
    Generate a new invite token for a pending team member.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        row = session.execute(text("""
            SELECT u.user_id, u.user_name, u.is_invite_pending, e.employee_name
            FROM "StreemLyne_MT"."User_Master" u
            JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            WHERE u.user_id = :user_id LIMIT 1
        """), {'user_id': user_id}).mappings().first()

        if not row:
            return jsonify({'error': 'User not found'}), 404

        if not row['is_invite_pending']:
            return jsonify({'error': 'User has already accepted their invite'}), 400

        new_token = secrets.token_urlsafe(32)

        session.execute(text("""
            UPDATE "StreemLyne_MT"."User_Master"
            SET invite_token = :token, password = :token
            WHERE user_id = :user_id
        """), {'token': new_token, 'user_id': user_id})

        session.commit()

        base_url = request.headers.get('Origin', 'https://your-app.vercel.app')
        invite_link = f"{base_url}/accept-invite?token={new_token}"

        return jsonify({
            'success': True,
            'message': 'New invite link generated',
            'invite_token': new_token,
            'invite_link': invite_link,
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error resending invite: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/invite/delete/<int:employee_id>', methods=['DELETE', 'OPTIONS'])
@platform_admin_required
def delete_team_member(employee_id):
    """
    Permanently delete a team member (Employee_Master + User_Master + Role_Mapping).
    Cannot delete yourself.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        admin = request.current_user

        # Prevent self-deletion
        if admin.employee_id == employee_id:
            return jsonify({'error': 'You cannot delete your own account'}), 400

        # Check employee exists and belongs to same tenant
        emp_row = session.execute(text("""
            SELECT e.employee_id, e.tenant_id, u.user_id
            FROM "StreemLyne_MT"."Employee_Master" e
            LEFT JOIN "StreemLyne_MT"."User_Master" u ON e.employee_id = u.employee_id
            WHERE e.employee_id = :eid LIMIT 1
        """), {'eid': employee_id}).mappings().first()

        if not emp_row:
            return jsonify({'error': 'Employee not found'}), 404

        # Verify same tenant
        admin_tenant_id = get_tenant_id_from_token()
        if not admin_tenant_id or emp_row['tenant_id'] != admin_tenant_id:
            return jsonify({'error': 'Cannot delete employee from another tenant'}), 403

        user_id = emp_row['user_id']

        # Delete in order: Role_Mapping → User_Master → Employee_Master
        if user_id:
            session.execute(text("""
                DELETE FROM "StreemLyne_MT"."User_Role_Mapping"
                WHERE user_id = :user_id
            """), {'user_id': user_id})

            session.execute(text("""
                DELETE FROM "StreemLyne_MT"."User_Master"
                WHERE user_id = :user_id
            """), {'user_id': user_id})

        session.execute(text("""
            DELETE FROM "StreemLyne_MT"."Employee_Master"
            WHERE employee_id = :eid
        """), {'eid': employee_id})

        session.commit()

        current_app.logger.info(f"✅ Deleted employee_id={employee_id} user_id={user_id}")

        return jsonify({'success': True, 'message': 'Team member deleted successfully'}), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting team member: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()