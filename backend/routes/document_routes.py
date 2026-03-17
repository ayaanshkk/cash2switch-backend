# -*- coding: utf-8 -*-
"""
Document Routes
API endpoints for document management (using Vercel Blob)
"""
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import json
from backend.routes.auth_helpers import token_required
from backend.routes.crm_routes import tenant_from_jwt
from backend.crm.controllers.document_controller import DocumentController
from backend.db import SessionLocal
from backend.models import Client_Master
import vercel_blob as blob

# Create blueprint
document_bp = Blueprint('documents', __name__, url_prefix='/api/crm/documents')

# Initialize controller
document_controller = DocumentController()


@document_bp.route('', methods=['GET'])
@token_required
@tenant_from_jwt
def list_documents():
    """List all template documents"""
    return document_controller.list_documents()


@document_bp.route('/upload', methods=['POST'])
@token_required
@tenant_from_jwt
def upload_document():
    """Upload a new template document"""
    return document_controller.upload_document()


@document_bp.route('', methods=['DELETE'])  
@token_required
@tenant_from_jwt
def delete_document():
    """Delete a document"""
    return document_controller.delete_document()


# ✅ NEW: Customer-specific document upload
@document_bp.route('/upload-customer-documents', methods=['POST', 'OPTIONS'])
@token_required
@tenant_from_jwt
def upload_customer_documents():
    """Upload documents for a specific customer using Vercel Blob"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        from werkzeug.utils import secure_filename
        from vercel_storage import blob
        import json
        from backend.db import SessionLocal
        from backend.models import Client_Master
        
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
                    
                    # Upload to Vercel Blob
                    blob_response = blob.put(
                        pathname=path,
                        body=file.read(),
                        options={'contentType': file.content_type or 'application/octet-stream'}
                    )
                    
                    uploaded_urls.append(blob_response['url'])
                    current_app.logger.info(f"✅ Uploaded: {filename} → {blob_response['url']}")
                    
                except Exception as upload_error:
                    current_app.logger.error(f"❌ Failed to upload {file.filename}: {upload_error}")
                    continue
        
        if not uploaded_urls:
            return jsonify({'error': 'No valid documents uploaded'}), 400
        
        # Update Client_Master.document_details
        session = SessionLocal()
        try:
            client = session.query(Client_Master).filter_by(client_id=int(client_id)).first()
            
            if client:
                # Get existing documents
                existing_docs = []
                if client.document_details:
                    try:
                        existing_docs = json.loads(client.document_details) if isinstance(client.document_details, str) else client.document_details
                        if not isinstance(existing_docs, list):
                            existing_docs = []
                    except:
                        existing_docs = []
                
                # Add new documents
                all_docs = existing_docs + uploaded_urls
                client.document_details = json.dumps(all_docs)
                session.commit()
                
                current_app.logger.info(f"✅ Updated document_details for client {client_id}")
        
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
        
    except ImportError:
        return jsonify({
            'error': 'vercel_storage package not installed. Run: pip install vercel-storage'
        }), 500
    except Exception as e:
        current_app.logger.exception(f"❌ Upload error: {e}")
        return jsonify({'error': str(e)}), 500