# -*- coding: utf-8 -*-
"""
Document Controller
Handles document uploads to Cloudinary for contract templates
"""
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.api
import os
from flask import g, request, jsonify
from typing import Tuple

logger = logging.getLogger(__name__)


class DocumentController:
    """Controller for document management"""
    
    def __init__(self):
        pass
    
    def list_documents(self) -> Tuple:
        """GET /api/crm/documents - List all template documents from Cloudinary"""
        try:
            tenant_id = g.tenant_id
            folder = f"tenant_{tenant_id}/templates"
            
            result = cloudinary.api.resources(
                type="upload",
                resource_type="raw",
                prefix=folder,
                max_results=500
            )
            
            documents = []
            for resource in result.get('resources', []):
                public_id = resource.get('public_id')
                filename = public_id.split('/')[-1]
                file_format = resource.get('format') or (
                    os.path.splitext(filename)[1].replace('.', '') if '.' in filename else ''
                )
                
                documents.append({
                    'public_id': public_id,
                    'document_name': filename,
                    'url': resource.get('secure_url'),
                    'format': file_format,
                    'file_size': resource.get('bytes'),
                    'created_at': resource.get('created_at'),
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
    
    def upload_document(self) -> Tuple:
        """POST /api/crm/documents/upload - Upload a template document"""
        try:
            tenant_id = g.tenant_id
            
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'No file provided'}), 400
            
            file = request.files['file']
            
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            
            # Extract extension from original filename
            original_filename = file.filename
            file_extension = os.path.splitext(original_filename)[1]
            
            # Get document name and ensure it has extension
            document_name = request.form.get('document_name', original_filename)
            if not document_name.endswith(file_extension):
                document_name = f"{document_name}{file_extension}"
            
            # Replace spaces with underscores for cleaner URLs
            document_name = document_name.replace(' ', '_')
            
            category = request.form.get('category', 'OTHER')
            folder = f"tenant_{tenant_id}/templates"
            
            logger.info(f"Uploading document: {document_name} to folder: {folder}")
            
            # Upload as public raw file
            upload_result = cloudinary.uploader.upload(
                file,
                folder=folder,
                resource_type='raw',
                public_id=document_name,
                use_filename=False,
                unique_filename=False,
                overwrite=True,
                invalidate=True,
                access_mode='public',
                context=f"category={category}"
            )
            
            logger.info(f"Upload successful: {upload_result.get('secure_url')}")
            
            return jsonify({
                'success': True,
                'data': {
                    'public_id': upload_result['public_id'],
                    'url': upload_result['secure_url'],
                    'document_name': document_name,
                    'format': file_extension.replace('.', ''),
                    'file_size': upload_result.get('bytes'),
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
    
    def delete_document(self) -> Tuple:
        """DELETE /api/crm/documents - Delete a document from Cloudinary"""
        try:
            data = request.get_json()
            public_id = data.get('public_id')
            
            if not public_id:
                return jsonify({'success': False, 'error': 'public_id is required'}), 400
            
            tenant_id = g.tenant_id
            if not public_id.startswith(f"tenant_{tenant_id}/"):
                return jsonify({'success': False, 'error': 'Unauthorized'}), 403
            
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type='raw',
                invalidate=True
            )
            
            if result.get('result') not in ['ok', 'not found']:
                return jsonify({'success': False, 'error': 'Failed to delete document'}), 400
            
            return jsonify({'success': True, 'message': 'Document deleted successfully'}), 200
            
        except Exception as e:
            logger.exception(f"Error deleting document: {e}")
            return jsonify({'success': False, 'error': 'Failed to delete document', 'message': str(e)}), 500