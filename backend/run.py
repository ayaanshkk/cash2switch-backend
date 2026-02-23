# File: /backend/run.py
#!/usr/bin/env python3

import os
import sys

# Add the project root to the Python path so backend.* imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from backend.app import create_app
    from backend.db import Base, engine
    print("✅ Successfully imported create_app, Base, and engine")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

app = create_app()

def create_tables():
    """Create database tables"""
    try:
        with app.app_context():
            Base.metadata.create_all(bind=engine)

            print("✅ Database tables created successfully!")
        return True
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")
        return False

def test_routes():
    """Test if routes are loaded"""
    try:
        rules = list(app.url_map.iter_rules())
        print(f"✅ Loaded {len(rules)} routes:")
        for rule in rules:
            if not rule.endpoint.startswith('static'):
                print(f"  - {rule.endpoint}: {rule.rule} [{', '.join(rule.methods)}]")
        return True
    except Exception as e:
        print(f"❌ Error checking routes: {e}")
        return False

if __name__ == '__main__':
    print("🚀 Starting FAI Backend...")
    print("=" * 50)
    
    print("Step 1: Creating Flask app...")
    try:
        app = create_app()
        print("✅ Flask app created successfully")
    except Exception as e:
        print(f"❌ Failed to create app: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("Step 2: Creating database tables...")
    if not create_tables():
        sys.exit(1)
    
    print("Step 3: Testing routes...")
    if not test_routes():
        sys.exit(1)
    
    print("=" * 50)
    print("🎉 Backend setup complete!")
    print("📍 Server will start at: http://127.0.0.1:5000")
    print("💡 Available form generation endpoint: /generate-form-link")
    print("=" * 50)
    
    # Start the server
    try:
        print("Step 4: Starting Flask server...")
        app.run(debug=True, host='127.0.0.1', port=5000)
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")
        sys.exit(1)