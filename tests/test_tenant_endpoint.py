# -*- coding: utf-8 -*-
import os, sys, io
from flask import Flask, jsonify

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.crm.repositories.tenant_repository import TenantRepository

app = Flask(__name__)

@app.route('/test-tenant/<int:tenant_id>')
def test_tenant(tenant_id):
    repo = TenantRepository()
    tenant = repo.get_tenant_by_id(tenant_id)
    
    if tenant:
        # Convert date/datetime to strings for JSON
        result = {}
        for k, v in tenant.items():
            result[k] = str(v) if hasattr(v, 'isoformat') else v
        return jsonify({"success": True, "tenant": result})
    else:
        return jsonify({"success": False, "message": "Tenant not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
