# -*- coding: utf-8 -*-
"""
CRM Services
Business logic layer for CRM operations
"""
import logging
from typing import Optional, Dict, Any, List
import io
import pandas as pd

logger = logging.getLogger(__name__)
from backend.crm.repositories.lead_repository import LeadRepository
from backend.crm.repositories.project_repository import ProjectRepository
from backend.crm.repositories.deal_repository import DealRepository
from backend.crm.repositories.user_repository import UserRepository
from backend.crm.repositories.tenant_repository import TenantRepository
from backend.crm.repositories.additional_repositories import (
    RoleRepository, StageRepository, ServiceRepository, 
    SupplierRepository, InteractionRepository
)


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
        # Use a projection that returns only the fields required by the frontend list view
        leads = self.lead_repo.get_leads_list(tenant_id, filters if filters else None)
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
    
    def update_lead_status(self, tenant_id: int, opportunity_id: int, stage_name: str) -> Dict[str, Any]:
        """
        Update lead status (stage_name) with tenant isolation
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
            stage_name: New stage name
        
        Returns:
            Dictionary with success status and updated data
        """
        stage = self.stage_repo.get_stage_by_name(stage_name)
        if not stage or not stage.get('stage_id'):
            return {
                'success': False,
                'error': 'Validation error',
                'message': f'Stage "{stage_name}" not found in Stage_Master'
            }

        stage_id = stage.get('stage_id')
        result = self.lead_repo.update_lead_status(tenant_id, opportunity_id, stage_id)
        
        if not result:
            return {
                'success': False,
                'error': 'Lead not found',
                'message': f'No lead found with ID {opportunity_id} or access denied'
            }

        updated_lead = self.lead_repo.get_lead_by_id(tenant_id, opportunity_id)

        return {
            'success': True,
            'data': updated_lead or result,
            'message': 'Lead status updated successfully'
        }
    
    def create_lead(self, tenant_id: int, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Disabled: Leads must be created only via the Excel import-confirm flow.

        This service method no longer permits creating leads via the API. Callers
        should use POST /api/crm/leads/import/confirm which inserts into
        Opportunity_Details and populates the required tenant-scoped fields.
        """
        return {
            'success': False,
            'error': 'Validation error',
            'message': 'Leads must be created via Excel import. Use POST /api/crm/leads/import/confirm.'
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

    def preview_lead_import(self, tenant_id: int, file_storage) -> Dict[str, Any]:
        """
        Parse uploaded CSV/XLSX and return a validation-only preview (no DB writes).
        This is intentionally permissive about column names (case-insensitive)
        and only validates the rules required by the UI preview.
        """
        import pandas as pd

        if not file_storage or not getattr(file_storage, 'filename', None):
            return {'success': False, 'error': 'No file provided', 'message': 'No file uploaded.'}

        filename = file_storage.filename or ''
        lower = filename.lower()
        try:
            if lower.endswith('.csv'):
                df = pd.read_csv(file_storage.stream, dtype=str)
            elif lower.endswith('.xlsx') or lower.endswith('.xls'):
                df = pd.read_excel(file_storage.stream, engine='openpyxl', dtype=str)
            else:
                return {'success': False, 'error': 'Unsupported file type', 'message': 'Only .csv and .xlsx files are accepted.'}
        except Exception as e:
            logger.exception('preview_lead_import: failed to read uploaded file: %s', e)
            return {'success': False, 'error': 'Failed to parse file', 'message': str(e)}

        original_columns = list(df.columns)
        col_map = {c.lower().strip(): c for c in original_columns}

        def get_col(df_row, *names):
            for n in names:
                key = n.lower()
                if key in col_map:
                    val = df_row.get(col_map[key])
                    if pd.isna(val):
                        return None
                    return str(val).strip()
            return None

        total_rows = len(df)
        if total_rows == 0:
            return {'success': False, 'error': 'Empty file', 'message': 'Uploaded file contains no data rows.'}

        # Determine MPAN column
        mpan_col_candidates = [k for k in col_map.keys() if k in ('mpan_mpr', 'mpan', 'mpr')]
        if not mpan_col_candidates:
            return {'success': False, 'error': 'Missing column', 'message': 'MPAN_MPR column is required in the uploaded file.'}
        mpan_key = mpan_col_candidates[0]

        series_mpan = df[col_map[mpan_key]].astype(str).fillna('').str.strip()
        mpan_counts = series_mpan[series_mpan != ''].value_counts()
        duplicated_values = set(mpan_counts[mpan_counts > 1].index.tolist())

        rows_out = []
        valid_count = 0
        invalid_count = 0

        for idx, row in df.iterrows():
            row_number = int(idx) + 1
            errors = []

            try:
                raw_mpan = row.get(col_map[mpan_key], None)
                mpan_val = None if pd.isna(raw_mpan) else str(raw_mpan).strip()
            except Exception:
                mpan_val = None

            if not mpan_val:
                errors.append('MPAN_MPR is mandatory')
            elif mpan_val in duplicated_values:
                errors.append('MPAN_MPR must be unique within the uploaded file')

            bname = get_col(row, 'business_name', 'client_company_name', 'business name')
            contact = get_col(row, 'contact_person', 'client_contact_name', 'contact person')
            if not (bname or contact):
                errors.append('Business_Name OR Contact_Person must exist')

            tel = get_col(row, 'tel_number', 'phone', 'telephone', 'tel number')
            if not tel:
                errors.append('Tel_Number must exist')

            start_raw = get_col(row, 'start_date', 'contract_start_date', 'start date')
            end_raw = get_col(row, 'end_date', 'contract_end_date', 'end date')
            if not start_raw:
                errors.append('Start_Date must exist')
            else:
                parsed = pd.to_datetime(start_raw, errors='coerce')
                if pd.isna(parsed):
                    errors.append('Start_Date is not a valid date')
            if not end_raw:
                errors.append('End_Date must exist')
            else:
                parsed = pd.to_datetime(end_raw, errors='coerce')
                if pd.isna(parsed):
                    errors.append('End_Date is not a valid date')

            is_valid = len(errors) == 0
            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                logger.warning('lead import preview - tenant=%s row=%s mpan=%s errors=%s', tenant_id, row_number, mpan_val, errors)

            data = {}
            for c in original_columns:
                v = row.get(c)
                if pd.isna(v):
                    data[c] = None
                else:
                    if hasattr(v, 'isoformat'):
                        try:
                            data[c] = v.isoformat()
                        except Exception:
                            data[c] = str(v)
                    else:
                        data[c] = None if (isinstance(v, float) and pd.isna(v)) else (str(v).strip())

            rows_out.append({'row_number': row_number, 'data': data, 'is_valid': is_valid, 'errors': errors})

        return {'success': True, 'total_rows': total_rows, 'valid_rows': valid_count, 'invalid_rows': invalid_count, 'rows': rows_out}

    def confirm_lead_import(self, tenant_id: int, rows: list, created_by: int | None) -> Dict[str, Any]:
        """
        Confirm/import validated rows into Opportunity_Details.

        - Stores MPAN_MPR directly in Opportunity_Details.mpan_mpr
        - Inserts Opportunity_Details with stage_id=1 (New), tenant_id from JWT
        - Skips rows where MPAN already exists in Opportunity_Details
        - Partial success allowed; per-row errors returned
        - NO dependency on Project_Details or Client_Master
        """
        if not isinstance(rows, list) or len(rows) == 0:
            return {'success': False, 'error': 'Invalid payload', 'message': 'Expected non-empty JSON array of validated rows.'}

        # Delegate to repository which handles DB checks/inserts per-row
        result = self.lead_repo.import_opportunities_from_import(tenant_id, rows, created_by)
        return {'inserted': int(result.get('inserted', 0)), 'skipped': int(result.get('skipped', 0)), 'errors': result.get('errors', [])}

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

            # Per new business rule: creating a client MUST NOT create an Opportunity_Details row.
            # Return the created client only and instruct callers to use the import flow for leads.
            return {
                'success': True,
                'data': {'client': client},
                'message': 'Client created successfully. Leads must be created via Excel import (POST /api/crm/leads/import/confirm).'
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
