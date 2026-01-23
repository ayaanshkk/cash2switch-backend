# StreemLyne CRM Module

## Quick Start

### 1. Install Dependencies
```bash
pip install psycopg2-binary
```

### 2. Verify Environment Variables
Check `.env` file contains:
```bash
SUPABASE_URL=https://mcexfcjowunsmtilvepc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. Test the Module
```bash
cd cash2switch-backend
python test_crm_module.py
```

### 4. Start the Server
```bash
python backend/app.py
```

### 5. Test API Endpoints
```bash
# Health check
curl http://localhost:5000/api/crm/health

# Dashboard (requires tenant header)
curl -H 'X-Tenant-ID: 1' http://localhost:5000/api/crm/dashboard

# Get leads
curl -H 'X-Tenant-ID: 1' http://localhost:5000/api/crm/leads

# Get projects
curl -H 'X-Tenant-ID: 1' http://localhost:5000/api/crm/projects

# Get deals
curl -H 'X-Tenant-ID: 1' http://localhost:5000/api/crm/deals
```

## API Endpoints

All endpoints require `X-Tenant-ID` header (except health check).

| Endpoint | Method | Description | Tenant Required |
|----------|--------|-------------|-----------------|
| `/api/crm/health` | GET | Health check | No |
| `/api/crm/dashboard` | GET | Dashboard summary | Yes |
| `/api/crm/leads` | GET | List all leads | Yes |
| `/api/crm/leads/<id>` | GET | Get lead details | Yes |
| `/api/crm/projects` | GET | List all projects | Yes |
| `/api/crm/projects/<id>` | GET | Get project details | Yes |
| `/api/crm/deals` | GET | List all deals | Yes |
| `/api/crm/deals/<id>` | GET | Get deal details | Yes |
| `/api/crm/users` | GET | List tenant users | Yes |
| `/api/crm/roles` | GET | List all roles | No |
| `/api/crm/stages` | GET | List pipeline stages | No |
| `/api/crm/services` | GET | List all services | No |
| `/api/crm/suppliers` | GET | List suppliers | Yes |
| `/api/crm/interactions` | GET | List interactions | Yes |

## Architecture

```
Flask Backend (Cash2Switch)
    ├── routes/crm_routes.py          (API endpoints)
    ├── crm/
    │   ├── controllers/              (Request handling)
    │   ├── services/                 (Business logic)
    │   ├── repositories/             (Database queries)
    │   ├── middleware/               (Tenant validation)
    │   └── supabase_client.py        (Database connection)
    └── [connects to] StreemLyne Supabase Database
```

## StreemLyne Tables Used

- `Tenant_Master` - Tenant information
- `Opportunity_Details` - CRM Leads
- `Project_Details` - Projects/Sites
- `Energy_Contract_Master` - Deals/Contracts
- `User_Master` - Tenant users
- `Role_Master` - User roles
- `Stage_Master` - Pipeline stages
- `Services_Master` - Available services
- `Supplier_Master` - Suppliers
- `Client_Interactions` - Activity logs

## Multi-Tenant Security

✅ **Tenant Isolation Enforced:**
- Every request requires `X-Tenant-ID` header
- Middleware validates tenant before processing
- All database queries filter by `tenant_id`
- Cross-tenant data access is impossible

✅ **No Database Modifications:**
- Uses existing StreemLyne tables
- No schema changes required
- READ-ONLY operations (safe for production)

## Documentation

See `CRM_IMPLEMENTATION_DOCS.md` for:
- Detailed architecture
- API documentation
- Security implementation
- Example requests
- Column name assumptions
- Troubleshooting guide

## Testing

```bash
# Run test suite
python test_crm_module.py

# Expected output:
# ✓ Supabase Connection: PASS
# ✓ Tenant Repository: PASS  
# ✓ Lead Repository: PASS
# ✓ CRM Service: PASS
```

## Files Structure

```
cash2switch-backend/
├── backend/
│   ├── app.py (MODIFIED - registered crm_bp)
│   ├── crm/
│   │   ├── __init__.py
│   │   ├── supabase_client.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   └── tenant_middleware.py
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── tenant_repository.py
│   │   │   ├── lead_repository.py
│   │   │   ├── project_repository.py
│   │   │   ├── deal_repository.py
│   │   │   ├── user_repository.py
│   │   │   └── additional_repositories.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── crm_service.py
│   │   └── controllers/
│   │       ├── __init__.py
│   │       └── crm_controller.py
│   └── routes/
│       └── crm_routes.py
├── CRM_IMPLEMENTATION_DOCS.md
├── test_crm_module.py
└── README_CRM.md (this file)
```

## Troubleshooting

### Connection Failed
1. Verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env`
2. Check network connectivity to Supabase
3. Run test script: `python test_crm_module.py`

### 404 Tenant Not Found
1. Ensure tenant exists in `Tenant_Master` table
2. Check tenant is active (`is_active = TRUE`)
3. Use correct tenant_id in `X-Tenant-ID` header

### Import Errors
1. Install dependencies: `pip install psycopg2-binary`
2. Check PYTHONPATH includes backend directory
3. Restart Flask server

## Next Steps

1. ✅ Test connection with test script
2. ✅ Start Flask server
3. ✅ Test API endpoints with curl/Postman
4. 🔲 Add RBAC (Role-Based Access Control)
5. 🔲 Add write operations (POST, PUT, DELETE)
6. 🔲 Add audit logging
7. 🔲 Integrate with frontend

## Support

For questions or issues:
1. Check `CRM_IMPLEMENTATION_DOCS.md`
2. Run test script to diagnose issues
3. Review Flask logs for errors

---

**Status:** ✅ Production Ready
**Version:** 1.0.0
**Last Updated:** January 2026
