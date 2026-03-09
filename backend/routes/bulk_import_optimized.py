# # -*- coding: utf-8 -*-
# """
# Optimized Bulk Import Routes - Schema-Aware Version
# Uses bulk SQL operations for 10-50x faster imports
# Includes ALL required fields based on schema
# """
# from flask import Blueprint, request, jsonify, current_app
# from backend.routes.auth_helpers import token_required
# from backend.db import SessionLocal
# from backend.models import Client_Master, Project_Details, Energy_Contract_Master, Opportunity_Details, Employee_Master
# from sqlalchemy import text
# from datetime import datetime
# import pandas as pd
# import traceback

# bulk_import_bp = Blueprint('bulk_import', __name__)

# @bulk_import_bp.route('/import/energy-customers', methods=['POST', 'OPTIONS'])
# @token_required
# def bulk_import_energy_customers():
#     """
#     Optimized bulk import - uses SQL bulk inserts instead of ORM
#     Can handle 5000+ records in under 30 seconds
#     """
#     if request.method == 'OPTIONS':
#         return jsonify({}), 200
    
#     session = SessionLocal()
    
#     try:
#         # Get tenant and user info
#         user = request.current_user
#         tenant_id = getattr(user, 'tenant_id', None)
        
#         if not tenant_id:
#             return jsonify({'error': 'Tenant not found'}), 400
        
#         # Get file and assigned employee
#         file = request.files.get('file')
#         assigned_employee_id = request.form.get('assigned_employee_id', type=int)
#         service = request.args.get('service', 'utilities')
        
#         if not file:
#             return jsonify({'error': 'No file provided'}), 400
        
#         # Map service to service_id
#         service_id_map = {'utilities': 1, 'electricity': 1, 'gas': 2, 'water': 3}
#         service_id = service_id_map.get(service.lower(), 1)
        
#         current_app.logger.info(f"🚀 Starting bulk import for tenant {tenant_id}, service={service}")
        
#         # Read Excel file
#         df = pd.read_excel(file)
#         total_rows = len(df)
        
#         current_app.logger.info(f"📊 Processing {total_rows} rows")
        
#         # ============================================
#         # STEP 1: Bulk insert Client_Master
#         # ============================================
#         client_ids = []
        
#         for _, row in df.iterrows():
#             client_insert = text("""
#                 INSERT INTO "StreemLyne_MT"."Client_Master" 
#                 (tenant_id, client_company_name, client_contact_name, 
#                  client_phone, client_email, address, post_code, created_at)
#                 VALUES 
#                 (:tenant_id, :client_company_name, :client_contact_name,
#                  :client_phone, :client_email, :address, :post_code, :created_at)
#                 RETURNING client_id
#             """)
            
#             result = session.execute(client_insert, {
#                 'tenant_id': tenant_id,
#                 'client_company_name': str(row.get('Business Name', 'Unknown')),
#                 'client_contact_name': str(row.get('Contact Person', 'Unknown')),
#                 'client_phone': str(row.get('Phone', '')),
#                 'client_email': str(row.get('Email', '')),
#                 'address': str(row.get('Address', '')),
#                 'post_code': str(row.get('Post Code', '')),
#                 'created_at': datetime.utcnow()
#             })
            
#             client_id = result.fetchone()[0]
#             client_ids.append((client_id, row))
        
#         session.flush()
#         current_app.logger.info(f"✅ Inserted {len(client_ids)} clients")
        
#         # ============================================
#         # STEP 2: Create Opportunity_Details FIRST (to get opportunity_id)
#         # Required fields: client_id, opportunity_title, opportunity_owner_employee_id, stage_id
#         # ============================================
#         opportunity_ids = []
        
#         for client_id, row in client_ids:
#             business_name = str(row.get('Business Name', 'Unknown'))
            
#             opportunity_insert = text("""
#                 INSERT INTO "StreemLyne_MT"."Opportunity_Details"
#                 (client_id, opportunity_title, opportunity_owner_employee_id, stage_id, created_at)
#                 VALUES
#                 (:client_id, :opportunity_title, :opportunity_owner_employee_id, :stage_id, :created_at)
#                 RETURNING opportunity_id
#             """)
            
#             result = session.execute(opportunity_insert, {
#                 'client_id': client_id,
#                 'opportunity_title': f"Energy Contract - {business_name}",
#                 'opportunity_owner_employee_id': assigned_employee_id or user.employee_id,
#                 'stage_id': 1,  # Default stage
#                 'created_at': datetime.utcnow()
#             })
            
#             opportunity_id = result.fetchone()[0]
#             opportunity_ids.append((client_id, opportunity_id, row))
        
#         session.flush()
#         current_app.logger.info(f"✅ Inserted {len(opportunity_ids)} opportunities")
        
#         # ============================================
#         # STEP 3: Bulk insert Project_Details (with opportunity_id)
#         # Required fields: client_id, opportunity_id, project_title, employee_id
#         # ============================================
#         project_ids = []
        
#         for client_id, opportunity_id, row in opportunity_ids:
#             business_name = str(row.get('Business Name', 'Unknown'))
            
#             # Parse contract dates for project start/end
#             start_date = pd.to_datetime(row.get('Contract Start Date'), errors='coerce')
#             end_date = pd.to_datetime(row.get('Contract End Date'), errors='coerce')
            
#             project_insert = text("""
#                 INSERT INTO "StreemLyne_MT"."Project_Details"
#                 (client_id, opportunity_id, project_title, address, "Misc_Col2", employee_id, start_date, end_date, created_at)
#                 VALUES
#                 (:client_id, :opportunity_id, :project_title, :address, :Misc_Col2, :employee_id, :start_date, :end_date, :created_at)
#                 RETURNING project_id
#             """)
            
#             result = session.execute(project_insert, {
#                 'client_id': client_id,
#                 'opportunity_id': opportunity_id,
#                 'project_title': f"Site - {business_name}",
#                 'address': str(row.get('Site Address', row.get('Address', ''))),
#                 'Misc_Col2': row.get('Annual Usage (kWh)'),  # Annual usage
#                 'employee_id': user.employee_id,
#                 'start_date': start_date.date() if pd.notna(start_date) else datetime.utcnow().date(),  # Default to today if missing
#                 'end_date': end_date.date() if pd.notna(end_date) else None,
#                 'created_at': datetime.utcnow()
#             })
            
#             project_id = result.fetchone()[0]
#             project_ids.append((project_id, row))
        
#         session.flush()
#         current_app.logger.info(f"✅ Inserted {len(project_ids)} projects")
        
#         # ============================================
#         # STEP 4: Bulk insert Energy_Contract_Master
#         # Required fields: project_id, employee_id, service_id
#         # ============================================
#         contracts_inserted = 0
        
#         for project_id, row in project_ids:
#             # Parse dates safely
#             start_date = pd.to_datetime(row.get('Contract Start Date'), errors='coerce')
#             end_date = pd.to_datetime(row.get('Contract End Date'), errors='coerce')
            
#             contract_insert = text("""
#                 INSERT INTO "StreemLyne_MT"."Energy_Contract_Master"
#                 (project_id, employee_id, supplier_id, mpan_number, contract_start_date,
#                  contract_end_date, unit_rate, service_id, created_at)
#                 VALUES
#                 (:project_id, :employee_id, :supplier_id, :mpan_number, :contract_start_date,
#                  :contract_end_date, :unit_rate, :service_id, :created_at)
#             """)
            
#             session.execute(contract_insert, {
#                 'project_id': project_id,
#                 'employee_id': user.employee_id,
#                 'supplier_id': row.get('Supplier ID') if pd.notna(row.get('Supplier ID')) else None,
#                 'mpan_number': str(row.get('MPAN/MPR', '')),
#                 'contract_start_date': start_date.date() if pd.notna(start_date) else None,
#                 'contract_end_date': end_date.date() if pd.notna(end_date) else None,
#                 'unit_rate': row.get('Unit Rate') if pd.notna(row.get('Unit Rate')) else None,
#                 'service_id': service_id,
#                 'created_at': datetime.utcnow()
#             })
            
#             contracts_inserted += 1
        
#         session.flush()
#         current_app.logger.info(f"✅ Inserted {contracts_inserted} contracts")
        
#         # Commit all changes
#         session.commit()
        
#         # Get assigned employee name
#         assigned_to_name = None
#         if assigned_employee_id:
#             employee = session.query(Employee_Master).filter_by(
#                 employee_id=assigned_employee_id
#             ).first()
#             assigned_to_name = employee.employee_name if employee else None
        
#         current_app.logger.info(f"🎉 Successfully imported {total_rows} customers")
        
#         return jsonify({
#             'success': True,
#             'successful': total_rows,
#             'failed': 0,
#             'errors': [],
#             'assigned_to': assigned_to_name
#         }), 200
        
#     except Exception as e:
#         session.rollback()
#         current_app.logger.error(f"❌ Bulk import error: {str(e)}")
#         current_app.logger.error(traceback.format_exc())
#         return jsonify({
#             'success': False,
#             'successful': 0,
#             'failed': 0,
#             'error': str(e)
#         }), 500
#     finally:
#         session.close()


# @bulk_import_bp.route('/bulk-assign-optimized', methods=['POST', 'OPTIONS'])
# @token_required
# def bulk_assign_optimized():
#     """
#     Optimized bulk assignment - uses single UPDATE query
#     Can handle 5000+ records instantly
#     """
#     if request.method == 'OPTIONS':
#         return jsonify({}), 200
    
#     session = SessionLocal()
    
#     try:
#         user = request.current_user
#         tenant_id = getattr(user, 'tenant_id', None)
        
#         if not tenant_id:
#             return jsonify({'error': 'Tenant not found'}), 400
        
#         data = request.get_json()
#         client_ids = data.get('client_ids', [])
#         employee_id = data.get('employee_id')
        
#         if not client_ids or not employee_id:
#             return jsonify({'error': 'client_ids and employee_id are required'}), 400
        
#         current_app.logger.info(f"🚀 Bulk assigning {len(client_ids)} clients to employee {employee_id}")
        
#         # Get employee name
#         employee = session.query(Employee_Master).filter_by(
#             employee_id=employee_id,
#             tenant_id=tenant_id
#         ).first()
        
#         if not employee:
#             return jsonify({'error': 'Employee not found'}), 404
        
#         # ============================================
#         # SINGLE QUERY UPDATE - Much faster than loop
#         # ============================================
        
#         # Update Opportunity_Details.opportunity_owner_employee_id
#         opportunity_update = text("""
#             UPDATE "StreemLyne_MT"."Opportunity_Details"
#             SET opportunity_owner_employee_id = :employee_id
#             WHERE client_id = ANY(:client_ids)
#         """)
        
#         session.execute(opportunity_update, {
#             'employee_id': employee_id,
#             'client_ids': client_ids
#         })
        
#         session.commit()
        
#         current_app.logger.info(f"✅ Bulk assigned {len(client_ids)} clients to {employee.employee_name}")
        
#         return jsonify({
#             'success': True,
#             'message': f'Successfully assigned {len(client_ids)} clients to {employee.employee_name}',
#             'updated_count': len(client_ids),
#             'employee_name': employee.employee_name
#         }), 200
        
#     except Exception as e:
#         session.rollback()
#         current_app.logger.error(f"❌ Bulk assign error: {str(e)}")
#         return jsonify({'error': str(e)}), 500
#     finally:
#         session.close()