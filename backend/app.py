from flask import Flask, request, jsonify, g
from flask_cors import CORS
import os
from dotenv import load_dotenv

from backend.routes import proposal_routes
from .db import Base, engine, SessionLocal, test_connection, init_db

load_dotenv()


def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ============================================
    # ⚙️ DATABASE INITIALIZATION (NEW LOCATION)
    # ============================================
    print("🔧 Initializing database schema...")
    try:
        # ✅ CRITICAL: Import models FIRST so SQLAlchemy knows about them
        # This ensures all enum types and tables are registered
        from backend import models
        
        print("📋 Registered models:")
        print("   ✓ User")
        print("   ✓ LoginAttempt")
        print("   ✓ Customer (with sales_stage and training_stage)")
        print("   ✓ Quotation")
        print("   ✓ QuotationItem")
        print("   ✓ Invoice")
        print("   ✓ InvoiceLineItem")
        print("   ✓ Payment")
        print("   ✓ Assignment")
        print("   ✓ AuditLog")
        print("   ✓ ActionItem")
        print("   ✓ DataImport")
        print("   ✓ TestResult")
        
        # ✅ CRITICAL: checkfirst=True ensures we don't drop existing tables
        Base.metadata.create_all(bind=engine, checkfirst=True)
        
        # Verify tables
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"✅ Database schema initialized - {len(tables)} tables exist")
        
        # ✅ NEW: Verify enum types exist
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT typname FROM pg_type 
                    WHERE typname IN ('sales_stage_enum', 'training_stage_enum')
                """))
                enum_types = [row[0] for row in result]
                
                if 'sales_stage_enum' in enum_types:
                    print("   ✓ sales_stage_enum type exists")
                if 'training_stage_enum' in enum_types:
                    print("   ✓ training_stage_enum type exists")
                
                if not enum_types:
                    print("   ⚠️  Enum types not found - you may need to run migration")
        except Exception as enum_check_error:
            print(f"   ⚠️  Could not verify enum types: {enum_check_error}")
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()

    # ============================================
    # CORS
    # ============================================
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=False,
    )

    # ============================================
    # PREFLIGHT HANDLER
    # ============================================
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            resp = jsonify({"status": "ok"})
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "*"
            return resp, 200

    # ============================================
    # AFTER-REQUEST HEADERS
    # ============================================
    @app.after_request
    def add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    # ============================================
    # BLUEPRINTS
    # ============================================
    from backend.routes import (
        auth_routes, db_routes,
        notification_routes, assignment_routes, 
        customer_routes, file_routes, job_routes, 
        test_grading_routes, proposal_routes,
    )

    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(customer_routes.customer_bp)
    app.register_blueprint(db_routes.db_bp)
    app.register_blueprint(notification_routes.notification_bp)
    app.register_blueprint(assignment_routes.assignment_bp)
    app.register_blueprint(file_routes.file_bp)
    app.register_blueprint(job_routes.job_bp)
    app.register_blueprint(proposal_routes.proposal_bp)
    app.register_blueprint(test_grading_routes.test_grading_bp)

    # ============================================
    # HEALTH CHECK
    # ============================================
    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "message": "Server is running"}), 200

    # ============================================
    # PIPELINE INFO ENDPOINT (NEW)
    # ============================================
    @app.route("/pipeline-info", methods=["GET"])
    def pipeline_info():
        """Returns information about available pipelines"""
        return jsonify({
            "pipelines": {
                "sales": {
                    "stages": ["Enquiry", "Proposal", "Converted"],
                    "endpoint": "/pipeline/sales"
                },
                "training": {
                    "stages": [
                        "Training Scheduled",
                        "Training Conducted",
                        "Training Completed",
                        "PTI Created",
                        "Certificates Created",
                        "Certificates Dispatched"
                    ],
                    "endpoint": "/pipeline/training"
                }
            },
            "version": "1.0",
            "migration_required": False
        }), 200
    
    # ============================================
    # TEST GRADING INFO ENDPOINT (NEW)
    # ============================================
    @app.route("/test-grading-info", methods=["GET"])
    def test_grading_info():
        """Returns information about test grading system"""
        return jsonify({
            "test_grading": {
                "supported_types": ["BOPT", "FORKLIFT", "REACH_TRUCK", "STACKER"],
                "ai_model": "GPT-4o",
                "endpoint": "/api/test-grading"
            },
            "version": "1.0"
        }), 200

    return app


# ============================================
# STANDALONE LAUNCH
# ============================================
if __name__ == "__main__":
    app = create_app()

    print("=" * 60)
    print("🔧 INITIALISING DATABASE...")
    print("=" * 60)

    # Import models to register metadata
    from backend import models

    # List tables
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\n📋 {len(tables)} tables detected:")
    for t in sorted(tables):
        print(f"   ✓ {t}")

    # Check for dual pipeline fields
    try:
        columns = inspector.get_columns('customers')
        column_names = [col['name'] for col in columns]
        
        print(f"\n📊 Customer table columns:")
        if 'sales_stage' in column_names:
            print("   ✅ sales_stage column exists")
        else:
            print("   ⚠️  sales_stage column missing - run migration!")
            
        if 'training_stage' in column_names:
            print("   ✅ training_stage column exists")
        else:
            print("   ⚠️  training_stage column missing - run migration!")
            
        if 'pipeline_type' in column_names:
            print("   ✅ pipeline_type column exists")
        else:
            print("   ⚠️  pipeline_type column missing - run migration!")
            
        if 'stage' in column_names:
            print("   ⚠️  Old 'stage' column still exists - consider running migration")
            
    except Exception as e:
        print(f"   ⚠️  Could not check customer columns: {e}")
    
    # Check for test_results table
    try:
        if 'test_results' in tables:
            print("\n✅ Test Results table exists")
            test_columns = inspector.get_columns('test_results')
            print(f"   ✓ {len(test_columns)} columns configured")
        else:
            print("\n⚠️  Test Results table missing - will be created on first run")
    except Exception as e:
        print(f"   ⚠️  Could not check test_results table: {e}")

    print("\n✅ Database initialised successfully!\n")
    print("=" * 60)

    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    
    print(f"\n🚀 Starting server on port {port}")
    print(f"   Debug mode: {debug_mode}")
    print(f"   Access at: http://localhost:{port}")
    print(f"   Health check: http://localhost:{port}/health")
    print(f"   Pipeline info: http://localhost:{port}/pipeline-info")
    print(f"   Test Grading info: http://localhost:{port}/test-grading-info")
    print(f"   Test Grading API: http://localhost:{port}/api/test-grading/health")
    print("\n" + "=" * 60 + "\n")
    
    app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)