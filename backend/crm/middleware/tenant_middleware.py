# -*- coding: utf-8 -*-
"""
Tenant Middleware for Multi-Tenant Isolation
Extracts and validates tenant_id from request headers
"""
import os
from functools import wraps
from flask import request, jsonify, g
from backend.crm.repositories.tenant_repository import TenantRepository


def _is_production():
    """True if we should enforce strict tenant validation (no auto-create)."""
    if (os.getenv("FLASK_ENV") or "").lower() in ("development",):
        return False
    if (os.getenv("TEST_MODE") or "").lower() in ("1", "true", "yes"):
        return False
    db_url = os.getenv("DATABASE_URL") or ""
    if not db_url or "sqlite" in db_url.lower():
        return False
    return True


def require_tenant(f):
    """
    Decorator to enforce tenant validation
    
    Extracts X-Tenant-ID from request headers
    Validates tenant existence in Tenant_Master table
    Attaches tenant_id to Flask's g object for use in views
    
    Usage:
        @app.route('/api/crm/leads')
        @require_tenant
        def get_leads():
            tenant_id = g.tenant_id
            # ... your code
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Extract tenant_id from header
        tenant_id = request.headers.get('X-Tenant-ID')
        
        if not tenant_id:
            return jsonify({
                'error': 'Missing tenant identifier',
                'message': 'X-Tenant-ID header is required'
            }), 400
        
        # Validate tenant_id format (assuming UUID or integer)
        try:
            # Try to convert to int if it's numeric
            if tenant_id.isdigit():
                tenant_id = int(tenant_id)
        except (ValueError, AttributeError):
            return jsonify({
                'error': 'Invalid tenant identifier format',
                'message': 'X-Tenant-ID must be a valid identifier'
            }), 400
        
        # Validate tenant exists in database
        tenant_repo = TenantRepository()
        
        try:
            tenant = tenant_repo.get_tenant_by_id(tenant_id)
        except Exception as e:
            print(f"Error during tenant lookup: {e}")
            return jsonify({
                'error': 'Tenant validation failed',
                'message': 'Unable to validate tenant. Please try again.'
            }), 500
        
        if not tenant:
            if not _is_production():
                default_tenant = tenant_repo.ensure_default_tenant()
                if default_tenant and default_tenant.get("Tenant_id") is not None:
                    tenant_id = int(default_tenant["Tenant_id"])
                    tenant = default_tenant
                    if not tenant.get("is_active", True):
                        tenant["is_active"] = True
                else:
                    # Stub or read-only DB: accept requested tenant_id so dev/test can proceed
                    tenant = {"Tenant_id": tenant_id, "tenant_company_name": "Default Tenant", "is_active": True}
            else:
                return jsonify({
                    'error': 'Tenant not found',
                    'message': f'Tenant with ID {tenant_id} does not exist or is inactive'
                }), 404
        
        # Check if tenant is active
        if not tenant.get('is_active', True):
            return jsonify({
                'error': 'Tenant inactive',
                'message': 'This tenant account is currently inactive'
            }), 403
        
        # Attach tenant info to Flask's g object
        g.tenant_id = tenant_id
        g.tenant = tenant
        
        # Call the actual view function
        return f(*args, **kwargs)
    
    return decorated_function


def require_tenant_jwt_only(f):
    """
    Decorator for endpoints that MUST take tenant_id from the authenticated JWT only.

    Behavior:
      - Reads tenant_id from request.current_user.tenant_id (decoded JWT)
      - If the JWT is missing or does not include tenant_id -> return 401 Unauthorized
      - Validates tenant exists (same as require_tenant) but DOES NOT accept X-Tenant-ID header
    """
    from functools import wraps
    from flask import request, jsonify, g
    from backend.crm.repositories.tenant_repository import TenantRepository

    @wraps(f)
    def decorated(*args, **kwargs):
        # Must have an authenticated user with tenant_id in the token
        current_user = getattr(request, 'current_user', None)
        if not current_user or getattr(current_user, 'tenant_id', None) is None:
            return jsonify({
                'error': 'Missing tenant in token',
                'message': 'Authenticated token must include tenant_id'
            }), 401

        tenant_id = getattr(current_user, 'tenant_id')

        # Normalize numeric tenant IDs
        try:
            if isinstance(tenant_id, str) and tenant_id.isdigit():
                tenant_id = int(tenant_id)
        except Exception:
            return jsonify({
                'error': 'Invalid tenant identifier in token',
                'message': 'tenant_id in token has invalid format'
            }), 401

        # Validate tenant exists (reuse existing repo behavior)
        tenant_repo = TenantRepository()
        try:
            tenant = tenant_repo.get_tenant_by_id(tenant_id)
        except Exception as e:
            print(f"Error during tenant lookup: {e}")
            return jsonify({
                'error': 'Tenant validation failed',
                'message': 'Unable to validate tenant. Please try again.'
            }), 500

        if not tenant:
            # Keep non-production convenience behaviour from require_tenant
            if not _is_production():
                default_tenant = tenant_repo.ensure_default_tenant()
                if default_tenant and default_tenant.get("Tenant_id") is not None:
                    tenant_id = int(default_tenant["Tenant_id"])
                    tenant = default_tenant
                    if not tenant.get("is_active", True):
                        tenant["is_active"] = True
                else:
                    tenant = {"Tenant_id": tenant_id, "tenant_company_name": "Default Tenant", "is_active": True}
            else:
                return jsonify({
                    'error': 'Tenant not found',
                    'message': f'Tenant with ID {tenant_id} does not exist or is inactive'
                }), 404

        if not tenant.get('is_active', True):
            return jsonify({
                'error': 'Tenant inactive',
                'message': 'This tenant account is currently inactive'
            }), 403

        g.tenant_id = tenant_id
        g.tenant = tenant
        return f(*args, **kwargs)

    return decorated


def get_tenant_id():
    """
    Helper function to get current tenant_id from Flask's g object
    
    Returns:
        tenant_id if set, None otherwise
    """
    return getattr(g, 'tenant_id', None)


def get_tenant():
    """
    Helper function to get current tenant object from Flask's g object
    
    Returns:
        tenant dict if set, None otherwise
    """
    return getattr(g, 'tenant', None)
