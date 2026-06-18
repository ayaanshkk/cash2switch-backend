"""Secured cron trigger for renewal customer emails."""

from __future__ import annotations

import hmac
import logging
import os
from datetime import date, datetime
from functools import wraps
from typing import Optional

from flask import Blueprint, g, jsonify, request
from sqlalchemy import text

from backend.db import SessionLocal
from backend.routes.auth_helpers import token_required
from backend.services.renewal_email_service import run_renewal_email_campaign

logger = logging.getLogger(__name__)

renewal_email_bp = Blueprint("renewal_email", __name__)


def _admin_required(f):
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        user = getattr(g, "user", None)
        role_values = []
        raw_role = getattr(user, "role", None)
        if raw_role:
            role_values.append(str(raw_role).lower())
        raw_roles = getattr(user, "roles", None) or []
        role_values.extend(str(role).lower() for role in raw_roles if role)

        if not any("admin" in role for role in role_values):
            return jsonify({"error": "Admin access required"}), 403

        return f(*args, **kwargs)

    return decorated


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(row):
    return {key: _json_value(value) for key, value in dict(row).items()}


def _current_tenant_id_text() -> Optional[str]:
    user = getattr(g, "user", None)
    tenant_id = getattr(user, "tenant_id", None)
    if tenant_id is None:
        tenant_id = request.headers.get("X-Tenant-ID")
    if tenant_id is None or str(tenant_id).strip() == "":
        return None
    return str(tenant_id).strip()


def _admin_logs_filters():
    tenant_id_text = _current_tenant_id_text()
    params = {}
    where = []

    if tenant_id_text:
        where.append("TRIM(CAST(cm.tenant_id AS TEXT)) = :tenant_id_text")
        params["tenant_id_text"] = tenant_id_text

    search = (request.args.get("search") or "").strip().lower()
    if search:
        where.append(
            """
            (
              LOWER(COALESCE(rel.recipient_email, '')) LIKE :search
              OR LOWER(COALESCE(cm.client_company_name, '')) LIKE :search
              OR LOWER(COALESCE(cm.client_contact_name, '')) LIKE :search
              OR LOWER(COALESCE(em.employee_name, '')) LIKE :search
              OR LOWER(COALESCE(rel.provider_message_id, '')) LIKE :search
            )
            """
        )
        params["search"] = f"%{search}%"

    status = (request.args.get("status") or "").strip()
    if status:
        where.append("LOWER(rel.status) = LOWER(:status)")
        params["status"] = status

    bucket = (request.args.get("bucket") or "").strip()
    if bucket:
        where.append("rel.bucket_key = :bucket")
        params["bucket"] = bucket

    date_from = (request.args.get("date_from") or "").strip()
    if date_from:
        where.append("rel.created_at >= CAST(:date_from AS timestamptz)")
        params["date_from"] = date_from

    date_to = (request.args.get("date_to") or "").strip()
    if date_to:
        where.append("rel.created_at < CAST(:date_to AS timestamptz) + INTERVAL '1 day'")
        params["date_to"] = date_to

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    return where_sql, params


_ADMIN_LOGS_FROM_SQL = """
FROM "StreemLyne_MT"."Renewal_Email_Send_Log" rel
LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm
  ON rel.energy_contract_master_id = ecm.energy_contract_master_id
LEFT JOIN "StreemLyne_MT"."Project_Details" pd
  ON ecm.project_id = pd.project_id
LEFT JOIN "StreemLyne_MT"."Client_Master" cm
  ON pd.client_id = cm.client_id
LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm
  ON ecm.supplier_id = sm.supplier_id
LEFT JOIN "StreemLyne_MT"."Employee_Master" em
  ON COALESCE(pd.assigned_employee_id, cm.assigned_employee_id, pd.employee_id, ecm.employee_id) = em.employee_id
"""


def _cron_secret_ok() -> bool:
    expected = (os.getenv("RENEWAL_EMAIL_CRON_SECRET") or "").strip()
    if not expected:
        return False
    got = (request.headers.get("X-Renewal-Email-Cron-Secret") or "").strip()
    return hmac.compare_digest(expected, got)


@renewal_email_bp.route("/internal/cron/renewal-emails", methods=["POST"])
def cron_renewal_emails():
    """
    Daily job entrypoint. Header: X-Renewal-Email-Cron-Secret (must match RENEWAL_EMAIL_CRON_SECRET).
    Optional JSON body: {"tenant_id": 1} to scope one tenant (testing).
    """
    if not _cron_secret_ok():
        if not (os.getenv("RENEWAL_EMAIL_CRON_SECRET") or "").strip():
            return jsonify({"error": "RENEWAL_EMAIL_CRON_SECRET is not configured; cron is disabled"}), 503
        return jsonify({"error": "Unauthorized"}), 401

    tenant_id: Optional[int] = None
    if request.is_json and request.get_json(silent=True):
        body = request.get_json(silent=True) or {}
        if body.get("tenant_id") is not None:
            try:
                tenant_id = int(body["tenant_id"])
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid tenant_id"}), 400

    try:
        counts = run_renewal_email_campaign(tenant_id=tenant_id)
        return jsonify({"success": True, "counts": counts}), 200
    except Exception as e:
        logger.exception("cron_renewal_emails failed: %s", e)
        return jsonify({"error": str(e)}), 500


@renewal_email_bp.route("/internal/admin/renewal-email-logs", methods=["GET"])
@renewal_email_bp.route("/api/internal/admin/renewal-email-logs", methods=["GET"])
@renewal_email_bp.route("/api/crm/renewal-email-logs", methods=["GET"])
@_admin_required
def admin_renewal_email_logs():
    page = max(int(request.args.get("page", 1) or 1), 1)
    page_size = min(max(int(request.args.get("page_size", 25) or 25), 1), 100)
    offset = (page - 1) * page_size

    where_sql, params = _admin_logs_filters()
    params.update({"limit": page_size, "offset": offset})

    session = SessionLocal()
    try:
        total = session.execute(
            text(f'SELECT COUNT(*) AS total {_ADMIN_LOGS_FROM_SQL} {where_sql}'),
            params,
        ).scalar_one()

        rows = session.execute(
            text(
                f"""
                SELECT
                  rel.renewal_email_send_log_id AS id,
                  rel.tenant_id,
                  rel.created_at AS sent_at,
                  rel.status,
                  rel.bucket_key,
                  rel.recipient_email,
                  rel.provider_message_id,
                  rel.error_message,
                  rel.contract_end_date,
                  rel.energy_contract_master_id,
                  ecm.service_id,
                  CASE WHEN ecm.service_id = 2 THEN 'Water' ELSE 'Electricity' END AS service_label,
                  ecm.project_id,
                  cm.client_id,
                  cm.client_company_name AS business_name,
                  cm.client_contact_name AS customer_name,
                  TRIM(CONCAT_WS(', ', NULLIF(cm.address, ''), NULLIF(cm.post_code, ''))) AS site_address,
                  sm.supplier_company_name AS supplier_name,
                  em.employee_name AS advisor_name,
                  em.phone AS advisor_phone,
                  (rel.contract_end_date - CURRENT_DATE) AS days_remaining
                {_ADMIN_LOGS_FROM_SQL}
                {where_sql}
                ORDER BY rel.created_at DESC, rel.renewal_email_send_log_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

        return jsonify(
            {
                "items": [_row_to_dict(row) for row in rows],
                "page": page,
                "page_size": page_size,
                "total": int(total or 0),
            }
        ), 200
    except Exception as e:
        logger.exception("admin_renewal_email_logs failed: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            session.close()
        except Exception as close_err:
            logger.warning("Session close failed after admin_renewal_email_logs: %s", close_err)


@renewal_email_bp.route("/internal/admin/renewal-email-logs/summary", methods=["GET"])
@renewal_email_bp.route("/api/internal/admin/renewal-email-logs/summary", methods=["GET"])
@renewal_email_bp.route("/api/crm/renewal-email-logs/summary", methods=["GET"])
@_admin_required
def admin_renewal_email_logs_summary():
    where_sql, params = _admin_logs_filters()
    scoped_where = where_sql if where_sql else "WHERE 1=1"

    session = SessionLocal()
    try:
        counts = session.execute(
            text(
                f"""
                SELECT
                  COUNT(*) FILTER (
                    WHERE LOWER(rel.status) = 'sent'
                    AND rel.created_at >= CURRENT_DATE
                  ) AS sent_today,
                  COUNT(*) FILTER (
                    WHERE LOWER(rel.status) = 'sent'
                    AND rel.created_at >= NOW() - INTERVAL '7 days'
                  ) AS sent_last_7_days,
                  COUNT(*) FILTER (
                    WHERE LOWER(rel.status) NOT IN ('sent', 'dry_run')
                    AND rel.created_at >= NOW() - INTERVAL '7 days'
                  ) AS failed_last_7_days,
                  COUNT(*) FILTER (WHERE LOWER(rel.status) = 'sent') AS total_sent,
                  COUNT(*) AS total_logged
                {_ADMIN_LOGS_FROM_SQL}
                {scoped_where}
                """
            ),
            params,
        ).mappings().one()

        latest_rows = session.execute(
            text(
                f"""
                SELECT
                  rel.renewal_email_send_log_id AS id,
                  rel.created_at AS sent_at,
                  rel.status,
                  rel.bucket_key,
                  rel.recipient_email,
                  rel.contract_end_date,
                  CASE WHEN ecm.service_id = 2 THEN 'Water' ELSE 'Electricity' END AS service_label,
                  cm.client_company_name AS business_name,
                  cm.client_contact_name AS customer_name,
                  em.employee_name AS advisor_name
                {_ADMIN_LOGS_FROM_SQL}
                {scoped_where}
                ORDER BY rel.created_at DESC, rel.renewal_email_send_log_id DESC
                LIMIT 6
                """
            ),
            params,
        ).mappings().all()

        return jsonify(
            {
                **_row_to_dict(counts),
                "latest": [_row_to_dict(row) for row in latest_rows],
            }
        ), 200
    except Exception as e:
        logger.exception("admin_renewal_email_logs_summary failed: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            session.close()
        except Exception as close_err:
            logger.warning("Session close failed after admin_renewal_email_logs_summary: %s", close_err)
