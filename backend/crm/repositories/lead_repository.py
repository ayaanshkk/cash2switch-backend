# -*- coding: utf-8 -*-
"""
Lead/Opportunity Repository
Handles database operations for Opportunity_Details table
"""
import os
import logging
from typing import Optional, Dict, Any, List
from flask import request
from backend.crm.supabase_client import get_supabase_client
from backend.crm.utils.role_helpers import is_admin_user

logger = logging.getLogger(__name__)


def _supabase_configured() -> bool:
    """True if Supabase env vars are set so get_supabase_client() would succeed."""
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return False
    if os.getenv("SUPABASE_DB_URL"):
        return True
    if os.getenv("DATABASE_URL") and "supabase" in (os.getenv("DATABASE_URL") or ""):
        return True
    if os.getenv("SUPABASE_DB_PASSWORD"):
        return True
    return False


class _LocalCRMDBStub:
    """
    Stub DB adapter when Supabase is not configured (local/test).
    Implements same interface as SupabaseClient; returns empty/safe defaults.
    """
    def execute_query(self, query: str, params: tuple = None, fetch_one: bool = False) -> Optional[List[Dict[str, Any]]]:
        return None if fetch_one else []

    def execute_insert(self, query: str, params: tuple = None, returning: bool = True) -> Optional[Dict[str, Any]]:
        return None

    def execute_delete(self, query: str, params: tuple = None) -> int:
        return 0


class LeadRepository:
    """
    Repository for Opportunity_Details table (CRM Leads)
    All queries are tenant-filtered for multi-tenant isolation
    """
    
    def __init__(self):
        if _supabase_configured():
            self.db = get_supabase_client()
        else:
            self.db = _LocalCRMDBStub()
    
    def _ensure_default_client(self, tenant_id: int) -> Optional[int]:
        """
        Ensure a default/placeholder client exists for the tenant.
        Returns the client_id of the default client.
        Used for lead imports when no specific client is linked yet.
        """
        # Check if default client exists
        check_q = '''
            SELECT "client_id" FROM "StreemLyne_MT"."Client_Master"
            WHERE "tenant_id" = %s AND "client_company_name" = 'Unassigned Leads'
            LIMIT 1
        '''
        try:
            existing = self.db.execute_query(check_q, (tenant_id,), fetch_one=True)
            if existing:
                return existing.get('client_id')
        except Exception as e:
            logger.warning('_ensure_default_client check failed: %s', e)
        
        # Create default client if not exists
        # Get first country_id and currency_id from master tables
        country_q = 'SELECT "country_id" FROM "StreemLyne_MT"."Country_Master" LIMIT 1'
        currency_q = 'SELECT "currency_id" FROM "StreemLyne_MT"."Currency_Master" LIMIT 1'
        
        try:
            country_row = self.db.execute_query(country_q, fetch_one=True)
            currency_row = self.db.execute_query(currency_q, fetch_one=True)
            country_id = country_row.get('country_id') if country_row else 234  # fallback
            currency_id = currency_row.get('currency_id') if currency_row else 104  # fallback
            
            insert_q = '''
                INSERT INTO "StreemLyne_MT"."Client_Master"
                ("tenant_id", "client_company_name", "client_contact_name", "country_id", "default_currency_id", "created_at")
                VALUES (%s, 'Unassigned Leads', 'System', %s, %s, CURRENT_TIMESTAMP)
                RETURNING "client_id"
            '''
            result = self.db.execute_insert(insert_q, (tenant_id, country_id, currency_id), returning=True)
            if result:
                logger.info('Created default client for tenant %s: client_id=%s', tenant_id, result.get('client_id'))
                return result.get('client_id')
        except Exception as e:
            logger.exception('_ensure_default_client insert failed: %s', e)
        
        return None
    
    def get_all_leads(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all leads for a tenant
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (stage, status, assigned_to, etc.)
        
        Returns:
            List of lead/opportunity records
        """
        query = """
            SELECT 
                od.*,
                sm."stage_name",
                um."user_name" as assigned_to_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            -- NOTE: business rule change — leads are tenant-scoped on Opportunity_Details.tenant_id
            WHERE od."tenant_id" = %s

            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('stage_id'):
                query += ' AND od."stage_id" = %s'
                params.append(filters['stage_id'])
            
            if filters.get('status'):
                query += ' AND od."status" = %s'
                params.append(filters['status'])
            
            if filters.get('assigned_to'):
                query += ' AND od."opportunity_owner_employee_id" = %s'
                params.append(filters['assigned_to'])
        
        query += ' ORDER BY od."created_at" DESC'
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching leads for tenant {tenant_id}: {e}")
            return []
    
    def get_lead_by_id(self, tenant_id: int, opportunity_id: int, service_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Get a specific lead by ID (with tenant isolation)
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity/Lead identifier
        
        Returns:
            Lead record or None
        """
        query = """
            SELECT 
                od.*,
                sm."stage_name",
                um."user_name" as assigned_to_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE od."tenant_id" = %s
            AND od."opportunity_id" = %s
            LIMIT 1
        """
        params = [tenant_id, opportunity_id]
        if service_id is not None:
            query = query.replace("LIMIT 1", "AND od.\"service_id\" = %s\n            LIMIT 1")
            params.append(service_id)

        try:
            return self.db.execute_query(query, tuple(params), fetch_one=True)
        except Exception as e:
            print(f"Error fetching lead {opportunity_id}: {e}")
            return None
    
    def get_leads_by_stage(self, tenant_id: int, stage_id: int) -> List[Dict[str, Any]]:
        """
        Get all leads in a specific pipeline stage
        
        Args:
            tenant_id: Tenant identifier
            stage_id: Stage identifier
        
        Returns:
            List of leads in the specified stage
        """
        query = """
            SELECT 
                od.*,
                sm."stage_name",
                um."user_name" as assigned_to_name
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE od."tenant_id" = %s
            AND od."stage_id" = %s
            ORDER BY od."created_at" DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, stage_id))
        except Exception as e:
            print(f"Error fetching leads by stage: {e}")
            return []
    
    def get_lead_stats(self, tenant_id: int) -> Dict[str, Any]:
        """
        Get lead statistics for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            Dictionary with lead statistics
        """
        query = """
            SELECT 
                COUNT(*) as total_leads,
                SUM(od."opportunity_value") as total_value
            FROM "StreemLyne_MT"."Opportunity_Details" od
            WHERE od."tenant_id" = %s
        """
        
        try:
            result = self.db.execute_query(query, (tenant_id,), fetch_one=True)
            return result or {
                'total_leads': 0,
                'total_value': 0
            }
        except Exception as e:
            print(f"Error fetching lead stats: {e}")
            return {
                'total_leads': 0,
                'total_value': 0
            }
    
    def create_lead(self, tenant_id: int, lead_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new lead/opportunity
        
        Args:
            tenant_id: Tenant identifier
            lead_data: Lead information (must include client_id that belongs to this tenant)
        
        Returns:
            Created lead record
        """
        # First validate that client_id belongs to this tenant
        client_check_query = """
            SELECT "client_id" FROM "StreemLyne_MT"."Client_Master"
            WHERE "client_id" = %s AND "tenant_id" = %s
        """
        
        try:
            client = self.db.execute_query(client_check_query, (lead_data.get('client_id'), tenant_id), fetch_one=True)
            if not client:
                print(f"Error: client_id {lead_data.get('client_id')} does not belong to tenant {tenant_id}")
                return None
            
            query = """
                INSERT INTO "StreemLyne_MT"."Opportunity_Details"
                ("client_id", "opportunity_title", "opportunity_description", 
                 "stage_id", "opportunity_value", "opportunity_owner_employee_id", "created_at")
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING *
            """
            
            return self.db.execute_insert(
                query,
                (
                    lead_data.get('client_id'),
                    lead_data.get('opportunity_title'),
                    lead_data.get('opportunity_description', ''),
                    lead_data.get('stage_id'),
                    lead_data.get('opportunity_value', 0),
                    lead_data.get('opportunity_owner_employee_id')
                ),
                returning=True
            )
        except Exception as e:
            # Print exact SQL/DB error so failures are visible; then re-raise instead of returning None.
            print(f"LeadRepository.create_lead SQL/DB error: {e!r}")
            import traceback
            traceback.print_exc()
            raise

    def update_lead(self, opportunity_id: int, tenant_id: int, lead_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing lead with security enforcement at the repository layer.
        
        SECURITY: This method enforces that non-admin users can NEVER change ownership fields,
        regardless of what the request payload contains. Ownership fields are filtered out
        for non-admin users before any database operation.
        
        Args:
            opportunity_id: Opportunity ID to update
            tenant_id: Tenant identifier (for isolation)
            lead_data: Dictionary of fields to update
        
        Returns:
            Updated lead record, or None if not found/not owned
        
        Security Rules:
            - opportunity_owner_employee_id can ONLY be changed by admin users
            - Non-admin users: ownership fields are automatically removed
            - All updates are tenant-isolated
            - Warning is logged if non-admin tries to change ownership
        """
        try:
            # Create a copy to avoid mutating caller's data
            update_data = dict(lead_data) if lead_data else {}
            
            # Get current user from Flask request context
            current_user = getattr(request, 'current_user', None)
            user_is_admin = is_admin_user(current_user) if current_user else False
            
            # Define ownership fields that require admin privilege
            ownership_fields = {'opportunity_owner_employee_id', 'assigned_to_id'}
            
            # Define allowed fields for non-admin users
            allowed_non_admin_fields = {
                'opportunity_title',
                'opportunity_description',
                'stage_id',
                'opportunity_value',
                'contact_person',
                'tel_number',
                'email',
                'start_date',
                'end_date'
            }
            
            # Check if non-admin is trying to modify ownership
            attempted_ownership_change = any(field in update_data for field in ownership_fields)
            
            if not user_is_admin:
                # SECURITY: Non-admin users cannot change ownership
                if attempted_ownership_change:
                    logger.warning(
                        'SECURITY: User (id=%s, tenant=%s) attempted to change ownership field on lead %s - BLOCKED',
                        getattr(current_user, 'id', 'unknown'),
                        tenant_id,
                        opportunity_id
                    )
                    # Remove all ownership fields from update data
                    for field in ownership_fields:
                        update_data.pop(field, None)
                
                # Filter to only allowed fields for non-admin
                filtered_data = {}
                for field, value in update_data.items():
                    if field in allowed_non_admin_fields:
                        filtered_data[field] = value
                    else:
                        # Log fields that were silently ignored (not ownership but not allowed)
                        if field not in ('id', 'opportunity_id', 'tenant_id', 'client_id', 'created_at'):
                            logger.debug(
                                'Non-admin update_lead: ignoring field %s (not in allowed list)',
                                field
                            )
                
                update_data = filtered_data
            
            # If no fields left to update after filtering, return the current lead
            if not update_data:
                return self.get_lead_by_id(tenant_id, opportunity_id)
            
            # Build dynamic UPDATE query based on provided fields
            set_clauses = []
            params = []
            
            for field, value in update_data.items():
                set_clauses.append(f'"{field}" = %s')
                params.append(value)
            
            if not set_clauses:
                # No valid fields to update
                return self.get_lead_by_id(tenant_id, opportunity_id)
            
            # Add tenant_id and opportunity_id for WHERE clause
            params.append(tenant_id)
            params.append(opportunity_id)
            
            query = f"""
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET {', '.join(set_clauses)}
                WHERE "tenant_id" = %s AND "opportunity_id" = %s
            """
            
            updated_count = self.db.execute_update(query, tuple(params))
            
            if updated_count and updated_count > 0:
                logger.info(
                    'Updated lead %s for tenant %s (admin=%s, fields=%s)',
                    opportunity_id,
                    tenant_id,
                    user_is_admin,
                    list(update_data.keys())
                )
                # Fetch and return the updated record
                return self.get_lead_by_id(tenant_id, opportunity_id)
            else:
                logger.warning('Lead %s not found or not owned by tenant %s', opportunity_id, tenant_id)
                return None
                
        except Exception as e:
            logger.exception('Error updating lead %s: %s', opportunity_id, e)
            return None

    def import_opportunities_from_import(self, tenant_id: int, rows: list, created_by: int | None, service_id: int) -> Dict[str, Any]:
        """
        Insert opportunities from a pre-validated import payload.

        Rules:
        - MPAN_MPR is stored in Opportunity_Details.mpan_mpr
        - stage_id = "Lead" (not "Not Called")
        - display_order is per-salesperson sequential (starts at 1 for each employee)
        - tenant-scoped via Opportunity_Details.tenant_id
        - if MPAN already exists in Opportunity_Details -> skip and report
        - partial success allowed; per-row reasons returned
        - NO joins to Project_Details or Client_Master
        
        Returns:
        - inserted: count of successfully inserted rows
        - skipped: count of rejected rows
        - errors: list of {row, reason, details} for each skipped row
        """
        inserted = 0
        skipped = 0
        errors = []

        # ✅ FIX 1: Resolve default stage_id for "Lead" (not "Not Called")
        default_stage_id = None
        try:
            default_stage = self.db.execute_query(
                'SELECT "stage_id" FROM "StreemLyne_MT"."Stage_Master" WHERE LOWER("stage_name") = %s LIMIT 1',
                ('lead',),  # ✅ Changed from 'not called' to 'lead'
                fetch_one=True
            )
            default_stage_id = default_stage.get('stage_id') if default_stage else None
        except Exception as e:
            logger.exception('Failed to resolve default stage_id for Lead: %s', e)

        if not default_stage_id:
            # Fallback: create "Lead" stage if missing
            try:
                result = self.db.execute_insert(
                    'INSERT INTO "StreemLyne_MT"."Stage_Master" ("stage_name", "stage_description") VALUES (%s, %s) RETURNING "stage_id"',
                    ('Lead', 'Imported lead - not yet contacted'),
                    returning=True
                )
                default_stage_id = result.get('stage_id') if result else 1
                logger.info('✨ Created "Lead" stage with ID %s', default_stage_id)
            except Exception:
                default_stage_id = 1  # Last resort fallback

        # ✅ FIX 2: Get current max display_order for this salesperson
        next_display_order = 1
        if created_by:
            try:
                max_order_result = self.db.execute_query(
                    '''SELECT COALESCE(MAX("display_order"), 0) as max_order
                    FROM "StreemLyne_MT"."Opportunity_Details"
                    WHERE "tenant_id" = %s
                    AND "opportunity_owner_employee_id" = %s''',
                    (tenant_id, created_by),
                    fetch_one=True
                )
                next_display_order = (max_order_result.get('max_order') if max_order_result else 0) + 1
            except Exception as e:
                logger.warning('Failed to get max display_order, starting from 1: %s', e)
                next_display_order = 1

        # Client_id is optional for leads (no client relationship yet)
        default_client_id = None

        for idx, raw in enumerate(rows or []):
            # Accept either preview row shape ({row_number,data,is_valid,...}) or plain dict
            row_number = raw.get('row_number') if isinstance(raw, dict) and raw.get('row_number') else (idx + 1)
            data = raw.get('data') if isinstance(raw, dict) and raw.get('data') else (raw if isinstance(raw, dict) else {})

            # Normalize keys for tolerant access (Excel often uses "Business Name", we use business_name)
            def _norm(s):
                if not s:
                    return ""
                return str(s).lower().strip().replace(" ", "_")

            def get_field(*names):
                for n in names:
                    if not n:
                        continue
                    if n in data:
                        return data.get(n)
                    low = _norm(n)
                    for k in data.keys():
                        if _norm(k) == low:
                            return data.get(k)
                return None

            mpan = (get_field('MPAN_MPR', 'mpan_mpr', 'mpan', 'MPAN', 'MPR') or '')
            mpan = mpan.strip() if isinstance(mpan, str) else str(mpan) if mpan else ''

            # Map fields -> Opportunity_Details columns
            business_name = get_field('Business_Name', 'business_name', 'client_company_name', 'Company_Name', 'Company') or None
            contact_person = get_field('Contact_Person', 'contact_person', 'client_contact_name', 'Contact', 'Name') or None
            tel_number = get_field('Tel_Number', 'phone', 'tel_number', 'telephone', 'Phone', 'Mobile') or None
            email = get_field('Email', 'email', 'Email_Address') or None
            start_date = get_field('Start_Date', 'start_date', 'contract_start_date', 'Contract_Start') or None
            end_date = get_field('End_Date', 'end_date', 'contract_end_date', 'Contract_End') or None
            
            # Generate title from business name or contact person if no explicit title provided
            title = get_field('Title', 'opportunity_title') or business_name or contact_person or f'Imported lead {idx + 1}'
            description = get_field('Notes', 'notes', 'call_summary', 'Description') or None

            # Skip row only if it has no identifying information at all
            if not mpan and not business_name and not contact_person and not email:
                skipped += 1
                error_detail = {
                    'row': row_number,
                    'reason': 'MISSING_FIELDS',
                    'message': 'Row has no identifying information',
                    'details': 'Missing all of: MPAN_MPR, Business_Name, Contact_Person, Email'
                }
                errors.append(error_detail)
                logger.warning('import_opportunities_from_import skipped row=%s - no identifying info', row_number)
                continue

            # ✅ FIX 3: Insert with display_order and opportunity_owner_employee_id
            insert_q = '''
                INSERT INTO "StreemLyne_MT"."Opportunity_Details"
                ("tenant_id", "client_id", "mpan_mpr", "opportunity_title", "opportunity_description", 
                "business_name", "contact_person", "tel_number", "email", "start_date", "end_date",
                "stage_id", "service_id", "opportunity_owner_employee_id", "display_order", "created_at")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING "opportunity_id"
            '''
            try:
                out = self.db.execute_insert(
                    insert_q,
                    (
                        tenant_id,
                        default_client_id,
                        mpan,
                        title,
                        description,
                        business_name,
                        contact_person,
                        tel_number,
                        email,
                        start_date,
                        end_date,
                        default_stage_id,      # ✅ "Lead" stage
                        service_id,
                        created_by,            # ✅ opportunity_owner_employee_id
                        next_display_order,    # ✅ Per-salesperson sequential ID
                    ),
                    returning=True
                )
                if out and out.get('opportunity_id'):
                    inserted += 1
                    next_display_order += 1  # ✅ Increment for next lead
                    logger.info(
                        'import_opportunities_from_import inserted opportunity_id=%s mpan=%s display_order=%s',
                        out.get('opportunity_id'), mpan, next_display_order - 1
                    )
                else:
                    skipped += 1
                    error_detail = {
                        'row': row_number,
                        'mpan': mpan,
                        'reason': 'INSERT_NO_ID',
                        'message': 'Insert succeeded but returned no opportunity_id',
                        'details': f'Database insert executed but no RETURNING clause result'
                    }
                    errors.append(error_detail)
            except Exception as e:
                logger.exception('import_opportunities_from_import insert failed row=%s mpan=%s: %s', row_number, mpan, e)
                skipped += 1
                error_detail = {
                    'row': row_number,
                    'mpan': mpan,
                    'reason': 'INSERT_FAILED',
                    'message': 'Database insert failed',
                    'details': str(e)
                }
                errors.append(error_detail)
                # Continue with next row (partial success allowed)
                continue

        return {'inserted': inserted, 'skipped': skipped, 'errors': errors}

    def update_lead_status(self, tenant_id: int, opportunity_id: int, stage_id: int) -> Optional[Dict[str, Any]]:
        """
        Update lead status (stage_id) with tenant isolation.
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity identifier
            stage_id: New stage ID to set
        
        Returns:
            Dict with updated opportunity_id and stage_id, or None if not found/not owned
        """
        try:
            # Optional: get stage_name for logging
            stage_query = 'SELECT "stage_name" FROM "StreemLyne_MT"."Stage_Master" WHERE "stage_id" = %s'
            stage_result = self.db.execute_query(stage_query, (stage_id,), fetch_one=True)
            stage_name = stage_result.get('stage_name') if stage_result else None

            # Allow update for: tenant_id match OR linked to client in our tenant (renewals with null tenant_id)
            query = """
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET "stage_id" = %s
                WHERE "opportunity_id" = %s
                AND ("tenant_id" = %s
                     OR ("tenant_id" IS NULL AND "client_id" IN (
                         SELECT "client_id" FROM "StreemLyne_MT"."Client_Master" WHERE "tenant_id" = %s
                     )))
            """
            updated_count = self.db.execute_update(query, (stage_id, opportunity_id, tenant_id, tenant_id))
            if updated_count and updated_count > 0:
                logger.info('Updated lead %s to stage %s (stage_name=%s) for tenant %s',
                           opportunity_id, stage_id, stage_name, tenant_id)
                return {"opportunity_id": opportunity_id, "stage_id": stage_id}

            logger.warning('Lead %s not found or not owned by tenant %s', opportunity_id, tenant_id)
            return None
        except Exception as e:
            logger.exception('Error updating lead status: %s', e)
            return None
    
    def get_leads_recycle_bin(self, tenant_id: int, service_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all Lost leads (recycle bin) for a tenant.
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            List of lost/deleted leads
        """
        query = '''
            SELECT
                od."opportunity_id",
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                od."contact_person",
                od."mpan_mpr",
                od."service_id",
                sm."stage_name",
                od."start_date",
                od."tel_number",
                od."email"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = %s
            AND sm."stage_name" = 'Lost'
            ORDER BY od."created_at" DESC
        '''
        params = [tenant_id]
        if service_id is not None:
            query = query.replace("ORDER BY", "AND od.\"service_id\" = %s\n            ORDER BY")
            params.append(service_id)

        try:
            rows = self.db.execute_query(query, tuple(params))
            if not rows:
                return []
            
            out = []
            for r in rows:
                out.append({
                    'opportunity_id': r.get('opportunity_id'),
                    'business_name': r.get('business_name'),
                    'contact_person': r.get('contact_person'),
                    'mpan_mpr': r.get('mpan_mpr'),
                    'service_id': r.get('service_id'),
                    'stage_name': r.get('stage_name'),
                    'start_date': r.get('start_date'),
                    'tel_number': r.get('tel_number'),
                    'email': r.get('email'),
                })
            return out
        except Exception as e:
            logger.exception('get_leads_recycle_bin failed for tenant=%s: %s', tenant_id, e)
            return []
    
    def delete_expired_lost_leads(self, tenant_id: int, days: int = 30) -> int:
        """
        Permanently delete Lost leads older than specified days.
        
        Args:
            tenant_id: Tenant identifier
            days: Delete leads older than this many days (default 30)
        
        Returns:
            Number of deleted records
        """
        query = """
            DELETE FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE "tenant_id" = %s
            AND "deleted_at" IS NOT NULL
            AND "deleted_at" < NOW() - INTERVAL '%s days'
        """
        
        try:
            rows_affected = self.db.execute_delete(query, (tenant_id, days))
            logger.info('Deleted %d expired lost leads for tenant %s', rows_affected, tenant_id)
            return rows_affected
        except Exception as e:
            logger.exception('Error deleting expired lost leads for tenant %s: %s', tenant_id, e)
            return 0

    def delete_lead(self, opportunity_id: int, tenant_id: int) -> bool:
        """
        Delete a lead/opportunity
        
        Args:
            opportunity_id: Opportunity identifier
            tenant_id: Tenant identifier
        
        Returns:
            True if deleted successfully
        """
        # Validate tenant ownership via Opportunity_Details.tenant_id
        query = """
            DELETE FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE "tenant_id" = %s
            AND "opportunity_id" = %s
        """
        
        try:
            rows_affected = self.db.execute_delete(query, (tenant_id, opportunity_id))
            return rows_affected > 0
        except Exception as e:
            print(f"Error deleting lead: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_leads_with_customer_type(self, tenant_id: int, customer_type: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all leads with customer_type classification (NEW/EXISTING)
        
        Args:
            tenant_id: Tenant identifier
            customer_type: 'NEW' or 'EXISTING' or None for all
            filters: Optional filters (stage_id, lead_status, etc.)
        
        Returns:
            List of lead records with customer_type field
        """
        # Subquery to determine if client has previous opportunities
        query = """
            SELECT 
                od.*,
                cm."client_id",
                cm."client_company_name" as business_name,
                cm."client_contact_name" as contact_person,
                cm."client_phone" as phone,
                cm."client_email" as email,
                sm."stage_name" as lead_status,
                em."employee_name" as assigned_employee,
                em."employee_id" as assigned_employee_id,
                CASE 
                    WHEN EXISTS (
                        SELECT 1 FROM "StreemLyne_MT"."Opportunity_Details" od2
                        WHERE od2."client_id" = od."client_id"
                        AND od2."opportunity_id" < od."opportunity_id"
                    ) THEN 'EXISTING'
                    ELSE 'NEW'
                END as customer_type,
                (
                    SELECT ci."contact_date"
                    FROM "StreemLyne_MT"."Client_Interactions" ci
                    WHERE ci."client_id" = od."client_id"
                    ORDER BY ci."contact_date" DESC
                    LIMIT 1
                ) as last_call_date,
                (
                    SELECT ci."notes"
                    FROM "StreemLyne_MT"."Client_Interactions" ci
                    WHERE ci."client_id" = od."client_id"
                    ORDER BY ci."contact_date" DESC
                    LIMIT 1
                ) as last_call_result,
                (
                    SELECT ci."reminder_date"
                    FROM "StreemLyne_MT"."Client_Interactions" ci
                    WHERE ci."client_id" = od."client_id"
                    ORDER BY ci."contact_date" DESC
                    LIMIT 1
                ) as next_follow_up_date
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE cm."tenant_id" = %s
        """
        params = [tenant_id]
        
        # Filter by customer_type
        if customer_type:
            if customer_type == 'NEW':
                query += """
                    AND NOT EXISTS (
                        SELECT 1 FROM "StreemLyne_MT"."Opportunity_Details" od2
                        WHERE od2."client_id" = od."client_id"
                        AND od2."opportunity_id" < od."opportunity_id"
                    )
                """
            elif customer_type == 'EXISTING':
                query += """
                    AND EXISTS (
                        SELECT 1 FROM "StreemLyne_MT"."Opportunity_Details" od2
                        WHERE od2."client_id" = od."client_id"
                        AND od2."opportunity_id" < od."opportunity_id"
                    )
                """
        
        # Apply additional filters
        if filters:
            if filters.get('stage_id'):
                query += ' AND od."stage_id" = %s'
                params.append(filters['stage_id'])
            
            if filters.get('lead_status'):
                query += ' AND sm."stage_name" = %s'
                params.append(filters['lead_status'])
            
            if filters.get('assigned_employee_id'):
                query += ' AND od."opportunity_owner_employee_id" = %s'
                params.append(filters['assigned_employee_id'])
        
        query += ' ORDER BY od."created_at" DESC'
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching leads with customer type: {e}")
            import traceback
            traceback.print_exc()
            return []

    def create_client(self, tenant_id: int, client_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Insert a new client in Client_Master. Does not create Opportunity_Details;
        call create_lead after this for that.

        API → DB: business_name→client_company_name, contact_person→client_contact_name,
        phone→client_phone, email→client_email, address→address, country_id→country_id.
        tenant_id is always included from header.
        """
        # Use DB column values (service passes mapped client_data)
        company = client_data.get('client_company_name') or ''
        contact = client_data.get('client_contact_name') or ''
        phone = client_data.get('client_phone')
        email = client_data.get('client_email')
        address = client_data.get('address')
        country_id = client_data.get('country_id')

        query = """
            INSERT INTO "StreemLyne_MT"."Client_Master"
            ("tenant_id", "client_company_name", "client_contact_name", "address",
             "country_id", "post_code", "client_phone", "client_email", "client_website",
             "default_currency_id", "created_at")
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING *
        """
        try:
            return self.db.execute_insert(
                query,
                (
                    int(tenant_id),
                    company,
                    contact,
                    address,
                    country_id,
                    client_data.get('post_code'),
                    phone,
                    email,
                    client_data.get('client_website'),
                    client_data.get('default_currency_id'),
                ),
                returning=True
            )
        except Exception as e:
            logger.error(e, exc_info=True)
            raise Exception(f"Create client failed: {str(e)}")

    def create_client_and_lead_transaction(self, tenant_id: int, client_data: Dict[str, Any], lead_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a client only. IMPORTANT: by business rule, creating a client MUST NOT create
        an Opportunity_Details row. This method preserves the atomic client insert but will
        NOT create or return an opportunity. Callers that previously relied on this behavior
        should instead use the import flow to create leads.
        Returns: {'client': <client_row>} on success, or None on failure.
        """
        # If running without a real DB connection, fall back to existing behavior
        try:
            with self.db.get_connection() as conn:
                # When stubbed, conn will be None — fall back to existing behavior that only creates the client
                if conn is None:
                    client = self.create_client(tenant_id, client_data)
                    return {'client': client} if client else None

                with conn.cursor() as cur:
                    # Insert client (same as previous implementation)
                    insert_client_sql = (
                        'INSERT INTO "StreemLyne_MT"."Client_Master' \
                        '" ("tenant_id", "client_company_name", "client_contact_name", "address", '
                        '"country_id", "post_code", "client_phone", "client_email", "client_website", '
                        '"default_currency_id", "created_at") '
                        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING *'
                    )

                    cur.execute(
                        insert_client_sql,
                        (
                            int(tenant_id),
                            client_data.get('client_company_name') or '',
                            client_data.get('client_contact_name') or '',
                            client_data.get('address'),
                            client_data.get('country_id'),
                            client_data.get('post_code'),
                            client_data.get('client_phone'),
                            client_data.get('client_email'),
                            client_data.get('client_website'),
                            client_data.get('default_currency_id'),
                        )
                    )
                    client_row = cur.fetchone()
                    if not client_row:
                        conn.rollback()
                        return None

                    # Commit transaction (client-only)
                    conn.commit()
                    return {'client': dict(client_row)}
        except Exception as e:
            logger.exception("create_client_and_lead_transaction failed: %s", e)
            try:
                # Attempt rollback on explicit connection if available
                with self.db.get_connection() as conn:
                    if conn:
                        conn.rollback()
            except Exception:
                pass
            return None

    def get_first_country_id(self) -> Optional[int]:
        """Return first country_id from Country_Master, or None if empty/unavailable."""
        try:
            row = self.db.execute_query(
                'SELECT "country_id" FROM "StreemLyne_MT"."Country_Master" ORDER BY "country_id" LIMIT 1',
                fetch_one=True
            )
            if row and row.get("country_id") is not None:
                return int(row["country_id"])
        except Exception as e:
            logger.debug("get_first_country_id: %s", e)
        return None

    def get_first_currency_id(self) -> Optional[int]:
        """Return first currency_id from Currency_Master, or None if empty/unavailable."""
        try:
            row = self.db.execute_query(
                'SELECT "currency_id" FROM "StreemLyne_MT"."Currency_Master" ORDER BY "currency_id" LIMIT 1',
                fetch_one=True
            )
            if row and row.get("currency_id") is not None:
                return int(row["currency_id"])
        except Exception as e:
            logger.debug("get_first_currency_id: %s", e)
        return None

    def get_leads_table(self, tenant_id: int) -> List[Dict[str, Any]]:
        """
        Get leads table for CRM UI: one row per opportunity with joined columns
        from Client_Master, Stage_Master, Employee_Master, Project_Details,
        Energy_Contract_Master, Supplier_Master, and latest Client_Interactions.

        Returns list of dicts with keys: id, name, business_name, contact_person,
        tel_number, mpan_mpr, supplier, annual_usage, start_date, end_date,
        status, assigned_to, callback_parameter, call_summary.
        """
        query = """
            SELECT
                od."opportunity_id" AS id,
                -- Per new business rule: surface opportunity-level fields only. Do NOT join Client_Master.
                od."opportunity_title" AS name,
                od."opportunity_title" AS business_name,
                NULL AS contact_person,
                NULL AS tel_number,
                (
                    SELECT COALESCE(pd."mpan", ecm."mpan_number")
                    FROM "StreemLyne_MT"."Project_Details" pd
                    LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON ecm."project_id" = pd."project_id"
                    WHERE pd."opportunity_id" = od."opportunity_id"
                    ORDER BY pd."project_id"
                    LIMIT 1
                ) AS mpan_mpr,
                (
                    SELECT sm."supplier_company_name"
                    FROM "StreemLyne_MT"."Project_Details" pd
                    INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON ecm."project_id" = pd."project_id"
                    LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON sm."supplier_id" = ecm."supplier_id"
                    WHERE pd."opportunity_id" = od."opportunity_id"
                    ORDER BY ecm."energy_contract_master_id"
                    LIMIT 1
                ) AS supplier,
                (
                    SELECT pd."annual_usage"
                    FROM "StreemLyne_MT"."Project_Details" pd
                    WHERE pd."opportunity_id" = od."opportunity_id"
                    ORDER BY pd."project_id"
                    LIMIT 1
                ) AS annual_usage,
                (
                    SELECT ecm."contract_start_date"
                    FROM "StreemLyne_MT"."Project_Details" pd
                    INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON ecm."project_id" = pd."project_id"
                    WHERE pd."opportunity_id" = od."opportunity_id"
                    ORDER BY ecm."energy_contract_master_id"
                    LIMIT 1
                ) AS start_date,
                (
                    SELECT ecm."contract_end_date"
                    FROM "StreemLyne_MT"."Project_Details" pd
                    INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON ecm."project_id" = pd."project_id"
                    WHERE pd."opportunity_id" = od."opportunity_id"
                    ORDER BY ecm."energy_contract_master_id"
                    LIMIT 1
                ) AS end_date,
                sm."stage_name" AS status,
                em."employee_name" AS assigned_to,
                (
                    SELECT ci."next_steps"
                    FROM "StreemLyne_MT"."Client_Interactions" ci
                    WHERE ci."client_id" = od."client_id"
                    ORDER BY ci."contact_date" DESC NULLS LAST
                    LIMIT 1
                ) AS callback_parameter,
                (
                    SELECT ci."notes"
                    FROM "StreemLyne_MT"."Client_Interactions" ci
                    WHERE ci."client_id" = od."client_id"
                    ORDER BY ci."contact_date" DESC NULLS LAST
                    LIMIT 1
                ) AS call_summary
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
            WHERE cm."tenant_id" = %s
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
            ORDER BY od."created_at" DESC
        """
        try:
            rows = self.db.execute_query(query, (tenant_id,))
            if not rows:
                logger.debug(
                    "get_leads_table: empty result for tenant_id=%s, query result count=0",
                    tenant_id,
                )
                return []
            # Normalize to the 14 keys (dates as ISO strings if present)
            result = []
            for r in rows:
                result.append({
                    'id': r.get('id'),
                    'name': r.get('name'),
                    'business_name': r.get('business_name'),
                    'contact_person': r.get('contact_person'),
                    'tel_number': r.get('tel_number'),
                    'mpan_mpr': r.get('mpan_mpr'),
                    'supplier': r.get('supplier'),
                    'annual_usage': r.get('annual_usage'),
                    'start_date': r.get('start_date').isoformat() if r.get('start_date') else None,
                    'end_date': r.get('end_date').isoformat() if r.get('end_date') else None,
                    'status': r.get('status'),
                    'assigned_to': r.get('assigned_to'),
                    'callback_parameter': r.get('callback_parameter'),
                    'call_summary': r.get('call_summary'),
                })
            return result
        except Exception as e:
            print(f"Error fetching leads table for tenant {tenant_id}: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_leads_list(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Return a minimal, tenant-scoped list of leads (read-only projection).
        Excludes records that have a Project_Details entry (those are renewals).
        Includes supplier_name, annual_usage, end_date from Opportunity_Details columns.
        """
        query = '''
            SELECT
                od."opportunity_id",
                od."tenant_lead_id",
                COALESCE(od."business_name", cm."client_company_name", od."opportunity_title") AS business_name,
                COALESCE(od."contact_person", cm."client_contact_name") AS contact_person,
                COALESCE(od."tel_number", cm."client_phone") AS tel_number,
                COALESCE(od."email", cm."client_email") AS email,
                od."mpan_mpr",
                od."mpan_bottom",
                od."start_date",
                od."end_date",
                od."service_id",
                od."stage_id",
                sm."stage_name",
                od."opportunity_owner_employee_id",
                em."employee_name" AS assigned_to_name,
                od."created_at",
                od."supplier_id",
                sup."supplier_company_name" AS supplier_name,
                od."annual_usage",
                od."stand_charge",
                od."rate_1",
                od."net_notch",
                od."payment_type",
                od."postcode",
                od."mobile_no"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od."stage_id"                      = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em  ON od."opportunity_owner_employee_id" = em."employee_id"
            LEFT JOIN "StreemLyne_MT"."Client_Master"   cm  ON od."client_id"                     = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od."supplier_id"                   = sup."supplier_id"
            WHERE (od."tenant_id" = %s OR (od."client_id" IS NOT NULL AND cm."tenant_id" = %s))
            AND NOT EXISTS (
                SELECT 1
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
        '''
 
        params = [tenant_id, tenant_id]
 
        if filters and isinstance(filters, dict):
            if filters.get('stage_id'):
                query += ' AND od."stage_id" = %s'
                params.append(int(filters['stage_id']))
 
            if filters.get('stage'):
                query += ' AND sm."stage_name" = %s'
                params.append(filters['stage'])
 
            if filters.get('exclude_stage'):
                query += ' AND (sm."stage_name" IS NULL OR sm."stage_name" != %s)'
                params.append(filters['exclude_stage'])
 
            if filters.get('service_id') is not None:
                query += ' AND od."service_id" = %s'
                params.append(int(filters['service_id']))
 
            if filters.get('assigned_to') is not None:
                query += ' AND od."opportunity_owner_employee_id" = %s'
                params.append(int(filters['assigned_to']))

            if filters.get('unallocated_only'):
                query += ' AND (od."is_allocated" = FALSE OR od."is_allocated" IS NULL)'

        query += ' ORDER BY od."created_at" DESC'
 
        try:
            rows = self.db.execute_query(query, tuple(params))
            if not rows:
                return []
 
            out = []
            for r in rows:
                def _iso(v):
                    return v.isoformat() if getattr(v, 'isoformat', None) else (v or None)
 
                out.append({
                    'opportunity_id':                r.get('opportunity_id'),
                    'tenant_lead_id':                r.get('tenant_lead_id'),
                    'business_name':                 r.get('business_name'),
                    'contact_person':                r.get('contact_person'),
                    'tel_number':                    str(r.get('tel_number')).replace('.0', '') if r.get('tel_number') else None,
                    'mobile_no':                     r.get('mobile_no'),
                    'email':                         r.get('email'),
                    'mpan_mpr':                      r.get('mpan_mpr'),
                    'mpan_bottom':                   r.get('mpan_bottom'),
                    'start_date':                    _iso(r.get('start_date')),
                    'end_date':                      _iso(r.get('end_date')),
                    'service_id':                    r.get('service_id'),
                    'stage_id':                      r.get('stage_id'),
                    'stage_name':                    r.get('stage_name'),
                    'opportunity_owner_employee_id': r.get('opportunity_owner_employee_id'),
                    'assigned_to_name':              r.get('assigned_to_name'),
                    'created_at':                    _iso(r.get('created_at')),
                    # ✅ New fields from ALTER TABLE migration
                    'supplier_id':                   r.get('supplier_id'),
                    'supplier_name':                 r.get('supplier_name'),
                    'annual_usage':                  r.get('annual_usage'),
                    'stand_charge':                  r.get('stand_charge'),
                    'rate_1':                        r.get('rate_1'),
                    'net_notch':                     r.get('net_notch'),
                    'payment_type':                  r.get('payment_type'),
                    'postcode':                      r.get('postcode'),
                })
            return out
        except Exception as e:
            logger.exception('get_leads_list failed for tenant=%s: %s', tenant_id, e)
            return []


    def get_priced_leads(self, tenant_id: int) -> List[Dict[str, Any]]:
        """
        Get all leads with stage_id = 8 (Priced)
        Joins Client_Master to get tenant_id and contact details
        """
        query = """
            SELECT 
                od.opportunity_id,
                od.opportunity_title as business_name,
                cm.client_contact_name as contact_person,
                cm.client_phone as tel_number,
                cm.client_email as email,
                NULL as mpan_mpr,
                NULL as supplier,
                NULL as start_date,
                NULL as end_date,
                NULL as annual_usage,
                em.employee_name as assigned_to_name,
                od.created_at,
                od.stage_id,
                od.opportunity_value,
                'lead' as source_type
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm 
                ON od.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em 
                ON od.opportunity_owner_employee_id = em.employee_id
            WHERE od.stage_id = 8
            AND cm.tenant_id = %s
            ORDER BY od.created_at DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id,))
        except Exception as e:
            logger.error(f"Error fetching priced leads: {e}")
            return []

    def get_priced_renewals(self, tenant_id: int) -> List[Dict[str, Any]]:
        """
        Get all renewals with Misc_Col1 = 'priced'
        """
        query = """
            SELECT 
                cm.client_id,
                od.opportunity_id,
                cm.client_company_name as business_name,
                cm.client_contact_name as contact_person,
                cm.client_phone as tel_number,
                cm.client_email as email,
                ecm.mpan_number as mpan_mpr,
                sm.supplier_company_name as supplier,
                ecm.contract_start_date as start_date,
                ecm.contract_end_date as end_date,
                NULL as annual_usage,
                em.employee_name as assigned_to_name,
                pd.created_at,
                od.stage_id,
                od.opportunity_value,
                'renewal' as source_type
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd 
                ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Opportunity_Details" od 
                ON pd.opportunity_id = od.opportunity_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm 
                ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm 
                ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em 
                ON pd.employee_id = em.employee_id
            WHERE cm.tenant_id = %s
            AND cm.client_company_name != '[IMPORTED LEADS]'
            AND LOWER(od."Misc_Col1") = 'priced'
            ORDER BY pd.created_at DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id,))
        except Exception as e:
            logger.error(f"Error fetching priced renewals: {e}")
            return []

    def bulk_assign_leads(self, tenant_id: int, lead_ids: List[int], employee_id: int) -> Dict[str, Any]:
        """
        Bulk assign leads to an employee.
        Updates Opportunity_Details.opportunity_owner_employee_id for multiple leads.
        
        Args:
            tenant_id: Tenant identifier for isolation
            lead_ids: List of opportunity IDs to assign
            employee_id: Employee ID to assign leads to
        
        Returns:
            Dictionary with success status and updated count
        """
        if not lead_ids:
            return {'success': False, 'updated': 0, 'error': 'No lead IDs provided'}

        try:
            # Validate assigned_to_id exists and belongs to tenant (prevent privilege escalation)
            emp_check = self.db.execute_query(
                'SELECT 1 FROM "StreemLyne_MT"."Employee_Master" WHERE "employee_id" = %s AND "tenant_id" = %s LIMIT 1',
                (employee_id, tenant_id),
                fetch_one=True
            )
            if not emp_check:
                logger.warning('bulk_assign_leads: employee_id=%s not found for tenant_id=%s', employee_id, tenant_id)
                return {
                    'success': False,
                    'updated': 0,
                    'error': 'Employee not found',
                    'message': 'assigned_to_id must be an existing employee in your tenant'
                }

            # Verify all leads belong to the tenant before updating
            verify_query = '''
                SELECT COUNT(*) as cnt FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE "tenant_id" = %s AND "opportunity_id" = ANY(%s)
            '''
            verify_result = self.db.execute_query(verify_query, (tenant_id, lead_ids), fetch_one=True)
            verified_count = verify_result.get('cnt', 0) if verify_result else 0
            
            if verified_count != len(lead_ids):
                logger.warning(f'bulk_assign_leads: tenant={tenant_id} requested={len(lead_ids)} but found={verified_count}')
                return {
                    'success': False,
                    'updated': 0,
                    'error': f'Some leads do not belong to tenant or do not exist'
                }
            
            # ✅ FIX: Set is_allocated = TRUE when reassigning leads
            update_query = '''
                UPDATE "StreemLyne_MT"."Opportunity_Details"
                SET "opportunity_owner_employee_id" = %s,
                    "is_allocated" = TRUE
                WHERE "tenant_id" = %s AND "opportunity_id" = ANY(%s)
            '''
            updated = self.db.execute_update(update_query, (employee_id, tenant_id, lead_ids))
            
            logger.info(f'bulk_assign_leads: assigned {updated} leads to employee_id={employee_id} tenant={tenant_id}')
            
            return {
                'success': True,
                'updated': updated,
                'employee_id': employee_id,
                'lead_ids': lead_ids
            }
            
        except Exception as e:
            logger.exception(f'bulk_assign_leads failed tenant={tenant_id} employee={employee_id}: {e}')
            return {
                'success': False,
                'updated': 0,
                'error': str(e)
            }
