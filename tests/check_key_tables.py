# -*- coding: utf-8 -*-
import os, sys, io
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.supabase_client import get_supabase_client

client = get_supabase_client()

# Check key tables
tables = [
    'Tenant_Master',
    'User_Master',
    'Opportunity_Details',
    'Project_Details',
    'Energy_Contract_Master',
]

for table in tables:
    query = f'SELECT * FROM "StreemLyne_MT"."{table}" LIMIT 1'
    try:
        result = client.execute_query(query, fetch_one=True)
        print(f"\n{table}:")
        if result:
            for col_name in result.keys():
                print(f"  {col_name}")
        else:
            print("  (no data)")
    except Exception as e:
        print(f"  ERROR: {e}")
