# -*- coding: utf-8 -*-
"""
Lead/Opportunity Repository
Handles database operations for Opportunity_Details table
"""
import os
import logging
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client

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
    
    def get_lead_by_id(self, tenant_id: int, opportunity_id: int) -> Optional[Dict[str, Any]]:
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
        
        try:
            return self.db.execute_query(query, (tenant_id, opportunity_id), fetch_one=True)
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

    def import_opportunities_from_import(self, tenant_id: int, rows: list, created_by: int | None) -> Dict[str, Any]:
        """
        Insert opportunities from a pre-validated import payload.

        Rules:
          - MPAN_MPR is stored in Opportunity_Details.mpan_mpr
          - stage_id = 1 (New)
          - tenant-scoped via Opportunity_Details.tenant_id
          - if MPAN already exists in Opportunity_Details -> skip and report
          - partial success allowed; per-row errors returned
          - NO joins to Project_Details or Client_Master
        """
        inserted = 0
        skipped = 0
        errors = []

        for idx, raw in enumerate(rows or []):
            # Accept either preview row shape ({row_number,data,is_valid,...}) or plain dict
            row_number = raw.get('row_number') if isinstance(raw, dict) and raw.get('row_number') else (idx + 1)
            data = raw.get('data') if isinstance(raw, dict) and raw.get('data') else (raw if isinstance(raw, dict) else {})

            # Normalize keys to lowercase for tolerant access
            def get_field(*names):
                for n in names:
                    if not n:
                        continue
                    # try exact key
                    if n in data:
                        return data.get(n)
                    # try uppercase/lower variants
                    low = n.lower()
                    for k in data.keys():
                        if k.lower().strip() == low:
                            return data.get(k)
                return None

            mpan = (get_field('MPAN_MPR', 'mpan_mpr', 'mpan') or '')
            mpan = mpan.strip() if isinstance(mpan, str) else str(mpan)

            if not mpan:
                skipped += 1
                errors.append({'row': row_number, 'error': 'MPAN_MPR missing'})
                logger.warning('import_opportunities_from_import skipped row=%s missing mpan', row_number)
                continue

            # Enforce MPAN uniqueness: check if MPAN already exists in Opportunity_Details for this tenant
            dup_q = '''
                SELECT 1 FROM "StreemLyne_MT"."Opportunity_Details" od
                WHERE od."mpan_mpr" = %s AND od."tenant_id" = %s LIMIT 1
            '''
            try:
                exists = self.db.execute_query(dup_q, (mpan, tenant_id), fetch_one=True)
            except Exception as e:
                logger.exception('import_opportunities_from_import duplicate check failed row=%s mpan=%s: %s', row_number, mpan, e)
                errors.append({'row': row_number, 'mpan': mpan, 'error': 'Duplicate check failed: ' + str(e)})
                skipped += 1
                continue

            if exists:
                skipped += 1
                errors.append({'row': row_number, 'mpan': mpan, 'error': 'MPAN_MPR already exists in the system'})
                logger.info('import_opportunities_from_import skipped existing mpan=%s tenant=%s', mpan, tenant_id)
                continue

            # Ensure default client exists (client_id is NOT NULL)
            default_client_id = self._ensure_default_client(tenant_id)
            if not default_client_id:
                skipped += 1
                errors.append({'row': row_number, 'mpan': mpan, 'error': 'Failed to create default client for tenant'})
                logger.error('import_opportunities_from_import no default client for tenant=%s', tenant_id)
                continue

            # Map fields -> Opportunity_Details columns
            title = get_field('Business_Name', 'business_name', 'client_company_name') or get_field('Contact_Person', 'contact_person') or f'Imported lead {mpan}'
            description = get_field('Notes', 'notes', 'call_summary') or None
            business_name = get_field('Business_Name', 'business_name', 'client_company_name') or None
            contact_person = get_field('Contact_Person', 'contact_person', 'client_contact_name') or None
            tel_number = get_field('Tel_Number', 'phone', 'tel_number', 'telephone') or None
            email = get_field('Email', 'email') or None
            start_date = get_field('Start_Date', 'start_date', 'contract_start_date') or None

            insert_q = '''
                INSERT INTO "StreemLyne_MT"."Opportunity_Details"
                ("tenant_id", "client_id", "mpan_mpr", "opportunity_title", "opportunity_description", "business_name", "contact_person", "tel_number", "email", "start_date", "stage_id", "created_at")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING "opportunity_id"
            '''
            try:
                out = self.db.execute_insert(insert_q, (tenant_id, default_client_id, mpan, title, description, business_name, contact_person, tel_number, email, start_date, 1), returning=True)
                if out and out.get('opportunity_id'):
                    inserted += 1
                    logger.info('import_opportunities_from_import inserted opportunity_id=%s mpan=%s', out.get('opportunity_id'), mpan)
                else:
                    skipped += 1
                    errors.append({'row': row_number, 'mpan': mpan, 'error': 'Insert returned no id'})
            except Exception as e:
                logger.exception('import_opportunities_from_import insert failed row=%s mpan=%s: %s', row_number, mpan, e)
                skipped += 1
                errors.append({'row': row_number, 'mpan': mpan, 'error': 'DB insert failed: ' + str(e)})
                # Continue with next row (partial success allowed)
                continue

        return {'inserted': inserted, 'skipped': skipped, 'errors': errors}

    def update_lead_status(self, tenant_id: int, opportunity_id: int, stage_id: int) -> Optional[Dict[str, Any]]:
        """
        Update lead status (stage_id) with tenant isolation
        
        Args:
            tenant_id: Tenant identifier
            opportunity_id: Opportunity identifier
            stage_id: New stage ID to set
        
        Returns:
            Dict with updated opportunity_id and stage_id, or None if not found/not owned
        """
        query = """
            UPDATE "StreemLyne_MT"."Opportunity_Details"
            SET "stage_id" = %s
            WHERE "opportunity_id" = %s AND "tenant_id" = %s
            RETURNING "opportunity_id", "stage_id"
        """
        
        try:
            result = self.db.execute_query(query, (stage_id, opportunity_id, tenant_id), fetch_one=True)
            if result:
                logger.info('Updated lead %s to stage %s for tenant %s', opportunity_id, stage_id, tenant_id)
            else:
                logger.warning('Lead %s not found or not owned by tenant %s', opportunity_id, tenant_id)
            return result
        except Exception as e:
            logger.exception('Error updating lead status: %s', e)
            return None
    
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

        Fields returned (strict):
          - opportunity_id
          - business_name
          - contact_person
          - tel_number
          - email
          - mpan_mpr
          - start_date
          - stage_id
          - stage_name
          - created_at

        Sorting: latest first (created_at DESC)
        Uses ONLY Opportunity_Details table - NO Project_Details or Client_Master joins
        """
        # Base query: use Opportunity_Details columns directly, tenant-filter by od.tenant_id
        query = '''
            SELECT
                od."opportunity_id",
                COALESCE(od."business_name", od."opportunity_title") AS business_name,
                od."contact_person",
                od."tel_number",
                od."email",
                od."mpan_mpr",
                od."start_date",
                NULL AS end_date,
                od."stage_id",
                sm."stage_name",
                od."created_at"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            WHERE od."tenant_id" = %s
        '''

        params = [tenant_id]
        # support an optional stage_id filter (controller already extracts it)
        if filters and isinstance(filters, dict) and filters.get('stage_id'):
            query += ' AND od."stage_id" = %s'
            params.append(int(filters.get('stage_id')))

        query += ' ORDER BY od."created_at" DESC'

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
                    'tel_number': r.get('tel_number'),
                    'email': r.get('email'),
                    'mpan_mpr': r.get('mpan_mpr'),
                    'start_date': r.get('start_date').isoformat() if getattr(r.get('start_date'), 'isoformat', None) else (r.get('start_date') or None),
                    'end_date': r.get('end_date').isoformat() if getattr(r.get('end_date'), 'isoformat', None) else (r.get('end_date') or None),
                    'stage_id': r.get('stage_id'),
                    'stage_name': r.get('stage_name'),
                    'created_at': r.get('created_at').isoformat() if getattr(r.get('created_at'), 'isoformat', None) else (r.get('created_at') or None),
                })
            return out
        except Exception as e:
            logger.exception('get_leads_list failed for tenant=%s: %s', tenant_id, e)
            return []
