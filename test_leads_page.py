#!/usr/bin/env python3
"""
Test Leads Import Functionality
"""
import requests

BASE_URL = "http://localhost:5000"
TOKEN = None

def login():
    """Login and get token"""
    global TOKEN
    print("🔐 Logging in...")
    response = requests.post(f"{BASE_URL}/auth/login", json={
        "username": "admin",
        "password": "admin123"
    })
    
    if response.status_code == 200:
        TOKEN = response.json().get('token')
        print(f"✅ Login successful")
        return True
    else:
        print(f"❌ Login failed: {response.status_code} - {response.text}")
        return False

def test_get_leads():
    """Test GET /api/crm/leads"""
    print("\n📋 Testing GET /api/crm/leads...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.get(f"{BASE_URL}/api/crm/leads", headers=headers)
    
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Current leads count: {data.get('count', 0)}")
        return data.get('count', 0)
    else:
        print(f"❌ Failed: {response.text}")
        return None

def test_download_template():
    """Test GET /api/crm/leads/import/template"""
    print("\n📥 Testing template download...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.get(f"{BASE_URL}/api/crm/leads/import/template", headers=headers)
    
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print(f"✅ Template downloaded ({len(response.content)} bytes)")
        # Save template for inspection
        with open('downloaded_template.xlsx', 'wb') as f:
            f.write(response.content)
        print("   Saved as: downloaded_template.xlsx")
        return True
    else:
        print(f"❌ Failed: {response.text}")
        return False

def test_import_leads():
    """Test POST /api/crm/leads/import"""
    print("\n📤 Testing lead import...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    with open('test_leads_import.csv', 'rb') as f:
        files = {'file': ('test_leads_import.csv', f, 'text/csv')}
        response = requests.post(
            f"{BASE_URL}/api/crm/leads/import",
            headers=headers,
            files=files
        )
    
    print(f"Status: {response.status_code}")
    data = response.json()
    
    if response.status_code == 200:
        print(f"✅ Import successful!")
        print(f"   Total rows: {data.get('total_rows', 0)}")
        print(f"   Successful: {data.get('successful', 0)}")
        print(f"   Failed: {data.get('failed', 0)}")
        
        if data.get('errors'):
            print(f"   Errors:")
            for err in data.get('errors', []):
                print(f"     - {err}")
        
        return data.get('successful', 0)
    else:
        print(f"❌ Import failed: {data.get('message', 'Unknown error')}")
        if data.get('errors'):
            for err in data.get('errors', []):
                print(f"   - {err}")
        return 0

def delete_test_leads(initial_count, imported_count):
    """Delete the test leads we just imported"""
    if imported_count == 0:
        print("\n⏭️  No leads to delete")
        return
    
    print(f"\n🗑️  Getting leads to delete...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.get(f"{BASE_URL}/api/crm/leads", headers=headers)
    
    if response.status_code != 200:
        print(f"❌ Failed to fetch leads for deletion")
        return
    
    data = response.json()
    leads = data.get('data', [])
    
    # Get the last N leads (the ones we just imported)
    leads_to_delete = leads[:imported_count]
    
    print(f"Found {len(leads_to_delete)} leads to delete")
    
    deleted = 0
    for lead in leads_to_delete:
        opp_id = lead.get('opportunity_id')
        if opp_id:
            print(f"   Deleting lead {opp_id} ({lead.get('business_name', 'N/A')})...", end=' ')
            del_response = requests.delete(
                f"{BASE_URL}/api/crm/leads/{opp_id}",
                headers=headers
            )
            if del_response.status_code == 200:
                print("✅")
                deleted += 1
            else:
                print(f"❌ ({del_response.status_code})")
    
    print(f"\n✅ Deleted {deleted} test leads")

def main():
    print("=" * 60)
    print("🧪 LEADS PAGE TEST SUITE")
    print("=" * 60)
    
    # Step 1: Login
    if not login():
        return
    
    # Step 2: Get initial lead count
    initial_count = test_get_leads()
    if initial_count is None:
        return
    
    # Step 3: Test template download
    test_download_template()
    
    # Step 4: Test import
    imported_count = test_import_leads()
    
    # Step 5: Verify leads were added
    if imported_count > 0:
        print(f"\n✅ Verifying import...")
        final_count = test_get_leads()
        if final_count is not None:
            expected = initial_count + imported_count
            if final_count >= expected:
                print(f"✅ Lead count increased correctly!")
            else:
                print(f"⚠️  Expected at least {expected} leads, got {final_count}")
    
    # Step 6: Clean up - delete test data
    if imported_count > 0:
        delete_test_leads(initial_count, imported_count)
        
        # Verify deletion
        print(f"\n✅ Verifying deletion...")
        final_count = test_get_leads()
        if final_count == initial_count:
            print(f"✅ All test leads deleted successfully!")
        else:
            print(f"⚠️  Expected {initial_count} leads after cleanup, got {final_count}")
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS COMPLETE!")
    print("=" * 60)

if __name__ == "__main__":
    main()
