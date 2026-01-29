# -*- coding: utf-8 -*-
"""
Quick test script to verify Supabase connection
"""
import os
import sys
import io
from dotenv import load_dotenv

# Set UTF-8 encoding for console output on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Load environment variables
load_dotenv()

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("SUPABASE CONNECTION TEST")
print("=" * 60)

# Check environment variables
supabase_url = os.getenv('SUPABASE_URL')
service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
database_url = os.getenv('DATABASE_URL')

print(f"\n1. Environment Variables:")
print(f"   SUPABASE_URL: {supabase_url}")
print(f"   SUPABASE_SERVICE_ROLE_KEY: {'SET' if service_key else 'NOT SET'}")
print(f"   DATABASE_URL: {database_url if database_url else 'NOT SET'}")

# Try to initialize Supabase client
print(f"\n2. Initializing Supabase Client...")
try:
    from backend.crm.supabase_client import get_supabase_client
    
    client = get_supabase_client()
    print(f"   ✓ Client created")
    print(f"   Connection String: {client.connection_string}")
    
    # Test connection
    print(f"\n3. Testing Database Connection...")
    if client.test_connection():
        print(f"   ✓ Connection successful!")
        
        # Try to query Tenant_Master
        print(f"\n4. Querying Tenant_Master table...")
        query = 'SELECT tenant_id, tenant_name, is_active FROM "StreemLyne_MT"."Tenant_Master" LIMIT 5'
        results = client.execute_query(query)
        
        if results:
            print(f"   ✓ Found {len(results)} tenants:")
            for tenant in results:
                print(f"      - ID: {tenant.get('tenant_id')}, Name: {tenant.get('tenant_name')}, Active: {tenant.get('is_active')}")
        else:
            print(f"   ⚠ No tenants found in Tenant_Master table")
    else:
        print(f"   ✗ Connection failed")
        
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
