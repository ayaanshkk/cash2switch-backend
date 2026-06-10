"""
Run renewal reminder emails daily at 08:00 UK time.

This script is intended to run as a separate worker/process, not inside the
Flask web app. It sleeps until the next 08:00 Europe/London run, executes the
same campaign as backend.scripts.run_renewal_emails, then schedules tomorrow.

Usage:
  python -m backend.scripts.run_renewal_emails_daily_8am_uk --tenant-id 2
  python -m backend.scripts.run_renewal_emails_daily_8am_uk --tenant-id 2 --run-once-now
  python -m backend.scripts.run_renewal_emails_daily_8am_uk --tenant-id 2 --dry-run --run-once-now
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    from pytz import timezone as _pytz_timezone

    class ZoneInfo:  # type: ignore[no-redef]
        def __new__(cls, name: str):
            return _pytz_timezone(name)


UK_TZ = ZoneInfo("Europe/London")
STOP_REQUESTED = False


def _repo_root() -> str:
    # backend/scripts -> backend -> cash2switch-backend
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run renewal reminder emails daily at 08:00 UK time"
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=None,
        help="Limit to one tenant. Defaults to RENEWAL_EMAIL_CRON_TENANT_ID or all tenants.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions only; do not send or write send-log rows.",
    )
    parser.add_argument(
        "--run-once-now",
        action="store_true",
        help="Run immediately once and exit. Useful for testing the worker command.",
    )
    return parser.parse_args()


def _setup_imports_and_env() -> None:
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    from dotenv import load_dotenv

    load_dotenv(os.path.join(root, ".env"))


def _tenant_id_from_env() -> int | None:
    raw = (
        os.getenv("RENEWAL_EMAIL_CRON_TENANT_ID")
        or os.getenv("RENEWAL_EMAIL_TENANT_ID")
        or ""
    ).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            "RENEWAL_EMAIL_CRON_TENANT_ID must be an integer when set"
        ) from exc


def _next_8am_uk(now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_uk = now_utc.astimezone(UK_TZ)
    next_run_uk = now_uk.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_uk >= next_run_uk:
        next_run_uk += timedelta(days=1)
    return next_run_uk


def _sleep_until(run_at_uk: datetime) -> None:
    global STOP_REQUESTED

    while not STOP_REQUESTED:
        seconds = (
            run_at_uk.astimezone(timezone.utc) - datetime.now(timezone.utc)
        ).total_seconds()
        if seconds <= 0:
            return
        time.sleep(min(seconds, 60))


def _handle_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logging.info("Stop requested; exiting after current wait/run")


def _run_campaign(tenant_id: int | None, dry_run: bool) -> dict:
    from backend.services.renewal_email_service import run_renewal_email_campaign

    dry_kw = True if dry_run else None
    return run_renewal_email_campaign(tenant_id=tenant_id, dry_run=dry_kw)


def main() -> None:
    args = _parse_args()
    _setup_imports_and_env()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    tenant_id = args.tenant_id if args.tenant_id is not None else _tenant_id_from_env()

    if args.run_once_now:
        counts = _run_campaign(tenant_id=tenant_id, dry_run=args.dry_run)
        logging.info("Renewal email run complete: %s", counts)
        print(counts)
        return

    logging.info(
        "Renewal email scheduler started; tenant_id=%s, run_time=08:00 Europe/London",
        tenant_id if tenant_id is not None else "all",
    )

    while not STOP_REQUESTED:
        run_at_uk = _next_8am_uk()
        logging.info(
            "Next renewal email run: %s UK / %s UTC",
            run_at_uk.strftime("%Y-%m-%d %H:%M:%S %Z"),
            run_at_uk.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
        _sleep_until(run_at_uk)
        if STOP_REQUESTED:
            break

        try:
            counts = _run_campaign(tenant_id=tenant_id, dry_run=args.dry_run)
            logging.info("Renewal email run complete: %s", counts)
        except Exception:
            logging.exception("Renewal email run failed")


if __name__ == "__main__":
    main()
