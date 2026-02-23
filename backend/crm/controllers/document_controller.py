# -*- coding: utf-8 -*-
"""
Document Controller
Handles document uploads to Vercel Blob Storage
UPDATED: 2026-02-19 09:10:00
"""
import logging
import requests
import os
import re
from flask import g, request, jsonify
from typing import Tuple
from datetime import datetime
from urllib.parse import unquote

logger = logging.getLogger(__name__)


class DocumentController:
    """Controller for document management"""
    
    def __init__(self):
        self.blob_token = os.getenv('BLOB_READ_WRITE_TOKEN')
        if not self.blob_token:
            logger.warning("BLOB_READ_WRITE_TOKEN not set - document uploads will fail")
    
    def upload_document(self) -> Tuple:
        """POST /api/crm/documents/upload - Upload to Vercel Blob"""
        try:
            import re  # ✅ Add import at top of method
            
            tenant_id = g.tenant_id
            
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'No file provided'}), 400
            
            file = request.files['file']
            
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            
            original_filename = file.filename
            file_extension = os.path.splitext(original_filename)[1].lower()
            
            document_name = request.form.get('document_name', original_filename)
            if not document_name.endswith(file_extension):
                document_name = f"{document_name}{file_extension}"
            
            document_name = document_name.replace(' ', '_')
            category = request.form.get('category', 'OTHER')
            
            # Create path for tenant isolation
            blob_path = f"tenant_{tenant_id}/templates/{document_name}"
            
            print(f"🔥 Uploading to Vercel Blob: {blob_path}")
            
            # Read file content
            file_content = file.read()
            file_size = len(file_content)
            
            # ✅ Upload to Vercel Blob using proper API
            upload_url = f"https://blob.vercel-storage.com/{blob_path}"
            
            headers = {
                'Authorization': f'Bearer {self.blob_token}',
                'Content-Type': file.content_type or 'application/octet-stream',
                'x-api-version': '4',
            }
            
            params = {
                'filename': document_name,
            }
            
            response = requests.put(
                upload_url,
                data=file_content,
                headers=headers,
                params=params
            )
            
            if response.status_code not in [200, 201]:
                logger.error(f"Blob upload failed ({response.status_code}): {response.text}")
                return jsonify({
                    'success': False,
                    'error': 'Upload failed',
                    'message': response.text
                }), 500
            
            result = response.json()
            url = result.get('url')
            
            # ✅ Extract pathname from URL (includes the hash that Vercel adds)
            pathname_match = re.search(r'blob\.vercel-storage\.com/(.*?)(\?|$)', url)
            pathname = pathname_match.group(1) if pathname_match else result.get('pathname')
            
            # ✅ Add download URL
            download_url = result.get('downloadUrl', url)
            
            print(f"🔥✅ Upload successful: {url}")
            print(f"🔥✅ Pathname extracted from URL: {pathname}")
            
            return jsonify({
                'success': True,
                'data': {
                    'public_id': pathname,  # ✅ Now includes the hash from URL!
                    'url': url,
                    'download_url': download_url,
                    'document_name': document_name,
                    'format': file_extension.replace('.', ''),
                    'file_size': file_size,
                    'category': category
                },
                'message': 'Document uploaded successfully'
            }), 201
            
        except Exception as e:
            logger.exception(f"Error uploading document: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to upload document',
                'message': str(e)
            }), 500

    def list_documents(self) -> Tuple:
        """GET /api/crm/documents - List all documents"""
        logger.info("🔥🔥🔥 LIST_DOCUMENTS CALLED 🔥🔥🔥")
        try:
            tenant_id = g.tenant_id
            prefix = f"tenant_{tenant_id}/templates"
            
            list_url = "https://blob.vercel-storage.com/"
            
            headers = {
                'Authorization': f'Bearer {self.blob_token}',
            }
            
            params = {
                'prefix': prefix,
            }
            
            response = requests.get(list_url, headers=headers, params=params)
            
            if response.status_code != 200:
                logger.error(f"Failed to list documents ({response.status_code}): {response.text}")
                return jsonify({
                    'success': True,
                    'data': [],
                    'count': 0
                }), 200
            
            result = response.json()
            blobs = result.get('blobs', [])
            
            documents = []
            for blob in blobs:
                pathname = blob.get('pathname', '')  # ✅ Full path with unique ID from Vercel
                logger.info(f"🔥 PATHNAME: {pathname}")
                filename = pathname.split('/')[-1]
                
                # Extract display name (remove unique hash for display)
                display_name = filename
                
                file_format = os.path.splitext(filename)[1].replace('.', '')
                
                base_url = blob.get('url')
                download_url = blob.get('downloadUrl', base_url)
                
                documents.append({
                    'public_id': pathname,  # ✅ Use actual pathname from Vercel Blob API
                    'document_name': display_name,
                    'url': base_url,
                    'download_url': download_url,
                    'format': file_format,
                    'file_size': blob.get('size', 0),
                    'created_at': blob.get('uploadedAt'),
                })
            
            return jsonify({
                'success': True,
                'data': documents,
                'count': len(documents)
            }), 200
            
        except Exception as e:
            logger.exception(f"Error listing documents: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to list documents',
                'message': str(e)
            }), 500
    
    def delete_document(self, public_id: str = None) -> Tuple:
        """DELETE /api/crm/documents - Delete a document"""
        try:
            # ✅ Decode URL encoding
            if public_id:
                public_id = unquote(public_id)
            
            logger.info(f"🔍 Delete called with public_id: {public_id}")
            
            if not public_id:
                data = request.get_json()
                public_id = data.get('public_id')
                logger.info(f"🔍 Read from body: {public_id}")
            
            if not public_id:
                logger.error("❌ No public_id provided")
                return jsonify({'success': False, 'error': 'public_id is required'}), 400
            
            tenant_id = g.tenant_id
            logger.info(f"🔍 Tenant ID: {tenant_id}, Checking authorization for: {public_id}")
            
            if not public_id.startswith(f"tenant_{tenant_id}/"):
                logger.error(f"❌ Unauthorized: {public_id} doesn't start with tenant_{tenant_id}/")
                return jsonify({'success': False, 'error': 'Unauthorized'}), 403
            
            logger.info(f"🗑️ Deleting document: {public_id}")
            
            # Delete from Vercel Blob
            delete_url = f"https://blob.vercel-storage.com/{public_id}"
            logger.info(f"🔍 Delete URL: {delete_url}")
            
            headers = {
                'Authorization': f'Bearer {self.blob_token}',
            }
            
            response = requests.delete(delete_url, headers=headers)
            logger.info(f"🔍 Vercel response status: {response.status_code}")
            logger.info(f"🔍 Vercel response body: {response.text}")
            
            if response.status_code not in [200, 204]:
                logger.error(f"❌ Delete failed ({response.status_code}): {response.text}")
                return jsonify({'success': False, 'error': 'Failed to delete document', 'details': response.text}), 400
            
            logger.info(f"✅ Document deleted successfully: {public_id}")
            return jsonify({'success': True, 'message': 'Document deleted successfully'}), 200
            
        except Exception as e:
            logger.exception(f"❌ Error deleting document: {e}")
            return jsonify({'success': False, 'error': 'Failed to delete document', 'message': str(e)}), 500