# -*- coding: utf-8 -*-
"""
Setup test data for CRUD testing
Creates a test client, stage, and user for tenant_id=1
"""
import sys
import io
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

connection_string = os.getenv('SUPABASE_DB_URL')

print("Setting up test data for tenant_id=1...")

try:
    conn = psycopg2.connect(connection_string, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    # Check existing test client
    print("\n[1] Checking for existing clients for tenant_id=1...")
    cursor.execute("""
        SELECT "client_id", "client_company_name", "tenant_id"
        FROM "StreemLyne_MT"."Client_Master"
        WHERE "tenant_id" = 1
        LIMIT 5
    """)
    clients = cursor.fetchall()
    
    if clients:
        print(f"Found {len(clients)} existing client(s):")
        for client in clients:
            print(f"  - client_id: {client['client_id']}, name: {client['client_company_name']}")
    else:
        print("No clients found for tenant_id=1. Creating test client...")
        cursor.execute("""
            INSERT INTO "StreemLyne_MT"."Client_Master"
            ("tenant_id", "client_company_name", "client_contact_name", "client_email", "created_at")
            VALUES (1, 'Test Client Corp', 'John Doe', 'test@example.com', CURRENT_TIMESTAMP)
            RETURNING "client_id", "client_company_name"
        """)
        new_client = cursor.fetchone()
        conn.commit()
        print(f"✓ Created test client: ID={new_client['client_id']}, Name={new_client['client_company_name']}")
        clients = [new_client]
    
    test_client_id = clients[0]['client_id']
    
    # Check existing stages
    print("\n[2] Checking for existing stages...")
    cursor.execute("""
        SELECT "stage_id", "stage_name"
        FROM "StreemLyne_MT"."Stage_Master"
        ORDER BY "stage_id"
        LIMIT 5
    """)
    stages = cursor.fetchall()
    
    if stages:
        print(f"Found {len(stages)} existing stage(s):")
        for stage in stages:
            print(f"  - stage_id: {stage['stage_id']}, name: {stage['stage_name']}")
    else:
        print("No stages found. Creating test stages...")
        cursor.execute("""
            INSERT INTO "StreemLyne_MT"."Stage_Master"
            ("stage_name", "stage_order", "created_at")
            VALUES 
                ('Lead', 1, CURRENT_TIMESTAMP),
                ('Qualified', 2, CURRENT_TIMESTAMP),
                ('Proposal', 3, CURRENT_TIMESTAMP)
            RETURNING "stage_id", "stage_name"
        """)
        new_stages = cursor.fetchall()
        conn.commit()
        print(f"✓ Created {len(new_stages)} test stages")
        stages = new_stages
    
    test_stage_id = stages[0]['stage_id']
    
    # Check existing users for tenant
    print("\n[3] Checking for existing users for tenant_id=1...")
    cursor.execute("""
        SELECT "user_id", "user_name", "tenant_id"
        FROM "StreemLyne_MT"."User_Master"
        WHERE "tenant_id" = 1
        LIMIT 5
    """)
    users = cursor.fetchall()
    
    if users:
        print(f"Found {len(users)} existing user(s):")
        for user in users:
            print(f"  - user_id: {user['user_id']}, name: {user['user_name']}")
    else:
        print("No users found for tenant_id=1. Creating test user...")
        cursor.execute("""
            INSERT INTO "StreemLyne_MT"."User_Master"
            ("tenant_id", "user_name", "user_email", "role_id", "created_at")
            VALUES (1, 'Test User', 'testuser@example.com', 1, CURRENT_TIMESTAMP)
            RETURNING "user_id", "user_name"
        """)
        new_user = cursor.fetchone()
        conn.commit()
        print(f"✓ Created test user: ID={new_user['user_id']}, Name={new_user['user_name']}")
        users = [new_user]
    
    test_user_id = users[0]['user_id']
    
    print("\n" + "="*80)
    print("Test data ready!")
    print("="*80)
    print(f"  client_id: {test_client_id}")
    print(f"  stage_id: {test_stage_id}")
    print(f"  user_id (opportunity_owner_employee_id): {test_user_id}")
    print("\nUse these IDs in your CRUD test.")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
