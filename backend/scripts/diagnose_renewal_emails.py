"""
Print renewal-email eligibility facts for seeded test rows (and optional tenant filter).

Usage (from cash2switch-backend):
  set RENEWAL_EMAIL_DEBUG=1   # optional; not required for this script
  python -m backend.scripts.diagnose_renewal_emails
  python -m backend.scripts.diagnose_renewal_emails --tenant-id 1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO, ".env"))

    from sqlalchemy import text

    from backend.db import SessionLocal
    from backend.services.renewal_email_buckets import bucket_for_days_remaining, contract_window_end_dates
    from backend.services.renewal_email_whitelist import renewal_email_test_whitelist

    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, default=None)
    args = parser.parse_args()

    anchor = datetime.utcnow().date()
    ws, we = contract_window_end_dates(anchor)
    wl = renewal_email_test_whitelist()
    raw = os.getenv("RENEWAL_EMAIL_TEST_WHITELIST", "")

    print("=== Env ===")
    print("anchor (UTC date):", anchor)
    print("SQL window contract_end_date BETWEEN", ws, "AND", we, "(inclusive)")
    print("RENEWAL_EMAIL_TEST_WHITELIST raw len:", len(raw), "parsed:", list(wl) if wl else None)

    tenant_clause = ""
    params: dict = {}
    if args.tenant_id is not None:
        tenant_clause = "AND TRIM(CAST(cm.tenant_id AS TEXT)) = :tid"
        params["tid"] = str(int(args.tenant_id))

    sql = text(
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
        """
    )
    params["needle"] = "[TEST RENEWAL EMAIL]"

    session = SessionLocal()
    try:
        rows = session.execute(sql, params).mappings().all()
        print("\n=== Seed-tagged rows (company contains [TEST RENEWAL EMAIL]) ===")
        print("count:", len(rows))
        for r in rows:
            d = dict(r)
            end = d["contract_end_date"]
            if hasattr(end, "date"):
                end = end.date()
            days = (end - anchor).days
            in_win = ws <= end <= we
            bucket = bucket_for_days_remaining(days)
            wl_ok = (not wl) or ((d.get("client_email") or "").strip().lower() in wl)
            eligible_core = (
                not d["is_deleted"]
                and not d["is_archived"]
                and d.get("client_email")
                and len(str(d["client_email"]).strip()) > 3
                and int(d.get("service_id") or -1) in (1, 2)
                and in_win
            )
            print(
                f"  ecm={d['energy_contract_master_id']} project={d['project_id']} "
                f"tenant={d['tenant_id_text']!r} email={d['client_email']!r} "
                f"end={end} days={days} in_date_window={in_win} bucket={bucket.key if bucket else None} "
                f"svc={d['service_id']} del={d['is_deleted']} arch={d['is_archived']} "
                f"whitelist_ok={wl_ok} core_filters_ok={eligible_core}"
            )

        if wl:
            keys = ", ".join(f":wl_{i}" for i in range(len(wl)))
            allow_sql = text(
                f"""
                SELECT COUNT(*) AS c
                FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
                INNER JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
                INNER JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
                WHERE cm.is_deleted = false AND cm.is_archived = false
                  AND cm.tenant_id IS NOT NULL
                  AND cm.client_email IS NOT NULL
                  AND LENGTH(TRIM(cm.client_email)) > 3
                  AND ecm.contract_end_date IS NOT NULL
                  AND ecm.service_id IN (1, 2)
                  AND ecm.contract_end_date BETWEEN :ws AND :we
                  {tenant_clause}
                  AND LOWER(TRIM(cm.client_email)) IN ({keys})
                """
            )
            p2 = {"ws": ws, "we": we, **{f"wl_{i}": e for i, e in enumerate(sorted(wl))}}
            if args.tenant_id is not None:
                p2["tid"] = str(int(args.tenant_id))
            cnt = session.execute(allow_sql, p2).scalar()
            print("\n=== Full eligibility query (with whitelist), count ===")
            print("count:", int(cnt))
    finally:
        session.close()


if __name__ == "__main__":
    main()
