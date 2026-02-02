#!/usr/bin/env python3
"""
End-to-end test for Clients page
Tests:
1. Login
2. GET /api/crm/clients
3. Download template
4. Import clients from Excel
5. Verify imported clients appear in list
6. Delete test clients
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import uuid
from io import BytesIO
from openpyxl import Workbook

BASE_URL = "http://localhost:5000"

def create_test_excel():
    """Create a test Excel file with 3 clients"""
    wb = Workbook()
    ws = wb.active
    
    # Headers
    ws.append([
        'Client Company Name', 'Contact Name', 'Email', 'Phone', 
        'Address', 'Industry', 'Annual Revenue', 'Website'
    ])
    
    # Test data with unique suffix
    suffix = uuid.uuid4().hex[:6]
    ws.append([
        f'Test Company A {suffix}', 'John Doe', f'john{suffix}@test.com', '555-0001',
        '123 Test St', 'Technology', '1000000', 'www.testa.com'
    ])
    ws.append([
        f'Test Company B {suffix}', 'Jane Smith', f'jane{suffix}@test.com', '555-0002',
        '456 Test Ave', 'Finance', '2000000', 'www.testb.com'
    ])
    ws.append([
        f'Test Company C {suffix}', 'Bob Johnson', f'bob{suffix}@test.com', '555-0003',
        '789 Test Blvd', 'Healthcare', '3000000', 'www.testc.com'
    ])
    
    # Save to BytesIO
    excel_buffer = BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    
    return excel_buffer, suffix

def test_clients_page():
    """Run comprehensive clients page test"""
    print("=" * 70)
    print("CLIENTS PAGE END-TO-END TEST")
    print("=" * 70)
    
    # Step 1: Create test user and login
    print("\n1. Creating test user and logging in...")
    unique = uuid.uuid4().hex[:8]
    username = f"testclient_{unique}"
    email = f"{unique}@clienttest.com"
    password = "TestPass123"
    
    signup_response = requests.post(
        f"{BASE_URL}/auth/signup",
        json={
            "tenant_id": 1,
            "employee_name": "Client Test User",
            "email": email,
            "username": username,
            "password": password
        }
    )
    
    if signup_response.status_code not in (200, 201):
        print(f"❌ Signup failed: {signup_response.status_code}")
        print(signup_response.text)
        return False
    
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": password}
    )
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        return False
    
    token = login_response.json().get('token')
    print(f"✅ Logged in as {username}")
    
    headers = {
        "Authorization": f"Bearer {token}",
    }
    
    # Step 2: Get existing clients count
    print("\n2. Fetching existing clients...")
    clients_response = requests.get(f"{BASE_URL}/clients", headers=headers)
    
    if clients_response.status_code != 200:
        print(f"❌ Failed to fetch clients: {clients_response.status_code}")
        return False
    
    initial_count = len(clients_response.json().get('data', []))
    print(f"✅ Found {initial_count} existing clients")
    
    # Step 3: Download template
    print("\n3. Testing template download...")
    template_response = requests.get(
        f"{BASE_URL}/clients/import/template",
        headers=headers
    )
    
    if template_response.status_code != 200:
        print(f"❌ Template download failed: {template_response.status_code}")
        return False
    
    template_size = len(template_response.content)
    print(f"✅ Template downloaded: {template_size} bytes")
    
    # Step 4: Create and upload test Excel file
    print("\n4. Creating test Excel file with 3 clients...")
    excel_file, test_suffix = create_test_excel()
    
    files = {'file': ('test_clients.xlsx', excel_file, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    
    print("5. Uploading test file...")
    upload_response = requests.post(
        f"{BASE_URL}/clients/import",
        headers={"Authorization": f"Bearer {token}"},
        files=files
    )
    
    if upload_response.status_code != 200:
        print(f"❌ Upload failed: {upload_response.status_code}")
        print(upload_response.text)
        return False
    
    upload_data = upload_response.json()
    print(f"✅ Upload successful:")
    print(f"   Total rows: {upload_data.get('total_rows', upload_data.get('total', 'N/A'))}")
    print(f"   Successful: {upload_data.get('successful', upload_data.get('inserted', 0))}")
    print(f"   Failed: {upload_data.get('failed', upload_data.get('errors', 0))}")
    
    if upload_data.get('successful', upload_data.get('inserted', 0)) != 3:
        print(f"❌ Expected 3 successful imports, got {upload_data.get('successful', upload_data.get('inserted', 0))}")
        return False
    
    # Step 5: Verify clients appear in list
    print("\n6. Verifying imported clients appear in list...")
    clients_response = requests.get(f"{BASE_URL}/clients", headers=headers)
    
    if clients_response.status_code != 200:
        print(f"❌ Failed to fetch clients after import: {clients_response.status_code}")
        return False
    
    all_clients = clients_response.json().get('data', [])
    new_count = len(all_clients)
    
    if new_count != initial_count + 3:
        print(f"❌ Expected {initial_count + 3} clients, found {new_count}")
        return False
    
    # Find our test clients
    test_clients = [c for c in all_clients if test_suffix in c.get('name', '') or test_suffix in c.get('business_name', '')]
    
    if len(test_clients) != 3:
        print(f"❌ Expected to find 3 test clients, found {len(test_clients)}")
        return False
    
    print(f"✅ Found all 3 imported test clients:")
    for client in test_clients:
        print(f"   - {client.get('name', client.get('business_name', 'Unknown'))} (ID: {client['id']})")
    
    # Step 6: Delete test clients
    print("\n7. Cleaning up: Deleting test clients...")
    deleted_count = 0
    
    for client in test_clients:
        client_id = client['id']  # Use 'id' not 'client_id'
        delete_response = requests.delete(
            f"{BASE_URL}/clients/{client_id}",
            headers=headers
        )
        
        if delete_response.status_code == 200:
            deleted_count += 1
            print(f"   ✅ Deleted client ID {client_id}")
        else:
            print(f"   ❌ Failed to delete client ID {client_id}: {delete_response.status_code}")
    
    if deleted_count != 3:
        print(f"❌ Only deleted {deleted_count}/3 test clients")
        return False
    
    # Step 7: Verify cleanup
    print("\n8. Verifying cleanup...")
    final_response = requests.get(f"{BASE_URL}/clients", headers=headers)
    final_count = len(final_response.json().get('data', []))
    
    if final_count != initial_count:
        print(f"❌ Expected {initial_count} clients after cleanup, found {final_count}")
        return False
    
    print(f"✅ Cleanup verified: {final_count} clients (back to original count)")
    
    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED!")
    print("=" * 70)
    print("\nTest Summary:")
    print("  ✓ User signup and login")
    print("  ✓ Fetch existing clients")
    print("  ✓ Download template")
    print("  ✓ Upload Excel file with 3 clients")
    print("  ✓ Verify imports appear in list")
    print("  ✓ Delete test clients")
    print("  ✓ Verify cleanup complete")
    print("=" * 70)
    
    return True


if __name__ == '__main__':
    try:
        success = test_clients_page()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
