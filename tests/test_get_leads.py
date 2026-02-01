"""Controller-level tests for GET /api/crm/leads

- Ensures endpoint returns only the allowed fields and respects tenant filtering
- Repository is patched so tests remain fast and DB-free
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def get_app():
    from backend.app import create_app
    return create_app()


def test_get_leads_returns_expected_fields_and_order(monkeypatch):
    app = get_app()
    client = app.test_client()
    headers = {"X-Tenant-ID": "1"}

    sample_rows = [
        {
            'opportunity_id': 42,
            'business_name': 'Acme Ltd',
            'contact_person': 'Jane',
            'tel_number': '+441234',
            'email': 'jane@acme.test',
            'mpan_mpr': 'MPAN-42',
            'start_date': '2023-01-01',
            'end_date': '2023-12-31',
            'stage_id': 1,
            'stage_name': 'New',
            'created_at': '2024-01-02T03:04:05'
        },
        {
            'opportunity_id': 41,
            'business_name': 'Beta Ltd',
            'contact_person': 'Bob',
            'tel_number': '+441235',
            'email': 'bob@beta.test',
            'mpan_mpr': 'MPAN-41',
            'start_date': None,
            'end_date': None,
            'stage_id': 2,
            'stage_name': 'Contacted',
            'created_at': '2023-12-31T00:00:00'
        }
    ]

    # Patch repository method so no DB is required
    from backend.crm.repositories.lead_repository import LeadRepository

    def fake_get_leads_list(self, tenant_id, filters=None):
        assert int(tenant_id) == 1
        # Return rows already ordered (created_at DESC)
        return sample_rows

    monkeypatch.setattr(LeadRepository, 'get_leads_list', fake_get_leads_list)

    resp = client.get('/api/crm/leads', headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get('success') is True
    assert isinstance(body.get('data'), list)
    assert body.get('count') == 2

    # Only allowed fields should be present on each row
    allowed = {
        'opportunity_id', 'business_name', 'contact_person', 'tel_number', 'email',
        'mpan_mpr', 'start_date', 'end_date', 'stage_id', 'stage_name', 'created_at'
    }

    for item in body['data']:
        assert set(item.keys()) == allowed

    # Ensure order preserved (latest first)
    assert body['data'][0]['opportunity_id'] == 42


def test_get_leads_passes_stage_filter_and_tenant(monkeypatch):
    app = get_app()
    client = app.test_client()
    headers = {"X-Tenant-ID": "2"}

    from backend.crm.repositories.lead_repository import LeadRepository

    def fake_get_leads_list(self, tenant_id, filters=None):
        # ensure tenant forwarded and optional stage_id respected
        assert int(tenant_id) == 2
        assert isinstance(filters, dict) and filters.get('stage_id') == 5
        return []

    monkeypatch.setattr(LeadRepository, 'get_leads_list', fake_get_leads_list)

    resp = client.get('/api/crm/leads?stage_id=5', headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get('success') is True
    assert body.get('data') == []
    assert body.get('count') == 0
