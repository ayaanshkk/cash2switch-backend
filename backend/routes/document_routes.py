# -*- coding: utf-8 -*-
"""
Document Routes
API endpoints for document management (using Cloudinary only)
"""
from flask import Blueprint
from backend.routes.auth_helpers import token_required  # ✅ Import from auth_helpers
from backend.routes.crm_routes import tenant_from_jwt  # ✅ Import from crm_routes
from backend.crm.controllers.document_controller import DocumentController

# Create blueprint
document_bp = Blueprint('documents', __name__, url_prefix='/api/crm/documents')

# Initialize controller
document_controller = DocumentController()


@document_bp.route('', methods=['GET'])
@token_required
@tenant_from_jwt
def list_documents():
    """List all template documents from Cloudinary"""
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
    """Delete a document from Cloudinary"""
    return document_controller.delete_document()