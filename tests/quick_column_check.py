# -*- coding: utf-8 -*-
import os, sys, io
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.supabase_client import get_supabase_client

client = get_supabase_client()

# Just query one record to see column names
query = 'SELECT * FROM "StreemLyne_MT"."Tenant_Master" LIMIT 1'
try:
    result = client.execute_query(query, fetch_one=True)
    if result:
        print("Tenant_Master columns:")
        for col_name in result.keys():
            print(f"  {col_name}")
    else:
        print("No data in Tenant_Master")
except Exception as e:
    print(f"Error: {e}")
