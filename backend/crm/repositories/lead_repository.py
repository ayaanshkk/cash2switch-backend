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
                um."user_name" as assigned_to_name,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE cm."tenant_id" = %s
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
                um."user_name" as assigned_to_name,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE cm."tenant_id" = %s
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
                um."user_name" as assigned_to_name,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
            LEFT JOIN "StreemLyne_MT"."User_Master" um ON od."opportunity_owner_employee_id" = um."user_id"
            WHERE cm."tenant_id" = %s
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
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            WHERE cm."tenant_id" = %s
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
        Update an existing lead
        
        Args:
            opportunity_id: Opportunity identifier
            tenant_id: Tenant identifier
            lead_data: Updated lead information
        
        Returns:
            Updated lead record
        """
        # Build dynamic update query based on provided fields
        update_fields = []
        params = []
        
        if 'opportunity_title' in lead_data and lead_data['opportunity_title'] is not None:
            update_fields.append('"opportunity_title" = %s')
            params.append(lead_data['opportunity_title'])
        
        if 'opportunity_description' in lead_data and lead_data['opportunity_description'] is not None:
            update_fields.append('"opportunity_description" = %s')
            params.append(lead_data['opportunity_description'])
        
        if 'stage_id' in lead_data and lead_data['stage_id'] is not None:
            update_fields.append('"stage_id" = %s')
            params.append(lead_data['stage_id'])
        
        if 'opportunity_value' in lead_data and lead_data['opportunity_value'] is not None:
            update_fields.append('"opportunity_value" = %s')
            params.append(lead_data['opportunity_value'])
        
        if 'opportunity_owner_employee_id' in lead_data and lead_data['opportunity_owner_employee_id'] is not None:
            update_fields.append('"opportunity_owner_employee_id" = %s')
            params.append(lead_data['opportunity_owner_employee_id'])
        
        if not update_fields:
            print("No fields to update")
            return self.get_lead_by_id(tenant_id, opportunity_id)
        
        # Validate tenant ownership through client_id
        query = f"""
            UPDATE "StreemLyne_MT"."Opportunity_Details" od
            SET {', '.join(update_fields)}
            FROM "StreemLyne_MT"."Client_Master" cm
            WHERE od."client_id" = cm."client_id"
            AND cm."tenant_id" = %s
            AND od."opportunity_id" = %s
            RETURNING od.*
        """
        
        params.extend([tenant_id, opportunity_id])
        
        try:
            result = self.db.execute_query(query, tuple(params), fetch_one=True)
            return result
        except Exception as e:
            print(f"Error updating lead: {e}")
            import traceback
            traceback.print_exc()
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
        # Validate tenant ownership through client_id before deletion
        query = """
            DELETE FROM "StreemLyne_MT"."Opportunity_Details" od
            USING "StreemLyne_MT"."Client_Master" cm
            WHERE od."client_id" = cm."client_id"
            AND cm."tenant_id" = %s
            AND od."opportunity_id" = %s
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
        Atomically create a Client_Master row and an Opportunity_Details row in one DB transaction.
        - Returns { 'client': {...}, 'opportunity': {...} } on success
        - Returns None on failure (caller should interpret and return appropriate HTTP error)

        This uses the DB connection/transaction when available; falls back to separate
        calls (non-atomic) when running with the local stub.
        """
        # If running without a real DB connection, fall back to existing behavior
        try:
            with self.db.get_connection() as conn:
                # When stubbed, conn will be None — fall back
                if conn is None:
                    # Best-effort non-atomic fallback (useful for unit tests / local dev)
                    client = self.create_client(tenant_id, client_data)
                    if not client:
                        return None
                    lead_data['client_id'] = client.get('client_id')
                    opportunity = self.create_lead(tenant_id, lead_data)
                    return {'client': client, 'opportunity': opportunity}

                with conn.cursor() as cur:
                    # Insert client
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

                    client_id = client_row.get('client_id')

                    # Determine stage_id (use provided or default to first Stage_Master)
                    stage_id = lead_data.get('stage_id')
                    if stage_id is None:
                        cur.execute('SELECT "stage_id" FROM "StreemLyne_MT"."Stage_Master" ORDER BY "stage_id" LIMIT 1')
                        s = cur.fetchone()
                        stage_id = s.get('stage_id') if s else None

                    # Insert opportunity
                    insert_opp_sql = (
                        'INSERT INTO "StreemLyne_MT"."Opportunity_Details" '
                        '("client_id", "opportunity_title", "opportunity_description", "stage_id", "opportunity_value", "opportunity_owner_employee_id", "created_at") '
                        'VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING *'
                    )
                    cur.execute(
                        insert_opp_sql,
                        (
                            client_id,
                            lead_data.get('opportunity_title'),
                            lead_data.get('opportunity_description', ''),
                            stage_id,
                            lead_data.get('opportunity_value', 0),
                            lead_data.get('opportunity_owner_employee_id')
                        )
                    )
                    opp_row = cur.fetchone()

                    # Commit transaction and return normalized dicts
                    conn.commit()
                    return {
                        'client': dict(client_row),
                        'opportunity': dict(opp_row) if opp_row else None
                    }
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
                cm."client_contact_name" AS name,
                cm."client_company_name" AS business_name,
                cm."client_contact_name" AS contact_person,
                cm."client_phone" AS tel_number,
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
