import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv('.env')

from backend.app import create_app

app = create_app()
secret = app.config['SECRET_KEY']
print(f'✅ App loaded SECRET_KEY: {secret[:30]}...')
print(f'✅ Full length: {len(secret)} characters')

# Test signing a token
import jwt
from datetime import datetime, timedelta

payload = {
    'user_id': 1,
    'employee_id': 1,
    'tenant_id': 1,
    'user_name': 'test',
    'exp': datetime.utcnow() + timedelta(days=7),
    'iat': datetime.utcnow()
}

token = jwt.encode(payload, secret, algorithm='HS256')
print(f'✅ Generated test token: {token[:50]}...')

# Try to decode it
try:
    decoded = jwt.decode(token, secret, algorithms=['HS256'])
    print(f'✅ Token decoded successfully!')
    print(f'   Payload: {decoded}')
except Exception as e:
    print(f'❌ Token decode failed: {e}')
