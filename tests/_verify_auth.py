# quick verification script: signup -> login -> refresh -> assert tenant_id present
import json, sys, uuid, jwt
from backend.app import create_app

app = create_app()
client = app.test_client()

unique = uuid.uuid4().hex[:8]
username = f"verify_{unique}"
email = f"{unique}@example.test"
password = "TestPass123!"

print('signup:', username, email)
signup_payload = {
    "tenant_id": 1,
    "employee_name": "Verify Script",
    "email": email,
    "username": username,
    "password": password
}

r = client.post('/auth/signup', data=json.dumps(signup_payload), content_type='application/json')
print('  signup status:', r.status_code)
if r.status_code not in (200, 201):
    print('  signup body:', r.get_data(as_text=True))
    sys.exit(2)

r = client.post('/auth/login', data=json.dumps({'username': username, 'password': password}), content_type='application/json')
print('  login status:', r.status_code)
if r.status_code != 200:
    print('  login body:', r.get_data(as_text=True))
    sys.exit(3)
body = r.get_json()
orig_token = body.get('token')
if not orig_token:
    print('  login did not return token')
    sys.exit(4)

r = client.post('/auth/refresh', headers={'Authorization': f'Bearer {orig_token}'})
print('  refresh status:', r.status_code)
if r.status_code != 200:
    print('  refresh body:', r.get_data(as_text=True))
    sys.exit(5)

new_token = r.get_json().get('token')
if not new_token:
    print('  refresh did not return token')
    sys.exit(6)

payload = jwt.decode(new_token, app.config['SECRET_KEY'], algorithms=['HS256'])
print('  refreshed token payload:', payload)
if payload.get('tenant_id') != 1:
    print('  tenant_id missing or incorrect in refreshed token')
    sys.exit(7)

print('\nVERIFICATION SUCCESS: refreshed token contains tenant_id=1')
sys.exit(0)
