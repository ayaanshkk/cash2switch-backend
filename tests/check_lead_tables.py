# -*- coding: utf-8 -*-
"""
Check if Lead_Master and Call_Summary tables exist
"""
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
    
    # Check for Lead_Master and Call_Summary
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'StreemLyne_MT'
        AND (table_name ILIKE '%lead%' OR table_name ILIKE '%call%' OR table_name ILIKE '%summary%')
        ORDER BY table_name
    """)
    tables = cursor.fetchall()
    
    print("Tables matching 'lead', 'call', or 'summary':")
    for t in tables:
        print(f"  - {t['table_name']}")
    
    if not tables:
        print("\nNo Lead_Master or Call_Summary tables found.")
        print("\nExisting related tables:")
        print("  - Opportunity_Details (for leads/opportunities)")
        print("  - Client_Interactions (for call logs)")
        print("  - Client_Master (for client data)")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
