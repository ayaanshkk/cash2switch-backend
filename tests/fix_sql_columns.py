# -*- coding: utf-8 -*-
import os, sys, io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Manual fixes for each repository based on actual schema

fixes = {
    'backend/crm/repositories/project_repository.py': [
        ('FROM "Project_Details"', 'FROM "StreemLyne_MT"."Project_Details"'),
        ('FROM "User_Master"', 'FROM "StreemLyne_MT"."User_Master"'),
        ('JOIN "User_Master"', 'JOIN "StreemLyne_MT"."User_Master"'),
        ('JOIN "Project_Details"', 'JOIN "StreemLyne_MT"."Project_Details"'),
        ('od.tenant_id', 'od."Tenant_id"'),
        ('pd.tenant_id', 'pd."Tenant_id"'),
        ('WHERE tenant_id', 'WHERE "Tenant_id"'),
        ('um.user_id', 'um."User_id"'),
        ('pd.project_manager_id', 'pd."project_manager_id"'),
        ('pd.project_id', 'pd."Project_id"'),
        ('um.user_name', 'um."user_name"'),
        ('project_status', '"project_status"'),
        ('od.stage_id', 'od."Stage_id"'),
        ('sm.stage_id', 'sm."Stage_id"'),
    ],
    'backend/crm/repositories/deal_repository.py': [
        ('FROM "Energy_Contract_Master"', 'FROM "StreemLyne_MT"."Energy_Contract_Master"'),
        ('FROM "User_Master"', 'FROM "StreemLyne_MT"."User_Master"'),
        ('JOIN "User_Master"', 'JOIN "StreemLyne_MT"."User_Master"'),
        ('JOIN "Energy_Contract_Master"', 'JOIN "StreemLyne_MT"."Energy_Contract_Master"'),
        ('ecm.tenant_id', 'ecm."Tenant_id"'),
        ('WHERE tenant_id', 'WHERE "Tenant_id"'),
        ('um.user_id', 'um."User_id"'),
        ('ecm.contract_owner_id', 'ecm."contract_owner_id"'),
        ('ecm.contract_id', 'ecm."Contract_id"'),
        ('um.user_name', 'um."user_name"'),
        ('contract_status', '"contract_status"'),
        ('contract_value', '"contract_value"'),
    ],
    'backend/crm/repositories/user_repository.py': [
        ('FROM "User_Master"', 'FROM "StreemLyne_MT"."User_Master"'),
        ('FROM "Role_Master"', 'FROM "StreemLyne_MT"."Role_Master"'),
        ('JOIN "Role_Master"', 'JOIN "StreemLyne_MT"."Role_Master"'),
        ('JOIN "User_Master"', 'JOIN "StreemLyne_MT"."User_Master"'),
        ('um.tenant_id', 'um."Tenant_id"'),
        ('WHERE tenant_id', 'WHERE "Tenant_id"'),
        ('um.user_id', 'um."User_id"'),
        ('rm.role_id', 'rm."Role_id"'),
        ('um.role_id', 'um."role_id"'),
        ('rm.role_name', 'rm."role_name"'),
        ('rm.role_code', 'rm."role_code"'),
        ('um.user_name', 'um."user_name"'),
    ],
    'backend/crm/repositories/additional_repositories.py': [
        ('FROM "Role_Master"', 'FROM "StreemLyne_MT"."Role_Master"'),
        ('FROM "Stage_Master"', 'FROM "StreemLyne_MT"."Stage_Master"'),
        ('FROM "Services_Master"', 'FROM "StreemLyne_MT"."Services_Master"'),
        ('FROM "Supplier_Master"', 'FROM "StreemLyne_MT"."Supplier_Master"'),
        ('FROM "Client_Interactions"', 'FROM "StreemLyne_MT"."Client_Interactions"'),
        ('JOIN "User_Master"', 'JOIN "StreemLyne_MT"."User_Master"'),
        ('WHERE tenant_id', 'WHERE "Tenant_id"'),
        ('ci.tenant_id', 'ci."Tenant_id"'),
        ('role_name', '"role_name"'),
        ('role_code', '"role_code"'),
        ('stage_name', '"stage_name"'),
        ('stage_order', '"stage_order"'),
        ('pipeline_type', '"pipeline_type"'),
        ('service_name', '"service_name"'),
        ('supplier_name', '"supplier_name"'),
        ('um.user_id', 'um."User_id"'),
        ('ci.created_by', 'ci."created_by"'),
        ('um.user_name', 'um."user_name"'),
        ('ci.opportunity_id', 'ci."opportunity_id"'),
    ],
}

print("Applying precise SQL column fixes...\n")

for file_path, replacements in fixes.items():
    if not os.path.exists(file_path):
        print(f"⚠ Skipping {file_path} (not found)")
        continue
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in replacements:
        content = content.replace(old, new)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✓ Fixed {file_path}")

print("\n✅ All SQL queries updated with correct column names!")
