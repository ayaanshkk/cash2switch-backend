"""
Split existing MPAN numbers into top and bottom parts
MPAN Top: First 12 digits (or whatever exists if shorter)
MPAN Bottom: Everything after 12 digits
Example: 1100039381362900247 → top: 1100039381362, bottom: 900247
"""

import sys
import os

# ✅ Force the correct path
backend_path = r"C:\Users\ayaan\Techmynt Solutions\cash2switch-backend"
sys.path.insert(0, backend_path)

from backend.db import SessionLocal
from backend.models import Energy_Contract_Master

def split_mpan(mpan_string):
    """
    Split MPAN into top (12 digits) and bottom (rest)
    """
    if not mpan_string:
        return None, None
    
    # Remove spaces and clean
    mpan_clean = str(mpan_string).replace(' ', '').strip()
    
    # If empty after cleaning, return None
    if not mpan_clean:
        return None, None
    
    # MPAN Top is first 12 digits (or less if MPAN is shorter)
    mpan_top = mpan_clean[:12]
    
    # MPAN Bottom is everything after 12 digits
    mpan_bottom = mpan_clean[12:] if len(mpan_clean) > 12 else ''
    
    return mpan_top, mpan_bottom

def migrate_mpans():
    session = SessionLocal()
    
    try:
        # Get all contracts with MPANs
        contracts = session.query(Energy_Contract_Master).filter(
            Energy_Contract_Master.mpan_number.isnot(None),
            Energy_Contract_Master.mpan_number != ''
        ).all()
        
        print(f"\nFound {len(contracts)} contracts with MPANs")
        print("="*60)
        
        updated_count = 0
        already_split_count = 0
        empty_count = 0
        
        for contract in contracts:
            # Skip if mpan_bottom already has data (already migrated)
            if contract.mpan_bottom and contract.mpan_bottom.strip():
                already_split_count += 1
                continue
            
            original_mpan = contract.mpan_number
            mpan_top, mpan_bottom = split_mpan(original_mpan)
            
            # Skip only if completely empty
            if not mpan_top:
                empty_count += 1
                continue
            
            # Update the contract (even if short)
            contract.mpan_number = mpan_top
            contract.mpan_bottom = mpan_bottom if mpan_bottom else None
            updated_count += 1
            
            # Log first 10 examples (including short ones)
            if updated_count <= 10:
                print(f"Example {updated_count}:")
                print(f"   Original: '{original_mpan}' (length: {len(original_mpan)})")
                print(f"   Top:      '{mpan_top}' (length: {len(mpan_top)})")
                print(f"   Bottom:   '{mpan_bottom}' (length: {len(mpan_bottom) if mpan_bottom else 0})")
                print()
            
            # Commit in batches of 100
            if updated_count % 100 == 0:
                print(f"✅ Processed {updated_count} contracts...")
                session.commit()
        
        # Final commit
        session.commit()
        
        print("="*60)
        print(f"\n🎉 Migration complete!")
        print(f"   ✅ Updated: {updated_count}")
        print(f"   ⏭️  Already split: {already_split_count}")
        print(f"   ⚠️  Empty/null: {empty_count}")
        print(f"   📊 Total: {len(contracts)}")
        print()
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == '__main__':
    print("\n" + "="*60)
    print("MPAN MIGRATION SCRIPT")
    print("="*60)
    print("This will split existing MPANs into:")
    print("  • MPAN Top: First 12 digits (or all if shorter)")
    print("  • MPAN Bottom: Everything after 12 digits")
    print()
    print("Example: 1100039381362900247")
    print("  → Top: 1100039381362")
    print("  → Bottom: 900247")
    print()
    print("Short MPANs will also be processed:")
    print("Example: 12345")
    print("  → Top: 12345")
    print("  → Bottom: (empty)")
    print("="*60)
    
    confirm = input("\nContinue? (yes/no): ")
    if confirm.lower() == 'yes':
        migrate_mpans()
    else:
        print("Cancelled")