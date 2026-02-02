# -*- coding: utf-8 -*-
"""Integration-style test for /auth/login tenant-resolution behavior.

This test:
- Creates a fresh Employee_Master + User_Master via the public /auth/signup endpoint
  (signup still requires tenant_id)
- Calls /auth/login with ONLY { username, password }
- Asserts the response is 200 and the returned `user` object contains:
  - id (employee_id), username, tenant_id (resolved from DB), name

Note: this test exercises the running Flask app and a real DB connection similar
to other tests in this repo. It may be skipped in minimal CI setups that don't
provide a DB.
"""

import json
import uuid
from backend.app import create_app


def test_login_resolves_tenant_from_employee_master():
    app = create_app()
    client = app.test_client()

    # Use a reasonably-unique username/email to avoid collisions with existing test data
    unique = uuid.uuid4().hex[:8]
    username = f"testuser_{unique}"
    email = f"{unique}@example.test"
    password = "TestPass123!"

    # 1) Create via signup (signup still requires tenant_id)
    signup_payload = {
        "tenant_id": 1,
        "employee_name": "Test User",
        "email": email,
        "username": username,
        "password": password
    }

    resp = client.post("/auth/signup", data=json.dumps(signup_payload), content_type="application/json")
    assert resp.status_code in (200, 201), f"signup failed: {resp.status_code} {resp.data}"
    body = resp.get_json()
    assert body.get("success") is True

    # 2) Login with only username + password (no tenant_id)
    login_payload = {"username": username, "password": password}
    resp = client.post("/auth/login", data=json.dumps(login_payload), content_type="application/json")

    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.data}"
    body = resp.get_json()

    assert body.get("success") is True
    assert "token" in body and body["token"], "missing token"
    user = body.get("user")
    assert isinstance(user, dict), "user is not an object"

    # shape assertions per the new contract
    assert user.get("id") is not None
    assert user.get("username") == username
    assert user.get("tenant_id") == 1
    assert user.get("name") in ("Test User", username)


def test_refresh_preserves_tenant_in_token():
    """Refreshing a tenant-scoped token must preserve tenant_id in the new JWT."""
    import jwt as _jwt

    app = create_app()
    client = app.test_client()

    unique = 'refreshtest'
    username = f"rt_{unique}"
    email = f"{unique}@example.test"
    password = "TestPass123!"

    # create user (signup requires tenant_id)
    signup_payload = {
        "tenant_id": 1,
        "employee_name": "Refresh Test",
        "email": email,
        "username": username,
        "password": password
    }
    resp = client.post("/auth/signup", data=json.dumps(signup_payload), content_type="application/json")
    assert resp.status_code in (200, 201)

    # login -> get initial token with tenant_id
    resp = client.post("/auth/login", data=json.dumps({"username": username, "password": password}), content_type="application/json")
    assert resp.status_code == 200
    body = resp.get_json()
    orig_token = body.get('token')
    assert orig_token

    # call refresh
    resp = client.post("/auth/refresh", headers={"Authorization": f"Bearer {orig_token}"})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    new_token = body.get('token')
    assert new_token

    payload = _jwt.decode(new_token, app.config['SECRET_KEY'], algorithms=['HS256'])
    assert payload.get('tenant_id') == 1, f"refreshed token missing tenant_id: {payload}"
