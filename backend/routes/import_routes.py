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
    
    Expected columns (case-insensitive):
    - Business Name (required)
    - Contact Person
    - Tel Number / Phone (required)
    - Email
    - Address
    - Site Address
    - MPAN/MPR
    - Supplier
    - Annual Usage
    - Start Date
    - End Date
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    
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

        # ✅ GET ASSIGNED EMPLOYEE ID FROM FORM DATA
        assigned_employee_id = request.form.get('assigned_employee_id', type=int)
        
        # ✅ If assignment provided, use that; otherwise use uploader's ID
        opportunity_owner_id = assigned_employee_id if assigned_employee_id else employee_id
        
        # ✅ Get employee name for success message
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

        # ✅ LOGGING
        print(f"\n{'='*60}")
        print(f"📥 BULK IMPORT STARTED")
        print(f"{'='*60}")
        print(f"   Tenant ID: {tenant_id}")
        print(f"   Uploaded by: Employee ID {employee_id}")
        print(f"   Assigned to: {assigned_employee_name or 'Uploader'} (ID: {opportunity_owner_id})")
        print(f"{'='*60}\n")

        # Service filter: electricity=1, water=2 (for Energy_Contract_Master and tab separation)
        service_param = request.args.get('service', 'utilities')  # Default to 'utilities'
        current_app.logger.info(f"📥 IMPORT SERVICE PARAMETER: {service_param}")

        # Map service name to service_id
        service_id_map = {
            'utilities': 1,
            'electricity': 1, 
            'water': 2,
            'gas': 3
        }

        import_service_id = service_id_map.get(service_param.strip().lower(), 1)  # Default to 1

        current_app.logger.info(f"🔧 MAPPED SERVICE_ID: {import_service_id} (from '{service_param}')")
        
        # Read file based on extension
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower()

        current_app.logger.info(f"📁 Processing import file: {filename}")

        try:
            # ✅ Save to temporary file first (more reliable in production)
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp:
                file.save(tmp.name)
                tmp_path = tmp.name
            
            current_app.logger.info(f"💾 Saved to temp file: {tmp_path}")
            
            # Read from temp file
            if file_ext == 'csv':
                df = pd.read_csv(tmp_path, encoding='utf-8-sig')
            else:
                # Try openpyxl first, fallback to xlrd for older .xls files
                try:
                    df = pd.read_excel(tmp_path, engine='openpyxl')
                except Exception as openpyxl_error:
                    current_app.logger.warning(f"openpyxl failed: {openpyxl_error}, trying xlrd...")
                    df = pd.read_excel(tmp_path, engine='xlrd')
            
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except:
                pass  # Ignore cleanup errors
            
            current_app.logger.info(f"✅ File read successfully: {len(df)} rows, {len(df.columns)} columns")
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to read file: {str(e)}")
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
        
        # Normalize column names (lowercase, strip spaces, replace underscores with spaces)
        df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ').str.replace(r'\s+', ' ', regex=True)

        current_app.logger.info(f"📋 Normalized columns: {list(df.columns)}")
        
        current_app.logger.info(f"📊 Found {len(df)} rows in file")
        current_app.logger.info(f"📋 Columns: {list(df.columns)}")
        
        # Column mapping for Cash2Switch format
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
            'data_source': ['data source', 'source'],
            'welcome_call': ['welcome call'],
            'payment_type': ['payment type', 'payment method'],
            'supplier': ['supplier', 'supplier name'],
            'net_notch': ['net notch'],
            'in_contract': ['in contract', 'contract length'],
            'agent_sold': ['agent sold', 'sales agent', 'sold by'],
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
        
        # Find actual column names (columns already normalized to lowercase with spaces)
        actual_columns = {}
        for field, possible_names in column_map.items():
            for col in df.columns:
                if col in possible_names:
                    actual_columns[field] = col
                    break
        
        current_app.logger.info(f"🗺️ Mapped columns: {actual_columns}")
        
        # Validate required fields - check if EITHER old format OR new format exists
        has_client_or_trading = 'client_name' in actual_columns or 'trading_name' in actual_columns
        has_phone = 'tel_no' in actual_columns or 'mobile_no' in actual_columns

        current_app.logger.info(f"🔍 VALIDATION CHECK:")
        current_app.logger.info(f"   actual_columns keys: {list(actual_columns.keys())}")
        current_app.logger.info(f"   has_client_or_trading: {has_client_or_trading}")
        current_app.logger.info(f"   has_phone: {has_phone}")
        current_app.logger.info(f"   DataFrame columns: {list(df.columns)}")

        if not has_client_or_trading:
            return jsonify({
                'error': 'Missing required column: Client Name or Trading Name is required',
                'expected_columns': ['client name', 'trading name'],
                'found_columns': list(df.columns),
                'actual_columns_mapped': actual_columns 
            }), 400

        if not has_phone:
            return jsonify({
                'error': 'Missing required column: Tel No or Mobile No is required',
                'expected_columns': ['tel no', 'mobile no'],
                'found_columns': list(df.columns),
                'actual_columns_mapped': actual_columns 
            }), 400
        
        # Helper function to safely get string values
        def safe_str(value):
            """Convert value to string, handling NaN, None, and numeric types"""
            if pd.isna(value) or value is None:
                return ''
            return str(value).strip()
        
        # Process rows
        success_count = 0
        error_count = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                # Get values with fallbacks
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

                # Combine address fields (filter out empty strings and 'nan')
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

                old_supplier_name = safe_str(row.get(actual_columns.get('old_supplier', ''), ''))
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
                term_sold = parse_number(row.get(actual_columns.get('in_contract', '')))  # "In Contract" column
                aggregator = safe_str(row.get(actual_columns.get('aggregator', ''), ''))
                partner_details = safe_str(row.get(actual_columns.get('partner_details', ''), ''))

                # ✅ Bank details 
                bank_name = safe_str(row.get(actual_columns.get('bank_name', ''), ''))
                account_number = safe_str(row.get(actual_columns.get('ac_number', ''), ''))
                sort_code = safe_str(row.get(actual_columns.get('sort_code', ''), ''))

                # Find old supplier ID
                old_supplier_id = get_or_create_supplier(old_supplier_name, session) if old_supplier_name else None

                # Use Client Name as business name, Trading Name as fallback
                business_name = trading_name or client_name
                contact_person = main_contact or client_name 

                # Use Tel No as primary, Mobile No as fallback
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
                
                # Find supplier ID
                supplier_id = get_or_create_supplier(supplier_name, session)
                
                current_app.logger.info(f"🔄 Processing row {index + 2}: {business_name}")
                current_app.logger.info(f"   📍 MPAN: {mpan_mpr}, Supplier: {supplier_name} (ID: {supplier_id})")
                current_app.logger.info(f"   📅 Dates: {start_date} to {end_date}, Usage: {annual_usage}")
                
                # ============================================
                # DUPLICATE DETECTION & UPDATE
                # ============================================
                # Check if client already exists by phone or business name
                existing_client = session.query(Client_Master).filter(
                    and_(
                        Client_Master.tenant_id == tenant_id,
                        or_(
                            Client_Master.client_phone == phone,
                            Client_Master.client_company_name == business_name
                        )
                    )
                ).first()
                
                if existing_client:
                    current_app.logger.info(f"📝 Duplicate found: Updating client {existing_client.tenant_client_id}")
                    
                    # Update only empty/missing fields in Client_Master
                    if email and not existing_client.client_email:
                        existing_client.client_email = email
                    if address and not existing_client.address:
                        existing_client.address = address
                    if postcode and not existing_client.post_code:
                        existing_client.post_code = postcode
                    if contact_person and not existing_client.client_contact_name:
                        existing_client.client_contact_name = contact_person
                    
                    client_id = existing_client.tenant_client_id
                    
                    # Update or create Project_Details
                    project = session.query(Project_Details).filter_by(client_id=client_id).first()
                    if not project and (site_address or annual_usage or mpan_mpr or start_date or end_date):
                        project = Project_Details(
                            client_id=client_id,
                            opportunity_id=None,  # Will be set later
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
                            house_number=house_number or None,
                            door_number=door_number or None,  
                            town=town or None,
                            county=county or None,
                        )
                        session.add(project)
                        session.flush()
                    elif project:
                        # Update empty fields in existing project
                        if site_address and not project.address:
                            project.address = site_address
                        if annual_usage and not project.Misc_Col2:
                            project.Misc_Col2 = int(annual_usage)
                        if start_date and not project.start_date:
                            project.start_date = start_date
                        if end_date and not project.end_date:
                            project.end_date = end_date
                        project.updated_at = datetime.utcnow()
                    
                    # Get or create Opportunity_Details
                    opportunity = session.query(Opportunity_Details).filter_by(client_id=client_id).first()
                    if not opportunity:
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
                    else:
                        if assigned_employee_id:
                            opportunity.opportunity_owner_employee_id = opportunity_owner_id
                            current_app.logger.info(f"   🔄 Reassigned to {assigned_employee_name}")
                    
                    
                    # Update project with opportunity_id if needed
                    if project and not project.opportunity_id:
                        project.opportunity_id = opportunity.opportunity_id
                        session.flush()
                    
                    # Update or create Energy_Contract_Master
                    if project and mpan_mpr:
                        contract = session.query(Energy_Contract_Master).filter_by(
                            project_id=project.project_id
                        ).first()
                        
                        if not contract:
                            if supplier_name and not supplier_id:
                                current_app.logger.warning(f"⚠️ Row {index + 2}: Supplier '{supplier_name}' not found, using default")
                            
                            contract = Energy_Contract_Master(
                                project_id=project.project_id,
                                employee_id=employee_id,
                                supplier_id=supplier_id if supplier_id else 1,
                                contract_start_date=start_date,
                                contract_end_date=end_date,
                                terms_of_sale='',
                                service_id=import_service_id,
                                unit_rate=0.0,  # Default unit rate
                                currency_id=1,
                                document_details=None,
                                created_at=datetime.utcnow(),
                                updated_at=datetime.utcnow(),
                                mpan_number=mpan_mpr or ''
                            )
                            session.add(contract)
                            session.flush()
                        else:
                            # Update empty fields in existing contract
                            if mpan_mpr and not contract.mpan_number:
                                contract.mpan_number = mpan_mpr
                            if supplier_id and not contract.supplier_id:
                                contract.supplier_id = supplier_id
                            if start_date and not contract.contract_start_date:
                                contract.contract_start_date = start_date
                            if end_date and not contract.contract_end_date:
                                contract.contract_end_date = end_date
                            contract.updated_at = datetime.utcnow()
                    
                    success_count += 1
                    continue  # Move to next row
                
                # ============================================
                # NEW CLIENT CREATION (NOT DUPLICATE)
                # ============================================
                
                # 1. Create Client_Master
                new_client = Client_Master(
                    tenant_id=tenant_id,
                    client_company_name=business_name,
                    client_contact_name=contact_person or business_name,
                    address=address or '',
                    country_id=None,  # Can be mapped later if needed
                    post_code=postcode or '',
                    client_phone=phone,
                    client_email=email or '',
                    client_website='',
                    default_currency_id=1,  # Default GBP (currency_id from Currency_Master)
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
                
                client_id = new_client.tenant_client_id
                
                # 2. Create Opportunity_Details FIRST (so we have opportunity_id for Project)
                opportunity = Opportunity_Details(
                    client_id=client_id,
                    opportunity_title=f"Opportunity - {business_name}",
                    opportunity_description='Imported from bulk upload',
                    opportunity_date=datetime.utcnow().date(),
                    opportunity_owner_employee_id=opportunity_owner_id,
                    stage_id=1,  # Default to first stage (from Stage_Master)
                    opportunity_value=0,  # smallint - can be updated later
                    currency_id=1,  # Default GBP
                    created_at=datetime.utcnow(),
                    Misc_Col1=None  # Available for custom use
                )
                session.add(opportunity)
                session.flush()
                
                # 3. Create Project_Details (now we have opportunity_id)
                # Create project if we have ANY contract-related data (MPAN, usage, dates, site)
                project = None
                if site_address or annual_usage or mpan_mpr or start_date or end_date:
                    project = Project_Details(
                        client_id=client_id,
                        opportunity_id=opportunity.opportunity_id,  # Use the opportunity we just created
                        project_title=f"Site - {business_name}",
                        project_description='Imported site location',
                        start_date=start_date,
                        end_date=end_date,
                        employee_id=employee_id,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        address=site_address or address or '',
                        Misc_Col1=None,  # Available for custom use
                        Misc_Col2=int(annual_usage) if annual_usage else None,
                        site_name=site_name or None,
                        month_sold=month_sold or None,
                        house_name=house_name or None,
                        house_number=house_number or None
                    )
                    session.add(project)
                    session.flush()
                
                # 4. Create Energy_Contract_Master (if MPAN provided or supplier found)
                if project and mpan_mpr:  # Only create if we have MPAN
                    current_app.logger.info(f"   🔧 Creating contract: project_id={project.project_id}, mpan={mpan_mpr}")
                    
                    # Log if supplier name was provided but not found
                    if supplier_name and not supplier_id:
                        current_app.logger.warning(f"⚠️ Row {index + 2}: Supplier '{supplier_name}' not found, using default")
                    
                    contract = Energy_Contract_Master(
                        project_id=project.project_id,
                        employee_id=employee_id,
                        supplier_id=supplier_id if supplier_id else 1,  # Use default supplier_id=1 if not found
                        contract_start_date=start_date,
                        contract_end_date=end_date,
                        terms_of_sale='',
                        service_id=import_service_id,
                        unit_rate=rate_1 or 0.0,  # Default unit rate - required field (real type needs float)
                        currency_id=1,  # Default GBP
                        document_details=None,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        mpan_number=mpan_mpr or '',
                        old_supplier_id=old_supplier_id,
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
                    current_app.logger.info(f"   ✅ Created Energy_Contract_Master: {contract.energy_contract_master_id}")
                elif not project:
                    current_app.logger.warning(f"   ⚠️ No project created for {business_name} - cannot create contract")
                elif not mpan_mpr:
                    current_app.logger.warning(f"   ⚠️ No MPAN provided for {business_name} - skipping contract")
                
                success_count += 1
                
            except Exception as row_error:
                error_count += 1
                error_msg = f"Row {index + 2}: {str(row_error)}"
                errors.append(error_msg)
                current_app.logger.error(f"❌ {error_msg}")
                continue
        
        # Commit all successful inserts
        session.commit()
        
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