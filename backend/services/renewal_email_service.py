"""Scheduled renewal reminder emails: query, bucket, dedupe, send via Resend."""

from __future__ import annotations

import logging
import base64
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import SessionLocal
from backend.models import Renewal_Email_Send_Log
from backend.services.renewal_email_buckets import bucket_for_days_remaining, contract_window_end_dates
from backend.services.renewal_email_whitelist import is_allowed_renewal_recipient, renewal_email_test_whitelist
from backend.services.transactional_mailer import TransactionalMailError, send_resend_email

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", re.I)

_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"
_MARKET_GRAPH_ASSET = Path(__file__).resolve().parent.parent / "static" / "images" / "renewal-market-price-trend.png"

_ADVISOR_DISPLAY_NAMES = {
    "huzaifah": "Zak",
    "haleema": "Hannah",
    "saeed": "Saeed Adam",
    "abu": "Abu",
    "lawrence": "Lawrence",
    "imran": "Ali",
    "faiyaz": "Faiyaz",
    "khalid": "Khalid",
}

_AGGREGATOR_DISPLAY_NAMES = {
    "ucr": "Business Utility Brokers",
    "online/online direct": "Business Energy",
    "business gas": "Business Gas",
    "yu energy direct": "Business Gas",
    "eon next direct": "Business Gas",
    "pozitive direct": "Business Gas",
    "smartest energy": "Business Gas",
    "corona direct": "Business Gas",
    "total energies": "Business Gas",
}

_DEFAULT_MARKET_GRAPH_IMAGE_URL = (
    "https://quickchart.io/chart?width=640&height=280&format=png&c="
    "%7Btype%3A%27line%27%2Cdata%3A%7Blabels%3A%5B%27Jan%27%2C%27Feb%27%2C%27Mar%27%2C%27Apr%27%2C%27May%27%2C%27Jun%27%5D%2C"
    "datasets%3A%5B%7Blabel%3A%27Market%20Price%20Index%27%2Cdata%3A%5B62%2C67%2C71%2C76%2C84%2C91%5D%2C"
    "borderColor%3A%27%231f6feb%27%2CbackgroundColor%3A%27rgba%2831%2C111%2C235%2C0.12%29%27%2Cfill%3Atrue%7D%5D%7D%2C"
    "options%3A%7Blegend%3A%7Bdisplay%3Atrue%7D%2Ctitle%3A%7Bdisplay%3Atrue%2Ctext%3A%27Current%20Market%20Price%20Movement%27%7D%7D%7D"
)


def _renewal_debug_on() -> bool:
    import os

    return os.getenv("RENEWAL_EMAIL_DEBUG", "").lower() in ("1", "true", "yes")


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_ROOT)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _postal_line(row: dict) -> str:
    parts = [row.get("address") or "", row.get("post_code") or ""]
    line = ", ".join(p.strip() for p in parts if p and str(p).strip())
    return line


def _mapped_value(raw: str, mapping: dict[str, str]) -> str:
    key = (raw or "").strip().lower()
    return mapping.get(key, (raw or "").strip())


def _market_graph_image_url() -> str:
    import os

    configured_url = (os.getenv("RENEWAL_EMAIL_MARKET_GRAPH_URL") or "").strip()
    if configured_url:
        return configured_url

    public_base_url = (
        os.getenv("RENEWAL_EMAIL_PUBLIC_BASE_URL")
        or os.getenv("BACKEND_PUBLIC_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or ""
    ).strip()
    if public_base_url:
        return urljoin(public_base_url.rstrip("/") + "/", "static/images/renewal-market-price-trend.png")

    try:
        encoded = base64.b64encode(_MARKET_GRAPH_ASSET.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except OSError:
        logger.warning("Renewal email graph asset not found: %s", _MARKET_GRAPH_ASSET)

    return _DEFAULT_MARKET_GRAPH_IMAGE_URL


def _market_graph_attachments() -> list[dict]:
    if not _MARKET_GRAPH_ASSET.exists():
        logger.warning("Renewal email graph asset not found for attachment: %s", _MARKET_GRAPH_ASSET)
        return []
    encoded = base64.b64encode(_MARKET_GRAPH_ASSET.read_bytes()).decode("ascii")
    return [
        {
            "filename": "renewal-market-price-trend.png",
            "content": encoded,
            "content_type": "image/png",
        }
    ]


def fetch_eligible_contract_rows(
    session,
    anchor: date,
    tenant_id: Optional[int] = None,
    email_allowlist_lower: Optional[Sequence[str]] = None,
) -> List[dict]:
    window_start, window_end = contract_window_end_dates(anchor)
    tenant_clause = (
        "AND TRIM(CAST(cm.tenant_id AS TEXT)) = :tenant_id_text" if tenant_id is not None else ""
    )
    allow_clause = ""
    if email_allowlist_lower:
        keys = ", ".join(f":wl_{i}" for i in range(len(email_allowlist_lower)))
        allow_clause = f"AND LOWER(TRIM(cm.client_email)) IN ({keys})"
    sql = text(
        f"""
        SELECT
            ecm.energy_contract_master_id,
            ecm.contract_end_date,
            ecm.service_id,
            cm.client_id,
            cm.tenant_id,
            TRIM(cm.client_email) AS client_email,
            cm.client_company_name,
            cm.client_contact_name,
            cm.address,
            cm.post_code,
            ecm.aggregator,
            em.employee_name AS assigned_employee_name,
            em.phone AS assigned_employee_phone,
            sm.supplier_company_name AS supplier_name
        FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
        INNER JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
        INNER JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
        LEFT JOIN "StreemLyne_MT"."Employee_Master" em
          ON COALESCE(pd.assigned_employee_id, cm.assigned_employee_id, pd.employee_id, ecm.employee_id) = em.employee_id
        LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
        WHERE cm.is_deleted = false
          AND cm.is_archived = false
          AND cm.tenant_id IS NOT NULL
          AND cm.client_email IS NOT NULL
          AND LENGTH(TRIM(cm.client_email)) > 3
          AND ecm.contract_end_date IS NOT NULL
          AND ecm.service_id IN (1, 2)
          AND ecm.contract_end_date BETWEEN :window_start AND :window_end
          {tenant_clause}
          {allow_clause}
        ORDER BY cm.tenant_id, ecm.contract_end_date ASC, ecm.energy_contract_master_id ASC
        """
    )
    params: Dict[str, Any] = {"window_start": window_start, "window_end": window_end}
    if tenant_id is not None:
        params["tenant_id_text"] = str(int(tenant_id))
    if email_allowlist_lower:
        for i, em in enumerate(email_allowlist_lower):
            params[f"wl_{i}"] = em
    rows = session.execute(sql, params).mappings().all()
    if _renewal_debug_on():
        logger.info(
            "[renewal-debug] fetch_eligible_contract_rows params=%s row_count=%s",
            {k: v for k, v in params.items()},
            len(rows),
        )
    return [dict(r) for r in rows]


def _debug_probe_seeded_contracts(session, anchor: date, tenant_id: Optional[int]) -> None:
    """Log seed-tagged rows and per-filter eligibility hints (only when RENEWAL_EMAIL_DEBUG)."""
    tenant_clause = (
        "AND TRIM(CAST(cm.tenant_id AS TEXT)) = :tenant_id_text" if tenant_id is not None else ""
    )
    probe = text(
        f"""
        SELECT
            ecm.energy_contract_master_id,
            ecm.contract_end_date,
            ecm.service_id,
            cm.client_id,
            TRIM(CAST(cm.tenant_id AS TEXT)) AS tenant_id_text,
            TRIM(cm.client_email) AS client_email,
            cm.is_deleted,
            cm.is_archived,
            cm.client_company_name,
            pd.project_id
        FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
        INNER JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
        INNER JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
        WHERE POSITION(:needle IN COALESCE(cm.client_company_name, '')) > 0
        {tenant_clause}
        ORDER BY ecm.energy_contract_master_id
        LIMIT 50
        """
    )
    params: Dict[str, Any] = {"needle": "[TEST RENEWAL EMAIL]"}
    if tenant_id is not None:
        params["tenant_id_text"] = str(int(tenant_id))
    probe_rows = session.execute(probe, params).mappings().all()
    ws, we = contract_window_end_dates(anchor)
    logger.info("[renewal-debug] probe seed-tagged rows count=%s (window %s..%s)", len(probe_rows), ws, we)
    for pr in probe_rows:
        prd = dict(pr)
        end = _normalize_date(prd["contract_end_date"])
        days = (end - anchor).days
        in_date_window = ws <= end <= we
        svc_ok = int(prd.get("service_id") or -1) in (1, 2)
        email_ok = bool(prd.get("client_email") and len(str(prd["client_email"]).strip()) > 3)
        not_del = not prd.get("is_deleted")
        not_arch = not prd.get("is_archived")
        bucket = bucket_for_days_remaining(days)
        logger.info(
            "[renewal-debug] probe ecm=%s end=%s days=%s in_sql_date_window=%s bucket=%s "
            "svc=%s svc_ok=%s email=%r email_ok=%s tenant_id=%r not_deleted=%s not_archived=%s",
            prd.get("energy_contract_master_id"),
            end,
            days,
            in_date_window,
            bucket.key if bucket else None,
            prd.get("service_id"),
            svc_ok,
            prd.get("client_email"),
            email_ok,
            prd.get("tenant_id_text"),
            not_del,
            not_arch,
        )


def _normalize_date(d: Any) -> date:
    if isinstance(d, datetime):
        return d.date()
    return d


def build_renewal_email_context(
    *,
    customer_name: str,
    business_name: str,
    supplier_name: str,
    contract_end_date: date,
    days_remaining: int,
    bucket_key: str,
    bucket_title: str,
    service_label: str,
    aggregator_name: str = "",
    advisor_name: str = "",
    advisor_phone: str = "",
    market_graph_image_url: str = "",
    postal_address_line: str = "",
) -> Dict[str, Any]:
    """Template context with the four client-required fields plus campaign metadata."""
    return {
        "customer_name": customer_name or "Customer",
        "business_name": business_name or "—",
        "supplier_name": supplier_name or "—",
        "aggregator_name": aggregator_name or "—",
        "advisor_name": advisor_name or "Your renewal advisor",
        "advisor_phone": advisor_phone or "",
        "market_graph_image_url": market_graph_image_url or _market_graph_image_url(),
        "end_date": contract_end_date.strftime("%d/%m/%Y"),
        "contract_end_date": contract_end_date.strftime("%d/%m/%Y"),
        "days_remaining": days_remaining,
        "bucket_key": bucket_key,
        "bucket_title": bucket_title,
        "service_label": service_label,
        "postal_address_line": postal_address_line,
        # Legacy aliases used in older template fragments
        "contact_name": customer_name,
        "company_name": business_name,
    }


def render_renewal_email_bodies(ctx: Dict[str, Any]) -> tuple[str, str, str]:
    """Return (subject, html, plain_text) for a renewal reminder."""
    env = _jinja_env()
    subject = (
        f"{ctx['bucket_title']} — {ctx['service_label']} "
        f"({ctx['days_remaining']} days remaining)"
    )
    html = env.get_template("emails/renewal_reminder.html").render(**ctx)
    txt = env.get_template("emails/renewal_reminder.txt").render(**ctx)
    return subject, html, txt


def render_renewal_email_sample_preview(bucket_key: str = "renewal_90") -> tuple[str, str]:
    """Static sample for client review (no database). Returns (html, plain_text)."""
    from backend.services.renewal_email_buckets import (
        BUCKET_RENEWAL_30,
        BUCKET_RENEWAL_60,
        BUCKET_RENEWAL_70,
        BUCKET_RENEWAL_80,
        BUCKET_RENEWAL_90,
    )

    titles = {
        BUCKET_RENEWAL_90: "Your renewal is due in 90 days",
        BUCKET_RENEWAL_80: "Your renewal is due in 80 days",
        BUCKET_RENEWAL_70: "Your renewal is due in 70 days",
        BUCKET_RENEWAL_60: "Your renewal is due in 60 days",
        BUCKET_RENEWAL_30: "Your contract ends in 30 days",
    }
    key = bucket_key if bucket_key in titles else BUCKET_RENEWAL_90
    anchor = date(2026, 10, 1)
    sample_days = {
        BUCKET_RENEWAL_90: 90,
        BUCKET_RENEWAL_80: 80,
        BUCKET_RENEWAL_70: 70,
        BUCKET_RENEWAL_60: 60,
        BUCKET_RENEWAL_30: 30,
    }[key]
    sample_end = anchor + timedelta(days=sample_days)
    days = (sample_end - anchor).days
    ctx = build_renewal_email_context(
        customer_name="John Smith",
        business_name="Acme Trading Ltd",
        supplier_name="British Gas",
        aggregator_name="Business Gas",
        advisor_name="Zak",
        advisor_phone="01234 567890",
        contract_end_date=sample_end,
        days_remaining=days,
        bucket_key=key,
        bucket_title=titles[key],
        service_label="Electricity",
        postal_address_line="123 High Street, London, SW1A 1AA",
    )
    _, html, txt = render_renewal_email_bodies(ctx)
    return html, txt


def _context_from_contract_row(row: dict, anchor: date, bucket) -> Dict[str, Any]:
    import os

    end = _normalize_date(row["contract_end_date"])
    days = (end - anchor).days
    customer_name = (row.get("client_contact_name") or "").strip()
    business_name = (row.get("client_company_name") or "").strip()
    if not business_name:
        business_name = customer_name or "Customer"
    if not customer_name:
        customer_name = business_name
    supplier_name = (row.get("supplier_name") or "").strip()
    aggregator_name = _mapped_value(row.get("aggregator") or "", _AGGREGATOR_DISPLAY_NAMES)
    advisor_name = _mapped_value(row.get("assigned_employee_name") or "", _ADVISOR_DISPLAY_NAMES)
    advisor_phone = (row.get("assigned_employee_phone") or "").strip()
    service_label = "Water" if int(row.get("service_id") or 0) == 2 else "Electricity"
    return build_renewal_email_context(
        customer_name=customer_name,
        business_name=business_name,
        supplier_name=supplier_name,
        aggregator_name=aggregator_name,
        advisor_name=advisor_name,
        advisor_phone=advisor_phone,
        market_graph_image_url=_market_graph_image_url(),
        contract_end_date=end,
        days_remaining=days,
        bucket_key=bucket.key,
        bucket_title=bucket.title,
        service_label=service_label,
        postal_address_line=_postal_line(row),
    )


def run_renewal_email_campaign(
    anchor_date: Optional[date] = None,
    tenant_id: Optional[int] = None,
    dry_run: Optional[bool] = None,
) -> Dict[str, int]:
    """
    One cron run: eligible electricity/water contracts in the renewal windows, one email per bucket per contract end date.
    """
    import os

    _env_file = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_env_file)
    load_dotenv()

    anchor = anchor_date or datetime.utcnow().date()
    if dry_run is None:
        dry_run = os.getenv("RENEWAL_EMAIL_DRY_RUN", "").lower() in ("1", "true", "yes")

    resend_configured = bool((os.getenv("RESEND_API_KEY") or "").strip() and (os.getenv("RENEWAL_EMAIL_FROM") or "").strip())
    if not dry_run and not resend_configured:
        logger.warning(
            "RESEND_API_KEY or RENEWAL_EMAIL_FROM missing; running as dry-run (no outbound email)"
        )
        dry_run = True

    counts: Dict[str, int] = {
        "sent": 0,
        "dry_run": 0,
        "skipped_dup": 0,
        "skipped_bucket": 0,
        "skipped_bad_email": 0,
        "skipped_not_whitelist": 0,
        "failed": 0,
    }

    session = SessionLocal()
    try:
        window_start, window_end = contract_window_end_dates(anchor)
        whitelist = renewal_email_test_whitelist()
        allow_sql: Optional[List[str]] = sorted(whitelist) if whitelist else None
        wl_raw = os.getenv("RENEWAL_EMAIL_TEST_WHITELIST", "")

        if _renewal_debug_on():
            logger.info(
                "[renewal-debug] anchor=%s window_start=%s window_end=%s tenant_id_filter=%s dry_run=%s",
                anchor,
                window_start,
                window_end,
                tenant_id,
                dry_run,
            )
            logger.info(
                "[renewal-debug] RENEWAL_EMAIL_TEST_WHITELIST raw_set=%s raw_len=%s parsed_emails=%s",
                bool(wl_raw.strip()),
                len(wl_raw),
                list(whitelist) if whitelist else [],
            )
            logger.info(
                "[renewal-debug] SQL email allowlist (sorted lower): %s",
                allow_sql,
            )

        if whitelist:
            logger.info(
                "Renewal email test whitelist active (%s addresses); SQL filter applied",
                len(whitelist),
            )

        rows = fetch_eligible_contract_rows(session, anchor, tenant_id, email_allowlist_lower=allow_sql)

        if _renewal_debug_on():
            logger.info("[renewal-debug] eligible contracts count (after all SQL filters)=%s", len(rows))
            for r in rows:
                rd = dict(r)
                end_d = _normalize_date(rd["contract_end_date"])
                dr = (end_d - anchor).days
                bk = bucket_for_days_remaining(dr)
                logger.info(
                    "[renewal-debug] eligible row ecm_id=%s client_id=%s tenant_id=%r email=%r "
                    "contract_end=%s days_remaining=%s bucket=%s service_id=%s",
                    rd.get("energy_contract_master_id"),
                    rd.get("client_id"),
                    rd.get("tenant_id"),
                    rd.get("client_email"),
                    end_d,
                    dr,
                    bk.key if bk else None,
                    rd.get("service_id"),
                )
            if allow_sql:
                rows_no_email = fetch_eligible_contract_rows(
                    session, anchor, tenant_id, email_allowlist_lower=None
                )
                logger.info(
                    "[renewal-debug] same anchor/tenant WITHOUT email IN filter: count=%s",
                    len(rows_no_email),
                )
                if len(rows_no_email) and not len(rows):
                    for r in rows_no_email[:10]:
                        rd = dict(r)
                        em = (rd.get("client_email") or "").strip().lower()
                        allowed = em in (whitelist or frozenset())
                        logger.info(
                            "[renewal-debug]   (no-email-filter sample) ecm=%s email=%r lower=%r in_whitelist=%s",
                            rd.get("energy_contract_master_id"),
                            rd.get("client_email"),
                            em,
                            allowed,
                        )
            if not rows:
                _debug_probe_seeded_contracts(session, anchor, tenant_id)

        for row in rows:
            email = (row.get("client_email") or "").strip()
            wl_ok = is_allowed_renewal_recipient(email, whitelist)
            if _renewal_debug_on():
                logger.info(
                    "[renewal-debug] loop start ecm=%s email=%r whitelist_active=%s recipient_in_whitelist=%s",
                    row.get("energy_contract_master_id"),
                    email,
                    bool(whitelist),
                    wl_ok,
                )
            if not _EMAIL_RE.match(email):
                if _renewal_debug_on():
                    logger.info("[renewal-debug] skip bad_email regex ecm=%s", row.get("energy_contract_master_id"))
                counts["skipped_bad_email"] += 1
                continue
            if not wl_ok:
                if _renewal_debug_on():
                    logger.info("[renewal-debug] skip not_whitelist ecm=%s", row.get("energy_contract_master_id"))
                counts["skipped_not_whitelist"] += 1
                continue

            end = _normalize_date(row["contract_end_date"])
            days = (end - anchor).days
            bucket = bucket_for_days_remaining(days)
            if _renewal_debug_on():
                logger.info(
                    "[renewal-debug] bucket check ecm=%s days_remaining=%s bucket=%s",
                    row.get("energy_contract_master_id"),
                    days,
                    bucket.key if bucket else None,
                )
            if bucket is None:
                if _renewal_debug_on():
                    logger.info("[renewal-debug] skip outside_bucket ecm=%s", row.get("energy_contract_master_id"))
                counts["skipped_bucket"] += 1
                continue

            tid = int(str(row["tenant_id"]).strip())
            ecm_id = int(row["energy_contract_master_id"])

            dup = (
                session.query(Renewal_Email_Send_Log)
                .filter_by(
                    tenant_id=tid,
                    energy_contract_master_id=ecm_id,
                    contract_end_date=end,
                    bucket_key=bucket.key,
                )
                .first()
            )
            if dup:
                if _renewal_debug_on():
                    logger.info(
                        "[renewal-debug] skip dedup existing log id=%s ecm=%s bucket=%s end=%s",
                        getattr(dup, "renewal_email_send_log_id", None),
                        ecm_id,
                        bucket.key,
                        end,
                    )
                counts["skipped_dup"] += 1
                continue

            ctx = _context_from_contract_row(row, anchor, bucket)
            subject, html, txt = render_renewal_email_bodies(ctx)

            if dry_run:
                logger.info(
                    "[DRY_RUN] would send renewal email to=%s tenant=%s contract=%s bucket=%s",
                    email,
                    tid,
                    ecm_id,
                    bucket.key,
                )
                counts["dry_run"] += 1
                continue

            try:
                msg_id = send_resend_email(
                    email,
                    subject,
                    html,
                    txt,
                    attachments=_market_graph_attachments(),
                )
            except TransactionalMailError as e:
                logger.warning("Renewal email send failed contract=%s: %s", ecm_id, e)
                counts["failed"] += 1
                continue

            log_row = Renewal_Email_Send_Log(
                tenant_id=tid,
                energy_contract_master_id=ecm_id,
                contract_end_date=end,
                bucket_key=bucket.key,
                recipient_email=email,
                provider_message_id=msg_id or None,
                status="sent",
                error_message=None,
            )
            session.add(log_row)
            try:
                session.commit()
                counts["sent"] += 1
            except IntegrityError:
                session.rollback()
                logger.warning(
                    "Renewal email dedup race after send tenant=%s contract=%s bucket=%s",
                    tid,
                    ecm_id,
                    bucket.key,
                )
                counts["skipped_dup"] += 1

    finally:
        session.close()

    logger.info("Renewal email campaign finished: %s", counts)
    return counts
