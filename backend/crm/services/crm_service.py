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
        Get all leads for a tenant (excludes Lost leads by default)
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (stage_id, include_lost, etc.)
        
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
    
    def update_lead_status(self, tenant_id: int, opportunity_id: int, stage_id: int) -> Dict[str, Any]:
        """
        Update lead status (stage_id) with tenant isolation.
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity ID
            stage_id: New stage ID
        
        Returns:
            Dictionary with success status and updated data
        """
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

    def assign_leads(self, tenant_id: int, lead_ids: List[int], employee_id: int) -> Dict[str, Any]:
        """
        Bulk assign leads to an employee. Admin-only.
        """
        return self.lead_repo.bulk_assign_leads(tenant_id, lead_ids, employee_id)

    def get_employees(self, tenant_id: int) -> Dict[str, Any]:
        """Get all employees for a tenant (for assignment dropdowns)."""
        # Employee repository is disabled - return users instead
        users = self.user_repo.get_all_users(tenant_id, active_only=True)
        
        # Convert users to employee format for compatibility
        employees = []
        for user in users:
            employees.append({
                'employee_id': user.get('user_id') or user.get('employee_id'),
                'employee_name': user.get('username') or user.get('full_name'),
                'email': user.get('email'),
                'phone': user.get('phone')
            })
        
        return {'success': True, 'data': employees, 'count': len(employees)}
    
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
    
    def get_recycle_bin(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get all Lost leads (recycle bin) for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with recycle bin data
        """
        # ✅ CRITICAL: Convert tenant_id to string for VARCHAR column
        tenant_id_str = str(tenant_id)
        
        # Get service_id from request args if available
        from flask import request
        service_param = request.args.get('service', 'utilities') if request else 'utilities'
        service_id = 2 if service_param.strip().lower() == 'water' else 1
        
        logger.info('🔍 get_recycle_bin (SERVICE): tenant_id=%s (str), service_id=%s', tenant_id_str, service_id)
        
        # ✅ Pass STRING tenant_id to repository
        leads = self.lead_repo.get_leads_recycle_bin(tenant_id_str, service_id)
        
        logger.info('🔍 get_recycle_bin (SERVICE): returning %d leads', len(leads))
        
        return {
            'success': True,
            'data': leads,
            'count': len(leads)
        }
    
    def delete_expired_lost_leads(self, tenant_id: int, days: int = 30) -> Dict[str, Any]:
        """
        Permanently delete Lost leads older than specified days
        
        Args:
            tenant_id: Tenant identifier
            days: Delete leads older than this many days (default 30)
        
        Returns:
            Dictionary with deletion count
        """
        deleted_count = self.lead_repo.delete_expired_lost_leads(tenant_id, days)
        return {
            'success': True,
            'deleted_count': deleted_count,
            'message': f'Deleted {deleted_count} expired lost leads'
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
        Column matching is case-insensitive and handles underscore/space variants.
        """
        import pandas as pd
        import tempfile, os, re

        if not file_storage or not getattr(file_storage, 'filename', None):
            return {'success': False, 'error': 'No file provided', 'message': 'No file uploaded.'}

        filename = file_storage.filename or ''
        lower = filename.lower()

        if lower.endswith('.csv'):
            file_ext = 'csv'
        elif lower.endswith('.xlsx') or lower.endswith('.xls'):
            file_ext = 'xlsx'
        else:
            return {'success': False, 'error': 'Unsupported file type',
                    'message': 'Only .csv and .xlsx files are accepted.'}

        # ── Save to temp file (avoids stream exhaustion issues) ─────────────────
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp:
                file_storage.save(tmp.name)
                tmp_path = tmp.name

            if file_ext == 'csv':
                df = pd.read_csv(tmp_path, encoding='utf-8-sig', dtype=str)
            else:
                try:
                    df = pd.read_excel(tmp_path, engine='openpyxl', dtype=str)
                except Exception:
                    df = pd.read_excel(tmp_path, engine='xlrd', dtype=str)
        except Exception as e:
            logger.exception('preview_lead_import: failed to read file: %s', e)
            return {'success': False, 'error': 'Failed to parse file', 'message': str(e)}
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if len(df) == 0:
            return {'success': False, 'error': 'Empty file',
                    'message': 'Uploaded file contains no data rows.'}

        # ── Build normalised DataFrame ───────────────────────────────────────────
        # df_orig: original columns (used for output data dict)
        # df_norm: normalised columns (used for all field lookups)
        original_columns = list(df.columns)

        def normalise_col(c):
            return re.sub(r'\s+', ' ', c.lower().strip().replace('_', ' '))

        df_norm = df.copy()
        df_norm.columns = [normalise_col(c) for c in original_columns]

        # ── MPAN uniqueness check ────────────────────────────────────────────────
        mpan_col = next(
            (c for c in df_norm.columns
            if c in ('mpan top', 'mpan mpr', 'mpan', 'mpr', 'mpan core')),
            None
        )
        duplicated_mpans = set()
        if mpan_col:
            series = df_norm[mpan_col].astype(str).str.strip().replace('nan', '')
            counts = series[series != ''].value_counts()
            duplicated_mpans = set(counts[counts > 1].index)

        # ── Field lookup helper ──────────────────────────────────────────────────
        def get_col(norm_row, *aliases):
            """
            Return the first non-empty cell value from norm_row matching any alias.
            norm_row is a pandas Series with normalised column names as its index.
            Aliases are matched after normalising (lowercase, underscores→spaces).
            """
            for alias in aliases:
                key = re.sub(r'\s+', ' ', alias.lower().strip().replace('_', ' '))
                # Try space variant and underscore variant
                for k in (key, key.replace(' ', '_')):
                    if k in norm_row.index:
                        val = norm_row[k]
                        try:
                            if pd.isna(val):
                                continue
                        except Exception:
                            pass
                        s = str(val).strip()
                        if s and s.lower() != 'nan':
                            return s
            return None

        # ── Validate each row ────────────────────────────────────────────────────
        rows_out = []
        valid_count = 0
        invalid_count = 0

        for idx in range(len(df_norm)):
            norm_row = df_norm.iloc[idx]
            orig_row = df.iloc[idx]
            row_number = idx + 1
            errors = []

            # MPAN duplicate check
            mpan_val = None
            if mpan_col:
                raw = norm_row.get(mpan_col, '')
                try:
                    mpan_val = None if pd.isna(raw) else str(raw).strip() or None
                except Exception:
                    mpan_val = None
            if mpan_val and mpan_val in duplicated_mpans:
                errors.append('MPAN_MPR must be unique within the uploaded file')

            # Required: Business Name OR Contact Person
            # Covers: "Client Name", "Trading Name", "Business Name", "Company Name"
            bname = get_col(norm_row,
                            'client name', 'trading name', 'business name',
                            'company name', 'client company name')
            contact = get_col(norm_row,
                            'main contact', 'contact person',
                            'client contact name', 'contact')
            if not (bname or contact):
                errors.append('Business_Name OR Contact_Person must exist')

            # Required: Phone
            # Covers: "Tel No", "Tel Number", "Phone", "Mobile No", "Mobile"
            tel = get_col(norm_row,
                        'tel no', 'tel number', 'phone', 'telephone',
                        'mobile no', 'mobile')
            if not tel:
                errors.append('Tel_Number must exist')

            # Required: End Date (must be a valid date)
            # Covers: "Contract End", "End Date", "Expiry"
            end_raw = get_col(norm_row,
                            'contract end', 'end date',
                            'contract end date', 'expiry')
            if not end_raw:
                errors.append('End_Date must exist')
            else:
                parsed = pd.to_datetime(end_raw, dayfirst=True, errors='coerce')
                if pd.isna(parsed):
                    errors.append('End_Date is not a valid date')

            # Start Date — optional but validated if present
            # Covers: "Start Date", "Contract Start"
            start_raw = get_col(norm_row, 'start date', 'contract start',
                                'contract start date')
            if start_raw:
                parsed = pd.to_datetime(start_raw, dayfirst=True, errors='coerce')
                if pd.isna(parsed):
                    errors.append('Start_Date is not a valid date')

            is_valid = len(errors) == 0
            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                logger.warning(
                    'lead import preview - tenant=%s row=%s mpan=%s errors=%s',
                    tenant_id, row_number, mpan_val, errors
                )

            # Build output data dict using original column names
            data = {}
            for c in original_columns:
                v = orig_row[c]
                try:
                    is_na = pd.isna(v)
                except Exception:
                    is_na = False
                if is_na:
                    data[c] = None
                elif hasattr(v, 'isoformat'):
                    try:
                        data[c] = v.isoformat()
                    except Exception:
                        data[c] = str(v)
                else:
                    s = str(v).strip()
                    data[c] = s if s and s.lower() != 'nan' else None

            rows_out.append({
                'row_number': row_number,
                'data': data,
                'is_valid': is_valid,
                'errors': errors
            })

        return {
            'success': True,
            'total_rows': len(df),
            'valid_rows': valid_count,
            'invalid_rows': invalid_count,
            'rows': rows_out
        }

    def confirm_lead_import(self, tenant_id: int, rows: list, created_by: int | None, service_id: int) -> Dict[str, Any]:
        if not isinstance(rows, list) or len(rows) == 0:
            return {
                'success': False,
                'error': 'Invalid payload',
                'message': 'Expected non-empty JSON array of validated rows.'
            }

        import re
        from backend.db import SessionLocal
        from backend.models import Stage_Master
        from sqlalchemy import func

        # ✅ Resolve "Not Called" stage_id once, fall back to stage_id=6
        try:
            _session = SessionLocal()
            not_called = _session.query(Stage_Master).filter(
                func.lower(Stage_Master.stage_name) == 'not called'
            ).first()
            default_stage_id = not_called.stage_id if not_called else 6
            _session.close()
        except Exception:
            default_stage_id = 6

        def normalise_key(k):
            return re.sub(r'\s+', '_', k.lower().strip().replace(' ', '_'))

        # Column alias map: normalised Excel header → repository field name
        FIELD_MAP = {
            'client_name':     'business_name',
            'trading_name':    'business_name',   # fallback if client_name absent
            'main_contact':    'contact_person',
            'contact_person':  'contact_person',
            'tel_no':          'tel_number',
            'tel_number':      'tel_number',
            'mobile_no':       'mobile_no',
            'email':           'email',
            'mpan_top':        'mpan_mpr',
            'mpan_mpr':        'mpan_mpr',
            'mpan_bottom':     'mpan_bottom',
            'start_date':      'start_date',
            'contract_start':  'start_date',
            'contract_end':    'end_date',
            'end_date':        'end_date',
            'supplier':        'supplier',
            'annual_usage':    'annual_usage',
            'stand_charge':    'stand_charge',
            'rate_1':          'rate_1',
            'rate_2':          'rate_2',
            'rate_3':          'rate_3',
            'net_notch':       'net_notch',
            'payment_type':    'payment_type',
            'postcode':        'postcode',
            'post_code':       'postcode',
            'address_line_1':  'address',
            'street':          'address',
            'town':            'town',
            'county':          'county',
            'site_name':       'site_name',
            'aggregator':      'aggregator',
            'term_sold':       'term_sold',
            'in_contract':     'term_sold',
            'comms_paid':      'comms_paid',
            'position':        'position',
            'company_number':  'company_number',
        }

        def normalise_row(data: dict) -> dict:
            out = {}
            for raw_key, val in data.items():
                norm = normalise_key(raw_key)
                repo_key = FIELD_MAP.get(norm, norm)
                if repo_key not in out or out[repo_key] is None:
                    out[repo_key] = val

            if not out.get('business_name'):
                for raw_key, val in data.items():
                    if normalise_key(raw_key) == 'trading_name' and val:
                        out['business_name'] = val
                        break

            # ✅ Always inject the correct default stage — repo method will use this
            out.setdefault('stage_id', default_stage_id)
            out['stage_id'] = default_stage_id  # force override regardless of file content

            return out

        normalised_rows = [normalise_row(r) for r in rows]

        result = self.lead_repo.import_opportunities_from_import(
            tenant_id, normalised_rows, created_by, service_id
        )

        return {
            'success': True,
            'inserted': int(result.get('inserted', 0)),
            'skipped': int(result.get('skipped', 0)),
            'reasons': result.get('errors', [])
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

    def get_priced(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get all priced leads and renewals
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with priced leads and renewals
        """
        try:
            # Get priced leads (stage_id = 8)
            priced_leads = self.lead_repo.get_priced_leads(tenant_id)
            
            # Get priced renewals (Misc_Col1 = 'priced')
            priced_renewals = self.lead_repo.get_priced_renewals(tenant_id)
            
            return {
                'success': True,
                'leads': priced_leads,
                'renewals': priced_renewals,
                'total_leads': len(priced_leads),
                'total_renewals': len(priced_renewals),
                'total': len(priced_leads) + len(priced_renewals)
            }
        except Exception as e:
            logger.exception("get_priced error: %s", e)
            return {
                'success': False,
                'error': 'Internal server error',
                'message': str(e)
            }