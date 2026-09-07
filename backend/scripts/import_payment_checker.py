"""
Import script: sync Excel renewals data to DB and generate commission schedules.
Usage: python -m scripts.import_payment_checker
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from decimal import Decimal
from backend.db import SessionLocal
from backend.models import (
    Client_Master, Project_Details, Energy_Contract_Master, Commission_Payment
)
from backend.utils.commission_schedule import generate_commission_schedule_for_project

EXCEL_PATH = r"C:\Users\ateeb\Downloads\Ayaan_Upload_07092026.xlsx"


def clean_mpan(val) -> str | None:
    if pd.isna(val) or str(val).strip() in ('', 'nan'):
        return None
    return str(val).strip().replace(' ', '')


def clean_decimal(val) -> Decimal | None:
    if pd.isna(val) or str(val).strip() in ('', 'nan'):
        return None
    try:
        return Decimal(str(val).strip())
    except Exception:
        return None


def run():
    print("Reading Excel...")
    df = pd.read_excel(EXCEL_PATH, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    print(f"Loaded {len(df)} rows from Excel")

    session = SessionLocal()
    matched_contract_ids = []
    matched = 0
    skipped = 0
    generated = 0

    try:
        for idx, row in df.iterrows():
            mpan_top = clean_mpan(row.get('Mpan Top') or row.get('MPAN Top'))
            mpan_bottom = clean_mpan(row.get('Mpan Bottom') or row.get('MPAN Bottom') or row.get('mpan_bottom'))
            net_notch = clean_decimal(row.get('Net Notch') or row.get('net_notch'))
            annual_usage = clean_decimal(row.get('Annual Usage') or row.get('Annual Usage (kWh)'))
            client_name = str(row.get('Client Name') or row.get('Trading Name') or '').strip()

            if not mpan_top and not mpan_bottom:
                print(f"  Row {idx+2}: No MPAN — skipping ({client_name})")
                skipped += 1
                continue

            contract = None
            if mpan_top:
                contract = (
                    session.query(Energy_Contract_Master)
                    .filter(Energy_Contract_Master.mpan_number == mpan_top)
                    .order_by(Energy_Contract_Master.energy_contract_master_id.desc())
                    .first()
                )
            if not contract and mpan_bottom:
                contract = (
                    session.query(Energy_Contract_Master)
                    .filter(Energy_Contract_Master.mpan_bottom == mpan_bottom)
                    .order_by(Energy_Contract_Master.energy_contract_master_id.desc())
                    .first()
                )

            if not contract:
                print(f"  Row {idx+2}: No contract found for MPAN {mpan_top}/{mpan_bottom} ({client_name})")
                skipped += 1
                continue

            # Update net_notch and annual_usage
            if net_notch is not None:
                contract.net_notch = net_notch
            if annual_usage is not None and contract.project_id:
                project = session.query(Project_Details).filter_by(
                    project_id=contract.project_id
                ).first()
                if project:
                    project.Misc_Col2 = int(annual_usage.to_integral_value())

            matched_contract_ids.append(contract.energy_contract_master_id)
            matched += 1
            print(f"  Row {idx+2}: Matched contract #{contract.energy_contract_master_id} for {client_name}")

            # Commission generation in separate session
            gen_session = SessionLocal()
            try:
                deleted = gen_session.query(Commission_Payment).filter_by(
                    contract_id=contract.energy_contract_master_id
                ).delete()
                if deleted:
                    print(f"    Deleted {deleted} existing commission row(s)")
                    gen_session.commit()

                if contract.project_id:
                    result = generate_commission_schedule_for_project(gen_session, contract.project_id)
                    if result.status == 'created':
                        gen_session.commit()
                        generated += 1
                        print(f"    Generated {result.rows_created} commission row(s) — status: {result.status}")
                    else:
                        gen_session.rollback()
                        print(f"    Skipped: {result.status} — {result.message}")
            except Exception as gen_err:
                gen_session.rollback()
                print(f"    Error: {gen_err}")
            finally:
                gen_session.close()

        # Commit net_notch/usage updates
        session.commit()

        # Bulk flag all matched contracts in one query
        if matched_contract_ids:
            from sqlalchemy import text
            session.execute(text("""
                UPDATE "StreemLyne_MT"."Energy_Contract_Master"
                SET include_in_payment_checker = TRUE
                WHERE energy_contract_master_id = ANY(:ids)
            """), {"ids": matched_contract_ids})
            session.commit()
            print(f"\nBulk flagged {len(matched_contract_ids)} contracts")

        print(f"\n--- Done ---")
        print(f"Matched:   {matched}")
        print(f"Skipped:   {skipped}")
        print(f"Generated: {generated}")

    except Exception as e:
        session.rollback()
        print(f"Fatal error: {e}")
        raise
    finally:
        session.close()


if __name__ == '__main__':
    run()