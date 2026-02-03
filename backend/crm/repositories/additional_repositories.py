# -*- coding: utf-8 -*-
"""
Additional CRM Repositories
Handles database operations for supporting tables
"""
import logging
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class RoleRepository:
    """Repository for Role_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_roles(self, tenant_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all roles (system + tenant-specific)
        
        Args:
            tenant_id: Optional tenant filter
        
        Returns:
            List of role records
        """
        if tenant_id:
            query = """
                SELECT * FROM "StreemLyne_MT"."Role_Master"
                WHERE "Tenant_id" IS NULL OR "Tenant_id" = %s
                ORDER BY "role_name"
            """
            params = (tenant_id,)
        else:
            query = 'SELECT * FROM "StreemLyne_MT"."Role_Master" ORDER BY "role_name"'
            params = None
        
        try:
            return self.db.execute_query(query, params)
        except Exception as e:
            print(f"Error fetching roles: {e}")
            return []


class StageRepository:
    """
    Repository for Stage_Master table.
    Real schema: stage_id, stage_name, stage_description, preceding_stage_id, stage_type.
    """

    # Map optional pipeline_type (API) to stage_type (DB integer) for filtering.
    _PIPELINE_TYPE_TO_STAGE_TYPE = {"lead": 1, "sales": 1, "training": 2}

    def __init__(self):
        self.db = get_supabase_client()

    def get_all_stages(self, pipeline_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all pipeline stages using real columns:
        stage_id, stage_name, stage_description, preceding_stage_id, stage_type.
        Ordered by stage_id. Optional filter by stage_type when pipeline_type is provided.
        """
        stage_type_filter = None
        if pipeline_type:
            stage_type_filter = self._PIPELINE_TYPE_TO_STAGE_TYPE.get(
                (pipeline_type or "").strip().lower()
            )

        if stage_type_filter is not None:
            query = """
                SELECT "stage_id", "stage_name", "stage_description",
                       "preceding_stage_id", "stage_type"
                FROM "StreemLyne_MT"."Stage_Master"
                WHERE "stage_type" = %s
                ORDER BY "stage_id"
            """
            params: Optional[tuple] = (stage_type_filter,)
        else:
            query = """
                SELECT "stage_id", "stage_name", "stage_description",
                       "preceding_stage_id", "stage_type"
                FROM "StreemLyne_MT"."Stage_Master"
                ORDER BY "stage_id"
            """
            params = None

        try:
            rows = self.db.execute_query(query, params)
            logger.info("StageRepository.get_all_stages: found %s stage(s)", len(rows) if rows else 0)
            return rows if rows else []
        except Exception as e:
            logger.exception("Error fetching stages: %s", e)
            return []

    def ensure_default_stage(self) -> Optional[Dict[str, Any]]:
        """
        Ensure at least one stage exists; return it. If none exist, insert default stage
        using real columns: stage_name='Lead', stage_type=1, preceding_stage_id=NULL,
        stage_description='Default Lead Stage'. Returns None only if no stage exists
        and insert failed (e.g. stub DB).
        """
        try:
            query = """
                SELECT "stage_id", "stage_name", "stage_description",
                       "preceding_stage_id", "stage_type"
                FROM "StreemLyne_MT"."Stage_Master"
                ORDER BY "stage_id"
                LIMIT 1
            """
            stages = self.db.execute_query(query)
            if stages and len(stages) > 0:
                logger.info(
                    "StageRepository.ensure_default_stage: using existing stage stage_id=%s stage_name=%s",
                    stages[0].get("stage_id"),
                    stages[0].get("stage_name"),
                )
                return stages[0]

            ins = """
                INSERT INTO "StreemLyne_MT"."Stage_Master"
                ("stage_name", "stage_description", "preceding_stage_id", "stage_type")
                VALUES (%s, %s, %s, %s)
                RETURNING "stage_id", "stage_name", "stage_description", "preceding_stage_id", "stage_type"
            """
            row = self.db.execute_insert(
                ins,
                ("Lead", "Default Lead Stage", None, 1),
                returning=True,
            )
            if row:
                logger.info(
                    "StageRepository.ensure_default_stage: created default stage stage_id=%s stage_name=Lead",
                    row.get("stage_id"),
                )
                return row
        except Exception as e:
            logger.exception("StageRepository.ensure_default_stage failed: %s", e)
        return None

    def get_stage_by_name(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a stage by exact name (case-insensitive).

        Args:
            stage_name: Stage name to look up

        Returns:
            Stage record or None if not found
        """
        if not stage_name:
            return None

        query = """
            SELECT "stage_id", "stage_name", "stage_description",
                   "preceding_stage_id", "stage_type"
            FROM "StreemLyne_MT"."Stage_Master"
            WHERE LOWER("stage_name") = LOWER(%s)
            ORDER BY "stage_id"
            LIMIT 1
        """
        try:
            return self.db.execute_query(query, (stage_name,), fetch_one=True)
        except Exception as e:
            logger.exception("StageRepository.get_stage_by_name failed: %s", e)
            return None


class ServiceRepository:
    """Repository for Services_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_services(self, tenant_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all services
        
        Args:
            tenant_id: Optional tenant filter
        
        Returns:
            List of service records
        """
        if tenant_id:
            query = """
                SELECT * FROM "StreemLyne_MT"."Services_Master"
                WHERE "Tenant_id" IS NULL OR "Tenant_id" = %s
                ORDER BY "service_name"
            """
            params = (tenant_id,)
        else:
            query = 'SELECT * FROM "StreemLyne_MT"."Services_Master" ORDER BY "service_name"'
            params = None
        
        try:
            return self.db.execute_query(query, params)
        except Exception as e:
            print(f"Error fetching services: {e}")
            return []


class SupplierRepository:
    """Repository for Supplier_Master table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_suppliers(self, tenant_id: int) -> List[Dict[str, Any]]:
        """
        Get all suppliers for a tenant
        
        Args:
            tenant_id: Tenant identifier
        
        Returns:
            List of supplier records
        """
        query = """
            SELECT * FROM "StreemLyne_MT"."Supplier_Master"
            WHERE "Tenant_id" = %s
            ORDER BY "supplier_name"
        """
        
        try:
            return self.db.execute_query(query, (tenant_id,))
        except Exception as e:
            print(f"Error fetching suppliers: {e}")
            return []


class InteractionRepository:
    """Repository for Client_Interactions table"""
    
    def __init__(self):
        self.db = get_supabase_client()
    
    def get_all_interactions(self, tenant_id: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all client interactions for a tenant (via Client_Master)
        
        Args:
            tenant_id: Tenant identifier
            filters: Optional filters (client_id, etc.)
        
        Returns:
            List of interaction records
        """
        query = """
            SELECT 
                ci.*,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Client_Interactions" ci
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON ci."client_id" = cm."client_id"
            WHERE cm."tenant_id" = %s
        """
        params = [tenant_id]
        
        # Apply filters if provided
        if filters:
            if filters.get('client_id'):
                query += ' AND ci."client_id" = %s'
                params.append(filters['client_id'])
        
        query += ' ORDER BY ci."contact_date" DESC'
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            print(f"Error fetching interactions: {e}")
            return []
    
    def get_interactions_by_opportunity(self, tenant_id: int, opportunity_id: int) -> List[Dict[str, Any]]:
        """
        Get all interactions for the client linked to the given opportunity.
        """
        client_query = """
            SELECT od."client_id" FROM "StreemLyne_MT"."Opportunity_Details" od
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
            WHERE cm."tenant_id" = %s AND od."opportunity_id" = %s
            LIMIT 1
        """
        try:
            row = self.db.execute_query(client_query, (tenant_id, opportunity_id), fetch_one=True)
            if not row:
                return []
            return self.get_interactions_by_client(tenant_id, row['client_id'])
        except Exception as e:
            print(f"Error fetching interactions by opportunity: {e}")
            return []

    def get_interactions_by_client(self, tenant_id: int, client_id: int) -> List[Dict[str, Any]]:
        """
        Get all interactions for a specific client
        
        Args:
            tenant_id: Tenant identifier
            client_id: Client identifier
        
        Returns:
            List of interaction records
        """
        query = """
            SELECT 
                ci.*,
                cm."client_company_name",
                cm."client_contact_name"
            FROM "StreemLyne_MT"."Client_Interactions" ci
            INNER JOIN "StreemLyne_MT"."Client_Master" cm ON ci."client_id" = cm."client_id"
            WHERE cm."tenant_id" = %s
            AND ci."client_id" = %s
            ORDER BY ci."contact_date" DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, client_id))
        except Exception as e:
            print(f"Error fetching interactions by client: {e}")
            return []
    
    def create_call_summary(self, tenant_id: int, client_id: int, call_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a call summary/interaction record
        
        Args:
            tenant_id: Tenant identifier
            client_id: Client identifier
            call_data: Call information (call_status, call_result, remarks, next_follow_up_date)
        
        Returns:
            Created interaction record
        """
        # Validate client belongs to tenant
        client_check_query = """
            SELECT "client_id" FROM "StreemLyne_MT"."Client_Master"
            WHERE "client_id" = %s AND "tenant_id" = %s
        """
        
        try:
            client = self.db.execute_query(client_check_query, (client_id, tenant_id), fetch_one=True)
            if not client:
                print(f"Error: client_id {client_id} does not belong to tenant {tenant_id}")
                return None
            
            # Map call_data to Client_Interactions columns:
            # call_status -> contact_method (smallint: 1=Phone, 2=Email, 3=Meeting, etc.)
            # call_result/remarks -> notes
            # next_follow_up_date -> reminder_date
            
            contact_method = call_data.get('call_status', 1)  # Default to Phone (1)
            if isinstance(contact_method, str):
                # Map string to int: "Phone"=1, "Email"=2, "Meeting"=3, "Other"=4
                method_map = {"Phone": 1, "Email": 2, "Meeting": 3, "Other": 4}
                contact_method = method_map.get(contact_method, 1)
            
            notes = call_data.get('remarks', '')
            if call_data.get('call_result'):
                notes = f"{call_data.get('call_result')}\n{notes}".strip()
            
            query = """
                INSERT INTO "StreemLyne_MT"."Client_Interactions"
                ("client_id", "contact_date", "contact_method", "notes", "reminder_date", "created_at")
                VALUES (%s, CURRENT_DATE, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING *
            """
            
            return self.db.execute_insert(
                query,
                (
                    client_id,
                    contact_method,
                    notes,
                    call_data.get('next_follow_up_date')
                ),
                returning=True
            )
        except Exception as e:
            print(f"Error creating call summary: {e}")
            import traceback
            traceback.print_exc()
            return None
