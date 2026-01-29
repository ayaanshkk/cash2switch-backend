#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db import SessionLocal
from backend.models import User
from werkzeug.security import check_password_hash, generate_password_hash

session = SessionLocal()
try:
    # Get admin user
    user = session.query(User).filter_by(email='admin@aztecinteriors.com').first()
    
    if not user:
        print("❌ User not found!")
    else:
        print(f"✅ User found: {user.email}")
        print(f"   Name: {user.first_name} {user.last_name}")
        print(f"   Password hash: {user.password_hash[:50]}...")
        print(f"   Active: {user.is_active}")
        print()
        
        # Test password
        test_pwd = 'admin123'
        result = user.check_password(test_pwd)
        print(f"Testing password '{test_pwd}':")
        print(f"   Result: {'✅ CORRECT' if result else '❌ INCORRECT'}")
        
        # If incorrect, let's rehash it
        if not result:
            print()
            print("🔄 Re-hashing password...")
            user.set_password('admin123')
            session.commit()
            print("✅ Password re-hashed!")
            
            # Verify
            result2 = user.check_password('admin123')
            print(f"   Verification: {'✅ CORRECT' if result2 else '❌ STILL INCORRECT'}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    session.close()
