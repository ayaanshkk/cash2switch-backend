# -*- coding: utf-8 -*-
"""
Tenant Middleware for Multi-Tenant Isolation
Extracts and validates tenant_id from request headers
"""
from functools import wraps
from flask import request, jsonify, g
from backend.crm.repositories.tenant_repository import TenantRepository

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
        tenant = tenant_repo.get_tenant_by_id(tenant_id)
        
        if not tenant:
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
