# -*- coding: utf-8 -*-
"""
CRM Services
Business logic layer for CRM operations
"""
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)
from backend.crm.repositories.lead_repository import LeadRepository
from backend.crm.repositories.project_repository import ProjectRepository
from backend.crm.repositories.deal_repository import DealRepository
from backend.crm.repositories.user_repository import UserRepository
from backend.crm.repositories.tenant_repository import TenantRepository
from backend.crm.repositories.additional_repositories import (
    RoleRepository, ServiceRepository,
    SupplierRepository, InteractionRepository
)
from backend.crm.repositories.stage_repository import StageRepository


class CRMService:
    """
    Central CRM Service
    Handles business logic for all CRM operations
    """
    
    def __init__(self):
        self.lead_repo = LeadRepository()
        self.project_repo = ProjectRepository()
        self.deal_repo = DealRepository()
        self.user_repo = UserRepository()
        self.tenant_repo = TenantRepository()
        self.role_repo = RoleRepository()
        self.stage_repo = StageRepository()
        self.service_repo = ServiceRepository()
        self.supplier_repo = SupplierRepository()
        self.interaction_repo = InteractionRepository()
    
    # ========================================
    # LEAD OPERATIONS
    # ========================================
    
    def get_leads(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get all leads for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters
        
        Returns:
            Dictionary with leads data
        """
        leads = self.lead_repo.get_all_leads(tenant_id, filters)
        stats = self.lead_repo.get_lead_stats(tenant_id)
        
        return {
            'success': True,
            'data': leads,
            'stats': stats,
            'count': len(leads)
        }
    
    def get_lead_detail(self, tenant_id: int, opportunity_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a specific lead
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
        
        Returns:
            Dictionary with lead details
        """
        lead = self.lead_repo.get_lead_by_id(tenant_id, opportunity_id)
        
        if not lead:
            return {
                'success': False,
                'error': 'Lead not found',
                'message': f'No lead found with ID {opportunity_id}'
            }
        
        # Get related interactions
        interactions = self.interaction_repo.get_interactions_by_opportunity(tenant_id, opportunity_id)
        
        return {
            'success': True,
            'data': lead,
            'interactions': interactions
        }
    
    def create_lead(self, tenant_id: int, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new lead/opportunity.

        Supports two payload shapes:
        - Existing client: { "client_id": <id>, ... }
        - Create client + lead in one call: { "client": { ...client fields... }, ...lead fields... }

        Behavior:
        - If `client_id` is provided, validates tenant ownership and creates the opportunity.
        - If a `client` object or client company name is provided, creates the client and the
          opportunity inside a single DB transaction (atomic).
        - If `stage_id` is not provided, uses the first `Stage_Master` record as default.

        Returns a consistent response dict (success, data, message / error).
        """
        # Case A: client + lead in one call (transactional)
        try:
            # Detect client creation intent
            wants_create_client = bool(lead_data.get('client') or lead_data.get('client_company_name') or lead_data.get('business_name'))

            if wants_create_client and not lead_data.get('client_id'):
                # Prepare client payload (map API keys -> DB column names)
                client_payload = lead_data.get('client') or {
                    'client_company_name': lead_data.get('client_company_name') or lead_data.get('business_name'),
                    'client_contact_name': lead_data.get('client_contact_name') or lead_data.get('contact_person'),
                    'client_phone': lead_data.get('client_phone') or lead_data.get('phone') or lead_data.get('tel_number'),
                    'client_email': lead_data.get('client_email') or lead_data.get('email'),
                    'address': lead_data.get('address'),
                    'country_id': lead_data.get('country_id'),
                    'post_code': lead_data.get('post_code'),
                }

                if not (client_payload.get('client_company_name') or client_payload.get('client_contact_name')):
                    return {
                        'success': False,
                        'error': 'Validation error',
                        'message': 'client_company_name (or business_name) is required when creating a client.'
                    }

                # Lead-specific payload
                lead_payload = {
                    'opportunity_title': lead_data.get('opportunity_title') or lead_data.get('opportunity_name') or client_payload.get('client_company_name'),
                    'opportunity_description': lead_data.get('opportunity_description', ''),
                    'opportunity_value': lead_data.get('opportunity_value', 0),
                    'opportunity_owner_employee_id': lead_data.get('opportunity_owner_employee_id') or lead_data.get('opportunity_owner_id')
                }

                # If stage_id provided at top-level prefer it
                if lead_data.get('stage_id'):
                    lead_payload['stage_id'] = lead_data.get('stage_id')
                else:
                    # Try to pick first stage from Stage_Master
                    stages = self.stage_repo.get_all_stages()
                    if stages:
                        lead_payload['stage_id'] = stages[0].get('stage_id')

                created = self.lead_repo.create_client_and_lead_transaction(tenant_id, client_payload, lead_payload)

                if not created:
                    return {
                        'success': False,
                        'error': 'Failed to create client and lead',
                        'message': 'Could not create client and lead. Operation rolled back.'
                    }

                return {
                    'success': True,
                    'data': created,
                    'message': 'Client and lead created successfully'
                }

            # Case B: create lead for existing client_id
            client_id = lead_data.get('client_id')
            if not client_id:
                return {
                    'success': False,
                    'error': 'Validation error',
                    'message': 'Either client_id or client (payload) must be provided.'
                }

            # Ensure default stage if none provided
            if not lead_data.get('stage_id'):
                stages = self.stage_repo.get_all_stages()
                if stages:
                    lead_data['stage_id'] = stages[0].get('stage_id')

            lead = self.lead_repo.create_lead(tenant_id, lead_data)
            if not lead:
                return {
                    'success': False,
                    'error': 'Failed to create lead',
                    'message': 'Could not create lead. Please check client_id and provided fields.'
                }

            return {
                'success': True,
                'data': lead,
                'message': 'Lead created successfully'
            }

        except Exception as e:
            logger.exception("create_lead error: %s", e)
            return {
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }
    
    def update_lead(self, tenant_id: int, opportunity_id: int, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing lead
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
            lead_data: Updated lead information
        
        Returns:
            Dictionary with updated lead
        """
        lead = self.lead_repo.update_lead(opportunity_id, tenant_id, lead_data)
        
        if not lead:
            return {
                'success': False,
                'error': 'Failed to update lead',
                'message': f'Could not update lead with ID {opportunity_id}'
            }
        
        return {
            'success': True,
            'data': lead,
            'message': 'Lead updated successfully'
        }

    def update_lead_status(self, tenant_id: int, opportunity_id: int, stage_name: str) -> Dict[str, Any]:
        """
        Update only the status/stage of a lead
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
            stage_name: New stage name (e.g., "Called", "Priced", "Rejected", "Not Called")
        
        Returns:
            Dictionary with updated lead
        """
        try:
            # Check if lead exists
            lead = self.lead_repo.get_lead_by_id(tenant_id, opportunity_id)
            
            if not lead:
                return {
                    'success': False,
                    'error': 'Lead not found',
                    'message': f'No lead found with ID {opportunity_id}'
                }
            
            # ✅ FIX: Convert stage_name to stage_id
            stage = self.stage_repo.get_stage_by_name(stage_name)
            
            if not stage:
                return {
                    'success': False,
                    'error': 'Invalid stage',
                    'message': f'Stage "{stage_name}" not found'
                }
            
            # ✅ FIX: Update stage_id, not stage_name
            update_data = {
                'stage_id': stage['stage_id']  # ✅ Use stage_id!
            }
            
            # Call repository to update the lead
            updated_lead = self.lead_repo.update_lead(opportunity_id, tenant_id, update_data)
            
            if not updated_lead:
                return {
                    'success': False,
                    'error': 'Failed to update lead status',
                    'message': f'Could not update status for lead with ID {opportunity_id}'
                }
            
            return {
                'success': True,
                'data': updated_lead,
                'message': f'Lead status updated to "{stage_name}" successfully'
            }
            
        except Exception as e:
            logger.exception("update_lead_status error: %s", e)
            return {
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }
    
    def delete_lead(self, tenant_id: int, opportunity_id: int) -> Dict[str, Any]:
        """
        Delete a lead/opportunity
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
        
        Returns:
            Dictionary with deletion status
        """
        success = self.lead_repo.delete_lead(opportunity_id, tenant_id)
        
        if not success:
            return {
                'success': False,
                'error': 'Failed to delete lead',
                'message': f'Could not delete lead with ID {opportunity_id}'
            }
        
        return {
            'success': True,
            'message': f'Lead {opportunity_id} deleted successfully'
        }

    def import_leads_from_file(self, tenant_id: int, file, file_ext: str) -> Dict[str, Any]:
        """Import leads from Excel/CSV - stores in Misc_Col1"""
        try:
            import pandas as pd
            
            if file_ext == '.csv':
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
            
            total_rows = len(df)
            successful = 0
            failed = 0
            errors = []
            
            df.columns = df.columns.str.strip()
            
            column_mapping = {
                'business_name': ['Business_Name', 'Business Name', 'business_name', 'Company', 'Name'],
                'contact_person': ['Contact_Person', 'Contact Person', 'contact_person', 'Contact'],
                'tel_number': ['Tel_Number', 'Tel Number', 'tel_number', 'Phone', 'Telephone'],
                'email': ['Email', 'email'],
                'mpan_mpr': ['Mpan_MPR', 'MPAN/MPR', 'MPAN', 'MPR', 'Meter_Ref'],
                'start_date': ['Start_Date', 'Start Date', 'start_date'],
                'end_date': ['End_Date', 'End Date', 'end_date'],
                'supplier': ['Supplier', 'supplier'],
                'annual_usage': ['Annual_Usage', 'Annual Usage', 'annual_usage'],
            }
            
            found_columns = {}
            for field, possible_names in column_mapping.items():
                for col in df.columns:
                    if col in possible_names:
                        found_columns[field] = col
                        break
            
            if 'business_name' not in found_columns:
                return {
                    'success': False,
                    'error': 'Missing required column',
                    'message': 'Business_Name column is required',
                    'total_rows': 0,
                    'successful': 0,
                    'failed': 0
                }
            
            stages = self.stage_repo.get_all_stages()
            default_stage_id = stages[0]['stage_id'] if stages else None
            
            if not default_stage_id:
                return {
                    'success': False,
                    'error': 'No default stage',
                    'message': 'No stages configured',
                    'total_rows': 0,
                    'successful': 0,
                    'failed': 0
                }
            
            for index, row in df.iterrows():
                try:
                    row_num = index + 2
                    
                    business_col = found_columns['business_name']
                    business_name = str(row.get(business_col, '')).strip()
                    
                    if not business_name or business_name == 'nan':
                        errors.append(f'Row {row_num}: Business Name is empty')
                        failed += 1
                        continue
                    
                    # Build lead data object with all fields
                    lead_data = {
                        'opportunity_title': business_name,
                        'opportunity_description': f'Imported lead from bulk import',
                        'stage_id': default_stage_id,
                        'opportunity_value': 0,
                        'contact_person': '',
                        'tel_number': '',
                        'email': '',
                        'mpan_mpr': '',
                        'supplier': '',
                        'start_date': '',
                        'end_date': '',
                        'annual_usage': ''
                    }
                    
                    # Extract all optional fields
                    if 'contact_person' in found_columns:
                        contact = row.get(found_columns['contact_person'])
                        if pd.notna(contact) and str(contact).strip():
                            lead_data['contact_person'] = str(contact).strip()
                    
                    if 'tel_number' in found_columns:
                        phone = row.get(found_columns['tel_number'])
                        if pd.notna(phone) and str(phone).strip():
                            lead_data['tel_number'] = str(phone).replace('.0', '').strip()
                    
                    if 'email' in found_columns:
                        email = row.get(found_columns['email'])
                        if pd.notna(email) and str(email).strip():
                            lead_data['email'] = str(email).strip()
                    
                    if 'mpan_mpr' in found_columns:
                        mpan = row.get(found_columns['mpan_mpr'])
                        if pd.notna(mpan) and str(mpan).strip():
                            lead_data['mpan_mpr'] = str(mpan).replace('.0', '').strip()
                    
                    if 'supplier' in found_columns:
                        supplier = row.get(found_columns['supplier'])
                        if pd.notna(supplier) and str(supplier).strip():
                            lead_data['supplier'] = str(supplier).strip()
                    
                    if 'start_date' in found_columns:
                        start = row.get(found_columns['start_date'])
                        if pd.notna(start):
                            try:
                                start_date = pd.to_datetime(start)
                                lead_data['start_date'] = start_date.strftime('%Y-%m-%d')
                            except:
                                pass
                    
                    if 'end_date' in found_columns:
                        end = row.get(found_columns['end_date'])
                        if pd.notna(end):
                            try:
                                end_date = pd.to_datetime(end)
                                lead_data['end_date'] = end_date.strftime('%Y-%m-%d')
                            except:
                                pass
                    
                    if 'annual_usage' in found_columns:
                        usage = row.get(found_columns['annual_usage'])
                        if pd.notna(usage):
                            try:
                                lead_data['annual_usage'] = str(float(usage))
                            except:
                                pass
                    
                    # Create lead WITHOUT creating a client
                    result = self.lead_repo.create_lead_without_client(tenant_id, lead_data)
                    
                    if result:
                        successful += 1
                    else:
                        failed += 1
                        errors.append(f'Row {row_num}: Failed to create lead')
                
                except Exception as e:
                    failed += 1
                    errors.append(f'Row {row_num}: {str(e)}')
            
            return {
                'success': True,
                'message': f'Import completed: {successful} successful, {failed} failed',
                'total_rows': total_rows,
                'successful': successful,
                'failed': failed,
                'errors': errors[:10] if errors else []
            }
            
        except Exception as e:
            logger.exception("import_leads_from_file error: %s", e)
            return {
                'success': False,
                'error': 'File processing error',
                'message': str(e),
                'total_rows': 0,
                'successful': 0,
                'failed': 0,
                'errors': []
            }
    
    # ========================================
    # PROJECT OPERATIONS
    # ========================================
    
    def get_projects(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get all projects for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters
        
        Returns:
            Dictionary with projects data
        """
        projects = self.project_repo.get_all_projects(tenant_id, filters)
        stats = self.project_repo.get_project_stats(tenant_id)
        
        return {
            'success': True,
            'data': projects,
            'stats': stats,
            'count': len(projects)
        }
    
    def get_project_detail(self, tenant_id: int, project_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a specific project
        
        Args:
            tenant_id: Tenant identifier
            project_id: Project ID
        
        Returns:
            Dictionary with project details
        """
        project = self.project_repo.get_project_by_id(tenant_id, project_id)
        
        if not project:
            return {
                'success': False,
                'error': 'Project not found',
                'message': f'No project found with ID {project_id}'
            }
        
        return {
            'success': True,
            'data': project
        }
    
    # ========================================
    # DEAL OPERATIONS
    # ========================================
    
    def get_deals(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get all deals/contracts for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters
        
        Returns:
            Dictionary with deals data
        """
        deals = self.deal_repo.get_all_deals(tenant_id, filters)
        stats = self.deal_repo.get_deal_stats(tenant_id)
        
        return {
            'success': True,
            'data': deals,
            'stats': stats,
            'count': len(deals)
        }
    
    def get_deal_detail(self, tenant_id: int, contract_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a specific deal
        
        Args:
            tenant_id: Tenant identifier
            contract_id: Contract ID
        
        Returns:
            Dictionary with deal details
        """
        deal = self.deal_repo.get_deal_by_id(tenant_id, contract_id)
        
        if not deal:
            return {
                'success': False,
                'error': 'Deal not found',
                'message': f'No deal found with ID {contract_id}'
            }
        
        return {
            'success': True,
            'data': deal
        }
    
    # ========================================
    # USER OPERATIONS
    # ========================================
    
    def get_users(self, tenant_id: int, active_only: bool = True) -> Dict[str, Any]:
        """
        Get all users for a tenant
        
        Args:
            tenant_id: Tenant identifier
            active_only: Filter active users only
        
        Returns:
            Dictionary with users data
        """
        users = self.user_repo.get_all_users(tenant_id, active_only)
        
        return {
            'success': True,
            'data': users,
            'count': len(users)
        }
    
    # ========================================
    # SUPPORTING DATA OPERATIONS
    # ========================================
    
    def get_roles(self, tenant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get all roles"""
        roles = self.role_repo.get_all_roles(tenant_id)
        return {
            'success': True,
            'data': roles,
            'count': len(roles)
        }
    
    def get_stages(self, pipeline_type: Optional[str] = None) -> Dict[str, Any]:
        """Get all pipeline stages"""
        stages = self.stage_repo.get_all_stages(pipeline_type)
        return {
            'success': True,
            'data': stages,
            'count': len(stages)
        }
    
    def get_services(self, tenant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get all services"""
        services = self.service_repo.get_all_services(tenant_id)
        return {
            'success': True,
            'data': services,
            'count': len(services)
        }
    
    def get_suppliers(self, tenant_id: int) -> Dict[str, Any]:
        """Get all suppliers for a tenant"""
        suppliers = self.supplier_repo.get_all_suppliers(tenant_id)
        return {
            'success': True,
            'data': suppliers,
            'count': len(suppliers)
        }
    
    def get_interactions(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get all client interactions for a tenant"""
        interactions = self.interaction_repo.get_all_interactions(tenant_id, filters)
        return {
            'success': True,
            'data': interactions,
            'count': len(interactions)
        }
    
    def get_leads_table(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get flat leads table for CRM UI (one row per lead with 14 columns from joined tables).
        """
        rows = self.lead_repo.get_leads_table(tenant_id)
        return {
            'success': True,
            'data': rows,
            'count': len(rows)
        }

    def get_leads_by_customer_type(self, tenant_id: int, customer_type: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get leads filtered by customer type (NEW/EXISTING)
        
        Args:
            tenant_id: Tenant identifier
            customer_type: 'NEW' or 'EXISTING' or None for all
            filters: Optional filters
        
        Returns:
            Dictionary with leads data
        """
        leads = self.lead_repo.get_leads_with_customer_type(tenant_id, customer_type, filters)
        return {
            'success': True,
            'data': leads,
            'count': len(leads)
        }
    
    def create_client(self, tenant_id: int, client_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new client in Client_Master and automatically create one row in
        Opportunity_Details (so every client appears as a lead).
        Ensures tenant and stage exist (creates defaults if missing).
        """
        try:
            # Ensure tenant exists; use default if not
            tenant = self.tenant_repo.get_tenant_by_id(tenant_id)
            if not tenant:
                default_tenant = self.tenant_repo.ensure_default_tenant()
                if default_tenant and default_tenant.get('Tenant_id') is not None:
                    tenant_id = int(default_tenant['Tenant_id'])

            # Map API fields → DB columns (tenant_id always from X-Tenant-ID)
            data = dict(client_data) if client_data else {}
            data["client_company_name"] = data.get("business_name") or data.get("client_company_name") or ""
            data["client_contact_name"] = data.get("contact_person") or data.get("client_contact_name") or ""
            data["client_phone"] = data.get("phone") or data.get("client_phone") or data.get("tel_number")
            data["client_email"] = data.get("email") or data.get("client_email")
            data["address"] = data.get("address")
            data["country_id"] = data.get("country_id")

            # Ensure required DB fields (query masters if missing)
            if data.get("country_id") is None:
                data["country_id"] = self.lead_repo.get_first_country_id()
            if data.get("country_id") is None:
                data["country_id"] = 234  # fallback if Country_Master empty
            if data.get("default_currency_id") is None:
                data["default_currency_id"] = self.lead_repo.get_first_currency_id()
            if data.get("default_currency_id") is None:
                data["default_currency_id"] = 104  # fallback if Currency_Master empty
            if data.get("address") is None:
                data["address"] = ""
            if data.get("post_code") is None:
                data["post_code"] = ""

            logger.info("create_client payload to LeadRepository: tenant_id=%s data=%s", tenant_id, data)
            client = self.lead_repo.create_client(tenant_id, data)
            if not client:
                logger.error("create_client insert failed: lead_repo.create_client returned None; tenant_id=%s data=%s", tenant_id, data)
                return {
                    'success': False,
                    'error': 'Failed to create client',
                    'message': 'Could not create client. Please try again.'
                }
            client_id = client.get('client_id')
            company_name = (client.get('client_company_name') or
                            data.get('client_company_name') or
                            data.get('business_name') or
                            '')

            # Ensure stage exists; use default if none
            stages = self.stage_repo.get_all_stages()
            default_stage_id = stages[0]['stage_id'] if stages else None
            if default_stage_id is None:
                default_stage = self.stage_repo.ensure_default_stage()
                if default_stage and default_stage.get('stage_id') is not None:
                    default_stage_id = default_stage['stage_id']

            # Always create Opportunity_Details when we have a stage
            opportunity = None
            if default_stage_id is not None:
                opportunity_title = company_name or 'New Lead'
                lead_data = {
                    'client_id': client_id,
                    'stage_id': default_stage_id,
                    'opportunity_title': opportunity_title,
                    'opportunity_description': data.get('opportunity_description', ''),
                    'opportunity_value': data.get('opportunity_value', 0),
                    'opportunity_owner_employee_id': data.get('opportunity_owner_employee_id'),
                }
                print("DEBUG client_id =", client_id)
                print("DEBUG tenant_id =", tenant_id)
                print("DEBUG stages =", stages)
                print("DEBUG default_stage_id =", default_stage_id)
                opportunity = self.lead_repo.create_lead(tenant_id, lead_data)
                print("DEBUG opportunity =", opportunity)
                if opportunity is None:
                    raise RuntimeError(
                        "create_lead returned None; client was created but opportunity insert failed. "
                        "Check LeadRepository logs above for the exact SQL/DB error."
                    )

            return {
                'success': True,
                'data': {'client': client, 'opportunity': opportunity},
                'message': 'Client and lead created successfully' if opportunity else 'Client created; opportunity could not be created.'
            }
        except Exception as e:
            import logging
            logger.error("CLIENT CREATE ERROR (insert failed): %s", str(e), exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Client creation failed"
            }

    def create_call_summary(self, tenant_id: int, client_id: int, call_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a call summary/interaction record
        
        Args:
            tenant_id: Tenant identifier
            client_id: Client identifier
            call_data: Call information
        
        Returns:
            Dictionary with created interaction
        """
        interaction = self.interaction_repo.create_call_summary(tenant_id, client_id, call_data)
        
        if not interaction:
            return {
                'success': False,
                'error': 'Failed to create call summary',
                'message': 'Could not create call summary. Please try again.'
            }
        
        return {
            'success': True,
            'data': interaction,
            'message': 'Call summary created successfully'
        }
    
    # ========================================
    # DASHBOARD & ANALYTICS
    # ========================================
    
    def get_dashboard_summary(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get CRM dashboard summary with key metrics
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with dashboard metrics
        """
        lead_stats = self.lead_repo.get_lead_stats(tenant_id)
        project_stats = self.project_repo.get_project_stats(tenant_id)
        deal_stats = self.deal_repo.get_deal_stats(tenant_id)
        
        return {
            'success': True,
            'data': {
                'leads': lead_stats,
                'projects': project_stats,
                'deals': deal_stats
            }
        }
