"""Secured cron trigger for renewal customer emails."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from flask import Blueprint, jsonify, request

from backend.services.renewal_email_service import run_renewal_email_campaign

logger = logging.getLogger(__name__)

renewal_email_bp = Blueprint("renewal_email", __name__)


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
