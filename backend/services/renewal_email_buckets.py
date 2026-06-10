"""Day-until-contract-end buckets for renewal reminder emails."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# Bucket keys stored in Renewal_Email_Send_Log and templates
BUCKET_RENEWAL_UNDER_30 = "renewal_under_30"
BUCKET_RENEWAL_60_90 = "renewal_60_90"
BUCKET_RENEWAL_91_180 = "renewal_91_180"

# Inclusive day ranges (anchor = "today" UTC date vs contract_end_date)
DAY_MIN = 0
DAY_MAX = 180


@dataclass(frozen=True)
class RenewalBucket:
    key: str
    title: str


def bucket_for_days_remaining(days: int) -> Optional[RenewalBucket]:
    """
    Map integer days from anchor date to contract end date into a single campaign bucket.
    Returns None if outside any automated window.
    """
    if days < DAY_MIN or days > DAY_MAX:
        return None
    if days < 30:
        return RenewalBucket(BUCKET_RENEWAL_UNDER_30, "Your contract ends very soon")
    if 60 <= days <= 90:
        return RenewalBucket(BUCKET_RENEWAL_60_90, "Your plan renews soon")
    if 91 <= days <= 180:
        return RenewalBucket(BUCKET_RENEWAL_91_180, "Plan renewal planning")
    return None


def contract_window_end_dates(anchor: date) -> tuple[date, date]:
    """SQL filter: contract_end_date between today and 180 days from today inclusive."""
    start = anchor + timedelta(days=DAY_MIN)
    end = anchor + timedelta(days=DAY_MAX)
    return start, end
