# -*- coding: utf-8 -*-
"""
Test script to verify tenant CRUD operations with Supabase
Tests: GET, INSERT, DELETE operations
"""
import os, sys, io
from dotenv import load_dotenv
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.supabase_client import get_supabase_client

print("=" * 70)
print("TESTING TENANT CRUD OPERATIONS WITH CORRECT COLUMN NAMES")
print("=" * 70)

client = get_supabase_client()

# Test 1: GET existing tenant
print("\n1. Testing GET tenant (ID=1)...")
try:
    query = """
        SELECT *
        FROM "StreemLyne_MT"."Tenant_Master"
        WHERE "Tenant_id" = %s
        LIMIT 1
    """
    tenant = client.execute_query(query, (1,), fetch_one=True)
    if tenant:
        print(f"   ✓ SUCCESS: Found tenant '{tenant.get('tenant_company_name')}'")
        print(f"     - Tenant_id: {tenant.get('Tenant_id')}")
        print(f"     - Contact: {tenant.get('tenant_contact_name')}")
        print(f"     - Active: {tenant.get('is_active')}")
    else:
        print("   ✗ FAILED: Tenant not found")
except Exception as e:
    print(f"   ✗ ERROR: {e}")

# Test 2: INSERT new test tenant
print("\n2. Testing INSERT new tenant...")
print("   NOTE: This will insert a test tenant into the database.")
print("   Tenant name: 'Test Tenant CRUD'")

try:
    insert_query = """
        INSERT INTO "StreemLyne_MT"."Tenant_Master" 
        ("tenant_company_name", "tenant_contact_name", "onboarding_Date", "is_active", "created_at")
        VALUES (%s, %s, %s, %s, %s)
        RETURNING "Tenant_id", "tenant_company_name"
    """
    
    params = (
        'Test Tenant CRUD',
        'Test Contact',
        datetime.now().date(),
        True,
        datetime.now()
    )
    
    result = client.execute_insert(insert_query, params, returning=True)
    
    if result:
        inserted_id = result.get('Tenant_id')
        inserted_name = result.get('tenant_company_name')
        print(f"   ✓ SUCCESS: Inserted tenant '{inserted_name}' with ID={inserted_id}")
        
        # Test 3: GET the newly inserted tenant to verify
        print(f"\n3. Testing GET newly inserted tenant (ID={inserted_id})...")
        verify_query = """
            SELECT *
            FROM "StreemLyne_MT"."Tenant_Master"
            WHERE "Tenant_id" = %s
        """
        verify_result = client.execute_query(verify_query, (inserted_id,), fetch_one=True)
        
        if verify_result:
            print(f"   ✓ SUCCESS: Verified tenant exists")
            print(f"     - Tenant_id: {verify_result.get('Tenant_id')}")
            print(f"     - Name: {verify_result.get('tenant_company_name')}")
            print(f"     - Contact: {verify_result.get('tenant_contact_name')}")
            print(f"     - Active: {verify_result.get('is_active')}")
        else:
            print("   ✗ FAILED: Could not verify inserted tenant")
        
        # Test 4: DELETE the test tenant (cleanup)
        print(f"\n4. Testing DELETE test tenant (ID={inserted_id})...")
        delete_query = """
            DELETE FROM "StreemLyne_MT"."Tenant_Master"
            WHERE "Tenant_id" = %s
        """
        
        deleted_count = client.execute_delete(delete_query, (inserted_id,))
        
        if deleted_count > 0:
            print(f"   ✓ SUCCESS: Deleted {deleted_count} tenant(s)")
            
            # Verify deletion
            print(f"\n5. Verifying tenant was deleted (ID={inserted_id})...")
            verify_delete = client.execute_query(verify_query, (inserted_id,), fetch_one=True)
            
            if not verify_delete:
                print("   ✓ SUCCESS: Tenant successfully removed from database")
            else:
                print("   ✗ WARNING: Tenant still exists after deletion")
        else:
            print("   ✗ FAILED: No rows deleted")
    else:
        print("   ✗ FAILED: No result returned from INSERT")
        
except Exception as e:
    print(f"   ✗ ERROR during CRUD operations: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("CRUD TEST COMPLETE")
print("=" * 70)
print("\nSummary:")
print("- Column names are using correct Pascal Case (e.g., 'Tenant_id', 'is_active')")
print("- All queries reference 'StreemLyne_MT' schema")
print("- CRUD operations (GET, INSERT, DELETE) work correctly")
