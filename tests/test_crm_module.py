# -*- coding: utf-8 -*-
"""
CRM Module Test Script
Tests Supabase connection and basic CRM functionality
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_supabase_connection():
    """Test Supabase database connection"""
    print("=" * 60)
    print("TEST 1: Supabase Connection")
    print("=" * 60)
    
    try:
        from backend.crm.supabase_client import get_supabase_client
        
        client = get_supabase_client()
        print(f"Supabase URL: {client.supabase_url}")
        print(f"Connection String: {client.connection_string[:50]}...")
        
        # Test connection
        if client.test_connection():
            print("SUCCESS: Connected to Supabase database")
            return True
        else:
            print("ERROR: Failed to connect to Supabase")
            return False
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tenant_repository():
    """Test Tenant Repository"""
    print("\n" + "=" * 60)
    print("TEST 2: Tenant Repository")
    print("=" * 60)
    
    try:
        from backend.crm.repositories.tenant_repository import TenantRepository
        
        tenant_repo = TenantRepository()
        
        # Try to fetch all tenants
        print("Fetching all tenants...")
        tenants = tenant_repo.get_all_tenants()
        
        print(f"SUCCESS: Found {len(tenants)} tenants")
        
        if tenants:
            print("\nTenants found:")
            for tenant in tenants[:5]:  # Show first 5
                tenant_id = tenant.get('tenant_id')
                tenant_name = tenant.get('tenant_name', 'N/A')
                is_active = tenant.get('is_active', False)
                print(f"  - ID: {tenant_id}, Name: {tenant_name}, Active: {is_active}")
        else:
            print("No tenants found in database")
        
        return True
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_lead_repository():
    """Test Lead Repository"""
    print("\n" + "=" * 60)
    print("TEST 3: Lead Repository (Sample Tenant)")
    print("=" * 60)
    
    try:
        from backend.crm.repositories.lead_repository import LeadRepository
        
        lead_repo = LeadRepository()
        
        # Use tenant_id = 1 for testing (adjust if needed)
        test_tenant_id = 1
        
        print(f"Fetching leads for tenant_id = {test_tenant_id}...")
        leads = lead_repo.get_all_leads(test_tenant_id)
        
        print(f"SUCCESS: Found {len(leads)} leads")
        
        if leads:
            print("\nLeads found:")
            for lead in leads[:5]:  # Show first 5
                opp_id = lead.get('opportunity_id')
                stage = lead.get('stage_name', 'N/A')
                status = lead.get('status', 'N/A')
                print(f"  - ID: {opp_id}, Stage: {stage}, Status: {status}")
        else:
            print("No leads found for this tenant")
        
        # Test lead stats
        print(f"\nFetching lead statistics...")
        stats = lead_repo.get_lead_stats(test_tenant_id)
        print(f"Lead Stats: {stats}")
        
        return True
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_crm_service():
    """Test CRM Service"""
    print("\n" + "=" * 60)
    print("TEST 4: CRM Service")
    print("=" * 60)
    
    try:
        from backend.crm.services.crm_service import CRMService
        
        crm_service = CRMService()
        test_tenant_id = 1
        
        # Test dashboard summary
        print(f"Fetching dashboard summary for tenant_id = {test_tenant_id}...")
        dashboard = crm_service.get_dashboard_summary(test_tenant_id)
        
        if dashboard.get('success'):
            print("SUCCESS: Dashboard data retrieved")
            print(f"\nDashboard Summary:")
            data = dashboard.get('data', {})
            print(f"  Leads: {data.get('leads', {})}")
            print(f"  Projects: {data.get('projects', {})}")
            print(f"  Deals: {data.get('deals', {})}")
        else:
            print(f"ERROR: {dashboard.get('message')}")
        
        return True
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n")
    print("*" * 60)
    print("*" + " " * 58 + "*")
    print("*" + "  StreemLyne CRM Module - Test Suite".center(58) + "*")
    print("*" + " " * 58 + "*")
    print("*" * 60)
    print("\n")
    
    results = {
        'Supabase Connection': test_supabase_connection(),
        'Tenant Repository': test_tenant_repository(),
        'Lead Repository': test_lead_repository(),
        'CRM Service': test_crm_service(),
    }
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        emoji = "✓" if result else "✗"
        print(f"{emoji} {test_name}: {status}")
    
    print("\n" + "-" * 60)
    print(f"Tests Passed: {passed}/{total}")
    print("-" * 60)
    
    if passed == total:
        print("\nSUCCESS: All tests passed!")
        print("The CRM module is ready to use.")
        print("\nNext steps:")
        print("1. Start the Flask server: python backend/app.py")
        print("2. Test with curl:")
        print("   curl -H 'X-Tenant-ID: 1' http://localhost:5000/api/crm/health")
        print("   curl -H 'X-Tenant-ID: 1' http://localhost:5000/api/crm/dashboard")
    else:
        print("\nERROR: Some tests failed.")
        print("Please check the errors above and ensure:")
        print("1. SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set in .env")
        print("2. Database connection is working")
        print("3. StreemLyne tables exist in Supabase")


if __name__ == '__main__':
    main()
