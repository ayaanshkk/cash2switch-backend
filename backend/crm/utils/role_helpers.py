# -*- coding: utf-8 -*-
"""
Role checking utilities for CRM
"""
from typing import Any, Optional

from flask import request, jsonify, current_app
from functools import wraps

ADMIN_ROLES = {
    "platform admin",
    "tenant super admin",
    "admin",
    "superadmin",
    "super admin",
}


def is_crm_leads_admin_role(jwt_role: Optional[Any]) -> bool:
    """
    True when the JWT `role` string should grant tenant-wide CRM leads visibility.

    Uses explicit names / suffixes — not naive substring match — so roles like
    `sales_admin` (one token) are not treated as full tenant admins.

    `platform admin`, `super admin`, etc. are included.
    """
    if jwt_role is None:
        return False
    r = ' '.join(str(jwt_role).strip().lower().split())
    if not r:
        return False
    if r in frozenset({
        'admin',
        'administrator',
        'platform admin',
        'super admin',
        'superadmin',
    }):
        return True
    if r.endswith(' admin') or r.endswith(' administrator'):
        return True
    return False


def get_user_role_name(user) -> str:
    """
    Get the role name for a user by querying Role_Master.
    
    Args:
        user: User object with role_id or Role_id attribute
    
    Returns:
        Role name (lowercase) or empty string if not found
    """
    if not user:
        return ""
    
    # Try to get role_name directly from user object (if already joined)
    role_name = getattr(user, 'role_name', None)
    if role_name:
        return str(role_name).strip().lower()
    
    # Try to get Role_id and query Role_Master
    role_id = getattr(user, 'Role_id', None) or getattr(user, 'role_id', None)
    if not role_id:
        return ""
    
    try:
        from backend.database import SessionLocal
        session = SessionLocal()
        
        query = """
            SELECT "role_name" 
            FROM "StreemLyne_MT"."Role_Master" 
            WHERE "Role_id" = %s
            LIMIT 1
        """
        
        result = session.execute(query, (role_id,)).fetchone()
        session.close()
        
        if result:
            return str(result[0]).strip().lower()
    except Exception as e:
        current_app.logger.error(f"Error fetching role for role_id {role_id}: {e}")
    
    return ""


def is_admin_user(user) -> bool:
    """
    Return True if the user has an admin-level role.
 
    Checks user.role case-insensitively against the known admin role names.
    Returns False if user is None or has no role attribute.
 
    Previously this compared against title-case strings only, which broke when
    auth_helpers.py stored the role in lowercase. Now both sides are lowercased
    so the comparison always works regardless of case.
    """
    if user is None:
        return False
 
    role = getattr(user, 'role', None)
    if not role:
        return False
 
    return str(role).strip().lower() in ADMIN_ROLES


def admin_required(f):
    """
    Decorator to require admin role.
    Must be used after @token_required decorator.
    Returns 403 Forbidden if user is not admin.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(request, 'current_user', None)
        
        if not user:
            return jsonify({
                'error': 'Authentication required',
                'message': 'Please log in to access this resource'
            }), 401
        
        if not is_admin_user(user):
            return jsonify({
                'error': 'Access denied',
                'message': 'Admin role required for this operation'
            }), 403
        
        return f(*args, **kwargs)
    
    return decorated
