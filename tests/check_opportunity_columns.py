# -*- coding: utf-8 -*-
import sys
import io
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

connection_string = os.getenv('SUPABASE_DB_URL')

print("Checking Opportunity_Details columns...")
try:
    conn = psycopg2.connect(connection_string, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    query = """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'StreemLyne_MT'
        AND table_name = 'Opportunity_Details'
        ORDER BY ordinal_position
    """
    
    cursor.execute(query)
    columns = cursor.fetchall()
    
    print("\nOPPORTUNITY_DETAILS COLUMNS:")
    print("-" * 60)
    for col in columns:
        print(f"{col['column_name']:30} {col['data_type']:20} {'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'}")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
