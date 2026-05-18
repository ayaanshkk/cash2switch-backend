"""
Bulk Import Route for Energy Customers and Leads
Handles Excel/CSV uploads and bulk insertion into database.

For 200-250k records, the import runs in a background thread and returns
a job_id immediately. The frontend polls /import/status/<job_id> for progress.
"""

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
import pandas as pd
import os
import time
import uuid
import threading
import tempfile
from datetime import datetime, timedelta
from sqlalchemy import text
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Supplier_Master, Employee_Master, Services_Master
)
from .auth_helpers import token_required
from ..db import SessionLocal
from .leads_import_handler import import_leads_handler, download_leads_template_handler
from .job_store import create_job, update_job, get_job, append_error, finish_job, purge_old_jobs


logger = logging.getLogger(__name__)
import_bp = Blueprint('import', __name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_tenant_id_from_user(user):
    """Get tenant_id from authenticated user — JWT tenant_id first."""
    if hasattr(user, 'tenant_id') and user.tenant_id is not None:
        return user.tenant_id
    session = SessionLocal()
    try:
        employee = session.query(Employee_Master).filter_by(employee_id=user.employee_id).first()
        return employee.tenant_id if employee else None
    finally:
        session.close()


def parse_date(date_value):
    """Parse date from various formats — prioritise DD/MM/YYYY (UK format)."""
    if date_value is None or date_value == '':
        return None
    try:
        if pd.isna(date_value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(date_value, datetime):
        return date_value.date()

    date_str = str(date_value).strip()
    if not date_str or date_str.lower() == 'nan':
        return None

    date_formats = [
        '%Y-%m-%d %H:%M:%S',
        '%d/%m/%Y',
        '%d-%m-%Y',
        '%d.%m.%Y',
        '%d %b %Y',
        '%d %B %Y',
        '%Y-%m-%d',
        '%m/%d/%Y',
        '%Y/%m/%d',
    ]
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value):
    """Parse number from string (handles commas, £ signs, etc.)."""
    if value is None or value == '':
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        cleaned = str(value).replace(',', '').replace('£', '').strip()
        return float(cleaned) if cleaned and cleaned != 'nan' else None
    except (ValueError, AttributeError):
        return None


def safe_str(value):
    """Convert value to clean string, removing trailing .0 from numeric strings."""
    if value is None or value == '':
        return ''
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    str_value = str(value).strip()
    if str_value.endswith('.0') and str_value[:-2].replace('.', '', 1).isdigit():
        str_value = str_value[:-2]
    return str_value


def _count_rows(tmp_path: str, file_ext: str) -> int:
    """Fast row count without loading the whole file into memory."""
    try:
        if file_ext == 'csv':
            with open(tmp_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                return max(0, sum(1 for _ in f) - 1)
        else:
            import openpyxl
            wb = openpyxl.load_workbook(tmp_path, read_only=True)
            count = max(0, (wb.active.max_row or 1) - 1)
            wb.close()
            return count
    except Exception:
        return 0



def _build_column_map() -> dict:
    """
    Maps internal field names to every column header variant seen across
    Cash2Switch Excel templates and CSV exports.
    Comparison is done after lowercasing + collapsing whitespace, so
    capitalisation differences don't matter.
    """
    return {
        'client_name':                ['client name', 'business name', 'company name', 'name'],
        'trading_name':               ['trading name', 'trade name', 'business', 'company'],
        'main_contact':               ['main contact', 'contact person', 'contact', 'contact name'],
        'position':                   ['position', 'role', 'title', 'job title'],
        'tel_no':                     ['tel no', 'tel no.', 'phone', 'telephone', 'tel', 'phone number', 'contact number'],
        'mobile_no':                  ['mobile no', 'mobile no.', 'mobile', 'cell', 'mobile number'],
        'email':                      ['email', 'e-mail', 'email address'],
        'site_name':                  ['site name', 'site'],
        'month_sold':                 ['month sold', 'sale month'],
        'house_name':                 ['house name'],
        'house_number':               ['house number', 'house no', 'house no.'],
        'door_number':                ['door number', 'door no'],
        # Cash2Switch template uses "Street" not "Address Line 1"
        'address_line_1':             ['address line 1', 'address 1', 'street', 'address'],
        'address_line_2':             ['address line 2', 'address 2'],
        'address_line_3':             ['address line 3', 'address 3'],
        'town':                       ['town', 'city'],
        'county':                     ['county', 'region'],
        # Cash2Switch uses "Postcode" — also handle "Home Post Code" as fallback
        'postcode':                   ['postcode', 'post code', 'zip', 'postal code'],
        'home_door_number':           ['home door number', 'home door no'],
        'home_street':                ['home street'],
        'home_postcode':              ['home post code', 'home postcode'],
        'mpan_top':                   ['mpan top', 'mpan core', 'mpan'],
        'mpan_bottom':                ['mpan bottom', 'mpan llf'],
        'data_source':                ['data source'],
        'old_supplier':               ['old supplier'],
        'supplier':                   ['supplier', 'supplier name', 'new supplier'],
        'payment_type':               ['payment type'],
        'net_notch':                  ['net notch'],
        # Cash2Switch uses "Term Sold" not "In Contract"
        'term_sold':                  ['term sold', 'in contract', 'contract length', 'term'],
        'agent_sold':                 ['agent sold', 'agent'],
        'start_date':                 ['start date', 'contract start', 'start'],
        'contract_end':               ['contract end', 'end date', 'expiry', 'contract expiry', 'renewal date'],
        'stand_charge':               ['stand charge', 'standing charge', 'standing charge p/day'],
        'rate_1':                     ['rate 1', 'unit rate', 'rate', 'day rate', 'p/kwh'],
        'rate_2':                     ['rate 2', 'night rate'],
        'rate_3':                     ['rate 3', 'evening rate'],
        'aggregator':                 ['aggregator'],
        'annual_usage':               ['annual usage', 'usage', 'kwh', 'annual kwh', 'consumption'],
        'comms_paid':                 ['comms paid', 'commission', 'comm paid'],
        'trading_type':               ['trading type'],
        'company_number':             ['company number', 'co number', 'companies house', 'reg number'],
        'date_of_birth':              ['date of birth', 'dob'],
        'charity_ltd_company_number': ['charity/ltd company number', 'charity number', 'charity ltd company number'],
        'bank_name':                  ['bank name', 'bank'],
        'ac_number':                  ['ac number', 'account number', 'bank account', 'account no'],
        'sort_code':                  ['sort code', 'sortcode'],
        'partner_details':            ['partner details', 'partner'],
        'partner_dob':                ['partner date of birth', 'partner dob'],
        'credit_score':               ['credit score'],
        'password':                   ['password'],
    }


def _resolve_columns(df_columns) -> dict:
    """Map internal field names to actual column names present in the file."""
    normalised = [c.strip().lower().replace('_', ' ') for c in df_columns]
    column_map = _build_column_map()
    actual = {}
    for field, aliases in column_map.items():
        for i, norm_col in enumerate(normalised):
            import re
            norm_col = re.sub(r'\s+', ' ', norm_col)
            if norm_col in aliases:
                actual[field] = df_columns[i]
                break
    return actual


# ---------------------------------------------------------------------------
# Background worker — energy customers (renewals)
# ---------------------------------------------------------------------------

def _run_energy_import(
    job_id: str,
    tmp_path: str,
    file_ext: str,
    tenant_id,
    employee_id: int,
    is_draft_import: bool,
    opportunity_owner_id,
    assigned_employee_name,
    import_service_id: int,
):
    """
    Background worker for renewals/energy-customers import.
    Mirrors _run_leads_import exactly — flat loop, always inserts,
    batch commit every 500 rows.
    """
    BATCH_SIZE = 500
    session = SessionLocal()
    sql_logger = logging.getLogger('sqlalchemy.engine')
    original_level = sql_logger.level
    sql_logger.setLevel(logging.WARNING)

    try:
        # ── Read file — auto-detect header row ───────────────────────────────
        def _unnamed_ratio(cols):
            return sum(1 for c in cols if str(c).startswith('Unnamed:') or str(c).strip() == '') / max(len(cols), 1)

        def _read_raw(path, ext, header_row):
            if ext == 'csv':
                return pd.read_csv(path, encoding='utf-8-sig', dtype=str, header=header_row)
            try:
                return pd.read_excel(path, engine='openpyxl', dtype=str, header=header_row)
            except Exception:
                return pd.read_excel(path, engine='xlrd', dtype=str, header=header_row)

        try:
            df = _read_raw(tmp_path, file_ext, 0)
            if _unnamed_ratio(df.columns) >= 0.5:
                for skip in range(1, 10):
                    candidate = _read_raw(tmp_path, file_ext, skip)
                    if _unnamed_ratio(candidate.columns) < 0.3:
                        print(f"[job:{job_id}] Header found at row {skip}")
                        df = candidate
                        break
        except Exception as e:
            finish_job(job_id, 'failed')
            append_error(job_id, f'Failed to read file: {str(e)[:200]}')
            return
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # ── Normalise columns then restore originals ───────────────────────────
        original_cols = list(df.columns)
        print(f"[job:{job_id}] Columns after smart-read: {original_cols[:15]}")

        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace('_', ' ', regex=False)
            .str.replace(r'\s+', ' ', regex=True)
        )
        normalised_cols = list(df.columns)
        actual_columns = _resolve_columns(normalised_cols)
        df.columns = original_cols

        print(f"[job:{job_id}] MAPPED {len(actual_columns)} fields: {list(actual_columns.keys())}")

        def gcol(field):
            return actual_columns.get(field, '')

        # Drop completely empty rows
        df = df.dropna(how='all').reset_index(drop=True)

        total_rows = len(df)
        update_job(job_id, total=total_rows)

        print(f"[job:{job_id}] Energy import started: {total_rows} rows, "
              f"tenant={tenant_id}, draft={is_draft_import}, service={import_service_id}")

        # ── Pre-load suppliers ─────────────────────────────────────────────────
        suppliers_dict = {
            s.supplier_company_name.lower().strip(): s.supplier_id
            for s in session.query(Supplier_Master).all()
        }
        print(f"[job:{job_id}] Loaded {len(suppliers_dict)} suppliers")

        # ── Pre-load existing MPANs (this tenant only) ─────────────────────────
        existing_mpans: dict = {}
        mpan_rows = session.execute(text("""
            SELECT ecm.mpan_number, ecm.contract_end_date, cm.client_id,
                   cm.is_archived, cm.is_draft, pd.assigned_employee_id
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
            JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
            WHERE cm.is_deleted = FALSE
              AND CAST(cm.tenant_id AS VARCHAR) = CAST(:tid AS VARCHAR)
              AND ecm.mpan_number IS NOT NULL AND ecm.mpan_number != ''
        """), {'tid': tenant_id})
        for r in mpan_rows:
            mpan_num, end_dt, cid, is_arch, is_dr, assigned = r
            if mpan_num:
                existing_mpans[mpan_num.strip().lower()] = {
                    'client_id': cid, 'end_date': end_dt,
                    'is_archived': is_arch, 'is_draft': is_dr,
                    'assigned_employee_id': assigned,
                }
        print(f"[job:{job_id}] Loaded {len(existing_mpans)} existing MPANs for this tenant")

        # ── Row loop ───────────────────────────────────────────────────────────
        success_count     = 0
        error_count       = 0
        duplicate_count   = 0
        rows_since_commit = 0
        start_time        = time.time()

        for index, row in df.iterrows():
            try:
                client_name    = safe_str(row.get(gcol('client_name'), ''))
                trading_name   = safe_str(row.get(gcol('trading_name'), ''))
                main_contact   = safe_str(row.get(gcol('main_contact'), ''))
                position       = safe_str(row.get(gcol('position'), ''))
                tel_no         = safe_str(row.get(gcol('tel_no'), ''))
                mobile_no      = safe_str(row.get(gcol('mobile_no'), ''))
                email          = safe_str(row.get(gcol('email'), ''))
                site_name      = safe_str(row.get(gcol('site_name'), ''))
                address_line_1 = safe_str(row.get(gcol('address_line_1'), ''))
                address_line_2 = safe_str(row.get(gcol('address_line_2'), ''))
                address_line_3 = safe_str(row.get(gcol('address_line_3'), ''))
                town           = safe_str(row.get(gcol('town'), ''))
                county         = safe_str(row.get(gcol('county'), ''))
                postcode       = safe_str(row.get(gcol('postcode'), ''))
                mpan_top       = safe_str(row.get(gcol('mpan_top'), ''))
                mpan_bottom    = safe_str(row.get(gcol('mpan_bottom'), ''))
                supplier_name  = safe_str(row.get(gcol('supplier'), ''))
                old_supplier_name = safe_str(row.get(gcol('old_supplier'), ''))
                payment_type   = safe_str(row.get(gcol('payment_type'), ''))
                annual_usage   = parse_number(row.get(gcol('annual_usage')))
                start_date     = parse_date(row.get(gcol('start_date')))
                end_date       = parse_date(row.get(gcol('contract_end')))
                stand_charge   = parse_number(row.get(gcol('stand_charge')))
                rate_1         = parse_number(row.get(gcol('rate_1')))
                rate_2         = parse_number(row.get(gcol('rate_2')))
                rate_3         = parse_number(row.get(gcol('rate_3')))
                net_notch      = parse_number(row.get(gcol('net_notch')))
                comms_paid     = parse_number(row.get(gcol('comms_paid')))
                term_sold      = parse_number(row.get(gcol('term_sold')))
                credit_score   = parse_number(row.get(gcol('credit_score')))
                company_number             = safe_str(row.get(gcol('company_number'), ''))
                date_of_birth              = parse_date(row.get(gcol('date_of_birth')))
                charity_ltd_company_number = safe_str(row.get(gcol('charity_ltd_company_number'), ''))
                month_sold     = safe_str(row.get(gcol('month_sold'), ''))
                house_name     = safe_str(row.get(gcol('house_name'), ''))
                house_number   = safe_str(row.get(gcol('house_number'), ''))
                door_number    = safe_str(row.get(gcol('door_number'), ''))
                aggregator     = safe_str(row.get(gcol('aggregator'), ''))
                partner_details = safe_str(row.get(gcol('partner_details'), ''))
                bank_name      = safe_str(row.get(gcol('bank_name'), ''))
                account_number = safe_str(row.get(gcol('ac_number'), ''))
                sort_code      = safe_str(row.get(gcol('sort_code'), ''))
                home_door_number = safe_str(row.get(gcol('home_door_number'), ''))
                home_street    = safe_str(row.get(gcol('home_street'), ''))
                partner_dob    = parse_date(row.get(gcol('partner_dob')))

                address_parts = [p for p in [address_line_1, address_line_2, address_line_3, town, county]
                                 if p and p.lower() != 'nan']
                address       = ', '.join(address_parts)
                site_address  = site_name or address
                business_name  = trading_name or client_name
                contact_person = main_contact or client_name
                phone          = tel_no or mobile_no

                # Debug first 3 rows
                if index < 3:
                    print(f"[job:{job_id}] Row {index+2}: business='{business_name}' "
                          f"contact='{contact_person}' phone='{phone}' mpan='{mpan_top}'")

                # Skip completely blank rows
                if not business_name and not phone and not email and not mpan_top and not contact_person:
                    if index < 5:
                        print(f"[job:{job_id}] Row {index+2}: BLANK — skipped")
                    continue

                # ── MPAN duplicate check ───────────────────────────────────────
                if mpan_top:
                    existing = existing_mpans.get(mpan_top.strip().lower())
                    if existing:
                        # Skip only if fully assigned and not a draft
                        if existing['assigned_employee_id'] is not None and not existing['is_draft']:
                            duplicate_count += 1
                            continue
                        # Skip if exact same end date
                        if existing['end_date'] and end_date and existing['end_date'] == end_date:
                            duplicate_count += 1
                            continue
                        # Skip if incoming is older
                        if existing['end_date'] and end_date and end_date < existing['end_date']:
                            duplicate_count += 1
                            continue
                        # Otherwise fall through (newer or unarchived draft — create fresh)

                # ── Supplier resolve ───────────────────────────────────────────
                supplier_id = None
                if supplier_name:
                    sup_key = supplier_name.lower().strip()
                    supplier_id = suppliers_dict.get(sup_key)
                    if not supplier_id:
                        for k, v in suppliers_dict.items():
                            if sup_key in k or k in sup_key:
                                supplier_id = v
                                break
                    if not supplier_id:
                        try:
                            new_sup = Supplier_Master(
                                supplier_company_name=supplier_name,
                                supplier_contact_name='Auto-imported',
                                supplier_provisions=3,
                                created_at=datetime.utcnow(),
                            )
                            session.add(new_sup)
                            session.flush()
                            supplier_id = new_sup.supplier_id
                            suppliers_dict[sup_key] = supplier_id
                        except Exception:
                            session.rollback()
                            supplier_id = None

                old_supplier_id = None
                if old_supplier_name:
                    old_key = old_supplier_name.lower().strip()
                    old_supplier_id = suppliers_dict.get(old_key)
                    if not old_supplier_id:
                        for k, v in suppliers_dict.items():
                            if old_key in k or k in old_key:
                                old_supplier_id = v
                                break

                # ── Insert Client + Project + Contract ─────────────────────────
                contract_start = start_date or datetime.utcnow().date()
                contract_end   = end_date or (contract_start + timedelta(days=365))

                new_client = Client_Master(
                    tenant_id=tenant_id,
                    assigned_employee_id=opportunity_owner_id,
                    client_company_name=business_name or '',
                    client_contact_name=contact_person or '',
                    address=address or '',
                    post_code=postcode or '',
                    home_door_number=home_door_number or None,
                    home_street=home_street or None,
                    client_phone=tel_no or '',
                    client_mobile=mobile_no or None,
                    client_email=email or '',
                    client_website='',
                    default_currency_id=1,
                    created_at=datetime.utcnow(),
                    position=position or None,
                    company_number=company_number or None,
                    date_of_birth=date_of_birth,
                    charity_ltd_company_number=charity_ltd_company_number or None,
                    partner_details=partner_details or None,
                    bank_name=bank_name or None,
                    account_number=account_number or None,
                    sort_code=sort_code or None,
                    partner_dob=partner_dob,
                    credit_score=credit_score,
                    is_archived=False,
                    is_draft=is_draft_import,
                    is_deleted=False,
                )
                session.add(new_client)
                session.flush()

                new_project = Project_Details(
                    client_id=new_client.client_id,
                    opportunity_id=None,
                    project_title=business_name or 'Renewal Contract',
                    project_description='Imported renewal contract',
                    start_date=contract_start,
                    end_date=contract_end,
                    employee_id=employee_id,
                    assigned_employee_id=opportunity_owner_id,
                    status=None,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    address=site_address or address or '',
                    Misc_Col1=None,
                    Misc_Col2=int(annual_usage) if annual_usage else None,
                    site_name=site_name or None,
                    month_sold=month_sold or None,
                    house_name=house_name or None,
                    house_number=house_number or None,
                    door_number=door_number or None,
                    town=town or None,
                    county=county or None,
                )
                session.add(new_project)
                session.flush()

                new_contract = Energy_Contract_Master(
                    project_id=new_project.project_id,
                    employee_id=employee_id,
                    supplier_id=supplier_id,
                    old_supplier_id=old_supplier_id,
                    contract_start_date=contract_start,
                    contract_end_date=contract_end,
                    terms_of_sale='',
                    service_id=import_service_id,
                    unit_rate=rate_1 or 0.0,
                    currency_id=1,
                    document_details=None,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    mpan_number=mpan_top or '',
                    mpan_bottom=mpan_bottom or '',
                    net_notch=net_notch,
                    rate_2=rate_2,
                    rate_3=rate_3,
                    comms_paid=comms_paid,
                    standing_charge=stand_charge,
                    aggregator=aggregator or None,
                    rate_1=rate_1,
                    payment_type=payment_type or None,
                    term_sold=term_sold,
                )
                session.add(new_contract)
                session.flush()

                # Register MPAN to catch intra-file duplicates
                if mpan_top:
                    existing_mpans[mpan_top.strip().lower()] = {
                        'client_id': new_client.client_id,
                        'end_date': end_date,
                        'is_archived': False,
                        'is_draft': is_draft_import,
                        'assigned_employee_id': opportunity_owner_id,
                    }

                success_count     += 1
                rows_since_commit += 1

            except Exception as row_err:
                session.rollback()
                error_count       += 1
                rows_since_commit  = 0
                err_str = str(row_err).split('\n')[0][:150]
                append_error(job_id, f"Row {index+2}: {err_str}")
                if index < 10:
                    print(f"[job:{job_id}] Row {index+2} ERROR: {err_str}")
                continue

            # ── Batch commit ───────────────────────────────────────────────────
            if rows_since_commit >= BATCH_SIZE:
                try:
                    session.commit()
                    rows_since_commit = 0
                    elapsed = time.time() - start_time
                    rate    = success_count / elapsed if elapsed > 0 else 1
                    eta_min = (total_rows - success_count) / rate / 60 if rate > 0 else 0
                    update_job(job_id, processed=index + 1,
                               successful=success_count, duplicates=duplicate_count)
                    print(f"[job:{job_id}] {success_count}/{total_rows} | "
                          f"{rate:.0f} rec/s | ETA {eta_min:.1f} min")
                except Exception as batch_err:
                    session.rollback()
                    rows_since_commit = 0
                    error_count += 1
                    append_error(job_id, f"Batch commit failed: {str(batch_err)[:100]}")

        # ── Final commit ───────────────────────────────────────────────────────
        try:
            session.commit()
        except Exception as final_err:
            session.rollback()
            append_error(job_id, f"Final commit failed: {str(final_err)[:100]}")

        elapsed = time.time() - start_time
        print(f"[job:{job_id}] DONE — {success_count} inserted, "
              f"{duplicate_count} dup, {error_count} err in {elapsed:.1f}s")
        finish_job(job_id, 'done')
        update_job(job_id, processed=total_rows,
                   successful=success_count, duplicates=duplicate_count)

    except Exception as fatal:
        import traceback; traceback.print_exc()
        try:
            session.rollback()
        except Exception:
            pass
        finish_job(job_id, 'failed')
        append_error(job_id, f"Fatal: {str(fatal)[:200]}")
        print(f"[job:{job_id}] FATAL: {str(fatal)}")
    finally:
        sql_logger.setLevel(original_level)
        session.close()


# ---------------------------------------------------------------------------
# Background worker — leads
# ---------------------------------------------------------------------------

def _run_leads_import(
    job_id: str,
    tmp_path: str,
    file_ext: str,
    tenant_id,
    employee_id: int,
    is_draft_import: bool,
    opportunity_owner_id,
    assigned_employee_name,
    import_service_id: int,
    default_stage_id: int,
):
    """Background worker for leads import (writes only to Opportunity_Details)."""
    BATCH_SIZE = 500

    session = SessionLocal()
    sql_logger = logging.getLogger('sqlalchemy.engine')
    original_level = sql_logger.level
    sql_logger.setLevel(logging.WARNING)

    try:
        # ── Read file — auto-detect header row ───────────────────────────────
        def _unnamed_ratio(cols):
            return sum(1 for c in cols if str(c).startswith('Unnamed:') or str(c).strip() == '') / max(len(cols), 1)

        def _read_raw(path, ext, header_row):
            if ext == 'csv':
                return pd.read_csv(path, encoding='utf-8-sig', dtype=str, header=header_row)
            try:
                return pd.read_excel(path, engine='openpyxl', dtype=str, header=header_row)
            except Exception:
                return pd.read_excel(path, engine='xlrd', dtype=str, header=header_row)

        try:
            df = _read_raw(tmp_path, file_ext, 0)
            if _unnamed_ratio(df.columns) >= 0.5:
                for skip in range(1, 10):
                    candidate = _read_raw(tmp_path, file_ext, skip)
                    if _unnamed_ratio(candidate.columns) < 0.3:
                        print(f"[job:{job_id}] Header found at row {skip}")
                        df = candidate
                        break
        except Exception as e:
            finish_job(job_id, 'failed')
            append_error(job_id, f'Failed to read file: {str(e)[:200]}')
            return
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        original_cols = list(df.columns)
        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace('_', ' ', regex=False)
            .str.replace(r'\s+', ' ', regex=True)
        )
        actual_columns = _resolve_columns(list(df.columns))
        df.columns = original_cols

        def gcol(field):
            return actual_columns.get(field, '')

        # Drop completely empty rows
        df = df.dropna(how='all').reset_index(drop=True)

        total_rows = len(df)
        update_job(job_id, total=total_rows)
        print(f"[job:{job_id}] Starting leads import: {total_rows} rows, tenant={tenant_id}")

        # ── Pre-load existing lead MPANs ───────────────────────────────────────
        existing_lead_mpans: dict = {}
        lead_mpan_rows = session.execute(text("""
            SELECT od."mpan_mpr", od."tenant_id", od."business_name", od."opportunity_title"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            WHERE od."mpan_mpr" IS NOT NULL AND od."mpan_mpr" != ''
              AND NOT EXISTS (
                  SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd
                  WHERE pd.opportunity_id = od.opportunity_id
              )
        """)).fetchall()
        for lr in lead_mpan_rows:
            key = lr[0].strip().lower()
            existing_lead_mpans.setdefault(key, []).append({
                'tenant_id':     lr[1],
                'business_name': lr[2] or lr[3],
            })
        print(f"[job:{job_id}] Loaded {len(existing_lead_mpans)} existing lead MPANs")

        # ── Pre-load suppliers (read-only lookup) ─────────────────────────────
        suppliers_dict = {
            s.supplier_company_name.lower().strip(): s.supplier_id
            for s in session.query(Supplier_Master).all()
        }

        success_count = 0
        error_count = 0
        duplicate_count = 0
        rows_since_commit = 0
        start_time = time.time()

        for index, row in df.iterrows():
            try:
                client_name   = safe_str(row.get(gcol('client_name'), ''))
                trading_name  = safe_str(row.get(gcol('trading_name'), ''))
                main_contact  = safe_str(row.get(gcol('main_contact'), ''))
                tel_no        = safe_str(row.get(gcol('tel_no'), ''))
                mobile_no     = safe_str(row.get(gcol('mobile_no'), ''))
                email         = safe_str(row.get(gcol('email'), ''))
                mpan_top      = safe_str(row.get(gcol('mpan_top'), ''))
                mpan_bottom   = safe_str(row.get(gcol('mpan_bottom'), ''))
                supplier_name = safe_str(row.get(gcol('supplier'), ''))
                start_date    = parse_date(row.get(gcol('start_date')))
                end_date      = parse_date(row.get(gcol('contract_end')))
                annual_usage  = parse_number(row.get(gcol('annual_usage')))
                payment_type  = safe_str(row.get(gcol('payment_type'), ''))
                postcode      = safe_str(row.get(gcol('postcode'), ''))

                business_name  = trading_name or client_name
                contact_person = main_contact or client_name
                phone          = tel_no or mobile_no

                if not business_name and not phone and not email and not mpan_top and not contact_person:
                    continue

                # Duplicate check
                if mpan_top:
                    mpan_key = mpan_top.strip().lower()
                    existing_records = existing_lead_mpans.get(mpan_key)
                    if existing_records:
                        duplicate_count += 1
                        cross_tenant = next((r for r in existing_records if r['tenant_id'] != tenant_id), None)
                        same_tenant  = next((r for r in existing_records if r['tenant_id'] == tenant_id), None)
                        if cross_tenant or same_tenant:
                            continue  # Skip all duplicates for leads

                # Supplier lookup (read-only — don't create new suppliers for leads)
                supplier_id = None
                if supplier_name:
                    sup_key = supplier_name.lower().strip()
                    supplier_id = suppliers_dict.get(sup_key)
                    if not supplier_id:
                        # Fuzzy match
                        for k, v in suppliers_dict.items():
                            if sup_key in k or k in sup_key:
                                supplier_id = v
                                break

                session.execute(text("""
                    INSERT INTO "StreemLyne_MT"."Opportunity_Details"
                    (tenant_id, client_id, opportunity_title, opportunity_description,
                     opportunity_date, opportunity_owner_employee_id, stage_id,
                     opportunity_value, currency_id, created_at, "Misc_Col1",
                     business_name, contact_person, tel_number, mobile_no, email,
                     mpan_mpr, mpan_bottom, start_date, end_date, service_id,
                     supplier_id, annual_usage, stand_charge, rate_1, rate_2,
                     rate_3, net_notch, payment_type, postcode, is_draft)
                    VALUES
                    (:tenant_id, NULL, :title, 'Imported lead',
                     :opp_date, :owner_id, :stage_id,
                     0, 1, :created_at, NULL,
                     :business_name, :contact_person, :tel_number, :mobile_no, :email,
                     :mpan_mpr, :mpan_bottom, :start_date, :end_date, :service_id,
                     :supplier_id, :annual_usage, :stand_charge, :rate_1, :rate_2,
                     :rate_3, :net_notch, :payment_type, :postcode, :is_draft)
                """), {
                    'tenant_id':     tenant_id,
                    'title':         business_name or '',
                    'opp_date':      datetime.utcnow().date(),
                    'owner_id':      opportunity_owner_id,
                    'stage_id':      default_stage_id,
                    'created_at':    datetime.utcnow(),
                    'business_name': business_name or None,
                    'contact_person': contact_person or None,
                    'tel_number':    phone or None,
                    'mobile_no':     mobile_no or None,
                    'email':         email or None,
                    'mpan_mpr':      mpan_top or None,
                    'mpan_bottom':   mpan_bottom or None,
                    'start_date':    start_date,
                    'end_date':      end_date,
                    'service_id':    import_service_id,
                    'supplier_id':   supplier_id,
                    'annual_usage':  int(annual_usage) if annual_usage else None,
                    'stand_charge':  parse_number(row.get(gcol('stand_charge'))),
                    'rate_1':        parse_number(row.get(gcol('rate_1'))),
                    'rate_2':        parse_number(row.get(gcol('rate_2'))),
                    'rate_3':        parse_number(row.get(gcol('rate_3'))),
                    'net_notch':     parse_number(row.get(gcol('net_notch'))),
                    'payment_type':  payment_type or None,
                    'postcode':      postcode or None,
                    'is_draft':      is_draft_import,
                })
                success_count += 1
                rows_since_commit += 1

                if mpan_top:
                    mpan_key = mpan_top.strip().lower()
                    existing_lead_mpans.setdefault(mpan_key, []).append({
                        'tenant_id':     tenant_id,
                        'business_name': business_name,
                    })

            except Exception as row_err:
                session.rollback()
                error_count += 1
                rows_since_commit = 0
                append_error(job_id, f"Row {index + 2}: {str(row_err).split(chr(10))[0][:150]}")
                continue

            if rows_since_commit >= BATCH_SIZE:
                try:
                    session.commit()
                    rows_since_commit = 0
                    elapsed = time.time() - start_time
                    rate = success_count / elapsed if elapsed > 0 else 1
                    eta_min = (total_rows - success_count) / rate / 60 if rate > 0 else 0
                    update_job(job_id, processed=index + 1, successful=success_count,
                               duplicates=duplicate_count)
                    print(f"[job:{job_id}] leads {success_count}/{total_rows} | "
                          f"{rate:.0f} rec/s | ETA {eta_min:.1f} min")
                except Exception as batch_err:
                    session.rollback()
                    rows_since_commit = 0
                    error_count += 1
                    append_error(job_id, f"Batch commit failed: {str(batch_err)[:100]}")

        try:
            session.commit()
        except Exception as final_err:
            session.rollback()
            append_error(job_id, f"Final commit failed: {str(final_err)[:100]}")

        elapsed = time.time() - start_time
        print(f"[job:{job_id}] LEADS DONE — {success_count} ok, {duplicate_count} dup, "
              f"{error_count} err in {elapsed:.1f}s")
        finish_job(job_id, 'done')
        update_job(job_id, processed=total_rows, successful=success_count, duplicates=duplicate_count)

    except Exception as fatal:
        import traceback
        traceback.print_exc()
        try:
            session.rollback()
        except Exception:
            pass
        finish_job(job_id, 'failed')
        append_error(job_id, f"Fatal error: {str(fatal)[:200]}")
    finally:
        sql_logger.setLevel(original_level)
        session.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@import_bp.route('/energy-customers', methods=['POST', 'OPTIONS'])
@token_required
def import_energy_customers():
    """
    POST /import/energy-customers
    Saves the file, starts a background thread, returns job_id immediately.
    Frontend polls GET /import/status/<job_id> for progress.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Please upload .xlsx, .xls, or .csv'}), 400

    tenant_id = get_tenant_id_from_user(request.current_user)
    if not tenant_id:
        return jsonify({'error': 'Tenant not found for user'}), 400

    employee_id = request.current_user.employee_id
    is_draft_import = str(request.form.get('is_draft', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    assigned_employee_id = request.form.get('assigned_employee_id', type=int)
    opportunity_owner_id = None if is_draft_import else (assigned_employee_id or employee_id)

    # Validate assigned employee before spawning thread
    assigned_employee_name = None
    if assigned_employee_id and not is_draft_import:
        session = SessionLocal()
        try:
            ae = session.query(Employee_Master).filter_by(
                employee_id=assigned_employee_id,
                tenant_id=tenant_id,
            ).first()
            if not ae:
                return jsonify({'error': f'Invalid employee ID: {assigned_employee_id}'}), 400
            assigned_employee_name = ae.employee_name
        finally:
            session.close()

    service_param = request.args.get('service', 'utilities')
    service_id_map = {'utilities': 1, 'electricity': 1, 'water': 2, 'gas': 3}
    import_service_id = service_id_map.get(service_param.strip().lower(), 1)

    # Save file to disk — must happen in request context before thread starts
    filename = secure_filename(file.filename)
    file_ext = filename.rsplit('.', 1)[1].lower()
    tmp_path = f'/tmp/import_{uuid.uuid4().hex}.{file_ext}'
    file.save(tmp_path)

    # Fast row count for progress display
    total_rows = _count_rows(tmp_path, file_ext)

    # Purge stale jobs opportunistically
    purge_old_jobs(max_age_hours=24)

    job_id = uuid.uuid4().hex
    create_job(job_id, total_rows, tenant_id=tenant_id)

    thread = threading.Thread(
        target=_run_energy_import,
        args=(
            job_id, tmp_path, file_ext,
            tenant_id, employee_id,
            is_draft_import, opportunity_owner_id, assigned_employee_name,
            import_service_id,
        ),
        daemon=True,
        name=f'import-energy-{job_id[:8]}',
    )
    thread.start()

    print(f"[job:{job_id}] Energy import thread started — {total_rows} rows, tenant={tenant_id}")

    return jsonify({
        'job_id':     job_id,
        'status':     'running',
        'total_rows': total_rows,
        'message':    f'Import started. Poll /import/status/{job_id} for progress.',
    }), 202


@import_bp.route('/leads', methods=['POST', 'OPTIONS'])
@token_required
def import_leads():
    """
    POST /import/leads
    Saves the file, starts a background thread, returns job_id immediately.
    Writes only to Opportunity_Details (no Client_Master / Project_Details).
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    filename = secure_filename(file.filename)
    if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in {'xlsx', 'xls', 'csv'}):
        return jsonify({'error': 'Invalid file type. Please upload .xlsx, .xls, or .csv'}), 400

    tenant_id = get_tenant_id_from_user(request.current_user)
    if not tenant_id:
        return jsonify({'error': 'Tenant not found for user'}), 400

    employee_id = request.current_user.employee_id
    is_draft_import = str(request.form.get('is_draft', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    assigned_employee_id = request.form.get('assigned_employee_id', type=int)
    opportunity_owner_id = None if is_draft_import else (assigned_employee_id or employee_id)

    assigned_employee_name = None
    if assigned_employee_id and not is_draft_import:
        session = SessionLocal()
        try:
            ae = session.query(Employee_Master).filter_by(
                employee_id=assigned_employee_id,
                tenant_id=tenant_id,
            ).first()
            if not ae:
                return jsonify({'error': f'Invalid employee ID: {assigned_employee_id}'}), 400
            assigned_employee_name = ae.employee_name
        finally:
            session.close()

    service_param = request.args.get('service', 'electricity')
    service_id_map = {'electricity': 1, 'utilities': 1, 'water': 2, 'gas': 3}
    import_service_id = service_id_map.get(service_param.strip().lower(), 1)

    # Resolve default stage_id before leaving request context
    session = SessionLocal()
    try:
        from ..models import Stage_Master
        default_stage = session.query(Stage_Master).order_by(Stage_Master.stage_id).first()
        default_stage_id = default_stage.stage_id if default_stage else 1
    finally:
        session.close()

    file_ext = filename.rsplit('.', 1)[1].lower()
    tmp_path = f'/tmp/import_{uuid.uuid4().hex}.{file_ext}'
    file.save(tmp_path)

    total_rows = _count_rows(tmp_path, file_ext)
    purge_old_jobs(max_age_hours=24)

    job_id = uuid.uuid4().hex
    create_job(job_id, total_rows, tenant_id=tenant_id)

    thread = threading.Thread(
        target=_run_leads_import,
        args=(
            job_id, tmp_path, file_ext,
            tenant_id, employee_id,
            is_draft_import, opportunity_owner_id, assigned_employee_name,
            import_service_id, default_stage_id,
        ),
        daemon=True,
        name=f'import-leads-{job_id[:8]}',
    )
    thread.start()

    print(f"[job:{job_id}] Leads import thread started — {total_rows} rows, tenant={tenant_id}")

    return jsonify({
        'job_id':     job_id,
        'status':     'running',
        'total_rows': total_rows,
        'message':    f'Import started. Poll /import/status/{job_id} for progress.',
    }), 202


@import_bp.route('/status/<job_id>', methods=['GET'])
@token_required
def import_status(job_id):
    """
    GET /import/status/<job_id>
    Returns current progress of a background import job.
    Poll every 2 seconds from the frontend.
    """
    job = get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    total = max(job.get('total') or 1, 1)
    processed = job.get('processed', 0)

    return jsonify({
        'job_id':       job_id,
        'status':       job.get('status', 'running'),   # running | done | failed
        'total':        total,
        'processed':    processed,
        'successful':   job.get('successful', 0),
        'duplicates':   job.get('duplicates', 0),
        'progress_pct': round(processed / total * 100, 1),
        'errors':       job.get('errors', [])[-20:],    # last 20 only
        'started_at':   job.get('started_at'),
        'finished_at':  job.get('finished_at'),
    }), 200


# ---------------------------------------------------------------------------
# Template downloads (unchanged)
# ---------------------------------------------------------------------------

@import_bp.route('/template', methods=['GET'])
@token_required
def download_template():
    """Download Excel template matching Cash2Switch renewals format."""
    try:
        import io
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Renewals Import Template"

        headers = [
            "Client Name", "Trading Name", "Main Contact", "Position", "Tel No", "Mobile No",
            "Email", "Site Name", "Month Sold", "", "Address Line 1", "Address Line 2",
            "Address Line 3", "Town", "County", "Postcode", "Mpan Top", "Mpan Bottom",
            "", "", "Data Source", "Welcome Call", "Payment Type", "Supplier", "Net Notch",
            "In Contract", "Agent Sold", "Start Date", "Contract End", "Stand Charge",
            "Rate 1", "Rate 2", "Rate 3", "", "", "Aggregator", "Annual Usage",
            "Comms Paid", "Company Number", "Date of Birth", "Bank Name", "Ac Number",
            "Sort Code", "Charity/Ltd Company Number", "Partner Details",
        ]
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            if header:
                cell.fill = header_fill
                cell.font = header_font

        example = [
            "ABC Limited", "ABC Trading", "John Smith", "Director",
            "07700900000", "07700900001", "john@abc.com", "Main Site", "Jan-24", "",
            "123 Main St", "Unit 5", "Industrial Estate", "London", "Greater London", "SW1A 1AA",
            "1100012314490", "04031N12", "", "",
            "Renewals", "Yes", "DD", "British Gas", "0.1",
            "1 Year", "Sales Team", "01/01/2024", "31/12/2024", "45.13",
            "35.00", "26.46", "", "", "",
            "Online", "25000", "7.92", "12345678", "",
            "Barclays", "12345678", "20-00-00", "", "",
        ]
        for col, value in enumerate(example, 1):
            ws.cell(row=2, column=col, value=value)

        for col in ws.columns:
            max_length = max((len(str(cell.value)) for cell in col if cell.value), default=0)
            ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 30)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='cash2switch_renewals_template.xlsx',
        )
    except Exception as e:
        current_app.logger.exception(f"❌ Template download failed: {e}")
        return jsonify({'error': 'Failed to generate template'}), 500


@import_bp.route('/leads/template', methods=['GET'])
@token_required
def download_leads_template():
    return download_leads_template_handler()


# ---------------------------------------------------------------------------
# Sequence reset (admin utility — unchanged)
# ---------------------------------------------------------------------------

@import_bp.route('/energy-clients/reset-sequence', methods=['POST'])
@jwt_required()
def reset_energy_client_sequence():
    """Reset the client_id sequence after deleting all customers."""
    current_user = get_jwt_identity()
    tenant_id = current_user.get('tenant_id')

    session = SessionLocal()
    try:
        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Client_Master"', 'client_id'),
                COALESCE((SELECT MAX(client_id) FROM "StreemLyne_MT"."Client_Master" WHERE tenant_id = :tid), 0),
                true
            )
        """), {'tid': tenant_id})

        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Project_Details"', 'project_id'),
                COALESCE((SELECT MAX(project_id) FROM "StreemLyne_MT"."Project_Details"), 0),
                true
            )
        """))

        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Energy_Contract_Master"', 'energy_contract_master_id'),
                COALESCE((SELECT MAX(energy_contract_master_id) FROM "StreemLyne_MT"."Energy_Contract_Master"), 0),
                true
            )
        """))

        session.commit()
        return jsonify({'message': 'All sequences reset successfully', 'success': True}), 200

    except Exception as e:
        session.rollback()
        logger.error(f"Error resetting sequences: {str(e)}")
        return jsonify({'error': 'Failed to reset sequences'}), 500
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Duplicate-handling helpers (kept for use by customer_routes if needed)
# ---------------------------------------------------------------------------

def handle_duplicate_customer(session, tenant_id, mpan_top, phone, new_end_date, new_client_id=None):
    """
    Check for existing customer by MPAN Top or Phone.
    Returns: (should_archive_new: bool, existing_client_id: int | None)
    """
    from sqlalchemy import or_

    existing_query = session.query(
        Client_Master.client_id,
        Client_Master.client_company_name,
        Energy_Contract_Master.contract_end_date,
        Energy_Contract_Master.mpan_number,
    ).join(
        Project_Details, Client_Master.client_id == Project_Details.client_id,
    ).join(
        Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id,
    ).filter(
        Client_Master.tenant_id == tenant_id,
        Client_Master.is_deleted == False,
        Client_Master.is_archived == False,
        or_(
            Energy_Contract_Master.mpan_number == mpan_top,
            Client_Master.client_phone == phone,
        ),
    )
    if new_client_id:
        existing_query = existing_query.filter(Client_Master.client_id != new_client_id)

    existing = existing_query.first()
    if not existing:
        return False, None

    existing_client_id, _, existing_end_date, _ = existing

    if not new_end_date and not existing_end_date:
        return True, existing_client_id
    if not new_end_date:
        return True, existing_client_id
    if not existing_end_date:
        return False, existing_client_id

    new_date = new_end_date if isinstance(new_end_date, datetime) else datetime.strptime(str(new_end_date), '%Y-%m-%d')
    ext_date = existing_end_date if isinstance(existing_end_date, datetime) else existing_end_date

    return (new_date <= ext_date), existing_client_id


def archive_customer(session, client_id, reason="Superseded by newer contract"):
    client = session.query(Client_Master).filter_by(client_id=client_id).first()
    if client:
        client.is_archived = True
        client.archived_at = datetime.utcnow()
        client.archived_reason = reason