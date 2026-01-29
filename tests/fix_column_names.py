# -*- coding: utf-8 -*-
"""
Script to fix all column names in CRM repositories to match Supabase schema
Based on discovered columns and PostgreSQL error hints
"""
import os
import re
import sys
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Column name mappings (lowercase -> correct case)
# Based on Tenant_Master structure and PostgreSQL naming patterns
column_mappings = {
    # Primary keys and IDs
    'tenant_id': '"Tenant_id"',
    'user_id': '"User_id"',
    'opportunity_id': '"Opportunity_id"',
    'project_id': '"Project_id"',
    'contract_id': '"Contract_id"',
    'stage_id': '"Stage_id"',
    'role_id': '"Role_id"',
    'service_id': '"Service_id"',
    'supplier_id': '"Supplier_id"',
    'interaction_id': '"Interaction_id"',
    'module_id': '"Module_id"',
    
    # Common fields
    'is_active': '"is_active"',
    'created_at': '"created_at"',
    'updated_at': '"updated_at"',
    'tenant_name': '"tenant_company_name"',  # Actual column name
    
    # User fields
    'user_name': '"user_name"',
    'assigned_to': '"assigned_to"',
    'created_by': '"created_by"',
    
    # Stage fields
    'stage_name': '"stage_name"',
    'stage_order': '"stage_order"',
    'pipeline_type': '"pipeline_type"',
    
    # Role fields
    'role_name': '"role_name"',
    'role_code': '"role_code"',
    
    # Opportunity fields
    'status': '"status"',
    'estimated_value': '"estimated_value"',
    
    # Project fields
    'project_status': '"project_status"',
    'project_manager_id': '"project_manager_id"',
    
    # Contract fields
    'contract_status': '"contract_status"',
    'contract_owner_id': '"contract_owner_id"',
    'contract_value': '"contract_value"',
    
    # Service/Supplier fields
    'service_name': '"service_name"',
    'supplier_name': '"supplier_name"',
}

# Files to update
repo_files = [
    'backend/crm/repositories/tenant_repository.py',
    'backend/crm/repositories/lead_repository.py',
    'backend/crm/repositories/project_repository.py',
    'backend/crm/repositories/deal_repository.py',
    'backend/crm/repositories/user_repository.py',
    'backend/crm/repositories/additional_repositories.py',
]

def update_column_references(content):
    """Update column references in SQL queries"""
    # Don't replace if already quoted
    for old_name, new_name in column_mappings.items():
        # Match pattern: word boundary + column name + word boundary (not already in quotes)
        # This prevents replacing inside existing quoted strings
        pattern = rf'(?<!")(?<!\w){re.escape(old_name)}(?!\w)(?!")'
        content = re.sub(pattern, new_name, content, flags=re.MULTILINE)
    
    return content

print("Fixing column name mismatches in CRM repositories...\n")

for repo_file in repo_files:
    if not os.path.exists(repo_file):
        print(f"⚠ Skipping {repo_file} (not found)")
        continue
    
    with open(repo_file, 'r', encoding='utf-8') as f:
        original_content = f.read()
    
    updated_content = update_column_references(original_content)
    
    if updated_content != original_content:
        with open(repo_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        print(f"✓ Updated {repo_file}")
    else:
        print(f"- No changes needed for {repo_file}")

print("\n✅ All repository files updated with correct column names!")
