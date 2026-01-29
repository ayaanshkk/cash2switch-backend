#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db import SessionLocal
from backend.models import User

session = SessionLocal()
try:
    # Check existing users
    existing_user = session.query(User).filter_by(email='admin@aztecinteriors.com').first()
    
    if existing_user:
        print(f"✅ User already exists: {existing_user.email}")
        print(f"   Name: {existing_user.first_name} {existing_user.last_name}")
        print(f"   Role: {existing_user.role}")
        print(f"   Active: {existing_user.is_active}")
    else:
        # Create admin user
        admin = User(
            email='admin@aztecinteriors.com',
            first_name='Admin',
            last_name='User',
            role='Manager',
            is_active=True,
            is_verified=True
        )
        admin.set_password('admin123')
        session.add(admin)
        session.commit()
        print("✅ Created user: admin@aztecinteriors.com / admin123")
        
except Exception as e:
    session.rollback()
    print(f"❌ Error: {e}")
finally:
    session.close()
