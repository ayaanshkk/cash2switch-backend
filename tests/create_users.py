# -*- coding: utf-8 -*-
import sys
import os

# Add to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db import SessionLocal
from backend.models import User

def create_default_users():
    """Create default users for login"""
    session = SessionLocal()
    
    try:
        # Check if users exist
        user_count = session.query(User).count()
        print(f"Current user count: {user_count}")
        
        if user_count > 0:
            print("\nExisting users:")
            for user in session.query(User).all():
                print(f"  - {user.email} ({user.role})")
            return
        
        print("\nCreating default users...")
        
        # Admin user
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
        print("  Created: admin@aztecinteriors.com / admin123")
        
        # Manager user
        manager = User(
            email='ayaan.ateeb@gmail.com',
            first_name='Ayaan',
            last_name='Ateeb',
            role='Manager',
            is_active=True,
            is_verified=True
        )
        manager.set_password('Ayaan#1804')
        session.add(manager)
        print("  Created: ayaan.ateeb@gmail.com / Ayaan#1804")
        
        # Employee user
        employee = User(
            email='employee@aztecinteriors.com',
            first_name='Test',
            last_name='Employee',
            role='Staff',
            is_active=True,
            is_verified=True
        )
        employee.set_password('employee123')
        session.add(employee)
        print("  Created: employee@aztecinteriors.com / employee123")
        
        session.commit()
        print("\nUsers created successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    create_default_users()
