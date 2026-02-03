from flask import request, jsonify, Blueprint, current_app, redirect, Response
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import uuid
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api

from .auth_helpers import token_required
from ..db import SessionLocal
from sqlalchemy import or_

file_bp = Blueprint("file_routes", __name__)


# =========================================================
# CLOUDINARY CONFIG
# =========================================================

def get_cloudinary_config():
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        return None

    return {
        "cloud_name": cloud_name,
        "api_key": api_key,
        "api_secret": api_secret,
    }


def ensure_cloudinary_configured():
    config = get_cloudinary_config()
    if not config:
        raise ValueError(
            "Cloudinary config missing: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET"
        )

    cloudinary.config(
        cloud_name=config["cloud_name"],
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        secure=True,
    )
    return True


ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "gif", "webp",
    "xlsx", "xls", "csv", "doc", "docx", "txt", "zip"
}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# =========================================================
# UNIFIED UPLOAD HELPER
# =========================================================

def upload_to_cloudinary(file, filename, folder):
    ensure_cloudinary_configured()

    file.seek(0)
    extension = filename.rsplit(".", 1)[-1].lower()
    mime = getattr(file, "mimetype", "").lower()

    # Determine resource type
    if extension in ["png", "jpg", "jpeg", "gif", "webp"] or "image" in mime:
        resource_type = "image"
    elif extension in ["pdf", "xlsx", "xls", "csv", "doc", "docx", "txt", "zip"]:
        resource_type = "raw"
    else:
        resource_type = "raw"

    upload_result = cloudinary.uploader.upload(
        file,
        folder=folder,
        public_id=filename.rsplit(".", 1)[0],
        resource_type=resource_type,
        overwrite=False,
        unique_filename=True,
    )

    return upload_result["secure_url"], upload_result["public_id"]


def delete_from_cloudinary(identifier):
    ensure_cloudinary_configured()

    public_id = identifier

    # If user provided a URL instead of public_id → extract public_id
    if "cloudinary.com" in identifier:
        try:
            part = identifier.split("/upload/")[1]
            part = part.split(".")[0]
            public_id = "/".join(part.split("/")[1:]) if part.startswith("v") else part
        except Exception:
            pass

    # Try deleting different resource types
    for rtype in ["raw", "image", "video"]:
        result = cloudinary.uploader.destroy(public_id, resource_type=rtype)
        if result.get("result") in ("ok", "not found"):
            return True

    return False


# =========================================================
# GENERIC UPLOAD
# =========================================================

@file_bp.route("/files/upload", methods=["POST", "OPTIONS"])
@token_required
def upload_file():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{filename}"

    folder = request.form.get("folder", "forklift-academy/general")
    customer_id = request.form.get("customer_id")

    if customer_id:
        folder = f"forklift-academy/clients/{customer_id}"

    url, public_id = upload_to_cloudinary(file, unique_filename, folder)

    uploaded_by = getattr(getattr(request, "current_user", None), "full_name", "System")

    return jsonify({
        "success": True,
        "file_url": url,
        "public_id": public_id,
        "filename": filename,
        "uploaded_by": uploaded_by
    }), 201


# =========================================================
# ENERGY CLIENT DOCUMENTS UPLOAD (NEW)
# =========================================================

@file_bp.route("/upload-documents", methods=["POST", "OPTIONS"])
@token_required
def upload_energy_documents():
    """
    Upload multiple documents for energy clients.
    Files are stored in Cloudinary under: energy-clients/documents/{client_id}/
    Returns array of file URLs to be stored in Energy_Contract_Master.document_details
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        # Get client_id from form data
        client_id = request.form.get("client_id")
        if not client_id:
            return jsonify({"error": "client_id is required"}), 400

        # Get all uploaded files
        files = request.files.getlist("documents")
        if not files or len(files) == 0:
            return jsonify({"error": "No files provided"}), 400

        # Validate all files before uploading
        for file in files:
            if not file.filename:
                return jsonify({"error": "Invalid file"}), 400
            if not allowed_file(file.filename):
                return jsonify({
                    "error": f"File type not allowed: {file.filename}"
                }), 400

        # Upload all files to Cloudinary
        uploaded_files = []
        folder = f"energy-clients/documents/{client_id}"

        for file in files:
            try:
                # Create unique filename
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}_{filename}"

                # Upload to Cloudinary
                url, public_id = upload_to_cloudinary(file, unique_filename, folder)

                uploaded_files.append({
                    "url": url,
                    "public_id": public_id,
                    "filename": filename,
                    "uploaded_at": datetime.now().isoformat()
                })

            except Exception as e:
                # If any file fails, log but continue with others
                print(f"Error uploading {file.filename}: {str(e)}")
                continue

        if len(uploaded_files) == 0:
            return jsonify({"error": "Failed to upload any files"}), 500

        # Return URLs in format expected by frontend
        file_paths = [f["url"] for f in uploaded_files]

        uploaded_by = getattr(getattr(request, "current_user", None), "full_name", "System")

        return jsonify({
            "success": True,
            "file_paths": file_paths,
            "files": uploaded_files,
            "uploaded_by": uploaded_by,
            "count": len(uploaded_files)
        }), 201

    except Exception as e:
        print(f"Error in upload_energy_documents: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================
# DELETE ENERGY CLIENT DOCUMENT (NEW)
# =========================================================

@file_bp.route("/delete-document", methods=["POST", "OPTIONS"])
@token_required
def delete_energy_document():
    """
    Delete a single document from Cloudinary.
    Accepts either public_id or file_url.
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        data = request.get_json() or {}
        identifier = data.get("public_id") or data.get("file_url") or data.get("url")

        if not identifier:
            return jsonify({"error": "public_id, file_url, or url required"}), 400

        # Delete from Cloudinary
        if delete_from_cloudinary(identifier):
            return jsonify({
                "success": True,
                "message": "Document deleted successfully"
            }), 200

        return jsonify({"error": "Failed to delete document"}), 500

    except Exception as e:
        print(f"Error in delete_energy_document: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================
# LIST ENERGY CLIENT DOCUMENTS (NEW)
# =========================================================

@file_bp.route("/list-documents/<client_id>", methods=["GET", "OPTIONS"])
@token_required
def list_energy_documents(client_id):
    """
    List all documents for a specific energy client from Cloudinary.
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        ensure_cloudinary_configured()

        folder = f"energy-clients/documents/{client_id}"

        # Get both raw files (PDFs, docs, etc.) and images
        result_raw = cloudinary.api.resources(
            prefix=folder,
            resource_type="raw",
            max_results=500
        )
        result_img = cloudinary.api.resources(
            prefix=folder,
            resource_type="image",
            max_results=500
        )

        files = []
        for res in result_raw.get("resources", []) + result_img.get("resources", []):
            files.append({
                "public_id": res["public_id"],
                "url": res["secure_url"],
                "format": res.get("format", ""),
                "size": res.get("bytes", 0),
                "created_at": res.get("created_at", ""),
                "filename": res["public_id"].split("/")[-1]
            })

        return jsonify({
            "success": True,
            "files": files,
            "count": len(files)
        }), 200

    except Exception as e:
        print(f"Error in list_energy_documents: {str(e)}")
        return jsonify({"error": str(e)}), 500


# =========================================================
# DELETE FILE (ORIGINAL)
# =========================================================

@file_bp.route("/files/delete", methods=["POST", "OPTIONS"])
@token_required
def delete_file():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.get_json() or {}
    identifier = data.get("public_id") or data.get("file_url")

    if not identifier:
        return jsonify({"error": "public_id or file_url required"}), 400

    if delete_from_cloudinary(identifier):
        return jsonify({"success": True}), 200

    return jsonify({"error": "Delete failed"}), 500


# =========================================================
# LIST FILES (ORIGINAL)
# =========================================================

@file_bp.route("/files/list", methods=["GET", "OPTIONS"])
@token_required
def list_files():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    ensure_cloudinary_configured()

    folder = request.args.get("folder", "forklift-academy")
    customer_id = request.args.get("customer_id")

    if customer_id:
        folder = f"forklift-academy/clients/{customer_id}"

    result_raw = cloudinary.api.resources(prefix=folder, resource_type="raw")
    result_img = cloudinary.api.resources(prefix=folder, resource_type="image")

    files = []
    for res in result_raw.get("resources", []) + result_img.get("resources", []):
        files.append({
            "public_id": res["public_id"],
            "url": res["secure_url"],
            "format": res["format"],
            "size": res["bytes"],
            "created_at": res["created_at"],
        })

    return jsonify({"files": files, "count": len(files)}), 200


# =========================================================
# HEALTH CHECK (renamed to avoid conflicts)
# =========================================================

@file_bp.route("/files/health", methods=["GET"])
def file_system_health_check():
    try:
        ensure_cloudinary_configured()
        return jsonify({"status": "ok"}), 200
    except Exception as ex:
        return jsonify({"status": "error", "message": str(ex)}), 500