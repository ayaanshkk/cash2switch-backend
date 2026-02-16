# -*- coding: utf-8 -*-
"""
Role checking utilities for CRM
"""
from flask import request, jsonify, current_app
from functools import wraps


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
    Check if user has admin role.
    
    Supports multiple admin identifiers:
    1. Checks Role_Master.role_name for "admin" or "administrator"
    2. Falls back to employee_id==1 or user_id==1 for backward compatibility
    3. Checks user_name for "admin" or "administrator"
    """
    if not user:
        return False
    
    # First: Check actual role from Role_Master
    role_name = get_user_role_name(user)
    if role_name in {"admin", "administrator"}:
        return True
    
    # Fallback: Legacy checks for backward compatibility
    employee_id = getattr(user, 'employee_id', None)
    user_id = getattr(user, 'user_id', None) or getattr(user, 'User_id', None)
    user_name = str(getattr(user, 'user_name', '') or getattr(user, 'User_name', '') or '').strip().lower()

    return employee_id == 1 or user_id == 1 or user_name in {"admin", "administrator"}


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
