# migration_fix_enum.py - Fixed version
import os
import sys

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from backend.db import SessionLocal, Base, engine
from backend.models import Customer
from sqlalchemy import text

def fix_enum_values():
    """Fix empty enum values in the database"""
    app = create_app()
    
    with app.app_context():
        print("Checking for customers with invalid preferred_contact_method values...")
        
        try:
            # Method 1: Check current data using SQLAlchemy text()
            result = session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.execute(
                text("SELECT id, name, preferred_contact_method FROM customers WHERE preferred_contact_method = '' OR preferred_contact_method IS NULL LIMIT 10")
            )
            
            invalid_customers = result.fetchall()
            print(f"Found {len(invalid_customers)} customers with invalid enum values (showing first 10)")
            
            if invalid_customers:
                for customer in invalid_customers:
                    print(f"Customer ID {customer[0]}: {customer[1]} - Contact method: '{customer[2]}'")
            
            # Get total count
            count_result = session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.execute(
                text("SELECT COUNT(*) FROM customers WHERE preferred_contact_method = '' OR preferred_contact_method IS NULL")
            )
            total_invalid = count_result.scalar()
            print(f"Total invalid records: {total_invalid}")
            
            if total_invalid > 0:
                # Method 2: Fix the data
                print(f"\nFixing {total_invalid} invalid enum values...")
                
                # Update empty strings and NULL values to a default
                update_result = session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.execute(
                    text("UPDATE customers SET preferred_contact_method = 'Phone' WHERE preferred_contact_method = '' OR preferred_contact_method IS NULL")
                )
                
                session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.commit()
                print(f"Updated {update_result.rowcount} customer records to use 'Phone' as default")
                
                # Verify the fix
                verify_result = session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.execute(
                    text("SELECT COUNT(*) FROM customers WHERE preferred_contact_method = '' OR preferred_contact_method IS NULL")
                )
                remaining_invalid = verify_result.scalar()
                print(f"Remaining invalid records: {remaining_invalid}")
                
                if remaining_invalid == 0:
                    print("✓ All enum values fixed successfully!")
                else:
                    print(f"⚠ Warning: {remaining_invalid} records still have invalid values")
            else:
                print("✓ No invalid enum values found - database is clean!")
                
        except Exception as e:
            print(f"Error during migration: {e}")
            session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.rollback()
            return False
            
    return True

def check_database_schema():
    """Check if the preferred_contact_method column exists and its current state"""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if the column exists and get some sample data
            result = session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.execute(
                text("SELECT preferred_contact_method, COUNT(*) as count FROM customers GROUP BY preferred_contact_method LIMIT 10")
            )
            
            print("Current preferred_contact_method values in database:")
            print("-" * 50)
            for row in result:
                contact_method = row[0] if row[0] is not None else 'NULL'
                if row[0] == '':
                    contact_method = 'EMPTY_STRING'
                print(f"{contact_method}: {row[1]} records")
                
        except Exception as e:
            print(f"Error checking database schema: {e}")
            print("This might indicate the column doesn't exist or there's a database connection issue.")

def create_backup():
    """Create a backup of the customers table before making changes"""
    app = create_app()
    
    with app.app_context():
        try:
            # For SQLite, we can create a backup table
            session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.execute(
                text("CREATE TABLE customers_backup AS SELECT * FROM customers")
            )
            session = SessionLocal()
# ...do stuff...
session.add(...)
session.commit()
session.close()
.commit()
            print("✓ Backup table 'customers_backup' created successfully")
            return True
        except Exception as e:
            print(f"Failed to create backup: {e}")
            return False

def main():
    """Main migration function"""
    print("Database Enum Fix Migration Tool")
    print("=" * 40)
    
    # Step 1: Check current database state
    print("\n1. Checking current database state...")
    check_database_schema()
    
    # Step 2: Ask user for confirmation
    print("\n2. Migration Options:")
    print("   a) Check database state only (safe)")
    print("   b) Create backup and fix enum values")
    print("   c) Fix enum values without backup (not recommended)")
    
    choice = input("\nEnter your choice (a/b/c): ").lower().strip()
    
    if choice == 'a':
        print("Database check completed. No changes made.")
        return
    elif choice == 'b':
        print("\n3. Creating backup...")
        if not create_backup():
            print("Backup failed. Aborting migration for safety.")
            return
        print("\n4. Fixing enum values...")
        if fix_enum_values():
            print("\n✓ Migration completed successfully!")
        else:
            print("\n✗ Migration failed. Check the error messages above.")
    elif choice == 'c':
        confirm = input("Are you sure you want to proceed without backup? (yes/no): ")
        if confirm.lower() == 'yes':
            print("\n3. Fixing enum values...")
            if fix_enum_values():
                print("\n✓ Migration completed successfully!")
            else:
                print("\n✗ Migration failed. Check the error messages above.")
        else:
            print("Migration cancelled.")
    else:
        print("Invalid choice. Exiting.")

if __name__ == "__main__":
    main()