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
# DELETE FILE
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
# LIST FILES
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
