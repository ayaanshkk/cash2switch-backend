# -*- coding: utf-8 -*-
"""
Document Service
Business logic for document management
"""
import logging
from typing import Dict, Any, List, Optional
from werkzeug.utils import secure_filename
from backend.crm.repositories.document_repository import DocumentRepository
from backend.utils.cloudinary_client import CloudinaryClient

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'txt'}


class DocumentService:
    """Service for document operations"""
    
    def __init__(self):
        self.document_repo = DocumentRepository()
        self.cloudinary_client = CloudinaryClient()
    
    def allowed_file(self, filename: str) -> bool:
        """Check if file extension is allowed"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
    def upload_document(
        self, 
        tenant_id: int, 
        file, 
        document_data: Dict[str, Any],
        uploaded_by_client: bool = False,
        client_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Upload and save a document to Cloudinary
        
        Args:
            tenant_id: Tenant identifier
            file: File object from request
            document_data: Additional document metadata
            uploaded_by_client: Whether uploaded by client
            client_id: Client ID if uploaded by client
        
        Returns:
            Result dictionary with success status and document data
        """
        try:
            if not file or file.filename == '':
                return {
                    'success': False,
                    'error': 'No file provided'
                }
            
            if not self.allowed_file(file.filename):
                return {
                    'success': False,
                    'error': f'File type not allowed. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
                }
            
            # Secure the filename
            filename = secure_filename(file.filename)
            file_extension = filename.rsplit('.', 1)[1].lower()
            
            # Determine folder based on upload source
            if uploaded_by_client:
                folder = f"streemlyne/tenant_{tenant_id}/client_uploads"
            else:
                folder = f"streemlyne/tenant_{tenant_id}/templates"
            
            # Upload to Cloudinary
            upload_result = self.cloudinary_client.upload_document(
                file,
                folder=folder
            )
            
            if not upload_result.get('success'):
                return {
                    'success': False,
                    'error': 'Failed to upload to Cloudinary',
                    'message': upload_result.get('error', 'Unknown error')
                }
            
            # Determine MIME type
            mime_type = self._get_mime_type(file_extension)
            
            # Prepare document data
            doc_data = {
                'document_name': document_data.get('document_name', filename),
                'document_description': document_data.get('document_description', ''),
                'document_type': file_extension,
                'cloudinary_url': upload_result['url'],
                'cloudinary_public_id': upload_result['public_id'],
                'file_size': upload_result['bytes'],
                'mime_type': mime_type,
                'category': document_data.get('category', 'OTHER'),
                'is_template': document_data.get('is_template', False),
                'uploaded_by_client': uploaded_by_client,
                'client_id': client_id
            }
            
            # Save to database
            document = self.document_repo.create_document(tenant_id, doc_data)
            
            if not document:
                # Cleanup Cloudinary file if database insert fails
                self.cloudinary_client.delete_document(upload_result['public_id'])
                return {
                    'success': False,
                    'error': 'Failed to save document to database'
                }
            
            return {
                'success': True,
                'message': 'Document uploaded successfully',
                'data': document
            }
        
        except Exception as e:
            logger.error(f"Error uploading document: {e}")
            return {
                'success': False,
                'error': 'Failed to upload document',
                'message': str(e)
            }
    
    def get_documents(self, tenant_id: int, filters: Optional[Dict] = None) -> Dict[str, Any]:
        """Get all documents for a tenant"""
        try:
            documents = self.document_repo.get_all_documents(tenant_id, filters)
            
            return {
                'success': True,
                'data': documents,
                'count': len(documents)
            }
        except Exception as e:
            logger.error(f"Error fetching documents: {e}")
            return {
                'success': False,
                'error': 'Failed to fetch documents',
                'message': str(e)
            }
    
    def get_document(self, tenant_id: int, document_id: int) -> Dict[str, Any]:
        """Get a specific document"""
        try:
            document = self.document_repo.get_document_by_id(tenant_id, document_id)
            
            if not document:
                return {
                    'success': False,
                    'error': 'Document not found'
                }
            
            return {
                'success': True,
                'data': document
            }
        except Exception as e:
            logger.error(f"Error fetching document: {e}")
            return {
                'success': False,
                'error': 'Failed to fetch document',
                'message': str(e)
            }
    
    def delete_document(self, tenant_id: int, document_id: int) -> Dict[str, Any]:
        """Delete a document"""
        try:
            # Get document to find Cloudinary public ID
            document = self.document_repo.get_document_by_id(tenant_id, document_id)
            
            if not document:
                return {
                    'success': False,
                    'error': 'Document not found'
                }
            
            # Delete from Cloudinary
            public_id = document.get('cloudinary_public_id')
            if public_id:
                self.cloudinary_client.delete_document(public_id)
            
            # Delete from database
            success = self.document_repo.delete_document(tenant_id, document_id)
            
            if not success:
                return {
                    'success': False,
                    'error': 'Failed to delete document from database'
                }
            
            return {
                'success': True,
                'message': 'Document deleted successfully'
            }
        except Exception as e:
            logger.error(f"Error deleting document: {e}")
            return {
                'success': False,
                'error': 'Failed to delete document',
                'message': str(e)
            }
    
    def get_client_documents(self, tenant_id: int, client_id: int) -> Dict[str, Any]:
        """Get all documents for a client"""
        try:
            documents = self.document_repo.get_client_documents(tenant_id, client_id)
            
            return {
                'success': True,
                'data': documents,
                'count': len(documents)
            }
        except Exception as e:
            logger.error(f"Error fetching client documents: {e}")
            return {
                'success': False,
                'error': 'Failed to fetch client documents',
                'message': str(e)
            }
    
    def _get_mime_type(self, extension: str) -> str:
        """Get MIME type based on file extension"""
        mime_types = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'txt': 'text/plain'
        }
        return mime_types.get(extension, 'application/octet-stream')