"""Optional dev/test allow-list for renewal reminder recipients."""

from __future__ import annotations

import os
from typing import FrozenSet, Optional


def renewal_email_test_whitelist() -> Optional[FrozenSet[str]]:
    """
    If RENEWAL_EMAIL_TEST_WHITELIST is non-empty, only those addresses (comma-separated,
    case-insensitive) may receive renewal emails. If unset or empty, all eligible recipients
    are allowed (production behaviour).
    """
    raw = (os.getenv("RENEWAL_EMAIL_TEST_WHITELIST") or "").strip().lstrip("\ufeff")
    if not raw:
        return None
    emails: set[str] = set()
    for p in raw.split(","):
        s = p.strip().lower()
        if not s:
            continue
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip().lower()
        if s:
            emails.add(s)
    return frozenset(emails) if emails else None


def is_allowed_renewal_recipient(email: str, whitelist: Optional[FrozenSet[str]]) -> bool:
    if whitelist is None:
        return True
    return email.strip().lower() in whitelist
