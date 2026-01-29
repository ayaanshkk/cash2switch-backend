# -*- coding: utf-8 -*-
import sys, io, psycopg2, os
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv()

conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'), cursor_factory=RealDictCursor)
cursor = conn.cursor()

# Check for employee tables
cursor.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'StreemLyne_MT'
    AND table_name ILIKE '%employee%'
""")
print('Employee-related tables:')
for r in cursor.fetchall():
    print(f"  - {r['table_name']}")

# List ALL tables to understand the schema better
cursor.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'StreemLyne_MT'
    ORDER BY table_name
""")
print('\nAll StreemLyne_MT tables:')
for r in cursor.fetchall():
    print(f"  - {r['table_name']}")

cursor.close()
conn.close()
