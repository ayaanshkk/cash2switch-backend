"""
Migration: Move existing Lost COT, Invalid Number, Incorrect Supplier records to proper flags
Runs for BOTH Renewals (Client_Master) and Leads (Opportunity_Details)
"""
from backend.db import SessionLocal
from backend.models import Client_Master, Project_Details, Opportunity_Details, Stage_Master
from sqlalchemy import text
from datetime import datetime

def migrate_existing_records():
    session = SessionLocal()
    try:
        # ✅ Statuses that should go to CLEANSING
        cleansing_statuses = ['Invalid Number', 'Incorrect Supplier']
        
        # ✅ Statuses that should go to RECYCLE BIN
        recycle_statuses = ['Lost COT']
        
        print("=" * 80)
        print("🔧 Starting migration for Lost COT, Invalid Number, Incorrect Supplier...")
        print("=" * 80)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PART 1: FIX RENEWALS (Client_Master + Project_Details)
        # ═══════════════════════════════════════════════════════════════════════
        print("\n📦 PART 1: Fixing RENEWALS (Client_Master)")
        print("-" * 80)
        
        # ── Fix Cleansing Records (Invalid Number, Incorrect Supplier) ──────────
        for status in cleansing_statuses:
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Client_Master" cm
                SET 
                    is_deleted = TRUE,
                    deleted_at = COALESCE(cm.deleted_at, NOW()),
                    deleted_reason = :status,
                    is_cleansing = TRUE
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE cm.client_id = pd.client_id
                    AND LOWER(pd.status) = LOWER(:status)
                    AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
                RETURNING cm.client_id, cm.client_company_name
            """), {'status': status})
            
            updated_records = result.fetchall()
            print(f"  ✅ [{status}] → Cleansing: {len(updated_records)} records")
            for record in updated_records[:5]:  # Show first 5
                print(f"     - ID {record[0]}: {record[1]}")
            if len(updated_records) > 5:
                print(f"     ... and {len(updated_records) - 5} more")
        
        # ── Fix Recycle Bin Records (Lost COT) ──────────────────────────────────
        for status in recycle_statuses:
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Client_Master" cm
                SET 
                    is_deleted = TRUE,
                    deleted_at = COALESCE(cm.deleted_at, NOW()),
                    deleted_reason = :status,
                    is_cleansing = FALSE
                FROM "StreemLyne_MT"."Project_Details" pd
                WHERE cm.client_id = pd.client_id
                    AND LOWER(pd.status) = LOWER(:status)
                    AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
                RETURNING cm.client_id, cm.client_company_name
            """), {'status': status})
            
            updated_records = result.fetchall()
            print(f"  ✅ [{status}] → Recycle Bin: {len(updated_records)} records")
            for record in updated_records[:5]:  # Show first 5
                print(f"     - ID {record[0]}: {record[1]}")
            if len(updated_records) > 5:
                print(f"     ... and {len(updated_records) - 5} more")
        
        # ═══════════════════════════════════════════════════════════════════════
        # PART 2: FIX LEADS (Opportunity_Details + Client_Master)
        # ═══════════════════════════════════════════════════════════════════════
        print("\n📋 PART 2: Fixing LEADS (Opportunity_Details)")
        print("-" * 80)
        
        # ── Get stage_ids for cleansing statuses ────────────────────────────────
        cleansing_stage_ids = []
        for status in cleansing_statuses:
            stage = session.query(Stage_Master.stage_id).filter(
                Stage_Master.stage_name == status
            ).first()
            if stage:
                cleansing_stage_ids.append(stage.stage_id)
                print(f"  🔍 Found stage_id {stage.stage_id} for '{status}'")
        
        # ── Get stage_id for Lost COT ───────────────────────────────────────────
        lost_cot_stage_ids = []
        for status in recycle_statuses:
            stage = session.query(Stage_Master.stage_id).filter(
                Stage_Master.stage_name == status
            ).first()
            if stage:
                lost_cot_stage_ids.append(stage.stage_id)
                print(f"  🔍 Found stage_id {stage.stage_id} for '{status}'")
        
        # ── Fix leads with cleansing statuses ───────────────────────────────────
        if cleansing_stage_ids:
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Client_Master" cm
                SET 
                    is_deleted = TRUE,
                    deleted_at = COALESCE(cm.deleted_at, NOW()),
                    deleted_reason = sm.stage_name,
                    is_cleansing = TRUE
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
                WHERE cm.client_id = od.client_id
                    AND od.stage_id = ANY(:stage_ids)
                    AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
                RETURNING cm.client_id, cm.client_company_name, sm.stage_name
            """), {'stage_ids': cleansing_stage_ids})
            
            updated_records = result.fetchall()
            print(f"  ✅ [Cleansing Leads] → {len(updated_records)} records")
            for record in updated_records[:5]:
                print(f"     - ID {record[0]}: {record[1]} ({record[2]})")
            if len(updated_records) > 5:
                print(f"     ... and {len(updated_records) - 5} more")
        
        # ── Fix leads with Lost COT status ──────────────────────────────────────
        if lost_cot_stage_ids:
            result = session.execute(text("""
                UPDATE "StreemLyne_MT"."Client_Master" cm
                SET 
                    is_deleted = TRUE,
                    deleted_at = COALESCE(cm.deleted_at, NOW()),
                    deleted_reason = sm.stage_name,
                    is_cleansing = FALSE
                FROM "StreemLyne_MT"."Opportunity_Details" od
                LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od.stage_id = sm.stage_id
                WHERE cm.client_id = od.client_id
                    AND od.stage_id = ANY(:stage_ids)
                    AND (cm.is_deleted IS NULL OR cm.is_deleted = FALSE)
                RETURNING cm.client_id, cm.client_company_name, sm.stage_name
            """), {'stage_ids': lost_cot_stage_ids})
            
            updated_records = result.fetchall()
            print(f"  ✅ [Lost COT Leads] → Recycle Bin: {len(updated_records)} records")
            for record in updated_records[:5]:
                print(f"     - ID {record[0]}: {record[1]} ({record[2]})")
            if len(updated_records) > 5:
                print(f"     ... and {len(updated_records) - 5} more")
        
        # ═══════════════════════════════════════════════════════════════════════
        # COMMIT CHANGES
        # ═══════════════════════════════════════════════════════════════════════
        session.commit()
        
        print("\n" + "=" * 80)
        print("✅ Migration completed successfully!")
        print("=" * 80)
        print("\n📊 Summary:")
        print(f"  - Cleansing statuses: {', '.join(cleansing_statuses)}")
        print(f"  - Recycle bin statuses: {', '.join(recycle_statuses)}")
        print("\n🔄 Next steps:")
        print("  1. Restart your backend server")
        print("  2. Refresh the frontend")
        print("  3. Check Cleansing page for Invalid Number & Incorrect Supplier")
        print("  4. Check Recycle Bin page for Lost COT records")
        print("=" * 80)
        
    except Exception as e:
        session.rollback()
        print("\n" + "=" * 80)
        print(f"❌ Migration failed: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == '__main__':
    migrate_existing_records()