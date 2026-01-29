# -*- coding: utf-8 -*-
import sys
import io
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv()

connection_string = os.getenv('SUPABASE_DB_URL')

try:
    conn = psycopg2.connect(connection_string, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    print("User_Master columns:")
    print("="*80)
    cursor.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'StreemLyne_MT'
        AND table_name = 'User_Master'
        ORDER BY ordinal_position
    """)
    columns = cursor.fetchall()
    for col in columns:
        nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
        print(f"{col['column_name']:30} {col['data_type']:20} {nullable}")
    
    # Also check if there are any users
    print("\n\nExisting users (first 5):")
    print("="*80)
    cursor.execute("""
        SELECT * FROM "StreemLyne_MT"."User_Master"
        LIMIT 5
    """)
    users = cursor.fetchall()
    if users:
        for user in users:
            print(dict(user))
    else:
        print("No users found")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
