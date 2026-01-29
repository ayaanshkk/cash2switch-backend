# -*- coding: utf-8 -*-
"""Script to update all CRM repositories to use StreemLyne_MT schema"""
import os
import re
import sys
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Repository files to update
repo_files = [
    'backend/crm/repositories/lead_repository.py',
    'backend/crm/repositories/project_repository.py',
    'backend/crm/repositories/deal_repository.py',
    'backend/crm/repositories/user_repository.py',
    'backend/crm/repositories/additional_repositories.py',
]

# Table mappings (old name -> schema.table)
table_mappings = {
    '"Opportunity_Details"': '"StreemLyne_MT"."Opportunity_Details"',
    '"Stage_Master"': '"StreemLyne_MT"."Stage_Master"',
    '"User_Master"': '"StreemLyne_MT"."User_Master"',
    '"Project_Details"': '"StreemLyne_MT"."Project_Details"',
    '"Energy_Contract_Master"': '"StreemLyne_MT"."Energy_Contract_Master"',
    '"Role_Master"': '"StreemLyne_MT"."Role_Master"',
    '"Services_Master"': '"StreemLyne_MT"."Services_Master"',
    '"Supplier_Master"': '"StreemLyne_MT"."Supplier_Master"',
    '"Client_Interactions"': '"StreemLyne_MT"."Client_Interactions"',
}

for repo_file in repo_files:
    if not os.path.exists(repo_file):
        print(f"Skipping {repo_file} (not found)")
        continue
    
    with open(repo_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Replace all table references
    for old_table, new_table in table_mappings.items():
        content = content.replace(old_table, new_table)
    
    if content != original_content:
        with open(repo_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ Updated {repo_file}")
    else:
        print(f"- No changes needed for {repo_file}")

print("\n✅ All repository files updated with StreemLyne_MT schema!")
