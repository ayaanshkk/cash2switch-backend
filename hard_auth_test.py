#!/usr/bin/env python3
"""
Hard Auth Smoke Test - Final JWT verification
"""
import os
import requests
import jwt
from dotenv import load_dotenv

# Load .env to get JWT secret
load_dotenv()

BASE_URL = "http://localhost:5000"

print("=" * 60)
print("🔍 HARD AUTH SMOKE TEST")
print("=" * 60)

# Step 1: Check JWT secret from .env
jwt_secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
print(f"\n1️⃣ JWT_SECRET_KEY from .env:")
print(f"   {jwt_secret[:16]}...{jwt_secret[-8:]} (len={len(jwt_secret)})")

# Step 2: Login
print(f"\n2️⃣ Logging in...")
login_payload = {
    "username": "admin",
    "password": "admin123"  # Test password
}

try:
    response = requests.post(f"{BASE_URL}/auth/login", json=login_payload)
    print(f"   Status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"   ❌ Login failed: {response.text}")
        exit(1)
    
    data = response.json()
    token = data.get('token')
    
    if not token:
        print(f"   ❌ No token in response: {data}")
        exit(1)
    
    print(f"   ✅ Got token (first 50 chars): {token[:50]}...")
    
    # Step 3: Decode token with .env secret
    print(f"\n3️⃣ Decoding token with .env secret...")
    try:
        decoded = jwt.decode(token, jwt_secret, algorithms=['HS256'])
        print(f"   ✅ Token decoded successfully!")
        print(f"   Payload:")
        for key, val in decoded.items():
            if key not in ['exp', 'iat']:
                print(f"     - {key}: {val}")
        
        # Check tenant_id
        if 'tenant_id' not in decoded:
            print(f"\n   ⚠️  WARNING: tenant_id missing from JWT payload!")
        else:
            print(f"\n   ✅ tenant_id present: {decoded['tenant_id']}")
            
    except jwt.ExpiredSignatureError:
        print(f"   ❌ Token expired")
        exit(1)
    except jwt.InvalidSignatureError:
        print(f"   ❌ Invalid signature - SECRET MISMATCH!")
        exit(1)
    except Exception as e:
        print(f"   ❌ Decode error: {e}")
        exit(1)
    
    # Step 4: Test /api/crm/leads with token
    print(f"\n4️⃣ Testing /api/crm/leads with token...")
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/crm/leads", headers=headers)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ SUCCESS!")
            print(f"   Response: {data.get('success')}, Count: {data.get('count')}")
        else:
            print(f"   ❌ FAILED!")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"   ❌ Request error: {e}")
        exit(1)
    
    # Step 5: Test /api/clients with same token
    print(f"\n5️⃣ Testing /api/clients with same token...")
    
    try:
        response = requests.get(f"{BASE_URL}/api/clients", headers=headers)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ SUCCESS!")
            print(f"   Response keys: {list(data.keys())}")
        else:
            print(f"   ❌ FAILED!")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"   ❌ Request error: {e}")
        exit(1)
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED - JWT AUTH IS WORKING!")
    print("=" * 60)
    
except requests.ConnectionError:
    print(f"\n❌ Cannot connect to {BASE_URL}")
    print(f"   Is the backend running?")
    exit(1)
except Exception as e:
    print(f"\n❌ Test error: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
