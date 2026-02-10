# -*- coding: utf-8 -*-
"""
Document Repository
Handles database operations for document management
"""
import os
import logging
from typing import Optional, Dict, Any, List
from backend.crm.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _supabase_configured() -> bool:
    """True if Supabase env vars are set"""
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return False
    if os.getenv("SUPABASE_DB_URL"):
        return True
    if os.getenv("DATABASE_URL") and "supabase" in (os.getenv("DATABASE_URL") or ""):
        return True
    if os.getenv("SUPABASE_DB_PASSWORD"):
        return True
    return False


class _LocalCRMDBStub:
    """Stub DB adapter when Supabase is not configured"""
    def execute_query(self, query: str, params: tuple = None, fetch_one: bool = False):
        return None if fetch_one else []


class DocumentRepository:
    """Repository for document management"""
    
    def __init__(self):
        if _supabase_configured():
            self.db = get_supabase_client()
        else:
            self.db = _LocalCRMDBStub()
    
    def create_document(self, tenant_id: int, document_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new document record"""
        query = """
            INSERT INTO "StreemLyne_MT"."Document_Master" (
                "tenant_id",
                "document_name",
                "document_description",
                "document_type",
                "cloudinary_url",
                "cloudinary_public_id",
                "file_size",
                "mime_type",
                "category",
                "is_template",
                "uploaded_by_client",
                "client_id",
                "created_at"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING 
                "document_id",
                "tenant_id",
                "document_name",
                "document_description",
                "document_type",
                "cloudinary_url",
                "cloudinary_public_id",
                "file_size",
                "mime_type",
                "category",
                "is_template",
                "uploaded_by_client",
                "client_id",
                "created_at"
        """
        
        try:
            return self.db.execute_query(
                query,
                (
                    tenant_id,
                    document_data.get('document_name'),
                    document_data.get('document_description'),
                    document_data.get('document_type'),
                    document_data.get('cloudinary_url'),
                    document_data.get('cloudinary_public_id'),
                    document_data.get('file_size'),
                    document_data.get('mime_type'),
                    document_data.get('category', 'OTHER'),
                    document_data.get('is_template', False),
                    document_data.get('uploaded_by_client', False),
                    document_data.get('client_id'),
                ),
                fetch_one=True
            )
        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return None
    
    def get_all_documents(self, tenant_id: int, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Get all documents for a tenant with optional filters"""
        query = """
            SELECT 
                d."document_id",
                d."tenant_id",
                d."document_name",
                d."document_description",
                d."document_type",
                d."cloudinary_url",
                d."cloudinary_public_id",
                d."file_size",
                d."mime_type",
                d."category",
                d."is_template",
                d."uploaded_by_client",
                d."client_id",
                d."created_at",
                c."client_company_name"
            FROM "StreemLyne_MT"."Document_Master" d
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON d."client_id" = c."client_id"
            WHERE d."tenant_id" = %s
        """
        
        params = [tenant_id]
        
        if filters:
            if filters.get('category'):
                query += ' AND d."category" = %s'
                params.append(filters['category'])
            
            if filters.get('document_type'):
                query += ' AND d."document_type" = %s'
                params.append(filters['document_type'])
            
            if filters.get('is_template') is not None:
                query += ' AND d."is_template" = %s'
                params.append(filters['is_template'])
            
            if filters.get('uploaded_by_client') is not None:
                query += ' AND d."uploaded_by_client" = %s'
                params.append(filters['uploaded_by_client'])
            
            if filters.get('client_id'):
                query += ' AND d."client_id" = %s'
                params.append(filters['client_id'])
        
        query += ' ORDER BY d."created_at" DESC'
        
        try:
            return self.db.execute_query(query, tuple(params))
        except Exception as e:
            logger.error(f"Error fetching documents: {e}")
            return []
    
    def get_document_by_id(self, tenant_id: int, document_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific document"""
        query = """
            SELECT 
                d."document_id",
                d."tenant_id",
                d."document_name",
                d."document_description",
                d."document_type",
                d."cloudinary_url",
                d."cloudinary_public_id",
                d."file_size",
                d."mime_type",
                d."category",
                d."is_template",
                d."uploaded_by_client",
                d."client_id",
                d."created_at",
                c."client_company_name"
            FROM "StreemLyne_MT"."Document_Master" d
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON d."client_id" = c."client_id"
            WHERE d."tenant_id" = %s AND d."document_id" = %s
            LIMIT 1
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, document_id), fetch_one=True)
        except Exception as e:
            logger.error(f"Error fetching document {document_id}: {e}")
            return None
    
    def delete_document(self, tenant_id: int, document_id: int) -> bool:
        """Delete a document"""
        query = """
            DELETE FROM "StreemLyne_MT"."Document_Master"
            WHERE "tenant_id" = %s AND "document_id" = %s
        """
        
        try:
            self.db.execute_query(query, (tenant_id, document_id))
            return True
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return False
    
    def get_client_documents(self, tenant_id: int, client_id: int) -> List[Dict[str, Any]]:
        """Get all documents for a specific client"""
        query = """
            SELECT 
                "document_id",
                "document_name",
                "document_description",
                "document_type",
                "cloudinary_url",
                "cloudinary_public_id",
                "file_size",
                "mime_type",
                "category",
                "is_template",
                "uploaded_by_client",
                "created_at"
            FROM "StreemLyne_MT"."Document_Master"
            WHERE "tenant_id" = %s AND "client_id" = %s
            ORDER BY "created_at" DESC
        """
        
        try:
            return self.db.execute_query(query, (tenant_id, client_id))
        except Exception as e:
            logger.error(f"Error fetching documents for client {client_id}: {e}")
            return []