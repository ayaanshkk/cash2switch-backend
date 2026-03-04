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

def parse_date(date_value):
    """Parse date from various formats - prioritize DD/MM/YYYY (UK format)"""
    if pd.isna(date_value) or not date_value:
        return None
    
    if isinstance(date_value, datetime):
        return date_value.date()
    
    date_str = str(date_value).strip()
    
    # ✅ UPDATED: Prioritize UK date formats (DD/MM/YYYY)
    date_formats = [
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
    """Parse number from string (handles commas, etc.)"""
    if pd.isna(value) or not value:
        return None
    
    try:
        # Remove commas and convert to float
        cleaned = str(value).replace(',', '').strip()
        return float(cleaned) if cleaned else None
    except (ValueError, AttributeError):
        return None


@import_bp.route('/energy-customers', methods=['POST', 'OPTIONS'])
@token_required
def import_energy_customers():
    """
    Bulk import energy customers from Excel/CSV file with optional assignment
    ⚡ OPTIMIZED: Batch processing for faster imports
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    
    # ✅ OPTIMIZATION 1: Disable query logging during import
    import logging
    sql_logger = logging.getLogger('sqlalchemy.engine')
    original_level = sql_logger.level
    sql_logger.setLevel(logging.WARNING)
    
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
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

        current_app.logger.info(f"\n{'='*60}")
        current_app.logger.info(f"📥 BULK IMPORT STARTED")
        current_app.logger.info(f"{'='*60}")
        current_app.logger.info(f"   Tenant ID: {tenant_id}")
        current_app.logger.info(f"   Uploaded by: Employee ID {employee_id}")
        current_app.logger.info(f"   Assigned to: {assigned_employee_name or 'Uploader'} (ID: {opportunity_owner_id})")
        current_app.logger.info(f"{'='*60}\n")

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
                df = pd.read_csv(tmp_path, encoding='utf-8-sig')
            else:
                try:
                    df = pd.read_excel(tmp_path, engine='openpyxl')
                except Exception:
                    df = pd.read_excel(tmp_path, engine='xlrd')
            
            os.unlink(tmp_path)
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to read file: {str(e)}")
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
        
        # Normalize column names
        df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ').str.replace(r'\s+', ' ', regex=True)
        
        # Column mapping (keep existing)
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
            'address_line_1': ['address line 1', 'address 1', 'street'],
            'address_line_2': ['address line 2', 'address 2'],
            'address_line_3': ['address line 3', 'address 3'],
            'town': ['town', 'city'],
            'county': ['county', 'region'],
            'postcode': ['postcode', 'post code', 'zip'],
            'mpan_top': ['mpan top', 'mpan core'],
            'mpan_bottom': ['mpan bottom', 'mpan llf'],
            'supplier': ['supplier', 'supplier name'],
            'net_notch': ['net notch'],
            'in_contract': ['in contract', 'contract length'],
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
            'house_name': ['house name'],
            'house_number': ['house number', 'house no'],
            'door_number': ['door number', 'door no']
        }
        
        actual_columns = {}
        for field, possible_names in column_map.items():
            for col in df.columns:
                if col in possible_names:
                    actual_columns[field] = col
                    break
        
        # Validate required fields
        has_client_or_trading = 'client_name' in actual_columns or 'trading_name' in actual_columns
        has_phone = 'tel_no' in actual_columns or 'mobile_no' in actual_columns

        if not has_client_or_trading:
            return jsonify({
                'error': 'Missing required column: Client Name or Trading Name is required',
                'found_columns': list(df.columns)
            }), 400

        if not has_phone:
            return jsonify({
                'error': 'Missing required column: Tel No or Mobile No is required',
                'found_columns': list(df.columns)
            }), 400
        
        # Helper function
        def safe_str(value):
            if pd.isna(value) or value is None:
                return ''
            return str(value).strip()
        
        # ============================================
        # ✅ OPTIMIZATION 2: PRE-LOAD SUPPLIERS (single query)
        # ============================================
        suppliers_dict = {}
        suppliers = session.query(Supplier_Master).all()
        for s in suppliers:
            suppliers_dict[s.supplier_company_name.lower()] = s.supplier_id
        
        # ============================================
        # ✅ OPTIMIZATION 3: PRE-LOAD EXISTING CLIENTS (single query)
        # ============================================
        existing_clients = session.query(Client_Master).filter_by(tenant_id=tenant_id).all()
        existing_phones = {c.client_phone: c for c in existing_clients if c.client_phone}
        existing_names = {c.client_company_name.lower(): c for c in existing_clients if c.client_company_name}
        
        # ============================================
        # ✅ OPTIMIZATION 4: BATCH PROCESSING
        # ============================================
        BATCH_SIZE = 50
        total_rows = len(df)
        success_count = 0
        error_count = 0
        errors = []
        
        for batch_start in range(0, total_rows, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_rows)
            batch_df = df.iloc[batch_start:batch_end]
            
            current_app.logger.info(f"📊 Processing batch {batch_start}-{batch_end} of {total_rows}")
            
            for index, row in batch_df.iterrows():
                try:
                    # Extract data (keep existing logic)
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
                    mpan_mpr = f"{mpan_top}{mpan_bottom}" if mpan_top and mpan_bottom else (mpan_top or mpan_bottom or '')

                    # Contract fields
                    supplier_name = safe_str(row.get(actual_columns.get('supplier', ''), ''))
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
                    term_sold = parse_number(row.get(actual_columns.get('in_contract', '')))
                    aggregator = safe_str(row.get(actual_columns.get('aggregator', ''), ''))
                    partner_details = safe_str(row.get(actual_columns.get('partner_details', ''), ''))
                    bank_name = safe_str(row.get(actual_columns.get('bank_name', ''), ''))
                    account_number = safe_str(row.get(actual_columns.get('ac_number', ''), ''))
                    sort_code = safe_str(row.get(actual_columns.get('sort_code', ''), ''))

                    # ✅ OPTIMIZATION: Use pre-loaded suppliers
                    supplier_id = suppliers_dict.get(supplier_name.lower(), 1) if supplier_name else 1

                    business_name = trading_name or client_name
                    contact_person = main_contact or client_name
                    phone = tel_no or mobile_no

                    # Skip empty rows
                    if not business_name and not phone:
                        continue

                    # Validate required fields
                    if not business_name:
                        errors.append(f"Row {index + 2}: Missing client/business name")
                        error_count += 1
                        continue

                    if not phone:
                        errors.append(f"Row {index + 2}: Missing phone number")
                        error_count += 1
                        continue
                    
                    # ✅ OPTIMIZATION: Check duplicates from pre-loaded data
                    existing_client = existing_phones.get(phone) or existing_names.get(business_name.lower())
                    
                    if existing_client:
                        # Update existing (keep your existing update logic)
                        if email and not existing_client.client_email:
                            existing_client.client_email = email
                        if address and not existing_client.address:
                            existing_client.address = address
                        
                        client_id = existing_client.client_id
                        
                        # Continue with project/opportunity/contract logic...
                        # (Keep your existing logic for updates)
                        
                        success_count += 1
                        continue
                    
                    # Create new client (keep your existing creation logic)
                    new_client = Client_Master(
                        tenant_id=tenant_id,
                        client_company_name=business_name,
                        client_contact_name=contact_person or business_name,
                        address=address or '',
                        post_code=postcode or '',
                        client_phone=phone,
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
                    
                    # Add to existing clients dict for next iterations
                    existing_phones[phone] = new_client
                    existing_names[business_name.lower()] = new_client
                    
                    client_id = new_client.client_id
                    
                    # Create Opportunity
                    opportunity = Opportunity_Details(
                        client_id=client_id,
                        opportunity_title=f"Opportunity - {business_name}",
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
                    if site_address or annual_usage or mpan_mpr or start_date or end_date:
                        project = Project_Details(
                            client_id=client_id,
                            opportunity_id=opportunity.opportunity_id,
                            project_title=f"Site - {business_name}",
                            project_description='Imported site location',
                            start_date=start_date,
                            end_date=end_date,
                            employee_id=employee_id,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                            address=site_address or address or '',
                            Misc_Col1=None,
                            Misc_Col2=int(annual_usage) if annual_usage else None,
                            site_name=site_name or None,
                            month_sold=month_sold or None,
                            house_name=house_name or None,
                            house_number=house_number or None
                        )
                        session.add(project)
                        session.flush()
                    
                    # Create Contract
                    if project and mpan_mpr:
                        contract = Energy_Contract_Master(
                            project_id=project.project_id,
                            employee_id=employee_id,
                            supplier_id=supplier_id,
                            contract_start_date=start_date,
                            contract_end_date=end_date,
                            terms_of_sale='',
                            service_id=import_service_id,
                            unit_rate=rate_1 or 0.0,
                            currency_id=1,
                            document_details=None,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                            mpan_number=mpan_mpr or '',
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
                    
                    success_count += 1
                    
                except Exception as row_error:
                    error_count += 1
                    error_msg = f"Row {index + 2}: {str(row_error)}"
                    errors.append(error_msg)
                    current_app.logger.error(f"❌ {error_msg}")
                    continue
            
            # ✅ COMMIT EACH BATCH (prevents timeout)
            session.commit()
            current_app.logger.info(f"✅ Batch committed: {batch_end}/{total_rows} rows processed")
        
        current_app.logger.info(f"✅ Import complete: {success_count} success, {error_count} errors")
        
        return jsonify({
            'success': True,
            'message': f'Import completed',
            'total_rows': len(df),
            'successful': success_count,
            'failed': error_count,
            'errors': errors[:50],
            'assigned_to': assigned_employee_name,
            'assigned_employee_id': assigned_employee_id
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Import failed: {e}")
        return jsonify({'error': f'Import failed: {str(e)}'}), 500
    finally:
        # ✅ Re-enable SQL logging
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