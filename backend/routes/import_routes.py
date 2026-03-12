"""
Bulk Import Route for Energy Customers
Handles Excel/CSV uploads and bulk insertion into database
"""

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import and_, or_, text
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging
import tempfile

from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Opportunity_Details, Supplier_Master, Employee_Master, Services_Master
)
from .auth_helpers import token_required
from ..db import SessionLocal

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

def find_supplier_id(supplier_name, session):
    """Find supplier ID by name (case-insensitive, fuzzy matching)"""
    if not supplier_name or pd.isna(supplier_name):
        return None
    
    supplier_name = str(supplier_name).strip()
    
    # Try exact match first
    supplier = session.query(Supplier_Master).filter(
        Supplier_Master.supplier_company_name.ilike(f'%{supplier_name}%')
    ).first()
    
    if supplier:
        return supplier.supplier_id
    
    # Try extracting name before parenthesis (e.g., "THRE (Corona Energy)" -> "THRE")
    if '(' in supplier_name:
        short_name = supplier_name.split('(')[0].strip()
        supplier = session.query(Supplier_Master).filter(
            Supplier_Master.supplier_company_name.ilike(f'%{short_name}%')
        ).first()
        if supplier:
            return supplier.supplier_id
    
    # Try extracting name in parenthesis (e.g., "THRE (Corona Energy)" -> "Corona Energy")
    if '(' in supplier_name and ')' in supplier_name:
        paren_name = supplier_name.split('(')[1].split(')')[0].strip()
        supplier = session.query(Supplier_Master).filter(
            Supplier_Master.supplier_company_name.ilike(f'%{paren_name}%')
        ).first()
        if supplier:
            return supplier.supplier_id
    
    # Try first word only (e.g., "British Gas Business" -> "British")
    first_word = supplier_name.split()[0] if supplier_name.split() else supplier_name
    if len(first_word) > 3:  # Only try if word is longer than 3 chars
        supplier = session.query(Supplier_Master).filter(
            Supplier_Master.supplier_company_name.ilike(f'{first_word}%')
        ).first()
        if supplier:
            return supplier.supplier_id
    
    return None


def get_or_create_supplier(supplier_name, session):
    """Get existing supplier or create new one if doesn't exist"""
    if not supplier_name or pd.isna(supplier_name):
        return 1  # Return default supplier_id
    
    supplier_name = str(supplier_name).strip()
    
    # Try to find existing supplier
    supplier_id = find_supplier_id(supplier_name, session)
    if supplier_id:
        return supplier_id
    
    # Supplier doesn't exist - create it
    try:
        new_supplier = Supplier_Master(
            supplier_company_name=supplier_name,
            supplier_contact_name='Auto-imported',
            supplier_provisions=3,  # Default: Electricity & Gas
            created_at=datetime.utcnow()
        )
        session.add(new_supplier)
        session.flush()
        
        current_app.logger.info(f"✨ Created new supplier: {supplier_name} (ID: {new_supplier.supplier_id})")
        return new_supplier.supplier_id
    except Exception as e:
        current_app.logger.error(f"Failed to create supplier {supplier_name}: {e}")
        return 1  # Fallback to default


def get_or_create_service(tenant_id, session):
    """Get existing default service or create one if doesn't exist"""
    # Try to find existing service for this tenant
    service = session.query(Services_Master).filter_by(
        tenant_id=tenant_id,
        service_title='Default Energy Service'
    ).first()
    
    if service:
        return service.service_id
    
    # Try to get any service for this tenant
    service = session.query(Services_Master).filter_by(tenant_id=tenant_id).first()
    if service:
        return service.service_id
    
    # No service exists - create default one
    try:
        new_service = Services_Master(
            tenant_id=tenant_id,
            service_title='Default Energy Service',
            service_description='Auto-created default service for energy contracts',
            service_rate=0.0,
            currency_id=1,
            supplier_id=None,
            date_from=None,
            date_to=None,
            created_at=datetime.utcnow(),
            service_code='DEFAULT'
        )
        session.add(new_service)
        session.flush()
        
        current_app.logger.info(f"✨ Created default service for tenant {tenant_id} (ID: {new_service.service_id})")
        return new_service.service_id
    except Exception as e:
        current_app.logger.error(f"Failed to create default service: {e}")
        return 1  # Fallback to ID 1

# def parse_date(date_value):
#     """Parse date from various formats - prioritize DD/MM/YYYY (UK format)"""
#     if pd.isna(date_value) or not date_value:
#         return None
    
#     if isinstance(date_value, datetime):
#         return date_value.date()
    
#     date_str = str(date_value).strip()
    
#     # ✅ UPDATED: Prioritize UK date formats (DD/MM/YYYY)
#     date_formats = [
#         '%d/%m/%Y',      
#         '%d-%m-%Y',      
#         '%d.%m.%Y',      
#         '%d %b %Y',      
#         '%d %B %Y',      
#         '%Y-%m-%d',      
#         '%m/%d/%Y',      
#         '%Y/%m/%d',
#     ]
    
#     for fmt in date_formats:
#         try:
#             return datetime.strptime(date_str, fmt).date()
#         except ValueError:
#             continue
    
#     return None

def parse_date(date_value):
    """Parse date from various formats - prioritize DD/MM/YYYY (UK format)"""
    if pd.isna(date_value) or not date_value or date_value == '':
        return None
    
    if isinstance(date_value, datetime):
        return date_value.date()
    
    date_str = str(date_value).strip()
    
    # Skip empty or 'nan' strings
    if not date_str or date_str.lower() == 'nan':
        return None
    
    # ✅ Prioritize UK date formats (DD/MM/YYYY) + datetime formats
    date_formats = [
        '%Y-%m-%d %H:%M:%S',  # ✅ ADD THIS FIRST - Excel datetime format
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

# def parse_number(value):
#     """Parse number from string (handles commas, etc.)"""
#     if pd.isna(value) or not value:
#         return None
    
#     try:
#         # Remove commas and convert to float
#         cleaned = str(value).replace(',', '').strip()
#         return float(cleaned) if cleaned else None
#     except (ValueError, AttributeError):
#         return None

def parse_number(value):
    """Parse number from string (handles commas, etc.)"""
    if pd.isna(value) or not value or value == '':
        return None
    
    try:
        # Remove commas and convert to float
        cleaned = str(value).replace(',', '').strip()
        
        # ✅ Handle empty string after cleaning
        if not cleaned or cleaned == 'nan':
            return None
            
        return float(cleaned) if cleaned else None
    except (ValueError, AttributeError):
        return None


@import_bp.route('/energy-customers', methods=['POST', 'OPTIONS'])
@token_required
def import_energy_customers():
    """
    Bulk import energy customers from Excel/CSV file with optional assignment
    ⚡ HANDLES UNLIMITED RECORDS: Individual commits prevent timeouts
    """
    print("\n\n🔥🔥🔥 IMPORT FUNCTION CALLED! 🔥🔥🔥\n\n")
    
    if request.method == 'OPTIONS':
        print("OPTIONS request - returning")
        return jsonify({}), 200
    
    print("Creating session...")
    session = SessionLocal()
    
    print("Setting up logging...")
    import logging
    sql_logger = logging.getLogger('sqlalchemy.engine')
    original_level = sql_logger.level
    sql_logger.setLevel(logging.WARNING)
    
    try:
        print("Checking for file...")
        if 'file' not in request.files:
            print("ERROR: No file uploaded")
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        print(f"File received: {file.filename}")
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload .xlsx, .xls, or .csv'}), 400
        
        # Get tenant and user info
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
        
        employee_id = request.current_user.employee_id

        # GET ASSIGNED EMPLOYEE ID FROM FORM DATA
        assigned_employee_id = request.form.get('assigned_employee_id', type=int)
        opportunity_owner_id = assigned_employee_id if assigned_employee_id else employee_id
        
        # Get employee name for success message
        assigned_employee_name = None
        if assigned_employee_id:
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
        print(f"   Assigned to: {assigned_employee_name or 'Uploader'} (ID: {opportunity_owner_id})")
        print(f"{'='*60}\n")

        # Service filter
        service_param = request.args.get('service', 'utilities')
        service_id_map = {
            'utilities': 1,
            'electricity': 1, 
            'water': 2,
            'gas': 3
        }
        import_service_id = service_id_map.get(service_param.strip().lower(), 1)
        
        # Read file
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
                    
        # Normalize column names
        df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ').str.replace(r'\s+', ' ', regex=True)
        
        # Column mapping
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
            'address_line_1': ['address line 1', 'address 1', 'street'],  
            'address_line_2': ['address line 2', 'address 2'],
            'address_line_3': ['address line 3', 'address 3'],
            'town': ['town', 'city'],
            'county': ['county', 'region'],
            'postcode': ['postcode', 'post code', 'zip'],
            'mpan_top': ['mpan top', 'mpan core'],
            'mpan_bottom': ['mpan bottom', 'mpan llf'],
            'old_supplier': ['old supplier'],  
            'supplier': ['supplier', 'supplier name'],
            'net_notch': ['net notch'],
            'term_sold': ['term sold', 'in contract', 'contract length'],  
            'start_date': ['start date', 'contract start'],
            'contract_end': ['contract end', 'end date', 'expiry'],
            'stand_charge': ['stand charge', 'standing charge'],
            'rate_1': ['rate 1', 'unit rate', 'rate'],
            'rate_2': ['rate 2'],
            'rate_3': ['rate 3'],
            'aggregator': ['aggregator'],
            'annual_usage': ['annual usage', 'usage', 'kwh'],
            'comms_paid': ['comms paid', 'commission'],
            'company_number': ['company number', 'co number'],
            'date_of_birth': ['date of birth', 'dob'],
            'bank_name': ['bank name', 'bank'],
            'ac_number': ['ac number', 'account number'],
            'sort_code': ['sort code'],
            'charity_ltd_company_number': ['charity/ltd company number', 'charity number'],
            'partner_details': ['partner details', 'partner'],
            'door_number': ['door number', 'door no'],
            'payment_type': ['payment type'],  
            'trading_type': ['trading type'],  
        }
        
        actual_columns = {}
        for field, possible_names in column_map.items():
            for col in df.columns:
                if col in possible_names:
                    actual_columns[field] = col
                    break

        def safe_str(value):
            if pd.isna(value) or value is None or value == '':
                return ''
            
            str_value = str(value).strip()
            
            # Remove .0 suffix from numeric strings
            if str_value.endswith('.0') and str_value[:-2].replace('.', '', 1).isdigit():
                str_value = str_value[:-2]
            
            return str_value
        
        # PRE-LOAD SUPPLIERS
        suppliers_dict = {}
        suppliers = session.query(Supplier_Master).all()
        for s in suppliers:
            suppliers_dict[s.supplier_company_name.lower().strip()] = s.supplier_id
        
        print(f"📊 Loaded {len(suppliers_dict)} suppliers for matching")
        
        # PRE-LOAD EXISTING MPANs
        existing_mpans = {}
        existing_contracts = session.query(Energy_Contract_Master).all()
        for contract in existing_contracts:
            if contract.mpan_number:
                existing_mpans[contract.mpan_number.strip().lower()] = contract

        print(f"📊 Loaded {len(existing_mpans)} existing MPANs for duplicate checking")
        
        # PROCESS EACH RECORD
        total_rows = len(df)
        success_count = 0
        error_count = 0
        duplicate_count = 0
        errors = []
        BATCH_SIZE = 50
        
        print(f"📊 Starting import of {total_rows} rows (individual commits)")
        
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

                # Address fields
                address_line_1 = safe_str(row.get(actual_columns.get('address_line_1', ''), ''))
                address_line_2 = safe_str(row.get(actual_columns.get('address_line_2', ''), ''))
                address_line_3 = safe_str(row.get(actual_columns.get('address_line_3', ''), ''))
                town = safe_str(row.get(actual_columns.get('town', ''), ''))
                county = safe_str(row.get(actual_columns.get('county', ''), ''))
                postcode = safe_str(row.get(actual_columns.get('postcode', ''), ''))

                address_parts = [p for p in [address_line_1, address_line_2, address_line_3, town, county] if p and p.lower() != 'nan']
                address = ', '.join(address_parts)
                site_address = site_name or address

                # MPAN fields
                mpan_top = safe_str(row.get(actual_columns.get('mpan_top', ''), ''))
                mpan_bottom = safe_str(row.get(actual_columns.get('mpan_bottom', ''), ''))

                # Contract fields
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

                # Get or create supplier
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
                            print(f"✨ Row {index + 2}: Created new supplier '{supplier_name}' (ID: {supplier_id})")
                            
                        except Exception as e:
                            print(f"❌ Row {index + 2}: Failed to create supplier '{supplier_name}': {e}")
                            supplier_id = 1
                else:
                    supplier_id = 1

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
                        except Exception as e:
                            print(f"Failed to create old supplier: {e}")

                business_name = trading_name or client_name
                contact_person = main_contact or client_name
                phone = tel_no or mobile_no

                # Skip empty rows
                if not business_name and not phone and not email and not mpan_top and not contact_person:
                    continue
                
                # CHECK DUPLICATES WITH ARCHIVING
                if mpan_top:
                    mpan_key = mpan_top.strip().lower()
                    existing_contract = existing_mpans.get(mpan_key)
                    
                    if existing_contract:
                        duplicate_count += 1
                        
                        project = session.query(Project_Details).filter_by(
                            project_id=existing_contract.project_id
                        ).first()
                        
                        if not project:
                            session.rollback()
                            error_count += 1
                            errors.append(f"Row {index + 2}: Project not found for MPAN {mpan_top}")
                            continue
                        
                        client = session.query(Client_Master).filter_by(
                            client_id=project.client_id
                        ).first()
                        
                        if not client:
                            session.rollback()
                            error_count += 1
                            errors.append(f"Row {index + 2}: Client not found for MPAN {mpan_top}")
                            continue
                        
                        new_end_date = end_date
                        existing_end_date = existing_contract.contract_end_date
                        
                        if not new_end_date:
                            print(f"⏭️ Row {index + 2}: Skipping - no end date in new record for MPAN {mpan_top}")
                            continue
                        
                        if existing_end_date and new_end_date < existing_end_date:
                            print(f"⏭️ Row {index + 2}: Skipping - new end date {new_end_date} is older than existing {existing_end_date}")
                            continue
                        
                        if existing_end_date and new_end_date == existing_end_date:
                            print(f"🔄 Row {index + 2}: Updating existing record (same end date {new_end_date}) for MPAN {mpan_top}")
                            
                            # Update existing record
                            client.client_company_name = business_name or client.client_company_name
                            client.client_contact_name = contact_person or client.client_contact_name
                            client.client_phone = phone or client.client_phone
                            client.client_email = email or client.client_email
                            client.address = address or client.address
                            client.post_code = postcode or client.post_code
                            client.position = position or client.position
                            client.company_number = company_number or client.company_number
                            client.date_of_birth = date_of_birth or client.date_of_birth
                            client.charity_ltd_company_number = charity_ltd_company_number or client.charity_ltd_company_number
                            client.partner_details = partner_details or client.partner_details
                            client.bank_name = bank_name or client.bank_name
                            client.account_number = account_number or client.account_number
                            client.sort_code = sort_code or client.sort_code
                            
                            project.address = site_address or address or project.address
                            project.Misc_Col2 = int(annual_usage) if annual_usage else project.Misc_Col2
                            project.start_date = start_date or project.start_date
                            project.end_date = end_date or project.end_date
                            project.site_name = site_name or project.site_name
                            project.month_sold = month_sold or project.month_sold
                            project.house_name = house_name or project.house_name
                            project.house_number = house_number or project.house_number
                            project.door_number = door_number or project.door_number
                            project.town = town or project.town
                            project.county = county or project.county
                            project.updated_at = datetime.utcnow()
                            
                            existing_contract.contract_start_date = start_date or existing_contract.contract_start_date
                            if supplier_id:
                                existing_contract.supplier_id = supplier_id
                            if old_supplier_id:
                                existing_contract.old_supplier_id = old_supplier_id
                            existing_contract.unit_rate = rate_1 or existing_contract.unit_rate
                            existing_contract.rate_1 = rate_1 or existing_contract.rate_1
                            existing_contract.rate_2 = rate_2 or existing_contract.rate_2
                            existing_contract.rate_3 = rate_3 or existing_contract.rate_3
                            existing_contract.standing_charge = stand_charge or existing_contract.standing_charge
                            existing_contract.net_notch = net_notch or existing_contract.net_notch
                            existing_contract.comms_paid = comms_paid or existing_contract.comms_paid
                            existing_contract.aggregator = aggregator or existing_contract.aggregator
                            existing_contract.term_sold = term_sold or existing_contract.term_sold
                            existing_contract.mpan_bottom = mpan_bottom or existing_contract.mpan_bottom
                            existing_contract.updated_at = datetime.utcnow()
                            
                            opportunity = session.query(Opportunity_Details).filter_by(
                                client_id=client.client_id
                            ).first()
                            
                            if not opportunity:
                                opportunity = Opportunity_Details(
                                    client_id=client.client_id,
                                    opportunity_title=f"Opportunity - {client.client_company_name}",
                                    opportunity_description='Imported from bulk upload',
                                    opportunity_date=datetime.utcnow().date(),
                                    opportunity_owner_employee_id=opportunity_owner_id,
                                    stage_id=1,
                                    opportunity_value=0,
                                    currency_id=1,
                                    created_at=datetime.utcnow(),
                                    Misc_Col1=None
                                )
                                session.add(opportunity)
                            elif assigned_employee_id:
                                opportunity.opportunity_owner_employee_id = opportunity_owner_id
                            
                            session.commit()
                            print(f"✅ Row {index + 2}: Updated existing record for MPAN {mpan_top}")
                            
                            if (success_count + duplicate_count) % 100 == 0:
                                print(f"📊 Progress: {success_count + duplicate_count}/{total_rows}")
                            
                            continue
                        
                        # New is NEWER - Archive old snapshot, update existing
                        if new_end_date > existing_end_date:
                            print(f"\n\n🔥 ARCHIVING TRIGGERED for MPAN {mpan_top}! 🔥\n\n")
                            print(f"\n{'='*60}")
                            print(f"📦 ARCHIVING LOGIC TRIGGERED")
                            print(f"   Row: {index + 2}")
                            print(f"   MPAN: {mpan_top}")
                            print(f"   Existing end date: {existing_end_date}")
                            print(f"   New end date: {new_end_date}")
                            print(f"   Existing client_id: {client.client_id}")
                            print(f"   Existing project_id: {project.project_id}")
                            print(f"   Existing contract_id: {existing_contract.energy_contract_master_id}")
                            print(f"{'='*60}\n")
                            
                            try:
                                # CREATE ARCHIVED SNAPSHOT
                                archived_client = Client_Master(
                                    tenant_id=client.tenant_id,
                                    assigned_employee_id=client.assigned_employee_id,
                                    client_company_name=client.client_company_name,
                                    client_contact_name=client.client_contact_name,
                                    address=client.address,
                                    post_code=client.post_code,
                                    client_phone=client.client_phone,
                                    client_email=client.client_email,
                                    client_website=client.client_website,
                                    default_currency_id=client.default_currency_id,
                                    position=client.position,
                                    company_number=client.company_number,
                                    date_of_birth=client.date_of_birth,
                                    charity_ltd_company_number=client.charity_ltd_company_number,
                                    partner_details=client.partner_details,
                                    bank_name=client.bank_name,
                                    account_number=client.account_number,
                                    sort_code=client.sort_code,
                                    created_at=client.created_at,
                                    is_archived=True,
                                    archived_at=datetime.utcnow(),
                                    archived_reason=f"Historical record (ended {existing_end_date}) - superseded by contract ending {new_end_date}"
                                )
                                session.add(archived_client)
                                session.flush()
                                
                                archived_client_id = archived_client.client_id
                                print(f"✅ Created archived client (ID: {archived_client_id})")
                                
                                # Clone Project
                                opportunity = session.query(Opportunity_Details).filter_by(
                                    client_id=client.client_id
                                ).first()

                                archived_opportunity = None
                                if opportunity:
                                    archived_opportunity = Opportunity_Details(
                                        client_id=archived_client_id,
                                        opportunity_title=opportunity.opportunity_title,
                                        opportunity_description=opportunity.opportunity_description,
                                        opportunity_date=opportunity.opportunity_date,
                                        opportunity_owner_employee_id=opportunity.opportunity_owner_employee_id,
                                        stage_id=opportunity.stage_id,
                                        opportunity_value=opportunity.opportunity_value,
                                        currency_id=opportunity.currency_id,
                                        Misc_Col1=opportunity.Misc_Col1,
                                        created_at=opportunity.created_at
                                    )
                                    session.add(archived_opportunity)
                                    session.flush()
                                    print(f"✅ Created archived opportunity (ID: {archived_opportunity.opportunity_id})")

                                # Clone Project (with opportunity_id now available)
                                archived_project = Project_Details(
                                    client_id=archived_client_id,
                                    opportunity_id=archived_opportunity.opportunity_id if archived_opportunity else None,  # ✅ SET THIS
                                    project_title=project.project_title,
                                    project_description=project.project_description,
                                    address=project.address,
                                    Misc_Col2=project.Misc_Col2,
                                    site_name=project.site_name,
                                    month_sold=project.month_sold,
                                    house_name=project.house_name,
                                    house_number=project.house_number,
                                    door_number=project.door_number,
                                    town=project.town,
                                    county=project.county,
                                    start_date=project.start_date,
                                    end_date=project.end_date,
                                    employee_id=project.employee_id,
                                    created_at=project.created_at,
                                    updated_at=datetime.utcnow()
                                )
                                session.add(archived_project)
                                session.flush()
                                print(f"✅ Created archived project (ID: {archived_project.project_id})")
                                
                                # Clone Contract
                                archived_contract = Energy_Contract_Master(
                                    project_id=archived_project.project_id,
                                    employee_id=existing_contract.employee_id,
                                    supplier_id=existing_contract.supplier_id,
                                    old_supplier_id=existing_contract.old_supplier_id,
                                    mpan_number=existing_contract.mpan_number,
                                    mpan_bottom=existing_contract.mpan_bottom,
                                    contract_start_date=existing_contract.contract_start_date,
                                    contract_end_date=existing_contract.contract_end_date,
                                    unit_rate=existing_contract.unit_rate,
                                    rate_1=existing_contract.rate_1,
                                    rate_2=existing_contract.rate_2,
                                    rate_3=existing_contract.rate_3,
                                    standing_charge=existing_contract.standing_charge,
                                    net_notch=existing_contract.net_notch,
                                    comms_paid=existing_contract.comms_paid,
                                    aggregator=existing_contract.aggregator,
                                    term_sold=existing_contract.term_sold,
                                    service_id=existing_contract.service_id,
                                    currency_id=existing_contract.currency_id,
                                    terms_of_sale=existing_contract.terms_of_sale,
                                    created_at=existing_contract.created_at,
                                    updated_at=datetime.utcnow()
                                )
                                session.add(archived_contract)
                                session.flush()
                                print(f"✅ Created archived contract (ID: {archived_contract.energy_contract_master_id})")
                                
                                # Clone Opportunity
                                opportunity = session.query(Opportunity_Details).filter_by(
                                    client_id=client.client_id
                                ).first()
                                
                                if opportunity:
                                    archived_opportunity = Opportunity_Details(
                                        client_id=archived_client_id,
                                        opportunity_title=opportunity.opportunity_title,
                                        opportunity_description=opportunity.opportunity_description,
                                        opportunity_date=opportunity.opportunity_date,
                                        opportunity_owner_employee_id=opportunity.opportunity_owner_employee_id,
                                        stage_id=opportunity.stage_id,
                                        opportunity_value=opportunity.opportunity_value,
                                        currency_id=opportunity.currency_id,
                                        Misc_Col1=opportunity.Misc_Col1,
                                        created_at=opportunity.created_at
                                    )
                                    session.add(archived_opportunity)
                                    session.flush()
                                    archived_project.opportunity_id = archived_opportunity.opportunity_id
                                    print(f"✅ Created archived opportunity (ID: {archived_opportunity.opportunity_id})")
                                
                                print(f"📦 Archive snapshot complete")
                                
                                # UPDATE EXISTING WITH NEW DATA
                                print(f"🔄 Now updating existing client {client.client_id} with new data...")
                                
                                client.client_company_name = business_name or client.client_company_name
                                client.client_contact_name = contact_person or client.client_contact_name
                                client.client_phone = phone or client.client_phone
                                client.client_email = email or client.client_email
                                client.address = address or client.address
                                client.post_code = postcode or client.post_code
                                client.position = position
                                client.company_number = company_number
                                client.date_of_birth = date_of_birth
                                client.charity_ltd_company_number = charity_ltd_company_number
                                client.partner_details = partner_details
                                client.bank_name = bank_name
                                client.account_number = account_number
                                client.sort_code = sort_code
                                
                                project.address = site_address or address or project.address
                                project.Misc_Col2 = int(annual_usage) if annual_usage else project.Misc_Col2
                                project.start_date = start_date or project.start_date
                                project.end_date = end_date
                                project.site_name = site_name
                                project.month_sold = month_sold
                                project.house_name = house_name
                                project.house_number = house_number
                                project.door_number = door_number
                                project.town = town
                                project.county = county
                                project.updated_at = datetime.utcnow()
                                
                                if supplier_id:
                                    existing_contract.supplier_id = supplier_id
                                if old_supplier_id:
                                    existing_contract.old_supplier_id = old_supplier_id
                                existing_contract.contract_start_date = start_date or existing_contract.contract_start_date
                                existing_contract.contract_end_date = end_date
                                existing_contract.unit_rate = rate_1 or existing_contract.unit_rate
                                existing_contract.rate_1 = rate_1 or existing_contract.rate_1
                                existing_contract.rate_2 = rate_2 or existing_contract.rate_2
                                existing_contract.rate_3 = rate_3 or existing_contract.rate_3
                                existing_contract.standing_charge = stand_charge or existing_contract.standing_charge
                                existing_contract.net_notch = net_notch or existing_contract.net_notch
                                existing_contract.comms_paid = comms_paid or existing_contract.comms_paid
                                existing_contract.aggregator = aggregator or existing_contract.aggregator
                                existing_contract.term_sold = term_sold or existing_contract.term_sold
                                existing_contract.mpan_bottom = mpan_bottom or existing_contract.mpan_bottom
                                existing_contract.updated_at = datetime.utcnow()
                                
                                if opportunity and assigned_employee_id:
                                    opportunity.opportunity_owner_employee_id = opportunity_owner_id
                                
                                session.commit()
                                
                                print(f"✅ ARCHIVE + UPDATE COMPLETE")
                                print(f"   Archived client ID: {archived_client_id} (is_archived=True)")
                                print(f"   Updated client ID: {client.client_id} (is_archived=False)")
                                print(f"   New end date: {end_date}")
                                print(f"{'='*60}\n")
                                
                                if (success_count + duplicate_count) % 100 == 0:
                                    print(f"📊 Progress: {success_count + duplicate_count}/{total_rows}")
                                
                                continue
                                
                            except Exception as archive_error:
                                session.rollback()
                                print(f"❌ ARCHIVE FAILED for row {index + 2}: {archive_error}")
                                import traceback
                                traceback.print_exc()
                                error_count += 1
                                errors.append(f"Row {index + 2}: Archive failed - {str(archive_error)}")
                                continue

                # CREATE NEW CLIENT
                new_client = Client_Master(
                    tenant_id=tenant_id,
                    assigned_employee_id=opportunity_owner_id,
                    client_company_name=business_name or '',  
                    client_contact_name=contact_person or '',  
                    address=address or '',
                    post_code=postcode or '',
                    client_phone=phone or '',
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
                )
                session.add(new_client)
                session.flush()
                
                client_id = new_client.client_id
                
                # Create Opportunity
                opportunity = Opportunity_Details(
                    client_id=client_id,
                    opportunity_title=business_name or '',
                    opportunity_description='Imported from bulk upload',
                    opportunity_date=datetime.utcnow().date(),
                    opportunity_owner_employee_id=opportunity_owner_id,
                    stage_id=1,
                    opportunity_value=0,
                    currency_id=1,
                    created_at=datetime.utcnow(),
                    Misc_Col1=None
                )
                session.add(opportunity)
                session.flush()
                
                # Create Project
                project = None
                if site_address or annual_usage or mpan_top or start_date or end_date:
                    project_start_date = start_date if start_date else datetime.utcnow().date()
                    project_end_date = end_date if end_date else None
                    project = Project_Details(
                        client_id=client_id,
                        opportunity_id=opportunity.opportunity_id,
                        project_title=business_name or '',
                        project_description='Imported site location',
                        start_date=project_start_date,
                        end_date=project_end_date,
                        employee_id=employee_id,
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
                
                # Create Contract
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
                        supplier_id=supplier_id or 1,
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
                        term_sold=term_sold,
                        rate_2=rate_2,
                        rate_3=rate_3,
                        comms_paid=comms_paid,
                        standing_charge=stand_charge,
                        aggregator=aggregator or None,
                        rate_1=rate_1,
                    )
                    session.add(contract)
                    session.flush()
                    
                    if mpan_top:
                        existing_mpans[mpan_top.strip().lower()] = contract
                
                success_count += 1
                
                if (success_count + duplicate_count) % BATCH_SIZE == 0:
                    session.commit()
                    print(f"📊 Batch committed: {success_count + duplicate_count}/{total_rows}")
                
            except Exception as row_error:
                session.rollback()
                error_count += 1
                error_msg = f"Row {index + 2}: {str(row_error)}"
                errors.append(error_msg)
                print(f"❌ {error_msg}")
                continue
        
        # FINAL COMMIT
        try:
            session.commit()
            print(f"📊 Final batch committed: {success_count + duplicate_count}/{total_rows}")
        except Exception as commit_error:
            print(f"❌ Final commit error: {commit_error}")
            session.rollback()
        
        print(f"✅ Import complete: {success_count} new, {duplicate_count} updated, {error_count} errors")
        
        return jsonify({
            'success': True,
            'message': f'Import completed',
            'total_rows': len(df),
            'successful': success_count,
            'duplicates': duplicate_count,
            'failed': error_count,
            'errors': errors[:50],
            'assigned_to': assigned_employee_name,
            'assigned_employee_id': assigned_employee_id
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
                pg_get_serial_sequence('"StreemLyne_MT"."Energy_Contract_Master"', 'ecm_id'),
                COALESCE((SELECT MAX(ecm_id) FROM "StreemLyne_MT"."Energy_Contract_Master"), 0),
                true
            )
        """))
        
        # Reset Opportunity_Details sequence
        session.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('"StreemLyne_MT"."Opportunity_Details"', 'opportunity_id'),
                COALESCE((SELECT MAX(opportunity_id) FROM "StreemLyne_MT"."Opportunity_Details"), 0),
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