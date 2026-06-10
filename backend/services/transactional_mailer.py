"""Send transactional email via Resend HTTP API (no extra Python deps beyond requests)."""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class TransactionalMailError(Exception):
    pass


def send_resend_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
) -> str:
    """
    Send one email via Resend. Returns provider message id.
    Raises TransactionalMailError on failure.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_addr = os.getenv("RENEWAL_EMAIL_FROM", "").strip()
    if not api_key:
        raise TransactionalMailError("RESEND_API_KEY is not set")
    if not from_addr:
        raise TransactionalMailError("RENEWAL_EMAIL_FROM is not set (e.g. 'Renewals <renewals@yourdomain.com>')")

    payload = {
        "from": from_addr,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body
    if attachments:
        payload["attachments"] = attachments

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        logger.exception("Resend request failed: %s", e)
        raise TransactionalMailError(str(e)) from e

    if resp.status_code >= 400:
        detail = resp.text[:2000]
        logger.error("Resend error %s: %s", resp.status_code, detail)
        raise TransactionalMailError(f"Resend HTTP {resp.status_code}: {detail}")

    data = resp.json() if resp.content else {}
    msg_id = data.get("id") or ""
    logger.info("Resend accepted email to=%s id=%s", to_email, msg_id)
    return msg_id
