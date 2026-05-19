"""
Seed temporary CRM rows for renewal email automation testing.

Creates or updates **one** client (`ayaans1804@gmail.com`) with **four** projects (slots 1–4) and
one energy contract each, ending in **75 days** (inside the 60–90 day bucket). Two electricity and two water contracts.

Usage (from cash2switch-backend, with .env and DATABASE_URL):

  python -m backend.scripts.seed_renewal_email_test_customers
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1
  python -m backend.scripts.seed_renewal_email_test_customers --dry-run

Set RENEWAL_EMAIL_SEED_TENANT_ID in .env if you omit --tenant-id (defaults to first
row in Tenant_Master by tenant_id).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

TEST_TAG = "[TEST RENEWAL EMAIL]"

TEST_EMAIL = "ayaans1804@gmail.com"

# (slot, service_id) — one inbox, four sites; 1 = electricity, 2 = water
SEED_ROWS = [
    (1, TEST_EMAIL, 1),
    (2, TEST_EMAIL, 1),
    (3, TEST_EMAIL, 2),
    (4, TEST_EMAIL, 2),
]


def _tenant_key(tenant_id: int) -> str:
    """DB stores tenant_id as varchar in some deployments; compare and persist as text."""
    return str(int(tenant_id))


def _resolve_tenant_id(session, explicit: int | None) -> int:
    from backend.models import Tenant_Master

    if explicit is not None:
        return explicit
    env_tid = (os.getenv("RENEWAL_EMAIL_SEED_TENANT_ID") or "").strip()
    if env_tid.isdigit():
        return int(env_tid)
    t = session.query(Tenant_Master).order_by(Tenant_Master.tenant_id).first()
    if not t:
        raise SystemExit("No tenant found in Tenant_Master; pass --tenant-id.")
    return int(t.tenant_id)


def _default_country_currency(session, tenant_id: int) -> tuple[int | None, int | None]:
    from backend.models import Client_Master

    tid_key = _tenant_key(tenant_id)
    ref = (
        session.query(Client_Master)
        .filter(Client_Master.tenant_id == tid_key, Client_Master.is_deleted == False)
        .first()
    )
    if ref:
        return ref.country_id, ref.default_currency_id
    return 1, 1


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO_ROOT, ".env"))

    from sqlalchemy import func

    from backend.db import SessionLocal
    from backend.models import (
        Client_Master,
        Employee_Master,
        Energy_Contract_Master,
        Project_Details,
        Supplier_Master,
    )

    parser = argparse.ArgumentParser(description="Seed renewal email test customers")
    parser.add_argument("--tenant-id", type=int, default=None, help="Tenant to attach rows to")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only; no DB writes")
    args = parser.parse_args()

    anchor = date.today()
    end = anchor + timedelta(days=75)
    start = anchor - timedelta(days=90)
    now = datetime.utcnow()

    session = SessionLocal()
    try:
        tenant_id = _resolve_tenant_id(session, args.tenant_id)
        country_id, default_currency_id = _default_country_currency(session, tenant_id)
        tid_key = _tenant_key(tenant_id)
        emp = (
            session.query(Employee_Master)
            .filter(Employee_Master.tenant_id == tid_key)
            .order_by(Employee_Master.employee_id)
            .first()
        )
        assigned_id = int(emp.employee_id) if emp else None
        if assigned_id is None:
            any_emp = (
                session.query(Employee_Master).order_by(Employee_Master.employee_id).first()
            )
            assigned_id = int(any_emp.employee_id) if any_emp else 1

        sup = session.query(Supplier_Master).order_by(Supplier_Master.supplier_id).first()
        default_supplier_id = int(sup.supplier_id) if sup else 1

        print(f"Using tenant_id={tenant_id}, contract_end_date={end} (75 days from today)")

        if args.dry_run:
            for slot, email, service_id in SEED_ROWS:
                print(f"  [DRY RUN] would upsert slot={slot} {email} service_id={service_id}")
            print("[DRY RUN] no database changes")
            return

        for slot, email, service_id in SEED_ROWS:
            local = f"s{slot}"
            company = f"{TEST_TAG} Temp - renewal test"
            contact = f"Renewal test (slot {slot})"
            project_title = f"{TEST_TAG} Site slot {slot}"

            client = (
                session.query(Client_Master)
                .filter(
                    Client_Master.tenant_id == tid_key,
                    func.lower(func.trim(Client_Master.client_email)) == email.lower(),
                )
                .first()
            )
            if client:
                print(f"  {email}: update client client_id={client.client_id}")
                client.client_company_name = company
                client.client_contact_name = contact
                client.client_email = email
                client.is_deleted = False
                client.is_archived = False
                client.archived_at = None
                client.archived_reason = None
                if client.country_id is None:
                    client.country_id = country_id
                if client.default_currency_id is None:
                    client.default_currency_id = default_currency_id
            else:
                print(f"  {email}: insert client")
                client = Client_Master(
                    tenant_id=tid_key,
                    client_email=email,
                    client_company_name=company,
                    client_contact_name=contact,
                    address="1 Test Street",
                    post_code="TE1 1ST",
                    country_id=country_id,
                    default_currency_id=default_currency_id,
                    is_deleted=False,
                    is_archived=False,
                    created_at=now,
                )
                session.add(client)
                session.flush()

            proj = (
                session.query(Project_Details)
                .filter(
                    Project_Details.client_id == client.client_id,
                    Project_Details.project_title == project_title,
                )
                .order_by(Project_Details.project_id)
                .first()
            )
            if not proj:
                proj = Project_Details(
                    client_id=client.client_id,
                    project_title=project_title,
                    project_description="Temporary row for renewal email automation tests.",
                    status="Active",
                    employee_id=assigned_id,
                    assigned_employee_id=assigned_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(proj)
                session.flush()
                print(f"    created project_id={proj.project_id} ({project_title})")
            else:
                proj.status = proj.status or "Active"
                proj.assigned_employee_id = proj.assigned_employee_id or assigned_id
                proj.employee_id = proj.employee_id or assigned_id
                proj.updated_at = now
                print(f"    using project_id={proj.project_id} ({project_title})")

            ecm = (
                session.query(Energy_Contract_Master)
                .filter(Energy_Contract_Master.project_id == proj.project_id)
                .order_by(Energy_Contract_Master.energy_contract_master_id)
                .first()
            )
            if not ecm:
                ecm = Energy_Contract_Master(
                    project_id=proj.project_id,
                    employee_id=assigned_id,
                    supplier_id=default_supplier_id,
                    contract_start_date=start,
                    contract_end_date=end,
                    terms_of_sale="TEST renewal email seed contract (safe to delete)",
                    service_id=service_id,
                    unit_rate=0.0,
                    currency_id=default_currency_id or 1,
                    document_details="",
                    mpan_number=f"TEST-REN-{local}",
                    created_at=now,
                    updated_at=now,
                )
                session.add(ecm)
                print(f"    created energy contract service_id={service_id}")
            else:
                ecm.contract_start_date = start
                ecm.contract_end_date = end
                ecm.service_id = service_id
                ecm.updated_at = now
                if ecm.supplier_id is None:
                    ecm.supplier_id = default_supplier_id
                if ecm.currency_id is None:
                    ecm.currency_id = default_currency_id or 1
                if not ecm.terms_of_sale:
                    ecm.terms_of_sale = "TEST renewal email seed contract (safe to delete)"
                if ecm.document_details is None:
                    ecm.document_details = ""
                if ecm.unit_rate is None:
                    ecm.unit_rate = 0.0
                if not ecm.mpan_number:
                    ecm.mpan_number = f"TEST-REN-{local}"
                print(
                    f"    updated energy_contract_master_id={ecm.energy_contract_master_id} "
                    f"service_id={service_id}"
                )

        session.commit()
        print("Committed.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
