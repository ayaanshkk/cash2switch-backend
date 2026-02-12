# -*- coding: utf-8 -*-
"""
Cloudinary Client
Handles file uploads to Cloudinary
"""
import os
import logging
import cloudinary
import cloudinary.uploader
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Configure Cloudinary with connection pooling
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
    # ✅ Add connection pooling configuration
    pool_maxsize=10,
    pool_block=True   
)


class CloudinaryClient:
    """Client for Cloudinary file operations"""
    
    @staticmethod
    def upload_document(file, folder: str = "documents", public_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a document to Cloudinary
        
        Args:
            file: File object to upload
            folder: Cloudinary folder name
            public_id: Optional public ID for the file
        
        Returns:
            Dictionary with upload results
        """
        try:
            upload_options = {
                'folder': folder,
                'resource_type': 'auto',
                'overwrite': False,
            }
            
            if public_id:
                upload_options['public_id'] = public_id
            
            result = cloudinary.uploader.upload(file, **upload_options)
            
            return {
                'success': True,
                'url': result.get('secure_url'),
                'public_id': result.get('public_id'),
                'format': result.get('format'),
                'resource_type': result.get('resource_type'),
                'bytes': result.get('bytes'),
                'created_at': result.get('created_at'),
            }
        
        except Exception as e:
            logger.error(f"Cloudinary upload error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def delete_document(public_id: str, resource_type: str = 'auto') -> Dict[str, Any]:
        """
        Delete a document from Cloudinary
        
        Args:
            public_id: Cloudinary public ID
            resource_type: Type of resource (auto, image, video, raw)
        
        Returns:
            Dictionary with deletion results
        """
        try:
            result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
            
            return {
                'success': result.get('result') == 'ok',
                'result': result.get('result')
            }
        
        except Exception as e:
            logger.error(f"Cloudinary deletion error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def get_download_url(public_id: str, resource_type: str = 'raw') -> str:
        """
        Generate a download URL for a document
        
        Args:
            public_id: Cloudinary public ID
            resource_type: Type of resource
        
        Returns:
            Download URL
        """
        try:
            url = cloudinary.CloudinaryResource(public_id, resource_type=resource_type).build_url(
                flags='attachment'
            )
            return url
        except Exception as e:
            logger.error(f"Error generating download URL: {e}")
            return ""