"""
Test JWT authentication flow after secret unification.

This script verifies that:
1. Login returns a valid JWT token
2. Token payload includes user_id and tenant_id
3. Token can be used to access protected endpoints
4. Both /clients and /api/crm/leads work with the same token
"""

import requests
import jwt
import json
from datetime import datetime

# Configuration
BACKEND_URL = "http://localhost:5000"
TEST_CREDENTIALS = {
    "username": "admin",  # Update with valid test credentials
    "password": "admin123"  # Update with valid test credentials
}

def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def test_login():
    """Test login and return token."""
    print_section("1. Testing Login")
    
    url = f"{BACKEND_URL}/auth/login"
    print(f"POST {url}")
    print(f"Body: {json.dumps(TEST_CREDENTIALS, indent=2)}")
    
    try:
        response = requests.post(url, json=TEST_CREDENTIALS, timeout=10)
        print(f"\nStatus: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Login successful!")
            print(f"Response: {json.dumps(data, indent=2)}")
            return data.get('token')
        else:
            print(f"❌ Login failed: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def decode_token(token):
    """Decode and inspect JWT token payload."""
    print_section("2. Inspecting Token Payload")
    
    try:
        # Decode without verification to inspect payload
        payload = jwt.decode(token, options={"verify_signature": False})
        print("✅ Token decoded successfully!")
        print(f"\nPayload: {json.dumps(payload, indent=2, default=str)}")
        
        # Verify required fields
        required_fields = ['user_id', 'tenant_id', 'exp', 'iat']
        missing_fields = [f for f in required_fields if f not in payload]
        
        if missing_fields:
            print(f"\n⚠️  Warning: Missing fields: {missing_fields}")
        else:
            print("\n✅ All required fields present (user_id, tenant_id, exp, iat)")
            
        # Check expiration
        exp_timestamp = payload.get('exp')
        if exp_timestamp:
            exp_date = datetime.fromtimestamp(exp_timestamp)
            print(f"Token expires: {exp_date}")
            
        return payload
        
    except Exception as e:
        print(f"❌ Error decoding token: {e}")
        return None

def test_protected_endpoint(endpoint, token):
    """Test access to a protected endpoint."""
    url = f"{BACKEND_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"\nGET {url}")
    print(f"Headers: Authorization: Bearer {token[:20]}...")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Access granted!")
            data = response.json()
            if isinstance(data, list):
                print(f"Returned {len(data)} items")
            else:
                print(f"Response: {json.dumps(data, indent=2)[:200]}...")
            return True
        elif response.status_code == 401:
            print(f"❌ 401 Unauthorized: {response.text}")
            return False
        else:
            print(f"❌ Error {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Run all authentication tests."""
    print("=" * 60)
    print("  JWT AUTHENTICATION TEST SUITE")
    print("  Backend: " + BACKEND_URL)
    print("=" * 60)
    
    # Test 1: Login
    token = test_login()
    if not token:
        print("\n❌ Cannot proceed without valid token")
        return False
    
    # Test 2: Decode token
    payload = decode_token(token)
    if not payload:
        print("\n❌ Cannot decode token")
        return False
    
    # Test 3: Test protected endpoints
    print_section("3. Testing Protected Endpoints")
    
    endpoints = [
        "/clients",
        "/api/crm/leads"
    ]
    
    results = {}
    for endpoint in endpoints:
        print(f"\n--- Testing {endpoint} ---")
        results[endpoint] = test_protected_endpoint(endpoint, token)
    
    # Summary
    print_section("SUMMARY")
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    for endpoint, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {endpoint}")
    
    print(f"\nResults: {success_count}/{total_count} endpoints accessible")
    
    if success_count == total_count:
        print("\n🎉 All tests passed! JWT authentication is working correctly.")
        return True
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
