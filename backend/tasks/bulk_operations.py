# # backend/tasks/bulk_operations.py
# """
# Celery tasks for async bulk operations
# """
# from celery import Task
# from backend.celery_app import celery_app
# from backend.db import SessionLocal
# from backend.models import Client_Master, Project_Details, Energy_Contract_Master, Opportunity_Details, Supplier_Master
# import pandas as pd
# from datetime import datetime, timedelta
# import logging
# import os

# logger = logging.getLogger(__name__)


# def parse_date(date_value):
#     """Parse date from various formats - prioritize DD/MM/YYYY (UK format)"""
#     if pd.isna(date_value) or not date_value:
#         return None
    
#     if isinstance(date_value, datetime):
#         return date_value.date()
    
#     date_str = str(date_value).strip()
    
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


# def parse_number(value):
#     """Parse number from string (handles commas, etc.)"""
#     if pd.isna(value) or not value:
#         return None
    
#     try:
#         cleaned = str(value).replace(',', '').strip()
#         return float(cleaned) if cleaned else None
#     except (ValueError, AttributeError):
#         return None


# def safe_str(value):
#     """Convert value to string, handling None/NaN"""
#     if pd.isna(value) or value is None:
#         return ''
#     return str(value).strip()


# @celery_app.task(bind=True, name='tasks.bulk_import_customers')
# def bulk_import_customers(self, file_path, tenant_id, user_employee_id, assigned_employee_id, service_id):
#     """
#     Bulk import customers from Excel file
#     Updates progress state for real-time tracking
#     """
#     session = SessionLocal()
    
#     try:
#         # Update state: Starting
#         self.update_state(
#             state='PROGRESS',
#             meta={
#                 'status': 'Reading Excel file...',
#                 'progress': 0,
#                 'successful': 0,
#                 'errors': 0
#             }
#         )
        
#         logger.info(f"🚀 [Task {self.request.id}] Starting bulk import for tenant {tenant_id}")
        
#         # Read Excel file
#         try:
#             df = pd.read_excel(file_path, engine='openpyxl')
#             logger.info(f"📊 Processing {len(df)} rows from {file_path}")
#         except Exception as e:
#             logger.error(f"❌ Failed to read Excel file: {e}")
#             raise Exception(f"Invalid Excel file: {e}")
        
#         # Normalize column names
#         df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ').str.replace(r'\s+', ' ', regex=True)
        
#         # Column mapping
#         column_map = {
#             'client_name': ['client name', 'business name', 'company name'],
#             'trading_name': ['trading name', 'business', 'company'],
#             'main_contact': ['main contact', 'contact person', 'contact'],
#             'position': ['position', 'role', 'title'],
#             'tel_no': ['tel no', 'phone', 'telephone', 'tel'],
#             'mobile_no': ['mobile no', 'mobile', 'cell'],
#             'email': ['email', 'e-mail'],
#             'site_name': ['site name', 'site'],
#             'month_sold': ['month sold', 'sale month'],
#             'address_line_1': ['address line 1', 'address 1', 'street'],
#             'address_line_2': ['address line 2', 'address 2'],
#             'address_line_3': ['address line 3', 'address 3'],
#             'town': ['town', 'city'],
#             'county': ['county', 'region'],
#             'postcode': ['postcode', 'post code', 'zip'],
#             'mpan_top': ['mpan top', 'mpan core'],
#             'mpan_bottom': ['mpan bottom', 'mpan llf'],
#             'supplier': ['supplier', 'supplier name'],
#             'net_notch': ['net notch'],
#             'in_contract': ['in contract', 'contract length'],
#             'start_date': ['start date', 'contract start'],
#             'contract_end': ['contract end', 'end date', 'expiry'],
#             'stand_charge': ['stand charge', 'standing charge'],
#             'rate_1': ['rate 1', 'unit rate', 'rate'],
#             'rate_2': ['rate 2'],
#             'rate_3': ['rate 3'],
#             'aggregator': ['aggregator'],
#             'annual_usage': ['annual usage', 'usage', 'kwh'],
#             'comms_paid': ['comms paid', 'commission'],
#             'company_number': ['company number', 'co number'],
#             'date_of_birth': ['date of birth', 'dob'],
#             'bank_name': ['bank name', 'bank'],
#             'ac_number': ['ac number', 'account number'],
#             'sort_code': ['sort code'],
#             'charity_ltd_company_number': ['charity/ltd company number', 'charity number'],
#             'partner_details': ['partner details', 'partner'],
#             'house_name': ['house name'],
#             'house_number': ['house number', 'house no'],
#             'door_number': ['door number', 'door no']
#         }
        
#         actual_columns = {}
#         for field, possible_names in column_map.items():
#             for col in df.columns:
#                 if col in possible_names:
#                     actual_columns[field] = col
#                     break
        
#         # Pre-load suppliers for matching
#         suppliers_dict = {}
#         suppliers = session.query(Supplier_Master).all()
#         for s in suppliers:
#             suppliers_dict[s.supplier_company_name.lower().strip()] = s.supplier_id
        
#         logger.info(f"📊 Loaded {len(suppliers_dict)} suppliers for matching")
        
#         # Pre-load existing MPANs for duplicate checking
#         existing_mpans = {}
#         existing_contracts = session.query(Energy_Contract_Master).all()
#         for contract in existing_contracts:
#             if contract.mpan_number:
#                 existing_mpans[contract.mpan_number.strip().lower()] = contract
        
#         logger.info(f"📊 Loaded {len(existing_mpans)} existing MPANs for duplicate checking")
        
#         # Process records
#         total_rows = len(df)
#         success_count = 0
#         error_count = 0
#         duplicate_count = 0
#         errors = []
        
#         BATCH_SIZE = 50
#         current_batch = 0
#         total_batches = (total_rows // BATCH_SIZE) + (1 if total_rows % BATCH_SIZE else 0)
        
#         opportunity_owner_id = assigned_employee_id if assigned_employee_id else user_employee_id
        
#         for index, row in df.iterrows():
#             try:
#                 # Extract data
#                 client_name = safe_str(row.get(actual_columns.get('client_name', ''), ''))
#                 trading_name = safe_str(row.get(actual_columns.get('trading_name', ''), ''))
#                 main_contact = safe_str(row.get(actual_columns.get('main_contact', ''), ''))
#                 position = safe_str(row.get(actual_columns.get('position', ''), ''))
#                 tel_no = safe_str(row.get(actual_columns.get('tel_no', ''), ''))
#                 mobile_no = safe_str(row.get(actual_columns.get('mobile_no', ''), ''))
#                 email = safe_str(row.get(actual_columns.get('email', ''), ''))
#                 site_name = safe_str(row.get(actual_columns.get('site_name', ''), ''))
                
#                 # Address fields
#                 address_line_1 = safe_str(row.get(actual_columns.get('address_line_1', ''), ''))
#                 address_line_2 = safe_str(row.get(actual_columns.get('address_line_2', ''), ''))
#                 address_line_3 = safe_str(row.get(actual_columns.get('address_line_3', ''), ''))
#                 town = safe_str(row.get(actual_columns.get('town', ''), ''))
#                 county = safe_str(row.get(actual_columns.get('county', ''), ''))
#                 postcode = safe_str(row.get(actual_columns.get('postcode', ''), ''))
                
#                 address_parts = [p for p in [address_line_1, address_line_2, address_line_3, town, county] if p and p.lower() != 'nan']
#                 address = ', '.join(address_parts)
#                 site_address = site_name or address
                
#                 # MPAN fields
#                 mpan_top = safe_str(row.get(actual_columns.get('mpan_top', ''), ''))
#                 mpan_bottom = safe_str(row.get(actual_columns.get('mpan_bottom', ''), ''))
#                 mpan_mpr = f"{mpan_top}{mpan_bottom}" if mpan_top and mpan_bottom else (mpan_top or mpan_bottom or '')
                
#                 # Contract fields
#                 supplier_name = safe_str(row.get(actual_columns.get('supplier', ''), ''))
#                 annual_usage = parse_number(row.get(actual_columns.get('annual_usage', '')))
#                 start_date = parse_date(row.get(actual_columns.get('start_date', '')))
#                 end_date = parse_date(row.get(actual_columns.get('contract_end', '')))
#                 stand_charge = parse_number(row.get(actual_columns.get('stand_charge', '')))
#                 rate_1 = parse_number(row.get(actual_columns.get('rate_1', '')))
#                 net_notch = parse_number(row.get(actual_columns.get('net_notch', '')))
#                 rate_2 = parse_number(row.get(actual_columns.get('rate_2', '')))
#                 rate_3 = parse_number(row.get(actual_columns.get('rate_3', '')))
#                 comms_paid = parse_number(row.get(actual_columns.get('comms_paid', '')))
#                 company_number = safe_str(row.get(actual_columns.get('company_number', ''), ''))
#                 date_of_birth = parse_date(row.get(actual_columns.get('date_of_birth', '')))
#                 charity_ltd_company_number = safe_str(row.get(actual_columns.get('charity_ltd_company_number', ''), ''))
#                 month_sold = safe_str(row.get(actual_columns.get('month_sold', ''), ''))
#                 house_name = safe_str(row.get(actual_columns.get('house_name', ''), ''))
#                 house_number = safe_str(row.get(actual_columns.get('house_number', ''), ''))
#                 door_number = safe_str(row.get(actual_columns.get('door_number', ''), ''))
#                 term_sold = parse_number(row.get(actual_columns.get('in_contract', '')))
#                 aggregator = safe_str(row.get(actual_columns.get('aggregator', ''), ''))
#                 partner_details = safe_str(row.get(actual_columns.get('partner_details', ''), ''))
#                 bank_name = safe_str(row.get(actual_columns.get('bank_name', ''), ''))
#                 account_number = safe_str(row.get(actual_columns.get('ac_number', ''), ''))
#                 sort_code = safe_str(row.get(actual_columns.get('sort_code', ''), ''))
                
#                 # Get/create supplier
#                 supplier_id = None
#                 if supplier_name:
#                     supplier_key = supplier_name.lower().strip()
#                     supplier_id = suppliers_dict.get(supplier_key)
                    
#                     if not supplier_id:
#                         # Create new supplier
#                         try:
#                             new_supplier = Supplier_Master(
#                                 supplier_company_name=supplier_name,
#                                 supplier_contact_name='Auto-imported',
#                                 supplier_provisions=3,
#                                 created_at=datetime.utcnow()
#                             )
#                             session.add(new_supplier)
#                             session.flush()
                            
#                             supplier_id = new_supplier.supplier_id
#                             suppliers_dict[supplier_key] = supplier_id
#                             logger.info(f"✨ Created new supplier '{supplier_name}' (ID: {supplier_id})")
#                         except Exception as e:
#                             logger.error(f"❌ Failed to create supplier '{supplier_name}': {e}")
#                             supplier_id = 1
#                 else:
#                     supplier_id = 1
                
#                 business_name = trading_name or client_name
#                 contact_person = main_contact or client_name
#                 phone = tel_no or mobile_no
                
#                 # Skip empty rows
#                 if not business_name and not phone:
#                     continue
                
#                 # Validate required fields
#                 if not business_name:
#                     errors.append(f"Row {index + 2}: Missing client/business name")
#                     error_count += 1
#                     continue
                
#                 if not phone:
#                     errors.append(f"Row {index + 2}: Missing phone number")
#                     error_count += 1
#                     continue
                
#                 # Check for duplicates by MPAN
#                 if mpan_mpr:
#                     mpan_key = mpan_mpr.strip().lower()
#                     existing_contract = existing_mpans.get(mpan_key)
                    
#                     if existing_contract:
#                         duplicate_count += 1
                        
#                         # Update existing (code omitted for brevity - same as before)
                        
#                         session.commit()
                        
#                         if (success_count + duplicate_count) % 100 == 0:
#                             logger.info(f"📊 Progress: {success_count + duplicate_count}/{total_rows}")
                        
#                         continue
                
#                 # ✅ CREATE NEW CLIENT
#                 new_client = Client_Master(
#                     tenant_id=tenant_id,
#                     assigned_employee_id=opportunity_owner_id,
#                     client_company_name=business_name,
#                     client_contact_name=contact_person or business_name,
#                     address=address or '',
#                     post_code=postcode or '',
#                     client_phone=phone,
#                     client_email=email or '',
#                     client_website='',
#                     default_currency_id=1,
#                     created_at=datetime.utcnow(),
#                     position=position or None,
#                     company_number=company_number or None,
#                     date_of_birth=date_of_birth,
#                     charity_ltd_company_number=charity_ltd_company_number or None,
#                     partner_details=partner_details or None,
#                     bank_name=bank_name or None,
#                     account_number=account_number or None,
#                     sort_code=sort_code or None,
#                 )
#                 session.add(new_client)
#                 session.flush()
                
#                 client_id = new_client.client_id
                
#                 # ✅ CREATE OPPORTUNITY FIRST
#                 opportunity = Opportunity_Details(
#                     client_id=client_id,
#                     opportunity_title=f"Opportunity - {business_name}",
#                     opportunity_description='Imported from bulk upload',
#                     opportunity_date=datetime.utcnow().date(),
#                     opportunity_owner_employee_id=opportunity_owner_id,
#                     stage_id=1,
#                     opportunity_value=0,
#                     currency_id=1,
#                     created_at=datetime.utcnow(),
#                     Misc_Col1=None
#                 )
#                 session.add(opportunity)
#                 session.flush()  # ✅ CRITICAL: Flush to get opportunity_id
                
#                 # ✅ NOW CREATE PROJECT WITH opportunity_id
#                 project = None
#                 if site_address or annual_usage or mpan_mpr or start_date or end_date:
#                     project = Project_Details(
#                         client_id=client_id,
#                         opportunity_id=opportunity.opportunity_id,  # ✅ FIX: Now we have the ID!
#                         project_title=f"Site - {business_name}",
#                         project_description='Imported site location',
#                         start_date=start_date,
#                         end_date=end_date,
#                         employee_id=user_employee_id,
#                         created_at=datetime.utcnow(),
#                         updated_at=datetime.utcnow(),
#                         address=site_address or address or '',
#                         Misc_Col1=None,
#                         Misc_Col2=int(annual_usage) if annual_usage else None,
#                         site_name=site_name or None,
#                         month_sold=month_sold or None,
#                         house_name=house_name or None,
#                         house_number=house_number or None,
#                         door_number=door_number or None,
#                         town=town or None,
#                         county=county or None,
#                     )
#                     session.add(project)
#                     session.flush()
                
#                 # Create Contract
#                 if project and mpan_mpr:
#                     if not end_date:
#                         if start_date:
#                             end_date = start_date + timedelta(days=365)
#                         else:
#                             end_date = datetime.utcnow().date() + timedelta(days=365)
                    
#                     contract = Energy_Contract_Master(
#                         project_id=project.project_id,
#                         employee_id=user_employee_id,
#                         supplier_id=supplier_id or 1,
#                         contract_start_date=start_date,
#                         contract_end_date=end_date,
#                         terms_of_sale='',
#                         service_id=service_id,
#                         unit_rate=rate_1 or 0.0,
#                         currency_id=1,
#                         document_details=None,
#                         created_at=datetime.utcnow(),
#                         updated_at=datetime.utcnow(),
#                         mpan_number=mpan_mpr or '',
#                         net_notch=net_notch,
#                         term_sold=term_sold,
#                         rate_2=rate_2,
#                         rate_3=rate_3,
#                         comms_paid=comms_paid,
#                         standing_charge=stand_charge,
#                         aggregator=aggregator or None,
#                         rate_1=rate_1,
#                     )
#                     session.add(contract)
#                     session.flush()
                    
#                     existing_mpans[mpan_mpr.strip().lower()] = contract
                
#                 success_count += 1
                
#                 # Commit every BATCH_SIZE records
#                 if (success_count + duplicate_count) % BATCH_SIZE == 0:
#                     session.commit()
#                     current_batch += 1
                    
#                     # Update progress
#                     progress = int((success_count + duplicate_count + error_count) / total_rows * 100)
#                     self.update_state(
#                         state='PROGRESS',
#                         meta={
#                             'status': f'Processing batch {current_batch}/{total_batches}...',
#                             'progress': progress,
#                             'successful': success_count,
#                             'errors': error_count,
#                             'current_batch': current_batch,
#                             'total_batches': total_batches
#                         }
#                     )
                    
#                     logger.info(f"📊 Batch {current_batch}/{total_batches} committed: {success_count} successful")
                
#             except Exception as row_error:
#                 session.rollback()
#                 error_count += 1
#                 error_msg = f"Row {index + 2}: {str(row_error)}"
#                 errors.append(error_msg)
#                 logger.error(f"❌ {error_msg}")
#                 continue
        
#         # Final commit
#         try:
#             session.commit()
#             logger.info(f"✅ Final batch committed")
#         except Exception as commit_error:
#             logger.error(f"❌ Final commit error: {commit_error}")
#             session.rollback()
        
#         # Delete temp file
#         try:
#             if os.path.exists(file_path):
#                 os.remove(file_path)
#                 logger.info(f"🗑️ Deleted temporary file: {file_path}")
#         except Exception as e:
#             logger.warning(f"⚠️ Could not delete temp file: {e}")
        
#         logger.info(f"✅ Import complete: {success_count} successful, {error_count} errors")
        
#         return {
#             'status': 'completed',
#             'successful': success_count,
#             'failed': error_count,
#             'total': total_rows,
#             'errors': errors[:50],
#             'assigned_to': None
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Import task failed: {e}")
        
#         # Delete temp file on error
#         try:
#             if os.path.exists(file_path):
#                 os.remove(file_path)
#         except:
#             pass
        
#         return {
#             'status': 'failed',
#             'error': str(e),
#             'successful': 0,
#             'failed': 0
#         }
    
#     finally:
#         session.close()


# @celery_app.task(bind=True, name='tasks.bulk_assign_customers')
# def bulk_assign_customers(self, client_ids, employee_id, tenant_id):
#     """
#     Bulk assign customers to an employee
#     Updates progress state for real-time tracking
#     """
#     session = SessionLocal()
    
#     try:
#         self.update_state(
#             state='PROGRESS',
#             meta={
#                 'status': f'Assigning {len(client_ids)} customers...',
#                 'progress': 0,
#                 'successful': 0,
#                 'errors': 0
#             }
#         )
        
#         logger.info(f"🚀 [Task {self.request.id}] Starting bulk assign: {len(client_ids)} clients to employee {employee_id}")
        
#         # Update Client_Master
#         from sqlalchemy import text
#         result = session.execute(
#             text("""
#                 UPDATE "StreemLyne_MT"."Client_Master"
#                 SET assigned_employee_id = :employee_id
#                 WHERE client_id = ANY(:client_ids)
#                 AND tenant_id = :tenant_id
#             """),
#             {
#                 'employee_id': employee_id,
#                 'client_ids': client_ids,
#                 'tenant_id': tenant_id
#             }
#         )
        
#         # Update Opportunity_Details
#         session.execute(
#             text("""
#                 UPDATE "StreemLyne_MT"."Opportunity_Details" od
#                 SET opportunity_owner_employee_id = :employee_id
#                 FROM "StreemLyne_MT"."Client_Master" cm
#                 WHERE od.client_id = cm.client_id
#                 AND cm.client_id = ANY(:client_ids)
#                 AND cm.tenant_id = :tenant_id
#             """),
#             {
#                 'employee_id': employee_id,
#                 'client_ids': client_ids,
#                 'tenant_id': tenant_id
#             }
#         )
        
#         session.commit()
        
#         logger.info(f"✅ Assigned {len(client_ids)} customers to employee {employee_id}")
        
#         return {
#             'status': 'completed',
#             'successful': len(client_ids),
#             'failed': 0,
#             'total': len(client_ids)
#         }
        
#     except Exception as e:
#         session.rollback()
#         logger.error(f"❌ Bulk assign failed: {e}")
        
#         return {
#             'status': 'failed',
#             'error': str(e),
#             'successful': 0,
#             'failed': len(client_ids)
#         }
    
#     finally:
#         session.close()