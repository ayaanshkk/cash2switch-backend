"""
Run renewal email campaign from the shell (same logic as POST /internal/cron/renewal-emails).

Usage (from repo root cash2switch-backend, with .env loaded):
  python -m backend.scripts.run_renewal_emails
  python -m backend.scripts.run_renewal_emails --tenant-id 1
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


def _repo_root() -> str:
    # backend/scripts -> backend -> cash2switch-backend
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def main() -> None:
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    from dotenv import load_dotenv

    load_dotenv(os.path.join(root, ".env"))

    if os.getenv("RENEWAL_EMAIL_DEBUG", "").lower() in ("1", "true", "yes"):
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
            force=True,
        )

    from backend.services.renewal_email_service import run_renewal_email_campaign

    parser = argparse.ArgumentParser(description="Run renewal reminder email campaign")
    parser.add_argument("--tenant-id", type=int, default=None, help="Limit to one tenant")
    parser.add_argument("--dry-run", action="store_true", help="Log actions only; do not send or write send log")
    args = parser.parse_args()

    dry_kw = True if args.dry_run else None  # None lets run_renewal_email_campaign read RENEWAL_EMAIL_DRY_RUN from env
    counts = run_renewal_email_campaign(tenant_id=args.tenant_id, dry_run=dry_kw)
    print(counts)


if __name__ == "__main__":
    main()
