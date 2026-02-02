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
    
    print("\n[Step 1] VERIFY API rejects direct lead creation (now import-only)...")
    new_lead = {
        "client_id": 2,
        "opportunity_title": "Test Solar Installation Project",
        "opportunity_description": "Large scale solar panel installation for commercial building",
        "stage_id": 1,
        "opportunity_value": 25000,
        "opportunity_owner_employee_id": None
    }

    response = requests.post(f"{BASE_URL}/leads", headers=headers, json=new_lead)
    print_response("ATTEMPT CREATE Lead (POST /api/crm/leads)", response)

    # New business rule: leads must be created via Excel import only
    assert response.status_code == 400, "Expected 400 Bad Request when creating leads via API"
    body = response.json()
    assert body.get('success') is False
    assert 'Excel import' in body.get('message', '') or 'import' in body.get('message', '').lower()

    print("\nConfirmed: direct lead creation via API is disallowed; use import/confirm.")

    # Remaining CRUD steps require an existing Opportunity_Details row which must be created
    # via the import flow. Stop here for API-level contract verification.
    return


def test_create_client_and_lead_in_single_call():
    """Integration test: POST /api/crm/leads with client payload is no longer allowed.

    Verifies API returns a validation error and instructs caller to use the import flow.
    """
    print("\n[Integration] ATTEMPT client + lead creation via POST /api/crm/leads (now disallowed)")
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
    print_response("ATTEMPT CREATE client+lead (POST /api/crm/leads)", response)

    # API-level lead creation (including client+lead) is now disallowed — leads must come from import
    assert response.status_code == 400, "Expected 400 Bad Request for client+lead creation via /leads"
    body = response.json()
    assert body.get('success') is False
    assert 'import' in body.get('message', '').lower() or 'excel' in body.get('message', '').lower()


def test_create_client_does_not_create_opportunity():
    """Creating a client (POST /api/crm/clients) must NOT create an Opportunity_Details row."""
    print("\n[Integration] CREATE client via POST /api/crm/clients and ensure no Opportunity_Details is created")
    client_payload = {
        "name": "NoOpp Test Co",
        "phone": "+441234500000",
        "email": "noopp@example.test"
    }
    resp = requests.post(f"http://127.0.0.1:5000/api/crm/clients", headers=headers, json=client_payload)
    print_response("CREATE client (POST /api/crm/clients)", resp)
    assert resp.status_code == 201
    body = resp.json()
    assert body.get('success') is True
    client = body.get('customer') or body.get('client') or {}
    # Ensure API did not return an opportunity
    assert 'opportunity' not in body.get('data', {})

    # Now assert leads list does not include this company's name
    leads_resp = requests.get(f"{BASE_URL}/leads", headers=headers)
    print_response("GET /api/crm/leads after client create", leads_resp)
    assert leads_resp.status_code == 200
    lead_names = [r.get('business_name') for r in leads_resp.json().get('data', [])]
    assert "NoOpp Test Co" not in lead_names, "Client creation must not create an Opportunity_Details row"

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
