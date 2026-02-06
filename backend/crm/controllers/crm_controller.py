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
    
    def update_lead_status(self, opportunity_id: int) -> tuple:
        """
        PATCH /api/crm/leads/<opportunity_id>/status
        Update only the status/stage of a lead
        """
        try:
            tenant_id = g.tenant_id
            data = request.get_json()
            
            if not data or 'stage_name' not in data:
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': 'stage_name is required in request body'
                }), 400
            
            stage_name = data['stage_name']
            
            # Validate stage name
            valid_stages = ['Not Called', 'Called', 'Priced', 'Rejected']
            if stage_name not in valid_stages:
                return jsonify({
                    'success': False,
                    'error': 'Validation error',
                    'message': f'Invalid stage name. Must be one of: {", ".join(valid_stages)}'
                }), 400
            
            # Update only the stage using the service layer
            result = self.crm_service.update_lead_status(tenant_id, opportunity_id, stage_name)
            
            if not result.get('success'):
                status_code = 404 if 'not found' in result.get('message', '').lower() else 500
                return jsonify(result), status_code
            
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

    def bulk_delete_leads(self):
        """
        Bulk delete multiple leads and automatically reset sequence if all deleted
        
        Request Body:
            {
                "opportunity_ids": [15, 16, 17, 18]
            }
        
        Returns:
            200: Deletion results with count
            400: Invalid request
            500: Internal server error
        """
        try:
            from flask import request, jsonify
            
            # Get request data
            data = request.get_json()
            if not data or 'opportunity_ids' not in data:
                return jsonify({
                    'success': False,
                    'error': 'opportunity_ids is required'
                }), 400
            
            opportunity_ids = data.get('opportunity_ids', [])
            
            if not isinstance(opportunity_ids, list) or len(opportunity_ids) == 0:
                return jsonify({
                    'success': False,
                    'error': 'opportunity_ids must be a non-empty list'
                }), 400
            
            # Get tenant_id from request context (set by middleware)
            tenant_id = g.tenant_id
            
            # Call repository bulk delete method
            from backend.crm.repositories.lead_repository import LeadRepository
            repo = LeadRepository()
            result = repo.bulk_delete_leads(tenant_id, opportunity_ids)
            
            # Build response message
            deleted = result.get('deleted', 0)
            total = result.get('total_requested', 0)
            errors = result.get('errors', [])
            
            # Check if sequence was reset
            sequence_reset_message = ""
            if deleted > 0:
                # Check if all leads are deleted
                remaining = repo.get_all_leads(tenant_id)
                if len(remaining) == 0:
                    sequence_reset_message = " ID sequence reset to 1."
            
            message = f"{deleted} lead(s) deleted successfully."
            if deleted < total:
                message += f" {total - deleted} failed."
            message += sequence_reset_message
            
            return jsonify({
                'success': True,
                'deleted': deleted,
                'total_requested': total,
                'errors': errors,
                'message': message
            }), 200
            
        except Exception as e:
            import traceback
            print(f"Error in bulk_delete_leads: {e}")
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'error': 'Failed to delete leads',
                'details': str(e)
            }), 500

    def import_leads(self) -> tuple:
            """
            POST /api/crm/leads/import
            Bulk import leads from Excel/CSV file
            """
            try:
                tenant_id = g.tenant_id
                
                # Check if file is present
                if 'file' not in request.files:
                    return jsonify({
                        'success': False,
                        'error': 'No file provided',
                        'message': 'Please upload a file'
                    }), 400
                
                file = request.files['file']
                
                if file.filename == '':
                    return jsonify({
                        'success': False,
                        'error': 'No file selected',
                        'message': 'Please select a file to upload'
                    }), 400
                
                # Validate file extension
                allowed_extensions = {'.xlsx', '.xls', '.csv'}
                file_ext = '.' + file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                
                if file_ext not in allowed_extensions:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid file type',
                        'message': 'Only .xlsx, .xls, and .csv files are allowed'
                    }), 400
                
                # Process the file
                result = self.crm_service.import_leads_from_file(tenant_id, file, file_ext)
                
                if not result.get('success'):
                    return jsonify(result), 400
                
                return jsonify(result), 200
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': 'Internal server error',
                    'message': str(e)
                }), 500
            
    def get_priced_leads(self):
        """
        Get all priced leads (stage_name = 'Priced')
        
        Returns:
            200: List of priced leads
            500: Internal server error
        """
        try:
            from flask import request, jsonify
            from backend.crm.repositories.lead_repository import LeadRepository
            
            # Get tenant_id from request context
            tenant_id = g.tenant_id
            
            # Get optional filters
            assigned_to = request.args.get('assigned_to')
            
            # Build filters
            filters = {}
            if assigned_to:
                filters['assigned_employee_id'] = assigned_to
            
            # Get priced leads from repository
            repo = LeadRepository()
            
            # Get the stage_id for "Priced" stage (stage_id = 8)
            from backend.crm.repositories.stage_repository import StageRepository
            stage_repo = StageRepository()
            priced_stage = stage_repo.get_stage_by_name('Priced')
            
            if not priced_stage:
                return jsonify({
                    'success': False,
                    'error': 'Priced stage not found in Stage_Master'
                }), 500
            
            # Add stage filter
            filters['stage_id'] = priced_stage['stage_id']
            
            # Get leads with this stage
            leads = repo.get_all_leads(tenant_id, filters)
            
            return jsonify({
                'success': True,
                'data': leads,
                'count': len(leads)
            }), 200
            
        except Exception as e:
            import traceback
            print(f"Error in get_priced_leads: {e}")
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'error': 'Failed to fetch priced leads',
                'details': str(e)
            }), 500


    def get_priced_lead_detail(self, opportunity_id):
        """
        Get details of a specific priced lead
        
        Args:
            opportunity_id: Opportunity identifier
        
        Returns:
            200: Lead details
            404: Lead not found
            500: Internal server error
        """
        try:
            from flask import request, jsonify
            from backend.crm.repositories.lead_repository import LeadRepository
            
            tenant_id = g.tenant_id
            repo = LeadRepository()
            
            lead = repo.get_lead_by_id(tenant_id, opportunity_id)
            
            if not lead:
                return jsonify({
                    'success': False,
                    'error': 'Lead not found'
                }), 404
            
            return jsonify({
                'success': True,
                'data': lead
            }), 200
            
        except Exception as e:
            import traceback
            print(f"Error in get_priced_lead_detail: {e}")
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'error': 'Failed to fetch lead details',
                'details': str(e)
            }), 500


    def move_priced_to_leads(self, opportunity_id):
        """
        Move a priced lead back to leads page
        Changes stage from 'Priced' (stage_id=8) to 'Not Called' (stage_id=6)
        
        Args:
            opportunity_id: Opportunity identifier
        
        Returns:
            200: Lead moved successfully
            404: Lead not found
            500: Internal server error
        """
        try:
            from flask import request, jsonify
            from backend.crm.repositories.lead_repository import LeadRepository
            from backend.crm.repositories.stage_repository import StageRepository
            
            tenant_id = g.tenant_id
            
            # Get the "Not Called" stage (stage_id = 6)
            stage_repo = StageRepository()
            not_called_stage = stage_repo.get_stage_by_name('Not Called')
            
            if not not_called_stage:
                return jsonify({
                    'success': False,
                    'error': 'Not Called stage not found'
                }), 500
            
            # Update the lead's stage
            repo = LeadRepository()
            updated_lead = repo.update_lead(opportunity_id, tenant_id, {
                'stage_id': not_called_stage['stage_id']
            })
            
            if not updated_lead:
                return jsonify({
                    'success': False,
                    'error': 'Lead not found or update failed'
                }), 404
            
            return jsonify({
                'success': True,
                'message': 'Lead moved back to leads page',
                'data': updated_lead
            }), 200
            
        except Exception as e:
            import traceback
            print(f"Error in move_priced_to_leads: {e}")
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'error': 'Failed to move lead',
                'details': str(e)
            }), 500


    def get_priced_stats(self):
        """
        Get statistics for priced leads
        
        Returns:
            200: Statistics object
            500: Internal server error
        """
        try:
            from flask import request, jsonify
            from backend.crm.repositories.lead_repository import LeadRepository
            from backend.crm.repositories.stage_repository import StageRepository
            
            tenant_id = g.tenant_id
            
            # Get priced stage (stage_id = 8)
            stage_repo = StageRepository()
            priced_stage = stage_repo.get_stage_by_name('Priced')
            
            if not priced_stage:
                return jsonify({
                    'success': False,
                    'error': 'Priced stage not found'
                }), 500
            
            # Get all priced leads
            repo = LeadRepository()
            priced_leads = repo.get_all_leads(tenant_id, {
                'stage_id': priced_stage['stage_id']
            })
            
            # Calculate statistics
            total_priced = len(priced_leads)
            total_value = sum(lead.get('opportunity_value', 0) for lead in priced_leads)
            
            # Group by employee
            by_employee = {}
            for lead in priced_leads:
                employee_name = lead.get('assigned_to_name', 'Unassigned')
                if employee_name not in by_employee:
                    by_employee[employee_name] = {
                        'count': 0,
                        'total_value': 0
                    }
                by_employee[employee_name]['count'] += 1
                by_employee[employee_name]['total_value'] += lead.get('opportunity_value', 0)
            
            return jsonify({
                'success': True,
                'total_priced': total_priced,
                'total_value': total_value,
                'by_employee': by_employee
            }), 200
            
        except Exception as e:
            import traceback
            print(f"Error in get_priced_stats: {e}")
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'error': 'Failed to fetch statistics',
                'details': str(e)
            }), 500
    
    def download_leads_template(self) -> tuple:
        """
        GET /api/crm/leads/import/template
        Download Excel template for bulk lead import
        """
        try:
            from flask import send_file
            import io
            import openpyxl
            from openpyxl.styles import Font, PatternFill
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Leads Template"
            
            # Define headers
            headers = [
                'Business Name',
                'Contact Person',
                'Tel Number',
                'Email',
                'MPAN/MPR',
                'Start Date',
                'End Date'
            ]
            
            # Write headers with styling
            header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
            header_font = Font(bold=True, color='FFFFFF')
            
            for col, header in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
            
            # Add example row
            example_data = [
                'ABC Energy Ltd',
                'John Smith',
                '01234567890',
                'john.smith@abcenergy.com',
                '1234567890123',
                '2025-01-01',
                '2026-01-01'
            ]
            
            for col, value in enumerate(example_data, start=1):
                ws.cell(row=2, column=col, value=value)
            
            # Set column widths
            ws.column_dimensions['A'].width = 25
            ws.column_dimensions['B'].width = 20
            ws.column_dimensions['C'].width = 15
            ws.column_dimensions['D'].width = 30
            ws.column_dimensions['E'].width = 20
            ws.column_dimensions['F'].width = 15
            ws.column_dimensions['G'].width = 15
            
            # Save to BytesIO
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name='leads_import_template.xlsx'
            )
            
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