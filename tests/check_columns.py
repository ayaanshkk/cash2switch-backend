# -*- coding: utf-8 -*-
import os, sys, io
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.supabase_client import get_supabase_client

client = get_supabase_client()

# Get column names for key tables
tables = [
    'Tenant_Master',
    'User_Master',
    'Opportunity_Details',
    'Project_Details',
    'Energy_Contract_Master',
    'Client_Interactions',
    'Stage_Master',
    'Role_Master',
]

for table in tables:
    query = f"""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'StreemLyne_MT'
    AND table_name = '{table}'
    ORDER BY ordinal_position
    """
    cols = client.execute_query(query)
    print(f"\n{table}:")
    for col in cols[:10]:  # First 10 columns
        print(f"  - {col['column_name']} ({col['data_type']})")
