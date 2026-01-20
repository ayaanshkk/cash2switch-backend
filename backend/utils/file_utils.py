import base64
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fetch allowed extensions from .env, default to common ones
# UPDATED: Added xlsx, xls, csv, and pdf for form documents
ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS", "pdf,jpg,jpeg,png,gif,xlsx,xls,csv").split(",")

# NEW: Separate function to check if file is allowed for drawings (images/PDFs only)
def allowed_drawing_file(filename):
    """Check if the file extension is allowed for drawings (images and PDFs)"""
    drawing_extensions = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in drawing_extensions

# NEW: Separate function to check if file is allowed for form documents (Excel/PDF)
def allowed_form_document(filename):
    """Check if the file extension is allowed for form documents (Excel and PDF)"""
    form_extensions = ['pdf', 'xlsx', 'xls', 'csv']
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in form_extensions

def allowed_file(filename):
    """Check if the file extension is allowed (general purpose)"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def encode_image_to_base64(image_path):
    """
    Encode image to base64 string for OpenAI Vision API
    """
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_image_mime_type(file_path):
    """
    Get MIME type for image based on file extension
    """
    extension = file_path.lower().split('.')[-1]
    mime_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'webp': 'image/webp'
    }
    return mime_types.get(extension, 'image/jpeg')

# NEW: Function to get MIME type for documents
def get_document_mime_type(file_path):
    """
    Get MIME type for document based on file extension
    """
    extension = file_path.lower().split('.')[-1]
    mime_types = {
        'pdf': 'application/pdf',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xls': 'application/vnd.ms-excel',
        'csv': 'text/csv',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    }
    return mime_types.get(extension, 'application/octet-stream')

# NEW: Function to determine file category
def get_file_category(filename):
    """
    Determine the category of a file based on its extension
    Returns: 'image', 'pdf', 'excel', 'document', or 'other'
    """
    if not filename or '.' not in filename:
        return 'other'
    
    extension = filename.rsplit('.', 1)[1].lower()
    
    if extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']:
        return 'image'
    elif extension == 'pdf':
        return 'pdf'
    elif extension in ['xlsx', 'xls', 'csv']:
        return 'excel'
    elif extension in ['doc', 'docx']:
        return 'document'
    else:
        return 'other'