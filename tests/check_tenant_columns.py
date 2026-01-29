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

tables = [
    'Tenant_Master',
    'User_Master',
    'Opportunity_Details',
    'Project_Details',
    'Energy_Contract_Master',
    'Client_Interactions'
]

print("Checking key CRM tables for Tenant_id column...")
try:
    conn = psycopg2.connect(connection_string, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    for table in tables:
        query = f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
            AND table_name = '{table}'
            AND column_name ILIKE '%tenant%'
            ORDER BY ordinal_position
        """
        
        cursor.execute(query)
        columns = cursor.fetchall()
        
        print(f"\n{table}:")
        if columns:
            for col in columns:
                print(f"  - {col['column_name']}")
        else:
            print(f"  ❌ NO TENANT COLUMN FOUND")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
