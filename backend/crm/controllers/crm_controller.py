# -*- coding: utf-8 -*-
"""
CRM Controllers
Request handling layer for CRM operations
"""
from flask import request, jsonify, g
from typing import Dict, Any
from backend.crm.services.crm_service import CRMService


class CRMController:
    """
    CRM Controller
    Handles HTTP requests and responses for CRM operations
    """
    
    def __init__(self):
        self.crm_service = CRMService()
    
    # ========================================
    # LEAD ENDPOINTS
    # ========================================
    
    def get_leads(self) -> tuple:
        """
        GET /api/crm/leads
        Get all leads for the current tenant
        """
        try:
            tenant_id = g.tenant_id
            
            # Extract query parameters for filtering
            filters = {}
            if request.args.get('stage_id'):
                filters['stage_id'] = int(request.args.get('stage_id'))
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            if request.args.get('assigned_to'):
                filters['assigned_to'] = int(request.args.get('assigned_to'))
            
            result = self.crm_service.get_leads(tenant_id, filters if filters else None)
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def get_lead_detail(self, opportunity_id: int) -> tuple:
        """
        GET /api/crm/leads/<opportunity_id>
        Get details of a specific lead
        """
        try:
            tenant_id = g.tenant_id
            result = self.crm_service.get_lead_detail(tenant_id, opportunity_id)
            
            if not result.get('success'):
                return jsonify(result), 404
            
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def create_lead(self) -> tuple:
        """
        POST /api/crm/leads
        Create a new lead. Supports either:
          - Existing client: provide `client_id`
          - Create client + lead: provide `client` object or `business_name`/`client_company_name`

        Tenant ID is taken from `g.tenant_id` (middleware enforces presence).
        """
        try:
            tenant_id = g.tenant_id
            payload = request.get_json()

            if not payload:
                return jsonify({
                    'success': False,
                    'error': 'Invalid request',
                    'message': 'Request body is required'
                }), 400

            # Basic validation: either client_id OR client payload/company name must exist
            if not payload.get('client_id') and not (payload.get('client') or payload.get('client_company_name') or payload.get('business_name')):
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': 'Provide client_id OR client (object) / business_name in the request body.'
                }), 400

            result = self.crm_service.create_lead(tenant_id, payload)

            # Service returns structured error info
            if not result.get('success'):
                status_code = 400 if result.get('error') and result.get('error').lower().startswith('validation') else 500
                return jsonify(result), status_code

            return jsonify(result), 201
        except Exception as e:
            logger.exception("create_lead controller error: %s", e)
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def update_lead(self, opportunity_id: int) -> tuple:
        """
        PUT /api/crm/leads/<opportunity_id>
        Update an existing lead
        """
        try:
            tenant_id = g.tenant_id
            lead_data = request.get_json()
            
            if not lead_data:
                return jsonify({
                    'success': False,
                    'error': 'Invalid request',
                    'message': 'Request body is required'
                }), 400
            
            result = self.crm_service.update_lead(tenant_id, opportunity_id, lead_data)
            
            if not result.get('success'):
                return jsonify(result), 404
            
            return jsonify(result), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def delete_lead(self, opportunity_id: int) -> tuple:
        """
        DELETE /api/crm/leads/<opportunity_id>
        Delete a lead
        """
        try:
            tenant_id = g.tenant_id
            
            result = self.crm_service.delete_lead(tenant_id, opportunity_id)
            
            if not result.get('success'):
                return jsonify(result), 404
            
            return jsonify(result), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    # ========================================
    # PROJECT ENDPOINTS
    # ========================================
    
    def get_projects(self) -> tuple:
        """
        GET /api/crm/projects
        Get all projects for the current tenant
        """
        try:
            tenant_id = g.tenant_id
            
            # Extract query parameters for filtering
            filters = {}
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            if request.args.get('project_manager_id'):
                filters['project_manager_id'] = int(request.args.get('project_manager_id'))
            
            result = self.crm_service.get_projects(tenant_id, filters if filters else None)
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def get_project_detail(self, project_id: int) -> tuple:
        """
        GET /api/crm/projects/<project_id>
        Get details of a specific project
        """
        try:
            tenant_id = g.tenant_id
            result = self.crm_service.get_project_detail(tenant_id, project_id)
            
            if not result.get('success'):
                return jsonify(result), 404
            
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    # ========================================
    # DEAL ENDPOINTS
    # ========================================
    
    def get_deals(self) -> tuple:
        """
        GET /api/crm/deals
        Get all deals/contracts for the current tenant
        """
        try:
            tenant_id = g.tenant_id
            
            # Extract query parameters for filtering
            filters = {}
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            if request.args.get('contract_owner_id'):
                filters['contract_owner_id'] = int(request.args.get('contract_owner_id'))
            
            result = self.crm_service.get_deals(tenant_id, filters if filters else None)
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def get_deal_detail(self, contract_id: int) -> tuple:
        """
        GET /api/crm/deals/<contract_id>
        Get details of a specific deal
        """
        try:
            tenant_id = g.tenant_id
            result = self.crm_service.get_deal_detail(tenant_id, contract_id)
            
            if not result.get('success'):
                return jsonify(result), 404
            
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    # ========================================
    # USER ENDPOINTS
    # ========================================
    
    def get_users(self) -> tuple:
        """
        GET /api/crm/users
        Get all users for the current tenant
        """
        try:
            tenant_id = g.tenant_id
            active_only = request.args.get('active_only', 'true').lower() == 'true'
            
            result = self.crm_service.get_users(tenant_id, active_only)
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    # ========================================
    # SUPPORTING DATA ENDPOINTS
    # ========================================
    
    def get_roles(self) -> tuple:
        """GET /api/crm/roles - Get all roles"""
        try:
            tenant_id = g.get('tenant_id')
            result = self.crm_service.get_roles(tenant_id)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_stages(self) -> tuple:
        """GET /api/crm/stages - Get all pipeline stages"""
        try:
            pipeline_type = request.args.get('pipeline_type')
            result = self.crm_service.get_stages(pipeline_type)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_services(self) -> tuple:
        """GET /api/crm/services - Get all services"""
        try:
            tenant_id = g.get('tenant_id')
            result = self.crm_service.get_services(tenant_id)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_suppliers(self) -> tuple:
        """GET /api/crm/suppliers - Get all suppliers"""
        try:
            tenant_id = g.tenant_id
            result = self.crm_service.get_suppliers(tenant_id)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_interactions(self) -> tuple:
        """GET /api/crm/interactions - Get all client interactions"""
        try:
            tenant_id = g.tenant_id
            
            # Extract filters
            filters = {}
            if request.args.get('client_id'):
                filters['client_id'] = int(request.args.get('client_id'))
            if request.args.get('interaction_type'):
                filters['interaction_type'] = request.args.get('interaction_type')
            if request.args.get('user_id'):
                filters['user_id'] = int(request.args.get('user_id'))
            
            result = self.crm_service.get_interactions(tenant_id, filters if filters else None)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    def get_leads_table(self) -> tuple:
        """
        GET /api/crm/leads/table
        Get leads table for CRM UI (flat rows with 14 columns from joined tables).
        """
        try:
            tenant_id = g.tenant_id
            result = self.crm_service.get_leads_table(tenant_id)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500

    def get_leads_by_customer_type(self) -> tuple:
        """
        GET /api/crm/leads/customer-type?type=NEW|EXISTING
        Get leads filtered by customer type
        """
        try:
            tenant_id = g.tenant_id
            customer_type_param = request.args.get('type', None)
            
            # Extract query parameters for filtering
            filters = {}
            if request.args.get('stage_id'):
                filters['stage_id'] = int(request.args.get('stage_id'))
            if request.args.get('lead_status'):
                filters['lead_status'] = request.args.get('lead_status')
            if request.args.get('assigned_employee_id'):
                filters['assigned_employee_id'] = int(request.args.get('assigned_employee_id'))
            
            result = self.crm_service.get_leads_by_customer_type(
                tenant_id, 
                customer_type_param, 
                filters if filters else None
            )
            return jsonify(result), 200
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    def create_client(self) -> tuple:
        """
        POST /api/crm/clients
        Create a new client in Client_Master and automatically create one
        Opportunity_Details record (lead) for that client.
        """
        try:
            tenant_id = g.tenant_id
            data = request.get_json()
            if not data:
                return jsonify({
                    'success': False,
                    'error': 'Invalid request',
                    'message': 'Request body is required'
                }), 400
            company = data.get('client_company_name') or data.get('business_name')
            if not company:
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': 'client_company_name or business_name is required'
                }), 400
            result = self.crm_service.create_client(tenant_id, data)
            if not result.get('success'):
                return jsonify(result), 400
            return jsonify(result), 201
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500

    def create_call_summary(self, client_id: int) -> tuple:
        """
        POST /api/crm/clients/<client_id>/call-summary
        Create a call summary/interaction record
        """
        try:
            tenant_id = g.tenant_id
            call_data = request.get_json()
            
            if not call_data:
                return jsonify({
                    'success': False,
                    'error': 'Invalid request',
                    'message': 'Request body is required'
                }), 400
            
            result = self.crm_service.create_call_summary(tenant_id, client_id, call_data)
            
            if not result.get('success'):
                return jsonify(result), 400
            
            return jsonify(result), 201
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }), 500
    
    # ========================================
    # DASHBOARD
    # ========================================
    
    def get_dashboard(self) -> tuple:
        """
        GET /api/crm/dashboard
        Get CRM dashboard summary
        """
        try:
            tenant_id = g.tenant_id
            result = self.crm_service.get_dashboard_summary(tenant_id)
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
