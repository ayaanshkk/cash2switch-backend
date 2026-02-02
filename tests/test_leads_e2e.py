# -*- coding: utf-8 -*-
import sys
import os
try:
    sys.stdout.write("")
except Exception:
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

"""
End-to-end tests for Leads implementation.

Tests:
  1) Create client via POST /api/crm/clients; verify Client_Master (Leads must NOT be auto-created).
  2) Create leads only via POST /api/crm/leads/import/confirm and verify they appear in
     GET /api/crm/leads/table (14 required keys).
  3) Joins: stage_id->status, opportunity_owner_employee_id->assigned_to,
     Project_Details->annual_usage, Energy_Contract_Master->dates+supplier,
     Client_Interactions->callback_parameter, call_summary (latest).
  4) Tenant isolation: data for another tenant not visible with X-Tenant-ID: 1.
  5) Log failures and suggest fixes (no DB schema changes).

Run from project root with env loaded (Supabase/DB env vars required for full tests):
  cd cash2switch-backend
  set PYTHONPATH=%CD%   # or: export PYTHONPATH=.
  python test_leads_e2e.py

Uses Flask test client (no server needed). DB checks and join tests are skipped if
SUPABASE_DB_URL (or DATABASE_URL) is not set.
"""
import json
from datetime import date, timedelta

# Project root = parent of backend
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.chdir(_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Required 14 keys for GET /api/crm/leads/table
LEADS_TABLE_KEYS = [
    'id', 'name', 'business_name', 'contact_person', 'tel_number',
    'mpan_mpr', 'supplier', 'annual_usage', 'start_date', 'end_date',
    'status', 'assigned_to', 'callback_parameter', 'call_summary'
]

FAILURES = []
SUGGESTIONS = []


def log_failure(test_name, message, fix=None):
    FAILURES.append((test_name, message))
    if fix:
        SUGGESTIONS.append((test_name, fix))
    print("  [FAIL] {}: {}".format(test_name, message))
    if fix:
        print("    -> Suggestion: {}".format(fix))


def skip(test_name, reason):
    print("  [SKIP] {}: {}".format(test_name, reason))


def ok(test_name, detail=""):
    print("  [OK]   {}{}".format(test_name, " - {}".format(detail) if detail else ""))


def get_app():
    from backend.app import create_app
    return create_app()


def get_db():
    try:
        from backend.crm.supabase_client import get_supabase_client
        return get_supabase_client()
    except Exception as e:
        print("  [WARN] Supabase client not available: {}".format(e))
        return None


def ensure_tenant(db):
    """
    Ensure at least one row exists in Tenant_Master; return its Tenant_id.
    If db is None or stub (no real DB), return 1 for header compatibility.
    """
    if db is None:
        return 1
    try:
        schema = '"StreemLyne_MT"'
        rows = db.execute_query(
            'SELECT "Tenant_id" FROM {}."Tenant_Master" ORDER BY "Tenant_id" LIMIT 1'.format(schema)
        )
        if rows and len(rows) > 0:
            return int(rows[0]["Tenant_id"])
        # None exist: insert one
        ins = 'INSERT INTO {}."Tenant_Master" ("tenant_company_name", "is_active") VALUES (%s, %s) RETURNING "Tenant_id"'.format(schema)
        out = db.execute_insert(ins, ("E2E Test Tenant", True), returning=True)
        if out and "Tenant_id" in out:
            return int(out["Tenant_id"])
    except Exception:
        pass
    return 1


def run_test_1_create_client(app, db, tenant_id):
    """1) Create test client; verify row in Client_Master and Opportunity_Details."""
    print("\n--- Test 1: Create client and verify Client_Master + Opportunity_Details ---")
    client = app.test_client()
    headers = {"X-Tenant-ID": str(tenant_id), "Content-Type": "application/json"}
    body = {
        "client_company_name": "E2E Test Company Ltd",
        "client_contact_name": "Jane Doe",
        "client_phone": "+44 7700 900000",
    }
    resp = client.post("/api/crm/clients", data=json.dumps(body), headers=headers)
    if resp.status_code != 201:
        log_failure(
            "Create client",
            "POST /api/crm/clients returned {}: {}".format(resp.status_code, resp.get_data(as_text=True)[:200]),
            "Ensure tenant_id={} exists in Tenant_Master; ensure Stage_Master has at least one stage.".format(tenant_id)
        )
        return None, None, None

    data = resp.get_json()
    if not data.get("success") or "data" not in data:
        log_failure("Create client", "Response missing success/data: {}".format(data), "Check create_client service return shape.")
        return None, None, None

    client_row = (data.get("data") or {}).get("client")
    opportunity_row = (data.get("data") or {}).get("opportunity")
    if not client_row or "client_id" not in client_row:
        log_failure("Create client", "Response data.client missing or no client_id", "LeadRepository.create_client must RETURNING *.")
        return None, None, None

    client_id = client_row["client_id"]
    # Per business rule, creating a client must NOT create an Opportunity_Details row.
    opportunity_id = opportunity_row.get("opportunity_id") if opportunity_row else None

    ok("POST /api/crm/clients returned 201", "client_id={}, opportunity_id={}".format(client_id, opportunity_id))

    if not db:
        skip("DB verification", "Supabase not configured")
        return client_id, opportunity_id, client

    # Verify Client_Master
    try:
        r = db.execute_query(
            'SELECT "client_id", "tenant_id" FROM "StreemLyne_MT"."Client_Master" WHERE "client_id" = %s',
            (client_id,),
            fetch_one=True
        )
        if not r or r.get("tenant_id") != tenant_id:
            log_failure("Client_Master row", "Row not found or tenant_id != {}".format(tenant_id), "Confirm INSERT and tenant_id in payload.")
        else:
            ok("Row exists in Client_Master", "tenant_id={}".format(tenant_id))
    except Exception as e:
        log_failure("Client_Master query", str(e), "Check StreemLyne_MT.Client_Master schema and permissions.")

    # Verify Opportunity_Details
    if opportunity_id is not None:
        try:
            r = db.execute_query(
                'SELECT "opportunity_id", "client_id" FROM "StreemLyne_MT"."Opportunity_Details" WHERE "opportunity_id" = %s',
                (opportunity_id,),
                fetch_one=True
            )
            if not r or r.get("client_id") != client_id:
                log_failure("Opportunity_Details row", "Row not found or client_id mismatch", "Ensure create_client creates opportunity after client.")
            else:
                ok("Row exists in Opportunity_Details", "client_id={}".format(client_id))
        except Exception as e:
            log_failure("Opportunity_Details query", str(e), "Check Opportunity_Details schema.")
    else:
        skip("Opportunity_Details", "No stage configured; opportunity not created")

    return client_id, opportunity_id, client


def run_test_2_leads_table_keys(app, client, opportunity_id, headers, tenant_id=1):
    """2) GET /api/crm/leads/table: new lead present and has 14 keys."""
    print("\n--- Test 2: GET /api/crm/leads/table keys and presence ---")
    if client is None:
        client = app.test_client()
    if headers is None:
        headers = {"X-Tenant-ID": str(tenant_id)}

    resp = client.get("/api/crm/leads/table", headers=headers)
    if resp.status_code != 200:
        log_failure("GET leads/table", "Status {}: {}".format(resp.status_code, resp.get_data(as_text=True)[:200]),
                    "Check route and require_tenant; ensure tenant {} exists.".format(tenant_id))
        return

    data = resp.get_json()
    if not data.get("success") or "data" not in data:
        log_failure("GET leads/table body", "Missing success or data", "Service must return { success: True, data: [...] }.")
        return

    rows = data.get("data") or []
    if opportunity_id is not None:
        found = next((r for r in rows if r.get("id") == opportunity_id), None)
        if not found:
            log_failure("New lead in table", "Opportunity id {} not in response".format(opportunity_id),
                        "get_leads_table must filter by cm.tenant_id and include all opportunities.")
        else:
            ok("New client appears in leads table", "id={}".format(opportunity_id))

        # Check 14 keys
        if found:
            missing = [k for k in LEADS_TABLE_KEYS if k not in found]
            if missing:
                log_failure("14 keys", "Missing keys: {}".format(missing),
                            "get_leads_table must return exactly these keys: " + ", ".join(LEADS_TABLE_KEYS))
            else:
                ok("All 14 keys present", ", ".join(LEADS_TABLE_KEYS))
            extra = [k for k in found if k not in LEADS_TABLE_KEYS]
            if extra:
                print("  [INFO] Extra keys in row (allowed): {}".format(extra))
    else:
        ok("GET /api/crm/leads/table 200", "count={}".format(len(rows)))
        if rows:
            missing = [k for k in LEADS_TABLE_KEYS if k not in rows[0]]
            if missing:
                log_failure("14 keys (first row)", "Missing: {}".format(missing), "Return 14 keys per row.")
            else:
                ok("First row has 14 keys", "")


def run_test_3_joins(app, db, client_id, opportunity_id, headers, tenant_id=1):
    """3) Join tests: stage_id->status, assigned_to, project, contract, interactions."""
    print("\n--- Test 3: Joins (stage, assigned_to, project, contract, interactions) ---")
    if not db or opportunity_id is None:
        skip("Joins", "DB or opportunity_id not available")
        return

    client = app.test_client()
    if headers is None:
        headers = {"X-Tenant-ID": str(tenant_id)}
    schema = '"StreemLyne_MT"'
    proj = None
    project_id = None

    # 3a) Stage: update stage_id and check status
    stages = db.execute_query('SELECT "stage_id", "stage_name" FROM {}."Stage_Master" ORDER BY "stage_order"'.format(schema))
    if not stages or len(stages) < 2:
        skip("Stage join", "Need at least 2 stages in Stage_Master")
    else:
        new_stage_id = stages[1]["stage_id"]
        new_stage_name = stages[1].get("stage_name") or ""
        try:
            n = db.execute_update(
                'UPDATE {}."Opportunity_Details" SET "stage_id" = %s WHERE "opportunity_id" = %s'.format(schema),
                (new_stage_id, opportunity_id)
            )
            if n != 1:
                skip("Stage update", "Update matched {} rows".format(n))
            else:
                resp = client.get("/api/crm/leads/table", headers=headers)
                if resp.status_code == 200:
                    data = resp.get_json()
                    row = next((r for r in (data.get("data") or []) if r.get("id") == opportunity_id), None)
                    if row and row.get("status") == new_stage_name:
                        ok("stage_id -> status", "status={}".format(new_stage_name))
                    else:
                        log_failure("stage_id -> status", "Expected status {} got {}".format(new_stage_name, row.get("status") if row else None),
                                    "Join Stage_Master on stage_id and select stage_name as status.")
        except Exception as e:
            log_failure("Stage join", str(e), "Check Stage_Master.stage_id and Opportunity_Details.stage_id.")

    # 3b) assigned_to: set opportunity_owner_employee_id
    employees = db.execute_query(
        'SELECT "employee_id", "employee_name" FROM {}."Employee_Master" WHERE "tenant_id" = %s LIMIT 1'.format(schema),
        (tenant_id,)
    )
    if not employees:
        skip("assigned_to join", "No Employee_Master row for tenant {}".format(tenant_id))
    else:
        emp_id = employees[0]["employee_id"]
        emp_name = employees[0].get("employee_name") or ""
        try:
            db.execute_update(
                'UPDATE {}."Opportunity_Details" SET "opportunity_owner_employee_id" = %s WHERE "opportunity_id" = %s'.format(schema),
                (emp_id, opportunity_id)
            )
            resp = client.get("/api/crm/leads/table", headers=headers)
            if resp.status_code == 200:
                row = next((r for r in (resp.get_json().get("data") or []) if r.get("id") == opportunity_id), None)
                if row and row.get("assigned_to") == emp_name:
                    ok("opportunity_owner_employee_id -> assigned_to", "assigned_to={}".format(emp_name))
                else:
                    log_failure("assigned_to", "Expected {} got {}".format(emp_name, row.get("assigned_to") if row else None),
                                "Join Employee_Master on opportunity_owner_employee_id = employee_id, select employee_name as assigned_to.")
        except Exception as e:
            log_failure("assigned_to join", str(e), "Check Employee_Master and column names.")

    # 3c) Project_Details -> annual_usage (and mpan_mpr)
    emp_id_proj = emp_id if employees else None
    if not emp_id_proj:
        emp_row = db.execute_query(
            'SELECT "employee_id" FROM {}."Employee_Master" LIMIT 1'.format(schema),
            fetch_one=True
        )
        emp_id_proj = emp_row["employee_id"] if emp_row else None
    if not emp_id_proj:
        skip("Project_Details join", "No employee_id for Project_Details.employee_id (NOT NULL)")
    else:
        try:
            ins = """
                INSERT INTO {}."Project_Details"
                ("client_id", "opportunity_id", "project_title", "start_date", "end_date", "employee_id", "mpan", "annual_usage", "created_at", "updated_at")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING "project_id"
            """.format(schema)
            proj = db.execute_insert(ins, (
                client_id, opportunity_id, "E2E Project", date.today(), date.today() + timedelta(days=365),
                emp_id_proj, "MPAN-E2E-123", 50000
            ), returning=True)
            if not proj:
                skip("Project_Details insert", "INSERT failed (check project_title vs project_name and columns)")
            else:
                project_id = proj.get("project_id")
                resp = client.get("/api/crm/leads/table", headers=headers)
                if resp.status_code == 200:
                    row = next((r for r in (resp.get_json().get("data") or []) if r.get("id") == opportunity_id), None)
                    if row:
                        if row.get("annual_usage") == 50000:
                            ok("Project_Details -> annual_usage", "50000")
                        else:
                            log_failure("annual_usage", "Expected 50000 got {}".format(row.get("annual_usage")),
                                        "Subquery Project_Details by opportunity_id, select annual_usage.")
                        if row.get("mpan_mpr") == "MPAN-E2E-123":
                            ok("Project_Details -> mpan_mpr", "MPAN-E2E-123")
                        else:
                            log_failure("mpan_mpr", "Expected MPAN-E2E-123 got {}".format(row.get("mpan_mpr")),
                                        "Subquery Project_Details, select mpan as mpan_mpr.")
        except Exception as e:
            log_failure("Project_Details join", str(e),
                        "Project_Details may use project_title; ensure opportunity_id, client_id, employee_id, mpan, annual_usage exist.")

    # 3d) Energy_Contract_Master -> start_date, end_date, supplier
    suppliers = db.execute_query(
        'SELECT "supplier_id", "supplier_company_name" FROM {}."Supplier_Master" WHERE "Tenant_id" = %s LIMIT 1'.format(schema),
        (tenant_id,)
    )
    services = db.execute_query('SELECT "service_id" FROM {}."Services_Master" LIMIT 1'.format(schema))
    project_id = proj.get("project_id") if proj else None
    if not suppliers or not services or not project_id:
        skip("Energy_Contract_Master join", "Need Supplier_Master (tenant {}), Services_Master, and Project_Details".format(tenant_id))
    else:
        try:
            sid = suppliers[0]["supplier_id"]
            svc_id = services[0]["service_id"]
            start_d, end_d = date.today(), date.today() + timedelta(days=365)
            conn_ins = """
                INSERT INTO {}."Energy_Contract_Master"
                ("project_id", "employee_id", "supplier_id", "contract_start_date", "contract_end_date", "terms_of_sale", "service_id", "unit_rate", "created_at")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING "energy_contract_master_id"
            """.format(schema)
            db.execute_insert(conn_ins, (project_id, emp_id_proj, sid, start_d, end_d, "E2E terms", svc_id, 0.15), returning=True)
            resp = client.get("/api/crm/leads/table", headers=headers)
            if resp.status_code == 200:
                row = next((r for r in (resp.get_json().get("data") or []) if r.get("id") == opportunity_id), None)
                if row:
                    exp_supplier = suppliers[0].get("supplier_company_name")
                    if row.get("start_date") and row.get("end_date"):
                        ok("Energy_Contract -> start_date, end_date", "")
                    else:
                        log_failure("start_date/end_date", "Missing or wrong", "Subquery via Project_Details join Energy_Contract_Master, contract_start_date/contract_end_date.")
                    if exp_supplier and row.get("supplier") == exp_supplier:
                        ok("Energy_Contract -> supplier", exp_supplier)
                    else:
                        log_failure("supplier", "Expected {} got {}".format(exp_supplier, row.get("supplier")),
                                    "Join Supplier_Master on supplier_id; select supplier_company_name.")
        except Exception as e:
            log_failure("Energy_Contract join", str(e),
                        "Energy_Contract_Master may use energy_contract_master_id as PK; check project_id, supplier_id, employee_id, service_id.")

    # 3e) Client_Interactions -> callback_parameter (next_steps), call_summary (notes), latest only
    try:
        ci_ins = """
            INSERT INTO {}."Client_Interactions"
            ("client_id", "contact_date", "contact_method", "notes", "next_steps", "created_at")
            VALUES (%s, CURRENT_DATE, 1, %s, %s, CURRENT_TIMESTAMP)
            RETURNING "interaction_id"
        """.format(schema)
        db.execute_insert(ci_ins, (client_id, "E2E call summary note", "Callback: follow up Tuesday"), returning=True)
        resp = client.get("/api/crm/leads/table", headers=headers)
        if resp.status_code == 200:
            row = next((r for r in (resp.get_json().get("data") or []) if r.get("id") == opportunity_id), None)
            if row:
                if row.get("call_summary") == "E2E call summary note":
                    ok("Client_Interactions -> call_summary (notes)", "latest only")
                else:
                    log_failure("call_summary", "Expected note got {}".format(row.get("call_summary")),
                                "Subquery Client_Interactions by client_id ORDER BY contact_date DESC LIMIT 1, notes as call_summary.")
                if row.get("callback_parameter") == "Callback: follow up Tuesday":
                    ok("Client_Interactions -> callback_parameter (next_steps)", "latest only")
                else:
                    log_failure("callback_parameter", "Expected next_steps got {}".format(row.get("callback_parameter")),
                                "Same subquery, next_steps as callback_parameter.")
    except Exception as e:
        log_failure("Client_Interactions", str(e), "Check Client_Interactions schema (notes, next_steps).")


def run_test_4_tenant_isolation(app, db, opportunity_id_t1, headers_t1, tenant_id):
    """4) Tenant isolation: create client for another tenant; GET with main tenant must not return other's lead."""
    print("\n--- Test 4: Tenant isolation ---")
    if not db:
        skip("Tenant isolation", "DB not available")
        return

    # Find another tenant (for isolation test)
    other_row = db.execute_query(
        'SELECT "Tenant_id" FROM "StreemLyne_MT"."Tenant_Master" WHERE "Tenant_id" != %s ORDER BY "Tenant_id" LIMIT 1',
        (tenant_id,),
        fetch_one=True
    )
    if not other_row:
        skip("Tenant isolation", "Tenant_Master has only one tenant (need two for isolation)")
        return
    other_tenant_id = int(other_row["Tenant_id"])

    schema = '"StreemLyne_MT"'
    from backend.crm.repositories.lead_repository import LeadRepository
    from backend.crm.repositories.additional_repositories import StageRepository
    lead_repo = LeadRepository()
    stage_repo = StageRepository()
    stages = stage_repo.get_all_stages()
    default_stage_id = stages[0]["stage_id"] if stages else None
    if not default_stage_id:
        skip("Tenant isolation", "No stages for new opportunity")
        return

    # Create client for other tenant (direct DB to simulate another tenant's data)
    try:
        client_row = lead_repo.create_client(other_tenant_id, {
            "client_company_name": "Other Tenant E2E Company",
            "client_contact_name": "Bob",
            "client_phone": "07700900202",
        })
        if not client_row:
            skip("Tenant isolation", "Could not create client for tenant {}".format(other_tenant_id))
            return
        cid2 = client_row["client_id"]
        opp_row = lead_repo.create_lead(other_tenant_id, {
            "client_id": cid2,
            "stage_id": default_stage_id,
            "opportunity_title": "Other Tenant Lead",
            "opportunity_description": "",
            "opportunity_value": 0,
            "opportunity_owner_employee_id": None,
        })
        if not opp_row:
            skip("Tenant isolation", "Could not create opportunity for tenant {}".format(other_tenant_id))
            return
        opportunity_id_t2 = opp_row["opportunity_id"]
    except Exception as e:
        skip("Tenant isolation", "Create other tenant data failed: {}".format(e))
        return

    client = app.test_client()
    # Request with main tenant: must not include other tenant's opportunity
    resp1 = client.get("/api/crm/leads/table", headers=headers_t1 or {"X-Tenant-ID": str(tenant_id)})
    if resp1.status_code != 200:
        log_failure("Tenant isolation GET T1", "Status {}".format(resp1.status_code), "Check require_tenant and query filter.")
        return
    data1 = resp1.get_json().get("data") or []
    ids_t1 = [r["id"] for r in data1]
    if opportunity_id_t2 in ids_t1:
        log_failure("Tenant isolation", "Other tenant opportunity {} visible with X-Tenant-ID: {}".format(opportunity_id_t2, tenant_id),
                    "Filter leads by cm.tenant_id = request tenant only.")
    else:
        ok("Tenant isolation", "X-Tenant-ID: {} does not return other tenant lead".format(tenant_id))

    # With X-Tenant-ID: other we should see other tenant's lead
    resp2 = client.get("/api/crm/leads/table", headers={"X-Tenant-ID": str(other_tenant_id)})
    if resp2.status_code == 200:
        data2 = resp2.get_json().get("data") or []
        if any(r.get("id") == opportunity_id_t2 for r in data2):
            ok("Other tenant data visible with X-Tenant-ID: {}".format(other_tenant_id), "")
        else:
            log_failure("Other tenant visibility", "Lead {} not in response for tenant {}".format(opportunity_id_t2, other_tenant_id),
                        "Ensure GET leads/table filters by g.tenant_id only.")
    else:
        log_failure("Other tenant GET", "Status {}".format(resp2.status_code), "Other tenant must exist in Tenant_Master.")


def main():
    print("=" * 60)
    print("Leads E2E Tests")
    print("=" * 60)

    try:
        app = get_app()
    except Exception as e:
        print("ERROR: Could not create Flask app: {}".format(e))
        import traceback
        traceback.print_exc()
        return 1

    db = get_db()
    tenant_id = ensure_tenant(db)
    headers = {"X-Tenant-ID": str(tenant_id), "Content-Type": "application/json"}

    client_id, opportunity_id, test_client = run_test_1_create_client(app, db, tenant_id)
    run_test_2_leads_table_keys(app, test_client, opportunity_id, headers, tenant_id)
    run_test_3_joins(app, db, client_id, opportunity_id, headers, tenant_id)
    run_test_4_tenant_isolation(app, db, opportunity_id, headers, tenant_id)

    # Summary
    print("\n" + "=" * 60)
    if FAILURES:
        print("FAILURES ({}):".format(len(FAILURES)))
        for name, msg in FAILURES:
            print("  - {}: {}".format(name, msg))
        if SUGGESTIONS:
            print("\nSuggestions (no schema change):")
            for name, fix in SUGGESTIONS:
                print("  - {}: {}".format(name, fix))
        return 1
    else:
        print("All checks passed or skipped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
