# core_routes.py - Fixed to use Blueprint
from flask import Blueprint, render_template, jsonify

# Create blueprint
core_bp = Blueprint('core', __name__)

# Import your config constants
try:
    from config import latest_structured_data, FORM_COLUMNS
except ImportError:
    # Fallback if config is not available
    latest_structured_data = {}
    FORM_COLUMNS = []

@core_bp.route('/')
def index():
    return render_template('index.html')

@core_bp.route('/view-data')
def view_data():
    if not latest_structured_data:
        return render_template('table.html', columns=FORM_COLUMNS, data=None, error="No data available. Please upload an image first.")
    return render_template('table.html', columns=FORM_COLUMNS, data=latest_structured_data, error=None)