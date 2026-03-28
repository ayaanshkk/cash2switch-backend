from functools import wraps
from flask import request, jsonify, current_app, g
import jwt
from ..models import UserMaster
from ..db import SessionLocal


def token_required(f):
    """Decorator to require valid JWT token (CRM-aware, uses UserMaster).

    Strategy mirrors auth_routes.py exactly:
      1. Decode JWT to get employee_id (primary identity claim).
      2. Look up UserMaster by employee_id column — this means the DB row
         always has employee_id populated, so user.employee_id is never None.
      3. Overlay tenant_id and role from JWT onto the user object.

    This is why renewals works and leads didn't: renewals uses auth_routes.py's
    token_required which does filter_by(employee_id=...). The old auth_helpers.py
    version did session.get(UserMaster, user_id) (lookup by PK) and then
    conditionally set employee_id from the JWT — meaning if the JWT omitted it,
    the attribute stayed as whatever was on the DB row (often None on live).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
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
                payload = jwt.decode(token, secret_key, algorithms=['HS256'])

                current_app.logger.info(
                    "🔐 JWT decoded. Keys: %s", list(payload.keys())
                )

                # ── Identity resolution (mirrors auth_routes.py) ──────────────
                # JWT carries both user_id (User_Master PK) and employee_id.
                # employee_id is the reliable scoping key for all CRM queries.
                # Prefer employee_id; fall back to user_id for old tokens.
                employee_id_from_jwt = payload.get('employee_id')
                user_id_from_jwt     = payload.get('user_id')

                user = None

                # ✅ PRIMARY: look up by employee_id (same as auth_routes.py)
                # This guarantees user.employee_id is never None — it comes
                # from the Employee_Master-joined column on the DB row itself.
                if employee_id_from_jwt is not None:
                    user = (
                        local_session.query(UserMaster)
                        .filter_by(employee_id=employee_id_from_jwt)
                        .first()
                    )

                # ✅ FALLBACK: look up by User_Master PK for old-format tokens
                if user is None and user_id_from_jwt is not None:
                    user = local_session.get(UserMaster, user_id_from_jwt)

                if user is None:
                    current_app.logger.warning(
                        "Auth token valid but UserMaster not found "
                        "(employee_id=%s, user_id=%s)",
                        employee_id_from_jwt, user_id_from_jwt
                    )
                    return jsonify({'error': 'User not found'}), 401

                if not getattr(user, 'is_active', True):
                    return jsonify({'error': 'User not active'}), 401

                # ── Overlay JWT claims onto user object ───────────────────────
                # tenant_id and role always come from JWT (authoritative source).
                # employee_id is already correct from the DB lookup above — only
                # override it if the JWT has a value (handles edge cases where
                # the DB row's employee_id column is still NULL).
                user.tenant_id = payload.get('tenant_id')
                if employee_id_from_jwt is not None:
                    user.employee_id = employee_id_from_jwt

                raw_role = payload.get('role')
                user.role = str(raw_role).strip().lower() if raw_role else None

                current_app.logger.info(
                    "👤 Authenticated: user_id=%s employee_id=%s tenant_id=%s role=%s",
                    getattr(user, 'user_id', None),
                    user.employee_id,
                    user.tenant_id,
                    user.role,
                )

                g.user = user
                request.current_user = user

            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError as e:
                current_app.logger.error("Invalid token: %s", e)
                return jsonify({'error': 'Token is invalid or expired'}), 401
            except Exception as e:
                current_app.logger.error("Token verification failed: %s", e)
                return jsonify({'error': 'Token verification failed'}), 401

            return f(*args, **kwargs)
        finally:
            local_session.close()

    return decorated


def get_tenant_id_from_user(user):
    """
    Extract tenant_id from authenticated user object.
    JWT is always the authoritative source (set in token_required above).
    Falls back to Employee_Master lookup for legacy flows.
    """
    if hasattr(user, 'tenant_id') and user.tenant_id is not None:
        return user.tenant_id

    if hasattr(user, 'employee_id') and user.employee_id is not None:
        session = SessionLocal()
        try:
            from ..models import Employee_Master
            employee = session.query(Employee_Master).filter_by(
                employee_id=user.employee_id
            ).first()
            return employee.tenant_id if employee else None
        finally:
            session.close()

    return None