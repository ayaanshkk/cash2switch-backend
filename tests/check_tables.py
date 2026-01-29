# -*- coding: utf-8 -*-
import os
import sys
import io
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.supabase_client import get_supabase_client

print("Checking available tables in Supabase database...")
client = get_supabase_client()

# List all tables
query = """
SELECT table_schema, table_name 
FROM information_schema.tables 
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name
"""

results = client.execute_query(query)
print(f"\nFound {len(results)} tables:")
for row in results:
    print(f"  {row['table_schema']}.{row['table_name']}")
