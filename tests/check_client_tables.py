# -*- coding: utf-8 -*-
import os
import sys
import io
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

connection_string = os.getenv('SUPABASE_DB_URL')
print("Checking Client-related tables for Tenant_id...")

try:
    conn = psycopg2.connect(connection_string, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    # Find tables that have client_id or client-related columns
    query = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'StreemLyne_MT'
        AND (column_name ILIKE '%client%' OR table_name ILIKE '%client%')
        ORDER BY table_name, ordinal_position
    """
    cursor.execute(query)
    results = cursor.fetchall()
    
    print("\nTables/Columns related to Client:")
    print("-" * 80)
    current_table = None
    for row in results:
        if current_table != row['table_name']:
            current_table = row['table_name']
            print(f"\n{current_table}:")
        print(f"  {row['column_name']:40} {row['data_type']}")
    
    # Check if there's a Client_Master or similar table with Tenant_id
    print("\n\nChecking for Client_Master or similar table structure:")
    print("-" * 80)
    query2 = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'StreemLyne_MT'
        AND table_name ILIKE '%client%'
    """
    cursor.execute(query2)
    client_tables = cursor.fetchall()
    
    for table in client_tables:
        table_name = table['table_name']
        print(f"\nTable: {table_name}")
        query3 = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
            AND table_name = %s
            ORDER BY ordinal_position
        """
        cursor.execute(query3, (table_name,))
        columns = cursor.fetchall()
        for col in columns:
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            print(f"  {col['column_name']:30} {col['data_type']:20} {nullable}")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
