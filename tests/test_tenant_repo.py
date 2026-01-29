# -*- coding: utf-8 -*-
import os, sys, io
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.repositories.tenant_repository import TenantRepository

print("Testing Tenant Repository...")
tenant_repo = TenantRepository()

# Test get_tenant_by_id
print("\n1. Testing get_tenant_by_id(1)...")
tenant = tenant_repo.get_tenant_by_id(1)
if tenant:
    print(f"   ✓ Success! Tenant: {tenant}")
else:
    print("   ✗ Tenant not found or error occurred")

# Test get_all_tenants
print("\n2. Testing get_all_tenants()...")
tenants = tenant_repo.get_all_tenants()
print(f"   Found {len(tenants)} tenants")
for t in tenants[:3]:
    print(f"   - ID: {t.get('Tenant_id')}, Name: {t.get('tenant_company_name')}")
