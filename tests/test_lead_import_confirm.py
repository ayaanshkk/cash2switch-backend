"""Controller-level tests for POST /api/crm/leads/import/confirm.

- Ensures controller validates input shape (expects JSON array)
- Ensures controller forwards payload to CRMService.confirm_lead_import and returns its result

These tests patch the CRMService to avoid any DB dependency.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

















def get_app():
    from backend.app import create_app
    return create_app()


def test_confirm_endpoint_rejects_non_array_payload(monkeypatch):
    app = get_app()
    client = app.test_client()

    # Inject a fake authenticated user (simulates decoded JWT with tenant_id)
    from types import SimpleNamespace
    @app.before_request
    def _inject_current_user():
        from flask import request
        request.current_user = SimpleNamespace(id=2, tenant_id=1, full_name='Importer')

    resp = client.post('/api/crm/leads/import/confirm', data='{}', content_type='application/json')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['success'] is False
    assert 'Expected a JSON array' in body.get('message', '')


def test_confirm_endpoint_delegates_to_service_and_returns_result(monkeypatch):
    app = get_app()
    client = app.test_client()
    headers = {"X-Tenant-ID": "1", "Content-Type": "application/json"}

    sample_payload = [
        {"row_number": 1, "data": {"MPAN_MPR": "MPAN-1"}, "is_valid": True, "errors": []}
    ]

    expected = {"success": True, "inserted": 1, "skipped": 0, "errors": []}

    # Patch CRMService.confirm_lead_import to avoid DB dependency
    from backend.crm.services.crm_service import CRMService

    def fake_confirm(tenant_id, rows, created_by):
        assert tenant_id == 1
        assert isinstance(rows, list)
        return expected

    monkeypatch.setattr(CRMService, 'confirm_lead_import', fake_confirm)

    resp = client.post('/api/crm/leads/import/confirm', json=sample_payload, headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body == expected
