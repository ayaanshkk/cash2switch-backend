# document_routes.py
# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import json
import os
import httpx  # already in your requirements
from backend.routes.auth_helpers import token_required
from backend.routes.crm_routes import tenant_from_jwt
from backend.crm.controllers.document_controller import DocumentController
from backend.db import SessionLocal
from backend.models import Client_Master

# ← NO vercel_blob or vercel_storage imports here

document_bp = Blueprint('documents', __name__, url_prefix='/api/crm/documents')
document_controller = DocumentController()


def _upload_to_vercel_blob(path: str, data: bytes, content_type: str) -> str:
    """Upload directly to Vercel Blob REST API."""
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise ValueError("BLOB_READ_WRITE_TOKEN env var not set")
    resp = httpx.put(
        f"https://blob.vercel-storage.com/{path}",
        content=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "x-api-version": "7",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["url"]


@document_bp.route('', methods=['GET'])
@token_required
@tenant_from_jwt
def list_documents():
    return document_controller.list_documents()


@document_bp.route('/upload', methods=['POST'])
@token_required
@tenant_from_jwt
def upload_document():
    return document_controller.upload_document()


@document_bp.route('', methods=['DELETE'])
@token_required
@tenant_from_jwt
def delete_document():
    return document_controller.delete_document()


@document_bp.route('/upload-customer-documents', methods=['POST', 'OPTIONS'])
@token_required
@tenant_from_jwt
def upload_customer_documents():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        client_id = request.form.get('client_id')
        if not client_id:
            return jsonify({'error': 'client_id is required'}), 400

        if 'documents' not in request.files:
            return jsonify({'error': 'No documents provided'}), 400

        files = request.files.getlist('documents')
        if not files:
            return jsonify({'error': 'No documents selected'}), 400

        uploaded_urls = []

        for file in files:
            if file and file.filename:
                try:
                    filename = secure_filename(file.filename)
                    path = f"customer_documents/client_{client_id}/{filename}"
                    url = _upload_to_vercel_blob(
                        path=path,
                        data=file.read(),
                        content_type=file.content_type or 'application/octet-stream'
                    )
                    uploaded_urls.append(url)
                    current_app.logger.info(f"✅ Uploaded: {filename} → {url}")
                except Exception as upload_error:
                    current_app.logger.error(f"❌ Failed to upload {file.filename}: {upload_error}")
                    continue

        if not uploaded_urls:
            return jsonify({'error': 'No valid documents uploaded'}), 400

        session = SessionLocal()
        try:
            client = session.query(Client_Master).filter_by(client_id=int(client_id)).first()
            if client:
                existing_docs = []
                if client.document_details:
                    try:
                        existing_docs = json.loads(client.document_details) if isinstance(client.document_details, str) else client.document_details
                        if not isinstance(existing_docs, list):
                            existing_docs = []
                    except Exception:
                        existing_docs = []
                client.document_details = json.dumps(existing_docs + uploaded_urls)
                session.commit()
        except Exception as db_error:
            session.rollback()
            current_app.logger.error(f"❌ Database error: {db_error}")
        finally:
            session.close()

        return jsonify({
            'success': True,
            'message': f'{len(uploaded_urls)} document(s) uploaded successfully',
            'file_paths': uploaded_urls
        }), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Upload error: {e}")
        return jsonify({'error': str(e)}), 500