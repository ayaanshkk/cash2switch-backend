"""
Cleansing Routes - backend/routes/cleansing_routes.py

Handles records flagged as "Invalid Number" or "Incorrect Supplier".
These are surfaced in the /cleansing frontend page and can be:
  - Fixed (correct phone number or supplier, then restored to active)
  - Deleted permanently
  - Annotated with notes

Routes:
  GET  /api/crm/cleansing           – list all cleansing records (both sources)
  POST /api/crm/leads/<id>/cleanse  – action on a CRM lead
  POST /api/energy-clients/<id>/cleanse – action on an energy client
"""

from flask import Blueprint, request, jsonify, g
from datetime import datetime
from functools import wraps

cleansing_bp = Blueprint("cleansing", __name__)

# ─── Auth helpers (re-use your existing pattern) ──────────────────────────────

def _get_tenant_id():
    """Pull tenant_id from Flask g (set by tenant_from_jwt) or request.current_user."""
    if hasattr(g, "tenant_id") and g.tenant_id:
        return g.tenant_id
    user = getattr(request, "current_user", None)
    if user:
        return getattr(user, "tenant_id", None) or getattr(user, "Tenant_ID", None)
    return None


# ─── Constants ────────────────────────────────────────────────────────────────

CLEANSING_STATUSES = {"Invalid Number", "Incorrect Supplier"}


# ═══════════════════════════════════════════════════════════════════════════════
# GET  /api/crm/cleansing
# Returns all records from both sources that are in a cleansing status.
# ═══════════════════════════════════════════════════════════════════════════════

def register_get_cleansing(crm_bp, token_required, tenant_from_jwt):
    """
    Call this from crm_routes.py to attach the GET /api/crm/cleansing endpoint
    to the existing crm_bp Blueprint, e.g.:

        from backend.routes.cleansing_routes import register_get_cleansing
        register_get_cleansing(crm_bp, token_required, tenant_from_jwt)
    """

    @crm_bp.route("/cleansing", methods=["GET"])
    @token_required
    @tenant_from_jwt
    def get_cleansing():
        """
        GET /api/crm/cleansing
        Returns records from:
          1. Opportunity_Details (CRM leads) where stage maps to cleansing statuses
          2. Client_Master / Energy clients where deleted_reason is a cleansing status

        Response:
          { records: [...], total: int }
        """
        from backend.crm.supabase_client import get_supabase_client

        try:
            tenant_id = _get_tenant_id()
            if not tenant_id:
                return jsonify({"error": "Missing tenant"}), 401

            db = get_supabase_client()
            records = []

            # ── 1. CRM Leads: stage_name matches a cleansing reason ─────────────
            lead_rows = db.execute_query(
                """
                SELECT
                    od.opportunity_id        AS id,
                    COALESCE(od.business_name, od.opportunity_title) AS business_name,
                    od.contact_person,
                    od.tel_number,
                    od.mpan_mpr,
                    sup.supplier_company_name AS supplier_name,
                    od.end_date,
                    od.address,
                    sm.stage_name            AS cleansing_reason,
                    od.updated_at            AS flagged_at,
                    od.comments              AS notes
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master"    sm  ON od.stage_id    = sm.stage_id
                LEFT JOIN "StreemLyne_MT"."Supplier_Master" sup ON od.supplier_id = sup.supplier_id
                WHERE od.tenant_id = %s
                  AND sm.stage_name IN ('Invalid Number', 'Incorrect Supplier')
                ORDER BY od.updated_at DESC
                """,
                (tenant_id,),
            )

            for r in lead_rows or []:
                records.append(
                    {
                        "id": r.get("id"),
                        "business_name": r.get("business_name") or "Unknown",
                        "contact_person": r.get("contact_person"),
                        "tel_number": r.get("tel_number"),
                        "mpan_mpr": r.get("mpan_mpr"),
                        "supplier_name": r.get("supplier_name"),
                        "end_date": r.get("end_date").isoformat() if r.get("end_date") else None,
                        "address": r.get("address"),
                        "cleansing_reason": r.get("cleansing_reason"),
                        "flagged_at": r.get("flagged_at").isoformat() if r.get("flagged_at") else None,
                        "notes": r.get("notes"),
                        "source": "lead",
                    }
                )

            # ── 2. Energy Clients: is_deleted=True, deleted_reason is cleansing ─
            try:
                from backend.models import Client_Master, Energy_Contract_Master, Project_Details, Supplier_Master
                from backend.db import SessionLocal

                session = SessionLocal()
                try:
                    client_rows = (
                        session.query(
                            Client_Master,
                            Energy_Contract_Master,
                            Supplier_Master,
                        )
                        .join(Project_Details, Client_Master.client_id == Project_Details.client_id)
                        .outerjoin(
                            Energy_Contract_Master,
                            Project_Details.project_id == Energy_Contract_Master.project_id,
                        )
                        .outerjoin(
                            Supplier_Master,
                            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id,
                        )
                        .filter(
                            Client_Master.tenant_id == tenant_id,
                            Client_Master.is_deleted == True,
                            Client_Master.deleted_reason.in_(CLEANSING_STATUSES),
                        )
                        .all()
                    )

                    for client, contract, supplier in client_rows:
                        records.append(
                            {
                                "id": client.client_id,
                                "business_name": client.client_company_name or "Unknown",
                                "contact_person": getattr(client, "client_contact_name", None),
                                "tel_number": getattr(client, "client_phone", None),
                                "mpan_mpr": getattr(contract, "mpan_mpr", None) if contract else None,
                                "supplier_name": supplier.supplier_company_name if supplier else None,
                                "end_date": (
                                    contract.contract_end_date.isoformat()
                                    if contract and contract.contract_end_date
                                    else None
                                ),
                                "address": getattr(client, "address", None),
                                "cleansing_reason": client.deleted_reason,
                                "flagged_at": (
                                    client.deleted_at.isoformat() if client.deleted_at else None
                                ),
                                "notes": getattr(client, "deleted_notes", None),
                                "source": "energy_client",
                            }
                        )
                finally:
                    session.close()

            except Exception as ec_err:
                # Energy client import may fail in CRM-only deployments — log and continue
                import logging
                logging.getLogger(__name__).warning(
                    "Could not load energy clients for cleansing: %s", ec_err
                )

            # Sort combined list by flagged_at desc (nulls last)
            records.sort(key=lambda x: x.get("flagged_at") or "", reverse=True)

            return jsonify({"records": records, "total": len(records)}), 200

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/crm/leads/<opportunity_id>/cleanse
# Actions: fix | delete | notes
# ═══════════════════════════════════════════════════════════════════════════════

def register_lead_cleanse(crm_bp, token_required, tenant_from_jwt):
    """
    Call from crm_routes.py:
        from backend.routes.cleansing_routes import register_lead_cleanse
        register_lead_cleanse(crm_bp, token_required, tenant_from_jwt)
    """

    @crm_bp.route("/leads/<int:opportunity_id>/cleanse", methods=["POST", "OPTIONS"])
    @token_required
    @tenant_from_jwt
    def lead_cleanse_action(opportunity_id):
        """
        POST /api/crm/leads/<opportunity_id>/cleanse
        Body:
          {
            "action": "fix" | "delete" | "notes",
            "tel_number":   "...",    // fix: Invalid Number
            "new_supplier": "...",    // fix: Incorrect Supplier
            "notes":        "..."     // all actions (optional for fix/delete)
          }
        """
        if request.method == "OPTIONS":
            return jsonify({}), 200

        from backend.crm.supabase_client import get_supabase_client

        try:
            tenant_id = _get_tenant_id()
            if not tenant_id:
                return jsonify({"error": "Missing tenant"}), 401

            data = request.get_json(force=True, silent=True) or {}
            action = data.get("action")

            if action not in ("fix", "delete", "notes"):
                return jsonify({"error": "action must be fix, delete, or notes"}), 400

            db = get_supabase_client()

            # Resolve real opportunity_id
            lead = db.execute_query(
                """
                SELECT opportunity_id, stage_id
                FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE tenant_id = %s
                  AND ("tenant_lead_id" = %s OR opportunity_id = %s)
                LIMIT 1
                """,
                (tenant_id, opportunity_id, opportunity_id),
                fetch_one=True,
            )

            if not lead:
                return jsonify({"error": "Lead not found"}), 404

            real_id = lead["opportunity_id"]

            # ── DELETE ──────────────────────────────────────────────────────────
            if action == "delete":
                db.execute_update(
                    """
                    DELETE FROM "StreemLyne_MT"."Opportunity_Details"
                    WHERE opportunity_id = %s AND tenant_id = %s
                    """,
                    (real_id, tenant_id),
                )
                return jsonify({"success": True, "message": "Lead permanently deleted"}), 200

            # ── NOTES ───────────────────────────────────────────────────────────
            if action == "notes":
                notes = (data.get("notes") or "").strip()
                if not notes:
                    return jsonify({"error": "Notes cannot be empty"}), 400

                db.execute_update(
                    """
                    UPDATE "StreemLyne_MT"."Opportunity_Details"
                    SET comments = CASE
                          WHEN comments IS NULL OR comments = '' THEN %s
                          ELSE comments || E'\n' || %s
                        END
                    WHERE opportunity_id = %s AND tenant_id = %s
                    """,
                    (notes, notes, real_id, tenant_id),
                )
                return jsonify({"success": True, "message": "Note added"}), 200

            # ── FIX ─────────────────────────────────────────────────────────────
            tel_number = data.get("tel_number", "").strip()
            new_supplier = data.get("new_supplier", "").strip()
            notes = (data.get("notes") or "").strip()

            update_fields = {}

            if tel_number:
                update_fields["tel_number"] = tel_number

            if new_supplier:
                # Look up or skip — caller provides display name
                sup = db.execute_query(
                    """
                    SELECT supplier_id FROM "StreemLyne_MT"."Supplier_Master"
                    WHERE LOWER(supplier_company_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (new_supplier,),
                    fetch_one=True,
                )
                if sup:
                    update_fields["supplier_id"] = sup["supplier_id"]

            if not update_fields:
                return jsonify({"error": "No valid fix data provided"}), 400

            # Move back to default active stage (stage_id = 1)
            update_fields["stage_id"] = 1

            if notes:
                update_fields["notes"] = notes

            set_clause = ", ".join(f'"{k}" = %s' for k in update_fields)
            params = list(update_fields.values()) + [real_id, tenant_id]

            db.execute_update(
                f'UPDATE "StreemLyne_MT"."Opportunity_Details" '
                f"SET {set_clause} "
                f"WHERE opportunity_id = %s AND tenant_id = %s",
                tuple(params),
            )

            return jsonify({"success": True, "message": "Lead fixed and restored"}), 200

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/energy-clients/<client_id>/cleanse
# Mirrors the logic above but for SQLAlchemy-backed energy clients.
# ═══════════════════════════════════════════════════════════════════════════════

def register_energy_client_cleanse(client_interaction_bp, token_required):
    """
    Call from client_interactions_routes.py:

        from backend.routes.cleansing_routes import register_energy_client_cleanse
        register_energy_client_cleanse(client_interaction_bp, token_required)
    """

    @client_interaction_bp.route(
        "/energy-clients/<int:client_id>/cleanse", methods=["POST", "OPTIONS"]
    )
    @token_required
    def energy_client_cleanse_action(client_id):
        """
        POST /api/energy-clients/<client_id>/cleanse
        Body: same shape as the lead cleanse endpoint.
        """
        if request.method == "OPTIONS":
            return jsonify({}), 200

        from backend.models import Client_Master, Energy_Contract_Master, Project_Details, Supplier_Master
        from backend.db import SessionLocal

        user = getattr(request, "current_user", None)
        tenant_id = (
            getattr(user, "tenant_id", None) or getattr(user, "Tenant_ID", None)
            if user
            else None
        )

        session = SessionLocal()
        try:
            data = request.get_json(force=True, silent=True) or {}
            action = data.get("action")

            if action not in ("fix", "delete", "notes"):
                return jsonify({"error": "action must be fix, delete, or notes"}), 400

            query = session.query(Client_Master).filter(
                Client_Master.client_id == client_id,
                Client_Master.deleted_reason.in_(CLEANSING_STATUSES),
            )
            if tenant_id:
                query = query.filter(Client_Master.tenant_id == tenant_id)

            client = query.first()
            if not client:
                return jsonify({"error": "Client not found in cleansing"}), 404

            # ── DELETE ──────────────────────────────────────────────────────────
            if action == "delete":
                # Hard delete — remove interaction history first to avoid FK issues
                from backend.models import Client_Interactions
                session.query(Client_Interactions).filter(
                    Client_Interactions.client_id == client_id
                ).delete()
                session.delete(client)
                session.commit()
                return jsonify({"success": True, "message": "Client permanently deleted"}), 200

            # ── NOTES ───────────────────────────────────────────────────────────
            if action == "notes":
                notes = (data.get("notes") or "").strip()
                if not notes:
                    return jsonify({"error": "Notes cannot be empty"}), 400

                db.execute_update(
                    """
                    UPDATE "StreemLyne_MT"."Opportunity_Details"
                    SET notes = CASE
                          WHEN notes IS NULL OR notes = '' THEN %s
                          ELSE notes || E'\n' || %s
                        END
                    WHERE opportunity_id = %s AND tenant_id = %s
                    """,
                    (notes, notes, real_id, tenant_id),
                )
                return jsonify({"success": True, "message": "Note added"}), 200

            # ── FIX ─────────────────────────────────────────────────────────────
            tel_number = data.get("tel_number", "").strip()
            new_supplier_name = data.get("new_supplier", "").strip()
            notes = (data.get("notes") or "").strip()

            if not tel_number and not new_supplier_name:
                return jsonify({"error": "No valid fix data provided"}), 400

            if tel_number:
                client.client_phone = tel_number

            if new_supplier_name:
                contract = (
                    session.query(Energy_Contract_Master)
                    .join(Project_Details, Project_Details.project_id == Energy_Contract_Master.project_id)
                    .filter(Project_Details.client_id == client_id)
                    .first()
                )
                if contract:
                    supplier = (
                        session.query(Supplier_Master)
                        .filter(
                            Supplier_Master.supplier_company_name.ilike(new_supplier_name)
                        )
                        .first()
                    )
                    if not supplier:
                        supplier = Supplier_Master(
                            supplier_company_name=new_supplier_name,
                            supplier_contact_name=new_supplier_name,
                            supplier_provisions=0,
                            created_at=datetime.utcnow(),
                        )
                        session.add(supplier)
                        session.flush()
                    contract.supplier_id = supplier.supplier_id
                    contract.updated_at = datetime.utcnow()

            # Restore: un-delete the client
            client.is_deleted = False
            client.deleted_at = None
            client.deleted_reason = None

            # Update project status back to active
            project = session.query(Project_Details).filter_by(client_id=client_id).first()
            if project:
                project.status = "Active"

            if notes:
                client.deleted_notes = notes

            session.commit()
            return jsonify({"success": True, "message": "Client fixed and restored"}), 200

        except Exception as e:
            session.rollback()
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
        finally:
            session.close()