# setup_auth.py - Setup authentication system
from app import app
from database import db
from models import User
from datetime import datetime

def setup_authentication():
    """Set up authentication system with demo accounts"""
    with app.app_context():
        print("Setting up Authentication System...")
        
        # Create tables
        Base.metadata.create_all(bind=engine)

        
        # Create demo admin user
        admin_email = "admin@aztecinteriors.com"
        if not User.query.filter_by(email=admin_email).first():
            admin_user = User(
                email=admin_email,
                first_name="Admin",
                last_name="User",
                role="admin",
                department="management",
                is_active=True,
                is_verified=True
            )
            admin_user.set_password("Admin123!")
            session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.add(admin_user)
            print(f"✅ Created admin user: {admin_email}")
        
        # Create demo regular user
        demo_email = "demo@aztecinteriors.com"
        if not User.query.filter_by(email=demo_email).first():
            demo_user = User(
                email=demo_email,
                first_name="Demo",
                last_name="User",
                role="user",
                department="sales",
                phone="01234 567890",
                is_active=True,
                is_verified=True
            )
            demo_user.set_password("Demo123!")
            session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.add(demo_user)
            print(f"✅ Created demo user: {demo_email}")
        
        # Create sample users for different roles
        sample_users = [
            {
                "email": "manager@aztecinteriors.com",
                "first_name": "Sarah",
                "last_name": "Johnson",
                "role": "manager",
                "department": "sales",
                "phone": "01234 567891"
            },
            {
                "email": "designer@aztecinteriors.com",
                "first_name": "Mike",
                "last_name": "Wilson",
                "role": "user",
                "department": "design",
                "phone": "01234 567892"
            },
            {
                "email": "installer@aztecinteriors.com",
                "first_name": "Dave",
                "last_name": "Matthews",
                "role": "user",
                "department": "installation",
                "phone": "01234 567893"
            }
        ]
        
        for user_data in sample_users:
            if not User.query.filter_by(email=user_data["email"]).first():
                user = User(
                    email=user_data["email"],
                    first_name=user_data["first_name"],
                    last_name=user_data["last_name"],
                    role=user_data["role"],
                    department=user_data["department"],
                    phone=user_data["phone"],
                    is_active=True,
                    is_verified=True
                )
                user.set_password("Password123!")
                session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.add(user)
                print(f"✅ Created user: {user_data['email']}")
        
        session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.commit()
        
        print("\n" + "="*50)
        print("🔐 AUTHENTICATION SETUP COMPLETED")
        print("="*50)
        
        print("\nDemo Accounts Created:")
        print("1. Admin Account:")
        print("   Email: admin@aztecinteriors.com")
        print("   Password: Admin123!")
        print("   Role: admin")
        
        print("\n2. Demo Account:")
        print("   Email: demo@aztecinteriors.com") 
        print("   Password: Demo123!")
        print("   Role: user")
        
        print(f"\nTotal users created: {User.query.count()}")
        print("\nNext Steps:")
        print("1. Update your app.py to register the auth blueprint")
        print("2. Add JWT_SECRET_KEY to your environment variables")
        print("3. Wrap your dashboard routes with ProtectedRoute component")
        print("4. Update your navigation to include login/logout")

if __name__ == '__main__':
    setup_authentication()