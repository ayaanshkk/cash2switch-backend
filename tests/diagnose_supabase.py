# -*- coding: utf-8 -*-
"""
Supabase Configuration Helper
Helps diagnose connection issues
"""
import os
import sys
import io
from dotenv import load_dotenv

# Set UTF-8 encoding for console output on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

load_dotenv()

print("=" * 70)
print("SUPABASE CONFIGURATION DIAGNOSTIC")
print("=" * 70)

supabase_url = os.getenv('SUPABASE_URL')
service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
database_url = os.getenv('DATABASE_URL')

# Extract project ID from SUPABASE_URL
if supabase_url:
    project_id = supabase_url.replace('https://', '').replace('.supabase.co', '')
    print(f"\n📌 Current Supabase Project:")
    print(f"   Project ID: {project_id}")
    print(f"   URL: {supabase_url}")
    print(f"   Service Role Key: {'✓ SET' if service_key else '✗ NOT SET'}")
else:
    print("\n✗ SUPABASE_URL not set")
    project_id = None

print(f"\n📌 Database Connection String:")
if database_url:
    # Parse the DATABASE_URL to extract components
    import re
    match = re.match(r'postgresql(?:\+psycopg2)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', database_url)
    if match:
        user, password, host, port, database = match.groups()
        print(f"   User: {user}")
        print(f"   Password: {'*' * len(password)} (length: {len(password)})")
        print(f"   Host: {host}")
        print(f"   Port: {port}")
        print(f"   Database: {database}")
        
        # Check if the host matches the current project
        if project_id and project_id not in host:
            print(f"\n⚠️  WARNING: DATABASE_URL host ({host}) does not match")
            print(f"   current SUPABASE_URL project ({project_id})")
            print(f"\n   This is likely the issue!")
    else:
        print(f"   {database_url}")
else:
    print("   ✗ NOT SET")

print(f"\n" + "=" * 70)
print(f"SOLUTION:")
print(f"=" * 70)
print(f"""
The DATABASE_URL in your .env file is for a DIFFERENT Supabase project.

Current project (from SUPABASE_URL): {project_id}
DATABASE_URL project: sfcrtdqyakkhcwkadgal (different!)

TO FIX THIS:
1. Go to your Supabase dashboard: https://supabase.com/dashboard/project/{project_id}
2. Click on "Project Settings" → "Database"
3. Find the "Connection String" section
4. Copy the "URI" connection string (it includes the password)
5. Replace the DATABASE_URL in your .env file with this string

The format should be:
DATABASE_URL=postgresql://postgres.[PROJECT_ID]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres

OR for direct connection:
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.{project_id}.supabase.co:5432/postgres

Note: Make sure to use the password from the CORRECT project ({project_id})!
""")
