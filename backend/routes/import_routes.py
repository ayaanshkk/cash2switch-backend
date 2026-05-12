"""
Bulk Import Route for Energy Customers
Handles Excel/CSV uploads and bulk insertion into database
"""

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
import pandas as pd
import os
import time  # ✅ ADD THIS
from datetime import datetime, timezone
from sqlalchemy import and_, or_, text
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging
import tempfile

from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Supplier_Master, Employee_Master, Services_Master
)
from .auth_helpers import token_required
from ..db import SessionLocal
from .leads_import_handler import import_leads_handler, download_leads_template_handler


logger = logging.getLogger(__name__)
import_bp = Blueprint('import', __name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}
UPLOAD_FOLDER = '/tmp/uploads'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_tenant_id_from_user(user):
    """Get tenant_id from authenticated user - match customer_routes (JWT tenant_id first)"""
    if hasattr(user, 'tenant_id') and user.tenant_id is not None:
        return user.tenant_id
    session = SessionLocal()
    try:
        employee = session.query(Employee_Master).filter_by(employee_id=user.employee_id).first()
        return employee.tenant_id if employee else None
    finally:
        session.close()

def parse_date(date_value):
    """Parse date from various formats - prioritize DD/MM/YYYY (UK format)"""
    if pd.isna(date_value) or not date_value or date_value == '':
        return None
    
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
            parsed = datetime.strptime(date_str, fmt).date()
            return parsed
        except ValueError:
            continue
    
    return None

def parse_number(value):
    """Parse number from string (handles commas, etc.)"""
    if pd.isna(value) or not value or value == '':
        return None
    
    try:
        cleaned = str(value).replace(',', '').strip()
        
        if not cleaned or cleaned == 'nan':
            return None
            
        return float(cleaned) if cleaned else None
    except (ValueError, AttributeError):
        return None

def safe_str(value):
    """Convert value to clean string, remove .0 suffix from numeric strings"""
    if pd.isna(value) or value is None or value == '':
        return ''
    str_value = str(value).strip()
    if str_value.endswith('.0') and str_value[:-2].replace('.', '', 1).isdigit():
        str_value = str_value[:-2]
    return str_value


@import_bp.route('/energy-customers', methods=['POST', 'OPTIONS'])
@token_required
def import_energy_customers():
    """
    Bulk import energy customers from Excel/CSV file with optional assignment
    ⚡ OPTIMIZED: Handles thousands of records efficiently
    """
    print("\n\n🔥🔥🔥 IMPORT FUNCTION CALLED! 🔥🔥🔥\n\n")
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # ✅ START TIMER
    start_time = time.time()
    
    session = SessionLocal()
    
    sql_logger = logging.getLogger('sqlalchemy.engine')
    original_level = sql_logger.level
    sql_logger.setLevel(logging.WARNING)
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload .xlsx, .xls, or .csv'}), 400
        
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
        
        employee_id = request.current_user.employee_id

        is_draft_import = str(request.form.get('is_draft', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
        assigned_employee_id = request.form.get('assigned_employee_id', type=int)
        opportunity_owner_id = None if is_draft_import else (assigned_employee_id if assigned_employee_id else employee_id)
        
        assigned_employee_name = None
        if assigned_employee_id and not is_draft_import:
            assigned_employee = session.query(Employee_Master).filter_by(
                employee_id=assigned_employee_id,
                tenant_id=tenant_id
            ).first()
            if assigned_employee:
                assigned_employee_name = assigned_employee.employee_name
            else:
                return jsonify({'error': f'Invalid employee ID: {assigned_employee_id}'}), 400

        print(f"\n{'='*60}")
        print(f"📥 BULK IMPORT STARTED")
        print(f"{'='*60}")
        print(f"   Tenant ID: {tenant_id}")
        print(f"   Uploaded by: Employee ID {employee_id}")
        print(f"   Assigned to: {assigned_employee_name or ('Draft' if is_draft_import else 'Uploader')} (ID: {opportunity_owner_id})")
        print(f"{'='*60}\n")

        service_param = request.args.get('service', 'utilities')
        service_id_map = {
            'utilities': 1,
            'electricity': 1, 
            'water': 2,
            'gas': 3
        }
        import_service_id = service_id_map.get(service_param.strip().lower(), 1)
        
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower()

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp:
                file.save(tmp.name)
                tmp_path = tmp.name
            
            if file_ext == 'csv':
                df = pd.read_csv(tmp_path, encoding='utf-8-sig', dtype=str)
            else:
                try:
                    df = pd.read_excel(tmp_path, engine='openpyxl', dtype=str)
                except Exception:
                    df = pd.read_excel(tmp_path, engine='xlrd', dtype=str)
            
            os.unlink(tmp_path)
            
        except Exception as e:
            print(f"❌ Failed to read file: {str(e)}")
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
                    
        df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ').str.replace(r'\s+', ' ', regex=True)
        
        column_map = {
            'client_name': ['client name', 'business name', 'company name'],
            'trading_name': ['trading name', 'business', 'company'],
            'main_contact': ['main contact', 'contact person', 'contact'],
            'position': ['position', 'role', 'title'],
            'tel_no': ['tel no', 'phone', 'telephone', 'tel'],
            'mobile_no': ['mobile no', 'mobile', 'cell'],
            'email': ['email', 'e-mail'],
            'site_name': ['site name', 'site'],
            'month_sold': ['month sold', 'sale month'],
            'house_name': ['house name'],
            'house_number': ['house number', 'house no'],
            'door_number': ['door number'],
            'address_line_1': ['address line 1', 'address 1', 'street'],
            'address_line_2': ['address line 2', 'address 2'],
            'address_line_3': ['address line 3', 'address 3'],
            'town': ['town', 'city'],
            'county': ['county', 'region'],
            'postcode': ['postcode', 'post code', 'zip', 'home post code', 'home postcode'],
            'home_door_number': ['home door number', 'home door no'],
            'home_street': ['home street'],
            'mpan_top': ['mpan top', 'mpan core'],
            'mpan_bottom': ['mpan bottom', 'mpan llf'],
            'data_source': ['data source'],
            'old_supplier': ['old supplier'],
            'supplier': ['supplier', 'supplier name'],
            'payment_type': ['payment type'],
            'net_notch': ['net notch'],
            'term_sold': ['term sold', 'in contract', 'contract length'],
            'agent_sold': ['agent sold'],
            'start_date': ['start date', 'contract start'],
            'contract_end': ['contract end', 'end date', 'expiry'],
            'stand_charge': ['stand charge', 'standing charge'],
            'rate_1': ['rate 1', 'unit rate', 'rate'],
            'rate_2': ['rate 2'],
            'rate_3': ['rate 3'],
            'aggregator': ['aggregator'],
            'annual_usage': ['annual usage', 'usage', 'kwh'],
            'comms_paid': ['comms paid', 'commission'],
            'trading_type': ['trading type'],
            'company_number': ['company number', 'co number'],
            'date_of_birth': ['date of birth', 'dob'],
            'charity_ltd_company_number': ['charity/ltd company number', 'charity number'],
            'bank_name': ['bank name', 'bank'],
            'ac_number': ['ac number', 'account number'],
            'sort_code': ['sort code'],
            'partner_details': ['partner details', 'partner'],
            'partner_dob': ['partner date of birth', 'partner dob'],
            'credit_score': ['credit score'],
            'password': ['password'],
        }
        
        actual_columns = {}
        for field, possible_names in column_map.items():
            for col in df.columns:
                if col in possible_names:
                    actual_columns[field] = col
                    break
        
        # ✅ PRE-LOAD SUPPLIERS - Already optimized
        suppliers_dict = {}
        suppliers = session.query(Supplier_Master).all()
        for s in suppliers:
            suppliers_dict[s.supplier_company_name.lower().strip()] = s.supplier_id

        print(f"📊 Loaded {len(suppliers_dict)} suppliers for matching")

        # ✅ OPTIMIZED: PRE-LOAD EXISTING MPANs - Use raw SQL
        print("📊 Loading existing MPANs...")
        existing_mpans = {}

        sql = text("""
            SELECT 
                ecm.mpan_number,
                cm.tenant_id,
                pd.assigned_employee_id,
                em.employee_name,
                cm.client_company_name,
                cm.is_archived,
                cm.is_draft,
                ecm.contract_end_date,
                ecm.energy_contract_master_id,
                pd.project_id,
                cm.client_id
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
            JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON pd.assigned_employee_id = em.employee_id
            WHERE cm.is_deleted = FALSE
            AND ecm.mpan_number IS NOT NULL
            AND ecm.mpan_number != ''
        """)

        result = session.execute(sql)
        rows_loaded = 0

        for row in result:
            mpan_number, contract_tenant_id, assigned_emp_id, emp_name, company_name, is_archived, is_draft, end_date, contract_id, project_id, client_id = row
            
            if mpan_number:
                mpan_key = mpan_number.strip().lower()
                
                if mpan_key not in existing_mpans:
                    existing_mpans[mpan_key] = []
                
                existing_mpans[mpan_key].append({
                    'tenant_id': contract_tenant_id,
                    'assigned_to_id': assigned_emp_id,
                    'assigned_to_name': emp_name or 'Unassigned',
                    'company_name': company_name,
                    'is_archived': is_archived,
                    'is_draft': is_draft,
                    'end_date': end_date,
                    'contract_id': contract_id,
                    'project_id': project_id,
                    'client_id': client_id
                })
                rows_loaded += 1

        elapsed_load = time.time() - start_time
        print(f"📊 Loaded {rows_loaded} contracts across {len(existing_mpans)} unique MPANs in {elapsed_load:.2f}s")

        duplicate_details = []
        cross_tenant_duplicates = []
        
        total_rows = len(df)
        success_count = 0
        error_count = 0
        duplicate_count = 0
        errors = []
        BATCH_SIZE = 100  # ✅ Optimized batch size
        
        print(f"📊 Starting import of {total_rows} rows")
        
        for index, row in df.iterrows():
            try:
                # Extract data
                client_name = safe_str(row.get(actual_columns.get('client_name', ''), ''))
                trading_name = safe_str(row.get(actual_columns.get('trading_name', ''), ''))
                main_contact = safe_str(row.get(actual_columns.get('main_contact', ''), ''))
                position = safe_str(row.get(actual_columns.get('position', ''), ''))
                tel_no = safe_str(row.get(actual_columns.get('tel_no', ''), ''))
                mobile_no = safe_str(row.get(actual_columns.get('mobile_no', ''), ''))
                email = safe_str(row.get(actual_columns.get('email', ''), ''))
                site_name = safe_str(row.get(actual_columns.get('site_name', ''), ''))

                address_line_1 = safe_str(row.get(actual_columns.get('address_line_1', ''), ''))
                address_line_2 = safe_str(row.get(actual_columns.get('address_line_2', ''), ''))
                address_line_3 = safe_str(row.get(actual_columns.get('address_line_3', ''), ''))
                town = safe_str(row.get(actual_columns.get('town', ''), ''))
                county = safe_str(row.get(actual_columns.get('county', ''), ''))
                postcode = safe_str(row.get(actual_columns.get('postcode', ''), ''))

                address_parts = [p for p in [address_line_1, address_line_2, address_line_3, town, county] if p and p.lower() != 'nan']
                address = ', '.join(address_parts)
                site_address = site_name or address

                mpan_top = safe_str(row.get(actual_columns.get('mpan_top', ''), ''))
                mpan_bottom = safe_str(row.get(actual_columns.get('mpan_bottom', ''), ''))

                supplier_name = safe_str(row.get(actual_columns.get('supplier', ''), ''))
                old_supplier_name = safe_str(row.get(actual_columns.get('old_supplier', ''), ''))
                payment_type = safe_str(row.get(actual_columns.get('payment_type', ''), ''))
                annual_usage = parse_number(row.get(actual_columns.get('annual_usage', '')))
                start_date = parse_date(row.get(actual_columns.get('start_date', '')))
                end_date = parse_date(row.get(actual_columns.get('contract_end', '')))
                stand_charge = parse_number(row.get(actual_columns.get('stand_charge', '')))
                rate_1 = parse_number(row.get(actual_columns.get('rate_1', '')))
                net_notch = parse_number(row.get(actual_columns.get('net_notch', '')))
                rate_2 = parse_number(row.get(actual_columns.get('rate_2', '')))
                rate_3 = parse_number(row.get(actual_columns.get('rate_3', '')))
                comms_paid = parse_number(row.get(actual_columns.get('comms_paid', '')))
                company_number = safe_str(row.get(actual_columns.get('company_number', ''), ''))
                date_of_birth = parse_date(row.get(actual_columns.get('date_of_birth', '')))
                charity_ltd_company_number = safe_str(row.get(actual_columns.get('charity_ltd_company_number', ''), ''))
                month_sold = safe_str(row.get(actual_columns.get('month_sold', ''), ''))
                house_name = safe_str(row.get(actual_columns.get('house_name', ''), ''))
                house_number = safe_str(row.get(actual_columns.get('house_number', ''), ''))
                door_number = safe_str(row.get(actual_columns.get('door_number', ''), ''))
                term_sold = parse_number(row.get(actual_columns.get('term_sold', '')))
                aggregator = safe_str(row.get(actual_columns.get('aggregator', ''), ''))
                partner_details = safe_str(row.get(actual_columns.get('partner_details', ''), ''))
                bank_name = safe_str(row.get(actual_columns.get('bank_name', ''), ''))
                account_number = safe_str(row.get(actual_columns.get('ac_number', ''), ''))
                sort_code = safe_str(row.get(actual_columns.get('sort_code', ''), ''))
                home_door_number = safe_str(row.get(actual_columns.get('home_door_number', ''), ''))
                home_street = safe_str(row.get(actual_columns.get('home_street', ''), ''))
                partner_dob = parse_date(row.get(actual_columns.get('partner_dob', '')))
                credit_score = parse_number(row.get(actual_columns.get('credit_score', '')))
                data_source = safe_str(row.get(actual_columns.get('data_source', ''), ''))
                agent_sold = safe_str(row.get(actual_columns.get('agent_sold', ''), ''))

                supplier_id = None
                if supplier_name:
                    supplier_key = supplier_name.lower().strip()
                    supplier_id = suppliers_dict.get(supplier_key)
                    
                    if not supplier_id:
                        try:
                            new_supplier = Supplier_Master(
                                supplier_company_name=supplier_name,
                                supplier_contact_name='Auto-imported',
                                supplier_provisions=3,
                                created_at=datetime.utcnow()
                            )
                            session.add(new_supplier)
                            session.flush()
                            
                            supplier_id = new_supplier.supplier_id
                            suppliers_dict[supplier_key] = supplier_id
                            
                            if (index + 1) % 100 == 0:
                                print(f"✨ Row {index + 2}: Created new supplier '{supplier_name}'")
                            
                        except Exception as e:
                            supplier_id = None

                old_supplier_id = None
                if old_supplier_name:
                    old_supplier_key = old_supplier_name.lower().strip()
                    old_supplier_id = suppliers_dict.get(old_supplier_key)
                    
                    if not old_supplier_id:
                        try:
                            new_old_supplier = Supplier_Master(
                                supplier_company_name=old_supplier_name,
                                supplier_contact_name='Auto-imported',
                                supplier_provisions=3,
                                created_at=datetime.utcnow()
                            )
                            session.add(new_old_supplier)
                            session.flush()
                            old_supplier_id = new_old_supplier.supplier_id
                            suppliers_dict[old_supplier_key] = old_supplier_id
                        except Exception:
                            pass

                business_name = trading_name or client_name
                contact_person = main_contact or client_name
                phone = tel_no or mobile_no

                if not business_name and not phone and not email and not mpan_top and not contact_person:
                    continue
                
                # ✅ OPTIMIZED DUPLICATE CHECK
                if mpan_top:
                    mpan_key = mpan_top.strip().lower()
                    existing_records = existing_mpans.get(mpan_key)
                    
                    if existing_records:
                        duplicate_count += 1
                        
                        cross_tenant_record = None
                        same_tenant_record = None
                        
                        for record in existing_records:
                            if record['tenant_id'] != tenant_id:
                                cross_tenant_record = record
                                break
                            else:
                                same_tenant_record = record
                        
                        if cross_tenant_record:
                            cross_tenant_duplicates.append({
                                'row': index + 2,
                                'mpan': mpan_top,
                                'new_company': business_name,
                                'existing_company': cross_tenant_record['company_name'],
                                'existing_tenant_id': cross_tenant_record['tenant_id'],
                                'assigned_to': cross_tenant_record['assigned_to_name'],
                                'is_archived': cross_tenant_record['is_archived']
                            })
                            
                            if (index + 1) % 100 == 0:
                                print(f"⚠️ Row {index + 2}: Cross-tenant duplicate - skipped")
                            continue
                        
                        if same_tenant_record:
                            if same_tenant_record['assigned_to_id'] is not None and not same_tenant_record['is_draft']:
                                duplicate_details.append({
                                    'row': index + 2,
                                    'mpan': mpan_top,
                                    'company': business_name,
                                    'assigned_to': same_tenant_record['assigned_to_name'],
                                    'action': f'Already assigned to {same_tenant_record["assigned_to_name"]} - skipped'
                                })
                                
                                if (index + 1) % 100 == 0:
                                    print(f"⏭️ Row {index + 2}: Already assigned - skipped")
                                continue
                            
                            existing_end_date = same_tenant_record['end_date']
                            new_end_date = end_date
                            
                            if same_tenant_record['is_archived']:
                                if (index + 1) % 100 == 0:
                                    print(f"⏭️ Row {index + 2}: Already archived - skipped")
                                continue
                            
                            if not new_end_date:
                                if (index + 1) % 100 == 0:
                                    print(f"⏭️ Row {index + 2}: No end date - skipped")
                                continue
                            
                            # ✅ OLDER RECORD LOGIC (remains same but with logging)
                            if existing_end_date and new_end_date < existing_end_date:
                                duplicate_details.append({
                                    'row': index + 2,
                                    'mpan': mpan_top,
                                    'company': business_name,
                                    'assigned_to': same_tenant_record['assigned_to_name'],
                                    'action': 'Older record - created as archived'
                                })
                                
                                try:
                                    archived_client = Client_Master(
                                        tenant_id=tenant_id,
                                        assigned_employee_id=opportunity_owner_id,
                                        client_company_name=business_name or '',
                                        client_contact_name=contact_person or '',
                                        address=address or '',
                                        post_code=postcode or '',
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
                                        is_archived=True,
                                        home_door_number=home_door_number or None,
                                        home_street=home_street or None,
                                        archived_at=datetime.utcnow(),
                                        archived_reason=f"Historical (ended {new_end_date}) - superseded by contract ending {existing_end_date}",
                                        is_draft=False,
                                        partner_dob=partner_dob,
                                        credit_score=credit_score,
                                    )
                                    session.add(archived_client)
                                    session.flush()
                                    
                                    archived_project = Project_Details(
                                        client_id=archived_client.client_id,
                                        opportunity_id=None,
                                        project_title=business_name or '',
                                        project_description='Imported site location',
                                        start_date=start_date if start_date else datetime.utcnow().date(),
                                        end_date=end_date,
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
                                    session.add(archived_project)
                                    session.flush()
                                    
                                    archived_contract = Energy_Contract_Master(
                                        project_id=archived_project.project_id,
                                        employee_id=employee_id,
                                        supplier_id=supplier_id,
                                        old_supplier_id=old_supplier_id,
                                        contract_start_date=start_date or datetime.utcnow().date(),
                                        contract_end_date=end_date,
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
                                        term_sold=term_sold,
                                        rate_2=rate_2,
                                        rate_3=rate_3,
                                        comms_paid=comms_paid,
                                        standing_charge=stand_charge,
                                        aggregator=aggregator or None,
                                        rate_1=rate_1,
                                    )
                                    session.add(archived_contract)
                                    session.flush()
                                    
                                    existing_mpans[mpan_key].append({
                                        'tenant_id': tenant_id,
                                        'assigned_to_id': opportunity_owner_id,
                                        'assigned_to_name': assigned_employee_name or 'Unassigned',
                                        'company_name': business_name,
                                        'is_archived': True,
                                        'is_draft': False,
                                        'end_date': end_date,
                                        'contract_id': archived_contract.energy_contract_master_id,
                                        'project_id': archived_project.project_id,
                                        'client_id': archived_client.client_id
                                    })
                                    
                                    success_count += 1
                                    
                                    if (index + 1) % 100 == 0:
                                        print(f"✅ Row {index + 2}: Older record archived")
                                    continue
                                    
                                except Exception as archive_error:
                                    session.rollback()
                                    error_count += 1
                                    errors.append(f"Row {index + 2}: Archive failed - {str(archive_error)[:100]}")
                                    
                                    if (index + 1) % 100 == 0:
                                        print(f"❌ Row {index + 2}: Archive failed")
                                    continue
                            
                            # ✅ EXACT DUPLICATE
                            if existing_end_date and new_end_date == existing_end_date:
                                duplicate_details.append({
                                    'row': index + 2,
                                    'mpan': mpan_top,
                                    'company': business_name,
                                    'assigned_to': same_tenant_record['assigned_to_name'],
                                    'action': 'Exact duplicate - skipped'
                                })
                                
                                if (index + 1) % 100 == 0:
                                    print(f"⏭️ Row {index + 2}: Exact duplicate - skipped")
                                continue
                            
                            # ✅ NEWER RECORD - Archive existing using raw SQL
                            if existing_end_date and new_end_date > existing_end_date:
                                duplicate_details.append({
                                    'row': index + 2,
                                    'mpan': mpan_top,
                                    'company': business_name,
                                    'assigned_to': same_tenant_record['assigned_to_name'],
                                    'action': 'Newer record - archived existing'
                                })
                                
                                try:
                                    archive_sql = text("""
                                        UPDATE "StreemLyne_MT"."Client_Master"
                                        SET is_archived = TRUE,
                                            archived_at = :archived_at,
                                            archived_reason = :reason
                                        WHERE client_id = :client_id
                                    """)
                                    
                                    session.execute(archive_sql, {
                                        'archived_at': datetime.utcnow(),
                                        'reason': f"Superseded by newer contract (ending {new_end_date})",
                                        'client_id': same_tenant_record['client_id']
                                    })
                                    
                                    for record in existing_mpans[mpan_key]:
                                        if record['client_id'] == same_tenant_record['client_id']:
                                            record['is_archived'] = True
                                            break
                                    
                                    if (index + 1) % 100 == 0:
                                        print(f"🔄 Row {index + 2}: Archived existing, creating newer")
                                    
                                except Exception as archive_error:
                                    session.rollback()
                                    error_count += 1
                                    errors.append(f"Row {index + 2}: Archive update failed - {str(archive_error)[:100]}")
                                    
                                    if (index + 1) % 100 == 0:
                                        print(f"❌ Row {index + 2}: Archive update failed")
                                    continue

                # CREATE NEW CLIENT
                try:
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
                    )
                    session.add(new_client)
                    session.flush()
                    
                    client_id = new_client.client_id
                                        
                    project = None
                    if site_address or annual_usage or mpan_top or start_date or end_date:
                        project = Project_Details(
                            client_id=client_id,
                            opportunity_id=None,
                            project_title=business_name or 'Renewal Contract',
                            project_description='Imported renewal contract',
                            start_date=start_date if start_date else datetime.utcnow().date(),
                            end_date=end_date,
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
                        session.add(project)
                        session.flush()
                    
                    if project and mpan_top:
                        from datetime import timedelta
                        
                        contract_start_date = start_date if start_date else datetime.utcnow().date()
                        
                        if end_date:
                            contract_end_date = end_date
                        else:
                            contract_end_date = contract_start_date + timedelta(days=365)
                        
                        contract = Energy_Contract_Master(
                            project_id=project.project_id,
                            employee_id=employee_id,
                            supplier_id=supplier_id,
                            old_supplier_id=old_supplier_id,
                            contract_start_date=contract_start_date,
                            contract_end_date=contract_end_date,
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
                        )
                        session.add(contract)
                        session.flush()

                        if mpan_top:
                            mpan_key = mpan_top.strip().lower()
                            
                            if mpan_key not in existing_mpans:
                                existing_mpans[mpan_key] = []
                            
                            existing_mpans[mpan_key].append({
                                'tenant_id': tenant_id,
                                'assigned_to_id': opportunity_owner_id,
                                'assigned_to_name': assigned_employee_name or 'Unassigned',
                                'company_name': business_name,
                                'is_archived': False,
                                'is_draft': is_draft_import,
                                'end_date': end_date,
                                'contract_id': contract.energy_contract_master_id,
                                'project_id': project.project_id,
                                'client_id': client_id
                            })
                                            
                        success_count += 1
                    
                    # ✅ OPTIMIZED BATCH COMMIT
                    if success_count % BATCH_SIZE == 0:
                        try:
                            session.commit()
                            elapsed = time.time() - start_time
                            rate = success_count / elapsed if elapsed > 0 else 0
                            remaining = (total_rows - success_count) / rate if rate > 0 else 0
                            
                            print(f"📊 Batch {success_count}/{total_rows} committed | "
                                f"{rate:.1f} records/sec | "
                                f"ETA: {remaining/60:.1f} min")
                            
                        except Exception as batch_error:
                            session.rollback()
                            print(f"❌ Batch commit failed at row {index + 2}")
                            error_count += 1
                            errors.append(f"Batch commit failed at row {index + 2}")
                
                except Exception as client_error:
                    session.rollback()
                    error_count += 1
                    
                    error_str = str(client_error)
                    
                    if "UniqueViolation" in error_str or "duplicate key" in error_str:
                        error_msg = f"Customer '{contact_person}'"
                        if business_name:
                            error_msg += f" from '{business_name}'"
                        error_msg += " already exists (duplicate record)"
                        errors.append(error_msg)
                    elif "IntegrityError" in error_str or "violates not-null constraint" in error_str:
                        errors.append(f"Missing required field - check your data")
                    elif "ForeignKeyViolation" in error_str or "foreign key constraint" in error_str:
                        errors.append(f"Invalid reference (supplier, employee, etc.)")
                    else:
                        error_lines = error_str.split('\n')
                        error_msg = error_lines[0] if error_lines else error_str
                        if len(error_msg) > 150:
                            error_msg = error_msg[:150] + "..."
                        errors.append(error_msg)
                    
                    continue
                
            except Exception as row_error:
                session.rollback()
                error_count += 1
                
                error_str = str(row_error)
                
                if "UniqueViolation" in error_str or "duplicate key" in error_str:
                    error_msg = f"Duplicate customer detected"
                elif "IntegrityError" in error_str:
                    error_msg = f"Data validation error"
                else:
                    error_lines = error_str.split('\n')
                    error_msg = error_lines[0][:150] if error_lines else error_str[:150]
                
                errors.append(error_msg)
                continue
                        
        # ✅ FINAL COMMIT WITH TIMING
        try:
            session.commit()
            elapsed = time.time() - start_time
            print(f"\n{'='*60}")
            print(f"✅ IMPORT COMPLETE")
            print(f"{'='*60}")
            print(f"   Total time: {elapsed:.2f}s ({total_rows/elapsed:.1f} records/sec)")
            print(f"   Successful: {success_count}")
            print(f"   Duplicates: {duplicate_count}")
            print(f"   Errors: {error_count}")
            print(f"{'='*60}\n")
            
        except Exception as commit_error:
            print(f"❌ Final commit error: {commit_error}")
            session.rollback()

        # BUILD DUPLICATE REPORT
        duplicate_report = []
        if duplicate_details:
            duplicate_report.append("\n📋 SAME-TENANT DUPLICATES:")
            for dup in duplicate_details:
                duplicate_report.append(
                    f"  Row {dup['row']}: {dup['company']} (MPAN: {dup['mpan']}) - "
                    f"Assigned to: {dup['assigned_to']} - {dup['action']}"
                )

        if cross_tenant_duplicates:
            duplicate_report.append("\n⚠️ CROSS-TENANT DUPLICATES (SKIPPED):")
            for dup in cross_tenant_duplicates:
                archived_status = " [ARCHIVED]" if dup['is_archived'] else ""
                duplicate_report.append(
                    f"  Row {dup['row']}: {dup['new_company']} (MPAN: {dup['mpan']}) - "
                    f"Already exists in another account{archived_status} - "
                    f"Assigned to: {dup['assigned_to']}"
                )

        return jsonify({
            'success': True,
            'message': f'Import completed',
            'total_rows': len(df),
            'successful': success_count,
            'duplicates': duplicate_count,
            'same_tenant_duplicates': len(duplicate_details),
            'cross_tenant_duplicates': len(cross_tenant_duplicates),
            'failed': error_count,
            'errors': errors[:50],
            'duplicate_report': duplicate_report,
            'assigned_to': assigned_employee_name,
            'assigned_employee_id': opportunity_owner_id,
            'is_draft': is_draft_import,
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"\n\n❌❌❌ EXCEPTION CAUGHT ❌❌❌")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"❌❌❌ END EXCEPTION ❌❌❌\n\n")
        return jsonify({'error': f'Import failed: {str(e)}'}), 500
    finally:
        sql_logger.setLevel(original_level)
        session.close()

@import_bp.route('/template', methods=['GET'])
@token_required
def download_template():
    """Download Excel template matching Cash2Switch format"""
    try:
        import io
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from flask import send_file
        
        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Renewals Import Template"
        
        # Headers (matching exact Excel structure)
        headers = [
            "Client Name", "Trading Name", "Main Contact", "Position", "Tel No", "Mobile No",
            "Email", "Site Name", "Month Sold", "", "Address Line 1", "Address Line 2",
            "Address Line 3", "Town", "County", "Postcode", "Mpan Top", "Mpan Bottom",
            "", "", "Data Source", "Welcome Call", "Payment Type", "Supplier", "Net Notch",
            "In Contract", "Agent Sold", "Start Date", "Contract End", "Stand Charge",
            "Rate 1", "Rate 2", "Rate 3", "", "", "Aggregator", "Annual Usage",
            "Comms Paid", "Company Number", "Date of Birth", "Bank Name", "Ac Number",
            "Sort Code", "Charity/Ltd Company Number", "Partner Details"
        ]
        
        # Style headers
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            if header:  # Only style non-empty headers
                cell.fill = header_fill
                cell.font = header_font
        
        # Add example row
        example = [
            "ABC Limited",  # Client Name
            "ABC Trading",  # Trading Name
            "John Smith",   # Main Contact
            "Director",     # Position
            "07700900000",  # Tel No
            "07700900001",  # Mobile No
            "john@abc.com", # Email
            "Main Site",    # Site Name
            "Jan-24",       # Month Sold
            "",             # Empty
            "123 Main St",  # Address Line 1
            "Unit 5",       # Address Line 2
            "Industrial Estate",  # Address Line 3
            "London",       # Town
            "Greater London",  # County
            "SW1A 1AA",     # Postcode
            "1100012314490",  # Mpan Top
            "04031N12",     # Mpan Bottom
            "", "",         # Empty
            "Renewals",     # Data Source
            "Yes",          # Welcome Call
            "DD",           # Payment Type
            "British Gas",  # Supplier
            "0.1",          # Net Notch
            "1 Year",       # In Contract
            "Sales Team",   # Agent Sold
            "01/01/2024",   # Start Date
            "31/12/2024",   # Contract End
            "45.13",        # Stand Charge
            "35.00",        # Rate 1
            "26.46",        # Rate 2
            "",             # Rate 3
            "", "",         # Empty
            "Online",       # Aggregator
            "25000",        # Annual Usage
            "£7.92",        # Comms Paid
            "12345678",     # Company Number
            "",             # Date of Birth
            "Barclays",     # Bank Name
            "12345678",     # Ac Number
            "20-00-00",     # Sort Code
            "",             # Charity/Ltd Company Number
            ""              # Partner Details
        ]
        
        for col, value in enumerate(example, 1):
            ws.cell(row=2, column=col, value=value)
        
        # Auto-adjust column widths
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[column].width = min(max_length + 2, 30)
        
        # Save to bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='cash2switch_renewals_template.xlsx'
        )
        
    except Exception as e:
        current_app.logger.exception(f"❌ Template download failed: {e}")
        return jsonify({'error': 'Failed to generate template'}), 500

@import_bp.route('/energy-clients/reset-sequence', methods=['POST'])
@jwt_required()
def reset_energy_client_sequence():
    """Reset the client_id sequence after deleting all customers"""
    current_user = get_jwt_identity()
    tenant_id = current_user.get('tenant_id')
    
    session = SessionLocal()  # ✅ Use SessionLocal instead of db.session
    
    try:
        # Reset Client_Master sequence
        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Client_Master"', 'client_id'),
                COALESCE((SELECT MAX(client_id) FROM "StreemLyne_MT"."Client_Master" WHERE tenant_id = :tenant_id), 0),
                true
            )
        """), {'tenant_id': tenant_id})
        
        # Reset Project_Details sequence
        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Project_Details"', 'project_id'),
                COALESCE((SELECT MAX(project_id) FROM "StreemLyne_MT"."Project_Details"), 0),
                true
            )
        """))
        
        # Reset Energy_Contract_Master sequence  
        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Energy_Contract_Master"', 'energy_contract_master_id'),
                COALESCE((SELECT MAX(energy_contract_master_id) FROM "StreemLyne_MT"."Energy_Contract_Master"), 0),
                true
            )
        """))
        
        session.commit()  # ✅ Changed from db.session.commit()
        
        return jsonify({
            'message': 'All sequences reset successfully',
            'success': True
        }), 200
        
    except Exception as e:
        session.rollback()  # ✅ Changed from db.session.rollback()
        logger.error(f"Error resetting sequences: {str(e)}")
        return jsonify({'error': 'Failed to reset sequences'}), 500
    finally:
        session.close()  # ✅ Always close the session

def handle_duplicate_customer(session, tenant_id, mpan_top, phone, new_end_date, new_client_id=None):
    """
    Check for existing customer by MPAN Top or Phone.
    If found, compare end dates and archive the older one.
    Returns: (should_archive_new, existing_client_id)
    """
    from datetime import datetime
    
    # Find existing customer by MPAN Top or Phone
    existing_query = session.query(
        Client_Master.client_id,
        Client_Master.client_company_name,
        Energy_Contract_Master.contract_end_date,
        Energy_Contract_Master.mpan_number
    ).join(
        Project_Details, Client_Master.client_id == Project_Details.client_id
    ).join(
        Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
    ).filter(
        Client_Master.tenant_id == tenant_id,
        Client_Master.is_deleted == False,
        Client_Master.is_archived == False,  # Only check non-archived records
        or_(
            Energy_Contract_Master.mpan_number == mpan_top,
            Client_Master.client_phone == phone
        )
    )
    
    # Exclude the current client if this is an update
    if new_client_id:
        existing_query = existing_query.filter(Client_Master.client_id != new_client_id)
    
    existing = existing_query.first()
    
    if not existing:
        return False, None  # No duplicate found
    
    existing_client_id, existing_name, existing_end_date, existing_mpan = existing
    
    # Compare end dates
    if not new_end_date and not existing_end_date:
        # Both have no end date - keep existing
        return True, existing_client_id
    
    if not new_end_date:
        # New has no end date - archive new, keep existing
        return True, existing_client_id
    
    if not existing_end_date:
        # Existing has no end date - archive existing, keep new
        return False, existing_client_id
    
    # Both have end dates - compare
    new_date = new_end_date if isinstance(new_end_date, datetime) else datetime.strptime(str(new_end_date), '%Y-%m-%d')
    existing_date = existing_end_date if isinstance(existing_end_date, datetime) else existing_end_date
    
    if new_date > existing_date:
        # New is more recent - archive existing
        current_app.logger.info(f"📦 Archiving older record: {existing_name} (End: {existing_end_date}) - New end date: {new_end_date}")
        return False, existing_client_id
    else:
        # Existing is more recent - archive new
        current_app.logger.info(f"📦 New record is older - will archive after creation (End: {new_end_date} vs {existing_end_date})")
        return True, existing_client_id


def archive_customer(session, client_id, reason="Superseded by newer contract"):
    """
    Archive a customer record
    """
    from datetime import datetime
    
    client = session.query(Client_Master).filter_by(client_id=client_id).first()
    if client:
        client.is_archived = True
        client.archived_at = datetime.utcnow()
        client.archived_reason = reason
        
        current_app.logger.info(f"📦 Archived client {client_id}: {client.client_company_name}")

@import_bp.route('/leads', methods=['POST', 'OPTIONS'])
@token_required
def import_leads():
    """
    Bulk import leads from Excel/CSV.
    Uses the same column map as /import/energy-customers but writes
    ONLY to Opportunity_Details (no Project_Details, no Energy_Contract_Master).
    This keeps leads separate from renewals.
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
    opportunity_owner_id = None if is_draft_import else (assigned_employee_id if assigned_employee_id else employee_id)
 
    # Get assigned employee name for response
    assigned_employee_name = None
    session = SessionLocal()
    try:
        if assigned_employee_id and not is_draft_import:
            ae = session.query(Employee_Master).filter_by(
                employee_id=assigned_employee_id,
                tenant_id=tenant_id
            ).first()
            if ae:
                assigned_employee_name = ae.employee_name
            else:
                return jsonify({'error': f'Invalid employee ID: {assigned_employee_id}'}), 400
 
        service_param = request.args.get('service', 'electricity')
        service_id_map = {'electricity': 1, 'utilities': 1, 'water': 2, 'gas': 3}
        import_service_id = service_id_map.get(service_param.strip().lower(), 1)
 
        # ── Read file ──────────────────────────────────────────────────────────
        file_ext = filename.rsplit('.', 1)[1].lower()
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp:
                file.save(tmp.name)
                tmp_path = tmp.name
            if file_ext == 'csv':
                df = pd.read_csv(tmp_path, encoding='utf-8-sig', dtype=str)
            else:
                try:
                    df = pd.read_excel(tmp_path, engine='openpyxl', dtype=str)
                except Exception:
                    df = pd.read_excel(tmp_path, engine='xlrd', dtype=str)
            os.unlink(tmp_path)
        except Exception as e:
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
 
        # ── Same column map as energy-customers import ─────────────────────────
        # Normalise headers first
        original_cols = list(df.columns)
        df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ').str.replace(r'\s+', ' ', regex=True)
 
        column_map = {
            'client_name':    ['client name', 'business name', 'company name'],
            'trading_name':   ['trading name', 'business', 'company'],
            'main_contact':   ['main contact', 'contact person', 'contact'],
            'position':       ['position', 'role', 'title'],
            'tel_no':         ['tel no', 'phone', 'telephone', 'tel'],
            'mobile_no':      ['mobile no', 'mobile', 'cell'],
            'email':          ['email', 'e-mail'],
            'site_name':      ['site name', 'site'],
            'month_sold':     ['month sold', 'sale month'],
            'house_name':     ['house name'],
            'house_number':   ['house number', 'house no'],
            'door_number':    ['door number'],
            'address_line_1': ['address line 1', 'address 1', 'street'],
            'address_line_2': ['address line 2', 'address 2'],
            'address_line_3': ['address line 3', 'address 3'],
            'town':           ['town', 'city'],
            'county':         ['county', 'region'],
            'postcode':       ['postcode', 'post code', 'zip', 'home post code', 'home postcode'],
            'home_door_number': ['home door number', 'home door no'],
            'home_street':    ['home street'],
            'mpan_top':       ['mpan top', 'mpan core'],
            'mpan_bottom':    ['mpan bottom', 'mpan llf'],
            'data_source':    ['data source'],
            'old_supplier':   ['old supplier'],
            'supplier':       ['supplier', 'supplier name'],
            'payment_type':   ['payment type'],
            'net_notch':      ['net notch'],
            'term_sold':      ['term sold', 'in contract', 'contract length'],
            'agent_sold':     ['agent sold'],
            'start_date':     ['start date', 'contract start'],
            'contract_end':   ['contract end', 'end date', 'expiry'],
            'stand_charge':   ['stand charge', 'standing charge'],
            'rate_1':         ['rate 1', 'unit rate', 'rate'],
            'rate_2':         ['rate 2'],
            'rate_3':         ['rate 3'],
            'aggregator':     ['aggregator'],
            'annual_usage':   ['annual usage', 'usage', 'kwh'],
            'comms_paid':     ['comms paid', 'commission'],
            'trading_type':   ['trading type'],
            'company_number': ['company number', 'co number'],
            'date_of_birth':  ['date of birth', 'dob'],
            'charity_ltd_company_number': ['charity/ltd company number', 'charity number'],
            'bank_name':      ['bank name', 'bank'],
            'ac_number':      ['ac number', 'account number'],
            'sort_code':      ['sort code'],
            'partner_details':['partner details', 'partner'],
            'partner_dob':    ['partner date of birth', 'partner dob'],
            'credit_score':   ['credit score'],
            'password':       ['password'],
        }
 
        actual_columns = {}
        for field, aliases in column_map.items():
            for col in df.columns:
                if col in aliases:
                    actual_columns[field] = col
                    break
 
        # Restore original column names
        df.columns = original_cols
 
        # Rebuild mapping with original-cased column names
        norm_to_orig = {}
        for orig in original_cols:
            normed = orig.strip().lower().replace('_', ' ')
            import re
            normed = re.sub(r'\s+', ' ', normed)
            norm_to_orig[normed] = orig
 
        actual_columns_orig = {}
        for field, normed_col in actual_columns.items():
            actual_columns_orig[field] = norm_to_orig.get(normed_col, normed_col)
 
        def gcol(field):
            return actual_columns_orig.get(field, '')
 
        # Get default stage_id for leads
        from ..models import Stage_Master
        default_stage = session.query(Stage_Master).order_by(Stage_Master.stage_id).first()
        default_stage_id = default_stage.stage_id if default_stage else 1
 
        # ── Pre-load existing lead MPANs for duplicate checking ────────────────
        existing_lead_mpans = {}
        existing_leads_rows = session.execute(text("""
            SELECT od."mpan_mpr", od."tenant_id", od."business_name", od."opportunity_title"
            FROM "StreemLyne_MT"."Opportunity_Details" od
            WHERE od."mpan_mpr" IS NOT NULL AND od."mpan_mpr" != ''
            AND NOT EXISTS (
                SELECT 1 FROM "StreemLyne_MT"."Project_Details" pd
                WHERE pd.opportunity_id = od.opportunity_id
            )
        """)).fetchall()
 
        for lead_row in existing_leads_rows:
            mpan_key = lead_row[0].strip().lower()
            if mpan_key not in existing_lead_mpans:
                existing_lead_mpans[mpan_key] = []
            existing_lead_mpans[mpan_key].append({
                'tenant_id': lead_row[1],
                'business_name': lead_row[2] or lead_row[3],
            })
 
        current_app.logger.info(f"📊 Loaded {len(existing_lead_mpans)} existing lead MPANs for duplicate checking")
 
        # Duplicate tracking
        lead_duplicate_details = []
        lead_cross_tenant_duplicates = []
        lead_duplicate_count = 0
 
        # ── Process rows ───────────────────────────────────────────────────────
        total_rows = len(df)
        success_count = 0
        error_count = 0
        errors = []
 
        for index, row in df.iterrows():
            try:
                client_name    = safe_str(row.get(gcol('client_name'), ''))
                trading_name   = safe_str(row.get(gcol('trading_name'), ''))
                main_contact   = safe_str(row.get(gcol('main_contact'), ''))
                tel_no         = safe_str(row.get(gcol('tel_no'), ''))
                mobile_no      = safe_str(row.get(gcol('mobile_no'), ''))
                email          = safe_str(row.get(gcol('email'), ''))
                mpan_top       = safe_str(row.get(gcol('mpan_top'), ''))
                mpan_bottom    = safe_str(row.get(gcol('mpan_bottom'), ''))
                supplier_name  = safe_str(row.get(gcol('supplier'), ''))
                start_date     = parse_date(row.get(gcol('start_date'), ''))
                end_date       = parse_date(row.get(gcol('contract_end'), ''))
                annual_usage   = parse_number(row.get(gcol('annual_usage'), ''))
                payment_type   = safe_str(row.get(gcol('payment_type'), ''))
                site_name      = safe_str(row.get(gcol('site_name'), ''))
                town           = safe_str(row.get(gcol('town'), ''))
                county         = safe_str(row.get(gcol('county'), ''))
                postcode       = safe_str(row.get(gcol('postcode'), ''))
                addr1          = safe_str(row.get(gcol('address_line_1'), ''))
                position       = safe_str(row.get(gcol('position'), ''))
                month_sold     = safe_str(row.get(gcol('month_sold'), ''))
                house_name     = safe_str(row.get(gcol('house_name'), ''))
                house_number   = safe_str(row.get(gcol('house_number'), ''))
                door_number    = safe_str(row.get(gcol('door_number'), ''))
                addr2          = safe_str(row.get(gcol('address_line_2'), ''))
                addr3          = safe_str(row.get(gcol('address_line_3'), ''))
 
                business_name  = trading_name or client_name
                contact_person = main_contact or client_name
                phone          = tel_no or mobile_no
 
                # Skip blank rows
                if not business_name and not phone and not email and not mpan_top and not contact_person:
                    continue
 
                # ── Duplicate check ────────────────────────────────────────────
                if mpan_top:
                    mpan_key = mpan_top.strip().lower()
                    existing_records = existing_lead_mpans.get(mpan_key)

                    if existing_records:
                        lead_duplicate_count += 1

                        cross_tenant = None
                        same_tenant = None

                        for rec in existing_records:
                            if rec['tenant_id'] != tenant_id:
                                cross_tenant = rec
                                break
                            else:
                                same_tenant = rec

                        # Cross-tenant: always skip
                        if cross_tenant:
                            lead_cross_tenant_duplicates.append({
                                'row': index + 2,
                                'mpan': mpan_top,
                                'new_company': business_name,
                                'existing_company': cross_tenant['business_name'],
                            })
                            current_app.logger.info(f"⚠️ Row {index + 2}: Cross-tenant duplicate - skipping")
                            continue

                        # Same-tenant: skip ALL duplicates (assigned or not)
                        if same_tenant:
                            assigned_status = f" (assigned to ID {same_tenant['assigned_to_id']})" if same_tenant['assigned_to_id'] else " (draft)"
                            lead_duplicate_details.append({
                                'row': index + 2,
                                'mpan': mpan_top,
                                'company': business_name,
                                'action': f'Duplicate MPAN{assigned_status} - skipped',
                            })
                            current_app.logger.info(f"⏭️ Row {index + 2}: Same-tenant duplicate{assigned_status} - skipping")
                            continue
 
                # Find supplier_id if supplier name provided
                supplier_id = None
                if supplier_name:
                    sup = session.query(Supplier_Master).filter(
                        Supplier_Master.supplier_company_name.ilike(f'%{supplier_name}%')
                    ).first()
                    if sup:
                        supplier_id = sup.supplier_id
 
                # ✅ INSERT ONLY INTO Opportunity_Details — no Client_Master, no Project_Details
                result = session.execute(text("""
                    INSERT INTO "StreemLyne_MT"."Opportunity_Details"
                    (tenant_id, client_id, opportunity_title, opportunity_description,
                    opportunity_date, opportunity_owner_employee_id, stage_id,
                    opportunity_value, currency_id, created_at, "Misc_Col1",
                    business_name, contact_person, tel_number, mobile_no, email,
                    mpan_mpr, mpan_bottom, start_date, end_date, service_id,
                    supplier_id, annual_usage, stand_charge, rate_1, rate_2,
                    rate_3, net_notch, payment_type, postcode, is_draft)  -- ✅ ADD is_draft HERE
                    VALUES
                    (:tenant_id, NULL, :title, 'Imported lead',
                    :opp_date, :owner_id, :stage_id,
                    0, 1, :created_at, NULL,
                    :business_name, :contact_person, :tel_number, :mobile_no, :email,
                    :mpan_mpr, :mpan_bottom, :start_date, :end_date, :service_id,
                    :supplier_id, :annual_usage, :stand_charge, :rate_1, :rate_2,
                    :rate_3, :net_notch, :payment_type, :postcode, :is_draft)  -- ✅ ADD :is_draft HERE
                """), {
                    'tenant_id': tenant_id,
                    'title': business_name or '',
                    'opp_date': datetime.utcnow().date(),
                    'owner_id': opportunity_owner_id,
                    'stage_id': default_stage_id,
                    'created_at': datetime.utcnow(),
                    'business_name': business_name or None,
                    'contact_person': contact_person or None,
                    'tel_number': phone or None,
                    'mobile_no': mobile_no or None,
                    'email': email or None,
                    'mpan_mpr': mpan_top or None,
                    'mpan_bottom': mpan_bottom or None,
                    'start_date': start_date,
                    'end_date': end_date,
                    'service_id': import_service_id,
                    'supplier_id': supplier_id,
                    'annual_usage': int(annual_usage) if annual_usage else None,
                    'stand_charge': parse_number(row.get(gcol('stand_charge'), '')),
                    'rate_1': parse_number(row.get(gcol('rate_1'), '')),
                    'rate_2': parse_number(row.get(gcol('rate_2'), '')),
                    'rate_3': parse_number(row.get(gcol('rate_3'), '')),
                    'net_notch': parse_number(row.get(gcol('net_notch'), '')),
                    'payment_type': payment_type or None,
                    'postcode': postcode or None,
                    'is_draft': is_draft_import,  # ✅ ADD THIS PARAMETER
                })
                session.flush()
                success_count += 1
 
                # ✅ Register newly imported MPAN so subsequent rows in same file are checked
                if mpan_top:
                    mpan_key = mpan_top.strip().lower()
                    if mpan_key not in existing_lead_mpans:
                        existing_lead_mpans[mpan_key] = []
                    existing_lead_mpans[mpan_key].append({
                        'tenant_id': tenant_id,
                        'business_name': business_name,
                    })
 
                if success_count % 50 == 0:
                    session.commit()
 
            except Exception as row_err:
                session.rollback()
                error_count += 1
                err_str = str(row_err).split('\n')[0][:150]
                errors.append(f"Row {index + 2}: {err_str}")
                continue
 
        # Final commit
        try:
            session.commit()
        except Exception:
            session.rollback()
 
        current_app.logger.info(f"✅ Leads import: {success_count} inserted, {lead_duplicate_count} duplicates, {error_count} errors")
 
        # ── Build duplicate report ─────────────────────────────────────────────
        duplicate_report = []
        if lead_duplicate_details:
            duplicate_report.append("📋 SAME-TENANT DUPLICATES:")
            for d in lead_duplicate_details:
                duplicate_report.append(f"  Row {d['row']}: {d['company']} (MPAN: {d['mpan']}) — {d['action']}")
        if lead_cross_tenant_duplicates:
            duplicate_report.append("⚠️ CROSS-TENANT DUPLICATES (SKIPPED):")
            for d in lead_cross_tenant_duplicates:
                duplicate_report.append(f"  Row {d['row']}: {d['new_company']} (MPAN: {d['mpan']}) — exists in another account")
 
        return jsonify({
            'success': True,
            'message': 'Import completed',
            'total_rows': total_rows,
            'successful': success_count,
            'duplicates': lead_duplicate_count,
            'same_tenant_duplicates': len(lead_duplicate_details),
            'cross_tenant_duplicates': len(lead_cross_tenant_duplicates),
            'failed': error_count,
            'errors': errors[:50],
            'duplicate_report': duplicate_report,
            'assigned_to': assigned_employee_name,
            'assigned_employee_id': opportunity_owner_id,
            'is_draft': is_draft_import,
        }), 200
 
    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        current_app.logger.error(f"❌ Leads import failed: {str(e)}")
        return jsonify({'error': f'Import failed: {str(e)}'}), 500
    finally:
        session.close()

@import_bp.route('/leads/template', methods=['GET'])
@token_required
def download_leads_template():
    return download_leads_template_handler()