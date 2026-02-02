#!/usr/bin/env python
"""Check actual columns in User_Master table"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv('.env')

from backend.crm.supabase_client import SupabaseClient
from sqlalchemy import text

db = SupabaseClient()

# Get actual columns using execute_query
result = db.execute_query("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'StreemLyne_MT'
    AND table_name = 'User_Master'
    ORDER BY ordinal_position
""")

print("📋 Actual columns in StreemLyne_MT.User_Master:")
print("=" * 60)
for row in result:
    print(f"  {row['column_name']:30} {row['data_type']:20} nullable={row['is_nullable']}")
