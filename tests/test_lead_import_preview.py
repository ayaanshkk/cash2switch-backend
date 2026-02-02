# -*- coding: utf-8 -*-
"""
Tests for POST /api/crm/leads/import/preview

Covers:
- CSV parsing
- XLSX parsing
- Validation rules (MPAN_MPR required, uniqueness, contact or business name,
  tel number, start/end dates)

These use the Flask test client (no DB writes).
"""
import io
import json
import sys
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from datetime import date

import pandas as pd


def get_app():
    from backend.app import create_app
    return create_app()


def test_csv_preview_validations():
    app = get_app()
    client = app.test_client()

    # Simulate authenticated user with tenant_id in decoded JWT
    from flask import request
    from types import SimpleNamespace
    @app.before_request
    def _fake_current_user():
        request.current_user = SimpleNamespace(id=11, tenant_id=1, full_name='Preview Tester')

    csv = (
        "MPAN_MPR,Business_Name,Contact_Person,Tel_Number,Start_Date,End_Date\n"
        "MPAN-1,Acme Ltd,,+441234,2023-01-01,2023-12-31\n"  # valid
        ",Missing MPAN,John Doe,+441235,2023-02-01,2023-11-30\n"  # missing mpan
        "MPAN-1,Duplicate Co,,+441236,2023-03-01,2023-09-30\n"  # duplicate mpan
        "MPAN-3,,, +441237,2023-04-01,2023-10-01\n"  # missing business/contact
        "MPAN-4,Has Name,, ,2023-05-01,2023-08-01\n"  # missing tel
        "MPAN-5,Good Co,Joe,+441238,not-a-date,2023-12-31\n"  # invalid start date
    )

    data = {
        'file': (io.BytesIO(csv.encode('utf-8')), 'leads.csv')
    }

    resp = client.post('/api/crm/leads/import/preview', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['success'] is True
    assert body['total_rows'] == 6
    assert body['invalid_rows'] >= 4
    assert body['valid_rows'] >= 1

    # Find row-level assertions
    rows = {r['row_number']: r for r in body['rows']}
    assert rows[1]['is_valid'] is True
    assert rows[2]['is_valid'] is False and 'MPAN_MPR is mandatory' in rows[2]['errors']
    assert rows[3]['is_valid'] is False and any('unique' in e.lower() for e in rows[3]['errors'])
    assert rows[4]['is_valid'] is False and any('Business_Name' in e or 'Contact_Person' in e for e in rows[4]['errors'])
    assert rows[5]['is_valid'] is False and any('Tel_Number' in e for e in rows[5]['errors'])
    assert rows[6]['is_valid'] is False and any('Start_Date' in e for e in rows[6]['errors'])


def test_xlsx_preview_accepts_excel_and_returns_same_shape():
    app = get_app()
    client = app.test_client()
    headers = {"X-Tenant-ID": "1"}

    df = pd.DataFrame([
        {
            'MPAN_MPR': 'X-MPAN-1',
            'Business_Name': 'Excel Co',
            'Tel_Number': '+441299',
            'Start_Date': '2024-01-01',
            'End_Date': '2024-12-31'
        }
    ])

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    bio.seek(0)

    data = {'file': (bio, 'leads.xlsx')}
    resp = client.post('/api/crm/leads/import/preview', data=data, headers=headers, content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['success'] is True
    assert body['total_rows'] == 1
    assert body['valid_rows'] == 1
    assert body['rows'][0]['is_valid'] is True
