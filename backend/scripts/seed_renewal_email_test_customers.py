"""
Seed temporary CRM rows for renewal email automation testing.

Creates or updates test clients/projects/contracts for renewal email testing.

Usage (from cash2switch-backend, with .env and DATABASE_URL):

  python -m backend.scripts.seed_renewal_email_test_customers
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1
  python -m backend.scripts.seed_renewal_email_test_customers --dry-run
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1 --days-from-today 30 --slots 30
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1 --bucket-suite
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1 --bucket-suite --bucket-suite-run-id client-demo-1
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1 --bucket-suite
  python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1 --bucket-suite --real-data

Set RENEWAL_EMAIL_SEED_TENANT_ID in .env if you omit --tenant-id (defaults to first
row in Tenant_Master by tenant_id).
"""

from __future__ import annotations

import argparse
import hashlib
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

BUCKET_SUITE_ROWS = [
    (190, TEST_EMAIL, 1, 90, "90_day"),
    (180, TEST_EMAIL, 1, 80, "80_day"),
    (170, TEST_EMAIL, 1, 70, "70_day"),
    (160, TEST_EMAIL, 1, 60, "60_day"),
    (130, TEST_EMAIL, 1, 30, "30_day"),
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
    parser.add_argument(
        "--days-from-today",
        type=int,
        default=75,
        help="Contract end date offset from today; defaults to 75",
    )
    parser.add_argument(
        "--slots",
        default="1,2,3,4",
        help="Comma-separated seed slots to upsert; defaults to 1,2,3,4",
    )
    parser.add_argument(
        "--bucket-suite",
        action="store_true",
        help="Create one test contract for each renewal email reminder day: 90, 80, 70, 60, and 30 days",
    )
    parser.add_argument(
        "--bucket-suite-run-id",
        default="",
        help="Optional label that creates a fresh bucket suite instead of reusing the default slots",
    )
    parser.add_argument(
        "--test-email",
        default=None,
        help="Recipient email to use for seeded test customers; defaults to all emails in RENEWAL_EMAIL_TEST_WHITELIST",
    )
    parser.add_argument(
        "--real-data",
        action="store_true",
        help="Use real customer/contract values from the database while overriding the recipient email",
    )
    args = parser.parse_args()

    anchor = date.today()
    now = datetime.utcnow()
    from backend.services.renewal_email_whitelist import renewal_email_test_whitelist

    if args.test_email:
        test_emails = [args.test_email.strip().lower()]
    else:
        test_emails = sorted(renewal_email_test_whitelist())
        if not test_emails:
            test_emails = [TEST_EMAIL]

    if args.bucket_suite:
        run_id = args.bucket_suite_run_id.strip() or f"auto-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        slot_offset = 0
        digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()
        slot_offset = 1000 + (int(digest[:6], 16) % 8000)
        seed_rows = []
        for email_index, test_email in enumerate(test_emails):
            email_offset = email_index * 10000
            seed_rows.extend(
                (slot + slot_offset + email_offset, test_email, service_id, days_from_today, bucket_label)
                for slot, email, service_id, days_from_today, bucket_label in BUCKET_SUITE_ROWS
            )
        selected_slots = {slot for slot, *_ in seed_rows}
    else:
        selected_slots = {
            int(slot.strip())
            for slot in args.slots.split(",")
            if slot.strip()
        }
        existing_rows = {slot: (slot, email, service_id) for slot, email, service_id in SEED_ROWS}
        seed_rows = []
        for email_index, test_email in enumerate(test_emails):
            email_offset = email_index * 10000
            seed_rows.extend(
                (
                    slot + email_offset,
                    test_email,
                    existing_rows.get(slot, (slot, TEST_EMAIL, 1))[2],
                    args.days_from_today,
                    "custom",
                )
                for slot in sorted(selected_slots)
            )
        if not selected_slots:
            raise SystemExit("No matching seed slots selected.")

    session = SessionLocal()
    try:
        tenant_id = _resolve_tenant_id(session, args.tenant_id)
        country_id, default_currency_id = _default_country_currency(session, tenant_id)
        tid_key = _tenant_key(tenant_id)
        next_tenant_client_id = (
            session.query(func.max(Client_Master.tenant_client_id))
            .filter(Client_Master.tenant_id == tid_key)
            .scalar()
            or 0
        )
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
        source_rows = []
        if args.real_data:
            source_rows = (
                session.query(Energy_Contract_Master, Project_Details, Client_Master)
                .join(Project_Details, Energy_Contract_Master.project_id == Project_Details.project_id)
                .join(Client_Master, Project_Details.client_id == Client_Master.client_id)
                .filter(Client_Master.tenant_id == tid_key)
                .filter(Client_Master.is_deleted == False)
                .filter(Client_Master.is_archived == False)
                .filter(Client_Master.client_company_name != None)
                .filter(~Client_Master.client_company_name.contains(TEST_TAG))
                .filter(Energy_Contract_Master.service_id.in_([1, 2]))
                .filter(Energy_Contract_Master.supplier_id != None)
                .order_by(Energy_Contract_Master.contract_end_date.desc().nullslast())
                .limit(len(seed_rows))
                .all()
            )
            if len(source_rows) < len(seed_rows):
                raise SystemExit("Not enough real source rows found for --real-data seed.")

        print(f"Using tenant_id={tenant_id}, emails={test_emails}, slots={sorted(selected_slots)}")
        if args.bucket_suite:
            print(f"Bucket suite run id: {run_id}")

        if args.dry_run:
            for slot, email, service_id, days_from_today, bucket_label in seed_rows:
                end = anchor + timedelta(days=days_from_today)
                print(
                    f"  [DRY RUN] would upsert slot={slot} {email} service_id={service_id} "
                    f"bucket={bucket_label} end={end} ({days_from_today} days from today)"
                )
            print("[DRY RUN] no database changes")
            return

        for index, (slot, email, service_id, days_from_today, bucket_label) in enumerate(seed_rows):
            end = anchor + timedelta(days=days_from_today)
            start = anchor - timedelta(days=90)
            local = f"s{slot}"
            source_contract = source_project = source_client = None
            if source_rows:
                source_contract, source_project, source_client = source_rows[index]
                service_id = int(source_contract.service_id or service_id)
            company = (
                source_client.client_company_name
                if source_client and source_client.client_company_name
                else f"{TEST_TAG} Temp - renewal test"
            )
            contact = (
                source_client.client_contact_name
                if source_client and source_client.client_contact_name
                else f"Renewal test {bucket_label} (slot {slot})"
            )
            if args.bucket_suite:
                project_title = f"{TEST_TAG} Site slot {slot} - {bucket_label}"
            else:
                project_title = f"{TEST_TAG} Site slot {slot}"

            existing_project = (
                session.query(Project_Details)
                .filter(Project_Details.project_title == project_title)
                .order_by(Project_Details.project_id)
                .first()
            )
            client = None
            if existing_project:
                client = (
                    session.query(Client_Master)
                    .filter(Client_Master.client_id == existing_project.client_id)
                    .first()
                )
            if not client and not args.real_data:
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
                next_tenant_client_id += 1
                print(f"  {email}: insert client ({company})")
                client = Client_Master(
                    tenant_client_id=next_tenant_client_id,
                    tenant_id=tid_key,
                    display_id=next_tenant_client_id,
                    client_email=email,
                    client_company_name=company,
                    client_contact_name=contact,
                    address=(source_client.address if source_client and source_client.address else "1 Test Street"),
                    post_code=(source_client.post_code if source_client and source_client.post_code else "TE1 1ST"),
                    country_id=(source_client.country_id if source_client and source_client.country_id else country_id),
                    default_currency_id=(
                        source_client.default_currency_id
                        if source_client and source_client.default_currency_id
                        else default_currency_id
                    ),
                    client_phone=(source_client.client_phone if source_client else None),
                    client_mobile=(source_client.client_mobile if source_client else None),
                    client_website=(source_client.client_website if source_client else None),
                    position=(source_client.position if source_client else None),
                    company_number=(source_client.company_number if source_client else None),
                    is_deleted=False,
                    is_archived=False,
                    created_at=now,
                )
                session.add(client)
                session.flush()

            proj = existing_project
            if proj and proj.client_id != client.client_id:
                proj = None
            if not proj:
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
                    project_description=(
                        source_project.project_description
                        if source_project and source_project.project_description
                        else "Temporary row for renewal email automation tests."
                    ),
                    status=(source_project.status if source_project and source_project.status else "Active"),
                    employee_id=(
                        source_project.employee_id
                        if source_project and source_project.employee_id
                        else assigned_id
                    ),
                    assigned_employee_id=(
                        source_project.assigned_employee_id
                        if source_project and source_project.assigned_employee_id
                        else assigned_id
                    ),
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
                    employee_id=(
                        source_contract.employee_id
                        if source_contract and source_contract.employee_id
                        else assigned_id
                    ),
                    supplier_id=(
                        source_contract.supplier_id
                        if source_contract and source_contract.supplier_id
                        else default_supplier_id
                    ),
                    contract_start_date=start,
                    contract_end_date=end,
                    terms_of_sale=(
                        source_contract.terms_of_sale
                        if source_contract and source_contract.terms_of_sale
                        else "TEST renewal email seed contract (safe to delete)"
                    ),
                    service_id=service_id,
                    unit_rate=(source_contract.unit_rate if source_contract and source_contract.unit_rate is not None else 0.0),
                    currency_id=(
                        source_contract.currency_id
                        if source_contract and source_contract.currency_id
                        else default_currency_id or 1
                    ),
                    document_details=(source_contract.document_details if source_contract and source_contract.document_details else ""),
                    mpan_number=f"TEST-REN-{local}",
                    aggregator=(source_contract.aggregator if source_contract else None),
                    rate_1=(source_contract.rate_1 if source_contract else None),
                    rate_2=(source_contract.rate_2 if source_contract else None),
                    rate_3=(source_contract.rate_3 if source_contract else None),
                    standing_charge=(source_contract.standing_charge if source_contract else None),
                    payment_type=(source_contract.payment_type if source_contract else None),
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
                if source_contract:
                    ecm.employee_id = source_contract.employee_id or ecm.employee_id
                    ecm.supplier_id = source_contract.supplier_id or ecm.supplier_id
                    ecm.aggregator = source_contract.aggregator
                    ecm.rate_1 = source_contract.rate_1
                    ecm.rate_2 = source_contract.rate_2
                    ecm.rate_3 = source_contract.rate_3
                    ecm.standing_charge = source_contract.standing_charge
                    ecm.payment_type = source_contract.payment_type
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
