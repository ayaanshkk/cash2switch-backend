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

# ✅ Only platform admins see ALL tenant data (leads + renewals)
PLATFORM_ADMIN_ROLES = {
    "platform admin",
    "platform_admin",
    "platformadmin",
}


def is_platform_admin(user) -> bool:
    """Returns True only for platform admins who can see all tenant data."""
    role = str(getattr(user, 'role', '') or '').strip().lower()
    return role in PLATFORM_ADMIN_ROLES


def is_crm_leads_admin_role(jwt_role: Optional[Any]) -> bool:
    """
    True when the JWT role should grant tenant-wide CRM leads visibility.
    Only platform admins see all leads — other admin roles see their own only.
    """
    if jwt_role is None:
        return False
    role = str(jwt_role).strip().lower()
    return role in PLATFORM_ADMIN_ROLES


def is_admin_user(user) -> bool:
    """
    Return True if the user has any admin-level role.
    Used for general admin checks (not tenant-wide data visibility).
    """
    if user is None:
        return False
    role = getattr(user, 'role', None)
    if not role:
        return False
    return str(role).strip().lower() in ADMIN_ROLES


def get_user_role_name(user) -> str:
    """
    Get the role name for a user by querying Role_Master.
    """
    if not user:
        return ""

    role_name = getattr(user, 'role_name', None)
    if role_name:
        return str(role_name).strip().lower()

    role_id = getattr(user, 'Role_id', None) or getattr(user, 'role_id', None)
    if not role_id:
        return ""

    try:
        from backend.db import SessionLocal
        session = SessionLocal()
        try:
            from sqlalchemy import text
            result = session.execute(
                text('SELECT "role_name" FROM "StreemLyne_MT"."Role_Master" WHERE "Role_id" = :rid LIMIT 1'),
                {'rid': role_id}
            ).fetchone()
            if result:
                return str(result[0]).strip().lower()
        finally:
            session.close()
    except Exception as e:
        current_app.logger.error(f"Error fetching role for role_id {role_id}: {e}")

    return ""


def admin_required(f):
    """
    Decorator to require admin role.
    Must be used after @token_required decorator.
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