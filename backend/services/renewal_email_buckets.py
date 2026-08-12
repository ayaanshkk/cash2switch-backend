"""Day-until-contract-end buckets for renewal reminder emails."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# Bucket keys stored in Renewal_Email_Send_Log and templates.
# These are exact reminder days, not ranges.
BUCKET_RENEWAL_90 = "renewal_90"
BUCKET_RENEWAL_80 = "renewal_80"
BUCKET_RENEWAL_70 = "renewal_70"
BUCKET_RENEWAL_60 = "renewal_60"
BUCKET_RENEWAL_30 = "renewal_30"

# Inclusive day ranges (anchor = "today" UTC date vs contract_end_date)
DAY_MIN = 30
DAY_MAX = 90


@dataclass(frozen=True)
class RenewalBucket:
    key: str
    title: str


def bucket_for_days_remaining(days: int) -> Optional[RenewalBucket]:
    """
    Map integer days from anchor date to contract end date into a reminder day.
    Returns None if the contract is not on a scheduled reminder day.
    """
    buckets = {
        90: RenewalBucket(BUCKET_RENEWAL_90, "Your renewal is due in 90 days"),
        80: RenewalBucket(BUCKET_RENEWAL_80, "Your renewal is due in 80 days"),
        70: RenewalBucket(BUCKET_RENEWAL_70, "Your renewal is due in 70 days"),
        60: RenewalBucket(BUCKET_RENEWAL_60, "Your renewal is due in 60 days"),
        30: RenewalBucket(BUCKET_RENEWAL_30, "Your contract ends in 30 days"),
    }
    return buckets.get(days)


def contract_window_end_dates(anchor: date) -> tuple[date, date]:
    """SQL filter: contract_end_date between 30 and 90 days from today inclusive."""
    start = anchor + timedelta(days=DAY_MIN)
    end = anchor + timedelta(days=DAY_MAX)
    return start, end
