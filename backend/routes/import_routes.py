"""
Bulk Import Route for Energy Customers
Handles Excel/CSV uploads and bulk insertion into database
"""

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import and_, or_  # Add missing imports
from ..models import (
    Client_Master, Project_Details, Energy_Contract_Master,
    Opportunity_Details, Supplier_Master, Employee_Master, Services_Master
)
from .auth_helpers import token_required
from ..db import SessionLocal

import_bp = Blueprint('import', __name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}
UPLOAD_FOLDER = '/tmp/uploads'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_tenant_id_from_user(user):
    """Get tenant_id from authenticated user"""
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
    """Parse date from various formats"""
    if pd.isna(date_value) or not date_value:
        return None
    
    if isinstance(date_value, datetime):
        return date_value.date()
    
    date_str = str(date_value).strip()
    
    # Try common date formats
    date_formats = [
        '%Y-%m-%d',
        '%d/%m/%Y',
        '%d-%m-%Y',
        '%m/%d/%Y',
        '%Y/%m/%d',
        '%d.%m.%Y',
        '%d %b %Y',
        '%d %B %Y',
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


@import_bp.route('/import/energy-customers', methods=['POST', 'OPTIONS'])
@token_required
def import_energy_customers():
    """
    Bulk import energy customers from Excel/CSV file
    
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
        
        # Get or create default service for this tenant
        default_service_id = get_or_create_service(tenant_id, session)
        
        # Read file based on extension
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower()
        
        current_app.logger.info(f"📁 Processing import file: {filename}")
        
        try:
            if file_ext == 'csv':
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
        except Exception as e:
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
        
        # Normalize column names (lowercase, strip spaces, replace underscores with spaces)
        df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ')
        
        current_app.logger.info(f"📊 Found {len(df)} rows in file")
        current_app.logger.info(f"📋 Columns: {list(df.columns)}")
        
        # Column mapping (flexible to handle variations)
        # Note: Columns are normalized to lowercase with spaces (underscores replaced)
        column_map = {
            'business_name': ['business name', 'company name', 'company', 'business'],
            'contact_person': ['contact person', 'contact', 'name'],
            'phone': ['tel number', 'phone', 'telephone', 'tel', 'phone number'],
            'email': ['email', 'e-mail', 'email address'],
            'address': ['address', 'main address', 'street'],
            'post_code': ['post code', 'postcode', 'postal code', 'zip', 'zip code'],
            'site_address': ['site address', 'site'],
            'mpan_mpr': ['mpan mpr', 'mpan/mpr', 'mpan', 'mpr', 'mpan number'],  # Added 'mpan mpr' for underscore format
            'supplier': ['supplier', 'supplier name'],
            'annual_usage': ['annual usage', 'usage', 'kwh', 'annual kwh'],
            'start_date': ['start date', 'contract start', 'start'],
            'end_date': ['end date', 'contract end', 'end', 'expiry date'],
        }
        
        # Find actual column names (columns already normalized to lowercase with spaces)
        actual_columns = {}
        for field, possible_names in column_map.items():
            for col in df.columns:
                if col in possible_names:
                    actual_columns[field] = col
                    break
        
        current_app.logger.info(f"🗺️ Mapped columns: {actual_columns}")
        
        # Validate required fields
        required_fields = ['business_name', 'phone']
        missing_fields = [f for f in required_fields if f not in actual_columns]
        
        if missing_fields:
            return jsonify({
                'error': f'Missing required columns: {", ".join(missing_fields)}',
                'expected_columns': list(column_map.keys()),
                'found_columns': list(df.columns)
            }), 400
        
        # Process rows
        success_count = 0
        error_count = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                # Get values with fallbacks
                business_name = row.get(actual_columns.get('business_name', ''), '').strip()
                contact_person = row.get(actual_columns.get('contact_person', ''), '').strip()
                phone = str(row.get(actual_columns.get('phone', ''), '')).strip()
                email = row.get(actual_columns.get('email', ''), '').strip()
                
                # Build address from multiple fields if available
                address_parts = []
                for addr_field in ['house_name', 'door_number', 'street', 'town', 'locality', 'county']:
                    col_name = actual_columns.get('address', None)
                    if col_name is None:
                        # Try to find specific address fields
                        for col in df.columns:
                            if col.lower().replace('_', ' ') == addr_field.replace('_', ' '):
                                val = str(row.get(col, '')).strip()
                                if val and val.lower() != 'nan':
                                    address_parts.append(val)
                                break
                
                # Fallback to single address column if available
                if not address_parts and 'address' in actual_columns:
                    address = row.get(actual_columns.get('address', ''), '').strip()
                else:
                    address = ', '.join(address_parts) if address_parts else ''
                
                post_code = row.get(actual_columns.get('post_code', ''), '').strip()
                site_address = row.get(actual_columns.get('site_address', ''), '').strip()
                mpan_mpr = str(row.get(actual_columns.get('mpan_mpr', ''), '')).strip()
                supplier_name = row.get(actual_columns.get('supplier', ''), '').strip()
                annual_usage = parse_number(row.get(actual_columns.get('annual_usage', '')))
                start_date = parse_date(row.get(actual_columns.get('start_date', '')))
                end_date = parse_date(row.get(actual_columns.get('end_date', '')))
                
                # Skip empty rows
                if not business_name and not phone:
                    continue
                
                # Validate required fields
                if not business_name:
                    errors.append(f"Row {index + 2}: Missing business name")
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
                    current_app.logger.info(f"📝 Duplicate found: Updating client {existing_client.client_id}")
                    
                    # Update only empty/missing fields in Client_Master
                    if email and not existing_client.client_email:
                        existing_client.client_email = email
                    if address and not existing_client.address:
                        existing_client.address = address
                    if post_code and not existing_client.post_code:
                        existing_client.post_code = post_code
                    if contact_person and not existing_client.client_contact_name:
                        existing_client.client_contact_name = contact_person
                    
                    client_id = existing_client.client_id
                    
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
                            Misc_Col2=int(annual_usage) if annual_usage else None
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
                            opportunity_owner_employee_id=employee_id,
                            stage_id=1,
                            opportunity_value=0,
                            currency_id=1,
                            created_at=datetime.utcnow(),
                            Misc_Col1=None
                        )
                        session.add(opportunity)
                        session.flush()
                    
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
                                service_id=default_service_id,
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
                    post_code=post_code or '',
                    client_phone=phone,
                    client_email=email or '',
                    client_website='',
                    default_currency_id=1,  # Default GBP (currency_id from Currency_Master)
                    created_at=datetime.utcnow()
                )
                session.add(new_client)
                session.flush()
                
                client_id = new_client.client_id
                
                # 2. Create Opportunity_Details FIRST (so we have opportunity_id for Project)
                opportunity = Opportunity_Details(
                    client_id=client_id,
                    opportunity_title=f"Opportunity - {business_name}",
                    opportunity_description='Imported from bulk upload',
                    opportunity_date=datetime.utcnow().date(),
                    opportunity_owner_employee_id=employee_id,
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
                        Misc_Col2=int(annual_usage) if annual_usage else None  # Annual Usage in kWh
                    )
                    session.add(project)
                    session.flush()
                
                # 4. Create Energy_Contract_Master (if MPAN provided or supplier found)
                if project and mpan_mpr:  # Only create if we have MPAN
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
                        service_id=default_service_id,  # Use tenant's default service
                        unit_rate=0.0,  # Default unit rate - required field (real type needs float)
                        currency_id=1,  # Default GBP
                        document_details=None,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        mpan_number=mpan_mpr or ''
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
        
        # Commit all successful inserts
        session.commit()
        
        current_app.logger.info(f"✅ Import complete: {success_count} success, {error_count} errors")
        
        return jsonify({
            'success': True,
            'message': f'Import completed',
            'total_rows': len(df),
            'successful': success_count,
            'failed': error_count,
            'errors': errors[:50]  # Return first 50 errors
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Import failed: {e}")
        return jsonify({'error': f'Import failed: {str(e)}'}), 500
    finally:
        session.close()


@import_bp.route('/import/template', methods=['GET'])
@token_required
def download_template():
    """Download Excel template for bulk import"""
    try:
        import io
        from openpyxl import Workbook
        from flask import send_file
        
        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Energy Customers Template"
        
        # Headers
        headers = [
            "Business Name",
            "Contact Person",
            "Tel Number",
            "Email",
            "Address",
            "Post Code",
            "Site Address",
            "MPAN/MPR",
            "Supplier",
            "Annual Usage",
            "Start Date",
            "End Date"
        ]
        
        # Add headers
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
        
        # Add example row
        example = [
            "ABC Limited",
            "John Smith",
            "07700900000",
            "john@abc.com",
            "123 Main St, London",
            "SW1A 1AA",
            "456 Factory Rd, Manchester",
            "1234567890123",
            "British Gas",
            "50000",
            "01/01/2024",
            "31/12/2024"
        ]
        
        for col, value in enumerate(example, 1):
            ws.cell(row=2, column=col, value=value)
        
        # Save to bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='energy_customers_template.xlsx'
        )
        
    except Exception as e:
        current_app.logger.exception(f"❌ Template download failed: {e}")
        return jsonify({'error': 'Failed to generate template'}), 500