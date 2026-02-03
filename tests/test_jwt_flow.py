#!/usr/bin/env python
"""Test JWT secret consistency across login and verification"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv('.env')

# Import Flask app
from backend.app import create_app
app = create_app()

# Get secret from config
app_secret = app.config['SECRET_KEY']
print(f"🔑 App config SECRET_KEY: {app_secret[:30]}... (len={len(app_secret)})")

# Now test login
with app.test_client() as client:
    # Login
    resp = client.post('/auth/login', json={'username': 'admin', 'password': 'admin123'})
    print(f"\n📡 Login Response: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.get_json()
        token = data['token']
        print(f"✅ Got token: {token[:50]}...")
        
        # Try to decode it
        import jwt
        try:
            decoded = jwt.decode(token, app_secret, algorithms=['HS256'])
            print(f"✅ Token decodes with app_secret!")
            print(f"   Payload: {decoded}")
        except jwt.InvalidSignatureError:
            print(f"❌ Token does NOT decode with app_secret!")
            print(f"   This means login used a different secret!")
            
            # Try with old secret
            old_secret = "dev-secret-key-change-in-production"
            try:
                decoded = jwt.decode(token, old_secret, algorithms=['HS256'])
                print(f"⚠️  Token decodes with OLD secret: {old_secret}")
            except:
                print(f"❌ Token doesn't decode with old secret either!")
        
        # Now test /api/crm/leads
        print(f"\n📡 Testing /api/crm/leads...")
        resp2 = client.get('/api/crm/leads', headers={'Authorization': f'Bearer {token}'})
        print(f"   Response: {resp2.status_code}")
        print(f"   Body: {resp2.get_json()}")
    else:
        print(f"❌ Login failed: {resp.get_json()}")
