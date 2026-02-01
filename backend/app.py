# -*- coding: utf-8 -*-
import sys
import io
import os
import logging
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH)

print("DEBUG ENV PATH =", ENV_PATH)
print("DEBUG DATABASE_URL =", os.getenv("DATABASE_URL"))

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

from flask import Flask, app, request, jsonify, g
from flask_cors import CORS

# from backend.routes import proposal_routes
from backend.db import Base, engine, SessionLocal, test_connection, init_db


def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ============================================
    # ⚙️ DATABASE INITIALIZATION (NEW LOCATION)
    # ============================================
    logging.info("Initializing database schema...")

    try:
        # ✅ CRITICAL: Import models FIRST so SQLAlchemy knows about them
        # This ensures all enum types and tables are registered
        from backend import models
        
        logging.info("📋 Registered models:")
        logging.info("   ✓ User")
        logging.info("   ✓ LoginAttempt")
        logging.info("   ✓ Customer (with sales_stage and training_stage)")
        logging.info("   ✓ Quotation")
        logging.info("   ✓ QuotationItem")
        logging.info("   ✓ Invoice")
        logging.info("   ✓ InvoiceLineItem")
        logging.info("   ✓ Payment")
        logging.info("   ✓ Assignment")
        logging.info("   ✓ AuditLog")
        logging.info("   ✓ ActionItem")
        logging.info("   ✓ DataImport")
        logging.info("   ✓ TestResult")
        logging.info("   ✓ CustomerDocument")
        
        # Create tables only for SQLite; Supabase/PostgreSQL schema is managed by migrations.
        if "sqlite" in str(engine.url):
            Base.metadata.create_all(bind=engine, checkfirst=True)
        
        # Verify tables
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logging.info(f"✅ Database schema initialized - {len(tables)} tables exist")
        
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
                    logging.info("   ✓ sales_stage_enum type exists")
                if 'training_stage_enum' in enum_types:
                    logging.info("   ✓ training_stage_enum type exists")
                
                if not enum_types:
                    logging.info("   ⚠️  Enum types not found - you may need to run migration")
        except Exception as enum_check_error:
            logging.info(f"   ⚠️  Could not verify enum types: {enum_check_error}")
        
    except Exception as e:
        logging.error("Database initialization failed: %s", e)
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
        notification_routes,
        customer_routes, file_routes,
        crm_routes, import_routes,
    )

    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(customer_routes.energy_customer_bp)
    app.register_blueprint(db_routes.db_bp)
    app.register_blueprint(notification_routes.notification_bp)
    # app.register_blueprint(assignment_routes.assignment_bp)
    app.register_blueprint(file_routes.file_bp)
    # app.register_blueprint(job_routes.job_bp)
    # app.register_blueprint(proposal_routes.proposal_bp)
    app.register_blueprint(crm_routes.crm_bp) # NEW: Register CRM blueprint
    app.register_blueprint(import_routes.import_bp)
    logging.info("CRM Blueprint registered successfully") 
    
    # Test CRM Supabase connection after blueprint registration
    try:
        from backend.crm.repositories.tenant_repository import TenantRepository
        test_repo = TenantRepository()
        test_tenant = test_repo.get_tenant_by_id(1)
        if test_tenant:
            logging.info(f"✅ CRM Supabase connection test: SUCCESS - Found tenant '{test_tenant.get('tenant_company_name')}'")
        else:
            logging.warning("CRM Supabase connection test: Tenant ID 1 not found")
    except Exception as e:
        logging.error("CRM Supabase connection test FAILED: %s", e)

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
    logging.debug("App url_map: %s", app.url_map)

    return app


# ============================================
# STANDALONE LAUNCH
# ============================================
if __name__ == "__main__":
    app = create_app()

    logging.info("=" * 60)
    logging.info("🔧 INITIALISING DATABASE...")
    logging.info("=" * 60)

    # Import models to register metadata
    from backend import models

    # List tables
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logging.info(f"\n📋 {len(tables)} tables detected:")
    for t in sorted(tables):
        logging.info(f"   ✓ {t}")

    # Check for dual pipeline fields
    try:
        columns = inspector.get_columns('customers')
        column_names = [col['name'] for col in columns]
        
        logging.info(f"\n📊 Customer table columns:")
        if 'sales_stage' in column_names:
            logging.info("   ✅ sales_stage column exists")
        else:
            logging.info("   ⚠️  sales_stage column missing - run migration!")
            
        if 'training_stage' in column_names:
            logging.info("   ✅ training_stage column exists")
        else:
            logging.warning("training_stage column missing - run migration!")
            
        if 'pipeline_type' in column_names:
            logging.info("   ✅ pipeline_type column exists")
        else:
            logging.info("   ⚠️  pipeline_type column missing - run migration!")
            
        if 'stage' in column_names:
            logging.info("   ⚠️  Old 'stage' column still exists - consider running migration")
            
    except Exception as e:
        logging.info(f"   ⚠️  Could not check customer columns: {e}")
    
    # Check for test_results table
    try:
        if 'test_results' in tables:
            logging.info("\n✅ Test Results table exists")
            test_columns = inspector.get_columns('test_results')
            logging.info(f"   ✓ {len(test_columns)} columns configured")
        else:
            logging.info("\n⚠️  Test Results table missing - will be created on first run")
    except Exception as e:
        logging.info(f"   ⚠️  Could not check test_results table: {e}")

    logging.info("\n✅ Database initialised successfully!\n")
    logging.info("=" * 60)

    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    
    logging.info(f"\n🚀 Starting server on port {port}")
    logging.info(f"   Debug mode: {debug_mode}")
    logging.info(f"   Access at: http://localhost:{port}")
    logging.info(f"   Health check: http://localhost:{port}/health")
    logging.info(f"   Pipeline info: http://localhost:{port}/pipeline-info")
    logging.info(f"   Test Grading info: http://localhost:{port}/test-grading-info")
    logging.info(f"   Test Grading API: http://localhost:{port}/api/test-grading/health")
    logging.info("\n" + "=" * 60 + "\n")
    
    try:
        app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)
    except Exception as e:
        logging.error("Server error: %s", e)
        import traceback
        traceback.print_exc()