# -*- coding: utf-8 -*-
"""
Comprehensive Database Structure Analysis
Analyzes all tables, columns, relationships, and constraints in StreemLyne_MT schema
"""
import sys
import io
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv()

connection_string = os.getenv('SUPABASE_DB_URL')

print("=" * 100)
print("STREEMLYNE DATABASE ARCHITECTURE ANALYSIS")
print("=" * 100)

try:
    conn = psycopg2.connect(connection_string, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    # 1. GET ALL TABLES
    print("\n[1] ALL TABLES IN StreemLyne_MT SCHEMA:")
    print("-" * 100)
    cursor.execute("""
        SELECT 
            table_name,
            (SELECT COUNT(*) FROM information_schema.columns 
             WHERE table_schema = 'StreemLyne_MT' 
             AND table_name = t.table_name) as column_count
        FROM information_schema.tables t
        WHERE table_schema = 'StreemLyne_MT'
        ORDER BY table_name
    """)
    tables = cursor.fetchall()
    
    print(f"\nTotal Tables: {len(tables)}\n")
    for i, table in enumerate(tables, 1):
        print(f"{i:2}. {table['table_name']:40} ({table['column_count']} columns)")
    
    # 2. DETAILED TABLE STRUCTURE
    print("\n\n[2] DETAILED TABLE STRUCTURES:")
    print("=" * 100)
    
    for table in tables:
        table_name = table['table_name']
        print(f"\n{'='*100}")
        print(f"TABLE: {table_name}")
        print('='*100)
        
        # Get columns
        cursor.execute("""
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
            AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        columns = cursor.fetchall()
        
        print(f"\nColumns ({len(columns)}):")
        print("-" * 100)
        print(f"{'Column Name':<35} {'Type':<25} {'Nullable':<10} {'Default'}")
        print("-" * 100)
        
        for col in columns:
            col_name = col['column_name']
            data_type = col['data_type']
            if col['character_maximum_length']:
                data_type += f"({col['character_maximum_length']})"
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            default = col['column_default'] or ""
            if len(default) > 40:
                default = default[:37] + "..."
            
            print(f"{col_name:<35} {data_type:<25} {nullable:<10} {default}")
        
        # Get primary keys
        cursor.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = 'StreemLyne_MT'
            AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
        """, (table_name,))
        pks = cursor.fetchall()
        
        if pks:
            print(f"\nPrimary Key: {', '.join([pk['column_name'] for pk in pks])}")
        
        # Get foreign keys
        cursor.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                rc.delete_rule
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            JOIN information_schema.referential_constraints AS rc
                ON rc.constraint_name = tc.constraint_name
                AND rc.constraint_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'StreemLyne_MT'
            AND tc.table_name = %s
        """, (table_name,))
        fks = cursor.fetchall()
        
        if fks:
            print(f"\nForeign Keys ({len(fks)}):")
            for fk in fks:
                print(f"  - {fk['column_name']} -> {fk['foreign_table_name']}.{fk['foreign_column_name']} (ON DELETE {fk['delete_rule']})")
        
        # Get row count (sample)
        try:
            cursor.execute(f'SELECT COUNT(*) as count FROM "StreemLyne_MT"."{table_name}"')
            count = cursor.fetchone()['count']
            print(f"\nRow Count: {count}")
        except Exception as e:
            print(f"\nRow Count: Unable to fetch ({str(e)[:50]})")
    
    # 3. DATABASE RELATIONSHIPS SUMMARY
    print("\n\n" + "=" * 100)
    print("[3] DATABASE RELATIONSHIP SUMMARY")
    print("=" * 100)
    
    cursor.execute("""
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = 'StreemLyne_MT'
        ORDER BY tc.table_name, kcu.column_name
    """)
    all_fks = cursor.fetchall()
    
    print(f"\nTotal Foreign Key Relationships: {len(all_fks)}\n")
    
    current_table = None
    for fk in all_fks:
        if fk['table_name'] != current_table:
            current_table = fk['table_name']
            print(f"\n{current_table}:")
        print(f"  └─ {fk['column_name']} → {fk['foreign_table_name']}.{fk['foreign_column_name']}")
    
    # 4. MULTI-TENANT ARCHITECTURE ANALYSIS
    print("\n\n" + "=" * 100)
    print("[4] MULTI-TENANT ARCHITECTURE ANALYSIS")
    print("=" * 100)
    
    print("\nTables with tenant_id or Tenant_id column:")
    for table in tables:
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
            AND table_name = %s
            AND column_name ILIKE '%tenant%'
        """, (table['table_name'],))
        tenant_cols = cursor.fetchall()
        if tenant_cols:
            print(f"  ✓ {table['table_name']:40} - {', '.join([c['column_name'] for c in tenant_cols])}")
    
    print("\n\nTables WITHOUT tenant isolation:")
    for table in tables:
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'StreemLyne_MT'
            AND table_name = %s
            AND column_name ILIKE '%tenant%'
        """, (table['table_name'],))
        tenant_cols = cursor.fetchall()
        if not tenant_cols:
            print(f"  ✗ {table['table_name']}")
    
    # 5. TABLE CATEGORIZATION
    print("\n\n" + "=" * 100)
    print("[5] TABLE CATEGORIZATION BY PURPOSE")
    print("=" * 100)
    
    categories = {
        "Core Tenant & Auth": [],
        "CRM & Sales": [],
        "Projects & Contracts": [],
        "Financial": [],
        "Master Data": [],
        "Configuration": []
    }
    
    for table in tables:
        name = table['table_name']
        if 'tenant' in name.lower() or 'subscription' in name.lower():
            categories["Core Tenant & Auth"].append(name)
        elif 'opportunity' in name.lower() or 'client' in name.lower() or 'interaction' in name.lower():
            categories["CRM & Sales"].append(name)
        elif 'project' in name.lower() or 'contract' in name.lower() or 'proposal' in name.lower():
            categories["Projects & Contracts"].append(name)
        elif 'invoice' in name.lower():
            categories["Financial"].append(name)
        elif name.endswith('_Master'):
            categories["Master Data"].append(name)
        else:
            categories["Configuration"].append(name)
    
    for category, table_list in categories.items():
        if table_list:
            print(f"\n{category} ({len(table_list)} tables):")
            for t in sorted(table_list):
                print(f"  - {t}")
    
    cursor.close()
    conn.close()
    
    print("\n\n" + "=" * 100)
    print("ANALYSIS COMPLETE")
    print("=" * 100)

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
