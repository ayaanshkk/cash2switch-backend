# -*- coding: utf-8 -*-
"""
Test CRUD operations for Leads (Opportunities)
Tests: Create, Read, Update, Delete with multi-tenant isolation
"""
import sys
import io
import requests
import json

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://127.0.0.1:5000/api/crm"
TENANT_ID = "1"

headers = {
    "X-Tenant-ID": TENANT_ID,
    "Content-Type": "application/json"
}

def print_response(title, response):
    """Pretty print API response"""
    print(f"\n{'='*80}")
    print(f"{title}")
    print(f"{'='*80}")
    print(f"Status Code: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"Response Text: {response.text}")

def test_crud_operations():
    print("Starting CRUD Operations Test for Leads")
    print(f"Base URL: {BASE_URL}")
    print(f"Tenant ID: {TENANT_ID}")
    
    # Step 0: Check if we need to create a test client first
    print("\n[Step 0] Checking existing clients...")
    response = requests.get(f"{BASE_URL}/leads", headers=headers)
    print_response("GET /api/crm/leads (Initial check)", response)
    
    # Step 1: CREATE a new lead
    # Note: client_id must exist in Client_Master for the tenant
    # We'll use client_id=2 which we know exists from the setup script
    
    print("\n[Step 1] CREATE a new lead...")
    new_lead = {
        "client_id": 2,  # Must exist in Client_Master for this tenant
        "opportunity_title": "Test Solar Installation Project",
        "opportunity_description": "Large scale solar panel installation for commercial building",
        "stage_id": 1,  # Must exist in Stage_Master
        "opportunity_value": 25000,  # Must be <= 32767 (smallint max)
        "opportunity_owner_employee_id": None  # Optional field, can be NULL
    }
    
    response = requests.post(f"{BASE_URL}/leads", headers=headers, json=new_lead)
    print_response("CREATE Lead (POST /api/crm/leads)", response)
    
    if response.status_code != 201:
        print("\nERROR: Failed to create lead. Check if:")
        print("  1. client_id=2 exists in Client_Master for tenant_id=1")
        print("  2. stage_id=1 exists in Stage_Master")
        print("  3. Backend logs for detailed error")
        print("\nStopping test...")
        return
    
    created_lead = response.json().get('data', {})
    lead_id = created_lead.get('opportunity_id')
    
    if not lead_id:
        print("\nERROR: No opportunity_id returned from CREATE")
        return
    
    print(f"\nCreated Lead ID: {lead_id}")
    
    # Step 2: READ the created lead
    print(f"\n[Step 2] READ the created lead (ID: {lead_id})...")
    response = requests.get(f"{BASE_URL}/leads", headers=headers)
    print_response(f"READ Leads (GET /api/crm/leads)", response)
    
    # Step 3: READ single lead by ID
    print(f"\n[Step 3] READ single lead by ID...")
    # Note: We don't have a GET /leads/:id endpoint yet, so we'll verify from the list
    
    # Step 4: UPDATE the lead
    print(f"\n[Step 4] UPDATE the lead (ID: {lead_id})...")
    update_data = {
        "opportunity_title": "UPDATED: Test Solar Installation Project",
        "opportunity_value": 30000,  # Must be <= 32767 (smallint max)
        "stage_id": 2  # Move to next stage
    }
    
    response = requests.put(f"{BASE_URL}/leads/{lead_id}", headers=headers, json=update_data)
    print_response(f"UPDATE Lead (PUT /api/crm/leads/{lead_id})", response)
    
    # Step 5: READ again to verify update
    print(f"\n[Step 5] READ again to verify update...")
    response = requests.get(f"{BASE_URL}/leads", headers=headers)
    print_response("READ Leads after UPDATE", response)
    
    # Step 6: Test multi-tenant isolation (try with wrong tenant)
    print(f"\n[Step 6] Test multi-tenant isolation (try with wrong tenant_id=999)...")
    wrong_tenant_headers = {
        "X-Tenant-ID": "999",
        "Content-Type": "application/json"
    }
    response = requests.get(f"{BASE_URL}/leads", headers=wrong_tenant_headers)
    print_response("READ Leads with wrong tenant (should be empty or error)", response)
    
    # Step 7: DELETE the lead
    print(f"\n[Step 7] DELETE the lead (ID: {lead_id})...")
    response = requests.delete(f"{BASE_URL}/leads/{lead_id}", headers=headers)
    print_response(f"DELETE Lead (DELETE /api/crm/leads/{lead_id})", response)
    
    # Step 8: Verify deletion
    print(f"\n[Step 8] Verify deletion...")
    response = requests.get(f"{BASE_URL}/leads", headers=headers)
    print_response("READ Leads after DELETE (should not contain deleted lead)", response)

    print("\n" + "="*80)
    print("CRUD Test Complete!")
    print("="*80)


def test_create_client_and_lead_in_single_call():
    """Integration test: POST /api/crm/leads with client payload should create both records transactionally."""
    print("\n[Integration] CREATE client + lead in a single POST /api/crm/leads call")
    payload = {
        "client": {
            "client_company_name": "ACME Transactional Test Ltd",
            "client_contact_name": "QA Tester",
            "client_phone": "+441234567890",
            "client_email": "qa+lead@example.test",
            "address": "1 Test Street"
        },
        "opportunity_title": "Transactional Lead - ACME",
        "opportunity_description": "Created together with client in one request",
        "opportunity_value": 12345
    }

    response = requests.post(f"{BASE_URL}/leads", headers=headers, json=payload)
    print_response("CREATE client+lead (POST /api/crm/leads)", response)

    assert response.status_code == 201, "Expected 201 Created for client+lead creation"
    body = response.json()
    assert body.get('success') is True
    data = body.get('data')
    assert data and data.get('client') and data.get('opportunity')
    created_client = data['client']
    created_opp = data['opportunity']
    assert created_client.get('client_id') is not None
    assert created_opp.get('opportunity_id') is not None


if __name__ == "__main__":
    try:
        test_crud_operations()
        test_create_client_and_lead_in_single_call()
    except requests.exceptions.ConnectionError:
        print("\nERROR: Cannot connect to backend. Make sure Flask is running on http://127.0.0.1:5000")
    except AssertionError as ae:
        print(f"\nTEST ASSERTION FAILED: {ae}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
