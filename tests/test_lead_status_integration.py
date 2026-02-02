#!/usr/bin/env python3
"""
Integration test for lead status update endpoint
Tests the full endpoint via HTTP requests
Requires backend server to be running on port 5000
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import uuid

BASE_URL = "http://localhost:5000"

def test_lead_status_update():
    """Test PATCH /api/crm/leads/<id>/status endpoint"""
    
    print("=" * 60)
    print("LEAD STATUS UPDATE INTEGRATION TEST")
    print("=" * 60)
    
    # Generate unique credentials
    unique = uuid.uuid4().hex[:8]
    username = f"testuser_{unique}"
    email = f"{unique}@test.com"
    password = "TestPass123"
    
    # Step 1: Create test user via signup
    print(f"\n1. Creating test user (username={username})...")
    signup_response = requests.post(
        f"{BASE_URL}/auth/signup",
        json={
            "tenant_id": 1,
            "employee_name": "Test User",
            "email": email,
            "username": username,
            "password": password
        }
    )
    
    if signup_response.status_code not in (200, 201):
        print(f"❌ Signup failed: {signup_response.status_code}")
        print(signup_response.text)
        return False
    
    print(f"✅ User created successfully")
    
    # Step 2: Login to get JWT token
    print(f"\n2. Logging in as {username}...")
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "username": username,
            "password": password
        }
    )
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        print(login_response.text)
        return False
    
    login_data = login_response.json()
    token = login_data.get('token')
    if not token:
        print(f"❌ No token in response: {login_data}")
        return False
    
    print(f"✅ Login successful, token: {token[:50]}...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Step 3: Get existing leads to find a test opportunity_id
    print("\n3. Fetching existing leads...")
    leads_response = requests.get(
        f"{BASE_URL}/api/crm/leads",
        headers=headers
    )
    
    if leads_response.status_code != 200:
        print(f"❌ Failed to fetch leads: {leads_response.status_code}")
        print(leads_response.text)
        return False
    
    leads_data = leads_response.json()
    if not leads_data.get('data'):
        print("⚠️  No leads found in database. Create a lead first.")
        return False
    
    test_lead = leads_data['data'][0]
    opportunity_id = test_lead['opportunity_id']
    current_stage_id = test_lead.get('stage_id')
    print(f"✅ Found test lead: ID={opportunity_id}, current stage_id={current_stage_id}")
    
    # Step 4: Update the status
    new_stage_id = 2 if current_stage_id != 2 else 3
    print(f"\n4. Updating lead {opportunity_id} status to stage_id={new_stage_id}...")
    
    update_response = requests.patch(
        f"{BASE_URL}/api/crm/leads/{opportunity_id}/status",
        headers=headers,
        json={"stage_id": new_stage_id}
    )
    
    if update_response.status_code != 200:
        print(f"❌ Status update failed: {update_response.status_code}")
        print(update_response.text)
        return False
    
    update_data = update_response.json()
    print(f"✅ Status updated successfully:")
    print(f"   Response: {json.dumps(update_data, indent=2)}")
    
    # Step 5: Verify the update
    print(f"\n5. Verifying update by fetching lead {opportunity_id}...")
    verify_response = requests.get(
        f"{BASE_URL}/api/crm/leads/{opportunity_id}",
        headers=headers
    )
    
    if verify_response.status_code != 200:
        print(f"❌ Verification failed: {verify_response.status_code}")
        return False
    
    verify_data = verify_response.json()
    updated_stage_id = verify_data['data'].get('stage_id')
    
    if updated_stage_id == new_stage_id:
        print(f"✅ Verification successful: stage_id is now {updated_stage_id}")
    else:
        print(f"❌ Verification failed: expected {new_stage_id}, got {updated_stage_id}")
        return False
    
    # Step 6: Test error scenarios
    print("\n6. Testing error scenarios...")
    
    # Test 6a: Missing stage_id
    print("   6a. Testing missing stage_id...")
    error1_response = requests.patch(
        f"{BASE_URL}/api/crm/leads/{opportunity_id}/status",
        headers=headers,
        json={}
    )
    if error1_response.status_code == 400:
        print(f"   ✅ Missing stage_id correctly returned 400")
    else:
        print(f"   ❌ Expected 400, got {error1_response.status_code}")
    
    # Test 6b: Invalid stage_id
    print("   6b. Testing invalid stage_id (string)...")
    error2_response = requests.patch(
        f"{BASE_URL}/api/crm/leads/{opportunity_id}/status",
        headers=headers,
        json={"stage_id": "invalid"}
    )
    if error2_response.status_code == 400:
        print(f"   ✅ Invalid stage_id correctly returned 400")
    else:
        print(f"   ❌ Expected 400, got {error2_response.status_code}")
    
    # Test 6c: Non-existent lead
    print("   6c. Testing non-existent lead...")
    error3_response = requests.patch(
        f"{BASE_URL}/api/crm/leads/999999/status",
        headers=headers,
        json={"stage_id": 2}
    )
    if error3_response.status_code == 404:
        print(f"   ✅ Non-existent lead correctly returned 404")
    else:
        print(f"   ❌ Expected 404, got {error3_response.status_code}")
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    return True


if __name__ == '__main__':
    try:
        success = test_lead_status_update()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
