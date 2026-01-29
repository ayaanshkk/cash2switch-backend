# -*- coding: utf-8 -*-
import os, sys, io
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.supabase_client import get_supabase_client

client = get_supabase_client()

# Tables to inspect
tables = {
    'Tenant_Master': 'tenant',
    'User_Master': 'user',
    'Role_Master': 'role',
    'Stage_Master': 'stage',
    'Opportunity_Details': 'opportunity',
    'Project_Details': 'project',
    'Energy_Contract_Master': 'contract',
    'Services_Master': 'service',
    'Supplier_Master': 'supplier',
    'Client_Interactions': 'interaction',
    'Module_Master': 'module',
    'Tenant_Module_Mapping': 'tenant_module',
}

print("DISCOVERING ACTUAL COLUMN NAMES FROM SUPABASE\n" + "=" * 70)

for table_name, alias in tables.items():
    query = """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'StreemLyne_MT'
    AND table_name = %s
    ORDER BY ordinal_position
    """
    try:
        cols = client.execute_query(query, (table_name,))
        print(f"\n{table_name}:")
        for col in cols:
            print(f"  {col['column_name']} ({col['data_type']})")
    except Exception as e:
        print(f"\n{table_name}: ERROR - {e}")

print("\n" + "=" * 70)
