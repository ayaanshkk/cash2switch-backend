# File: /backend/minimal_app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
# 🟢 FIX 1: Import necessary SQLAlchemy components
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base
import secrets
import string
import json
from datetime import datetime, timedelta
import os

# 🟢 FIX 2: Define Base and SessionLocal for ORM compatibility, mimicking db.py
# If using Flask-SQLAlchemy, Base isn't usually needed, but here it's mixed with ORM style.
# Assuming Base is declarative_base() and SessionLocal is a Session maker.
Base = declarative_base()
# NOTE: SessionLocal is not defined in this file, which will cause an error later.
# For simplicity in this "minimal_app", we will use `db.session` for Flask-SQLAlchemy style.

# Initialize Flask app
app = Flask(__name__)

# Enable CORS for all routes
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000"])

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
# Note: This is an SQLite setup, not a PostgreSQL/Supabase setup
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "database.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Customer Model
# 🟢 FIX 3: Change model definition to use Flask-SQLAlchemy style (db.Model)
class Customer(db.Model):
    __tablename__ = 'customer'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    status = Column(String(50), default='Active')
    created_at = Column(DateTime, default=datetime.utcnow)

# In-memory storage for form tokens
form_tokens = {}

def generate_secure_token(length=32):
    """Generate a cryptographically secure random token"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

# Routes
@app.route('/test', methods=['GET'])
def test():
    """Test endpoint to verify server is running"""
    return jsonify({
        'success': True,
        'message': 'Backend server is running!',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/clients', methods=['GET', 'POST'])
def handle_customers():
    if request.method == 'POST':
        data = request.json
        new_customer = Customer(
            name=data['name'],
            address=data.get('address', ''),
            phone=data.get('phone', ''),
            email=data.get('email', ''),
            status=data.get('status', 'Active')
        )
        # 🟢 FIX 4: Use db.session for Flask-SQLAlchemy transactions
        try:
            db.session.add(new_customer)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
            
        return jsonify({'id': new_customer.id}), 201
    
    customers = Customer.query.all()
    return jsonify([
        {
            'id': c.id,
            'name': c.name,
            'address': c.address,
            'phone': c.phone,
            'email': c.email,
            'status': c.status,
            'created_at': c.created_at.isoformat() if c.created_at else None
        } for c in customers
    ])

@app.route('/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_form_link():
    """Generate a secure form link for customers"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Generate a unique token
        token = generate_secure_token()
        
        # Store token with expiration (24 hours)
        expiration = datetime.now() + timedelta(hours=24)
        form_tokens[token] = {
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        
        print(f"✅ Generated form token: {token}")
        print(f"📅 Token expires at: {expiration}")
        
        return jsonify({
            'success': True,
            'token': token,
            'expires_at': expiration.isoformat(),
            'message': 'Form link generated successfully'
        }), 200
        
    except Exception as e:
        print(f"❌ Error generating form link: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500

@app.route('/validate-form-token/<token>', methods=['GET', 'OPTIONS'])
def validate_form_token(token):
    """Validate if a form token is still valid"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print(f"🔍 Validating token: {token}")
        
        if token not in form_tokens:
            return jsonify({
                'valid': False,
                'error': 'Invalid token'
            }), 404
            
        token_data = form_tokens[token]
        
        # Check if token has expired
        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({
                'valid': False,
                'error': 'Token has expired'
            }), 410
            
        # Check if token has already been used
        if token_data['used']:
            return jsonify({
                'valid': False,
                'error': 'Token has already been used'
            }), 410
            
        print(f"✅ Token {token} is valid")
        return jsonify({
            'valid': True,
            'expires_at': token_data['expires_at'].isoformat()
        }), 200
        
    except Exception as e:
        print(f"❌ Error validating token: {str(e)}")
        return jsonify({
            'valid': False,
            'error': f'Validation failed: {str(e)}'
        }), 500

@app.route('/submit-customer-form', methods=['POST', 'OPTIONS'])
def submit_customer_form():
    """Handle customer form submission and create new customer"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        token = data.get('token')
        form_data = data.get('formData', {})
        
        print(f"📝 Received form submission for token: {token}")
        
        if not token or not form_data:
            return jsonify({
                'success': False,
                'error': 'Missing token or form data'
            }), 400
            
        # Validate token
        if token not in form_tokens:
            return jsonify({
                'success': False,
                'error': 'Invalid token'
            }), 404
            
        token_data = form_tokens[token]
        
        # Check if token has expired
        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({
                'success': False,
                'error': 'Token has expired'
            }), 410
            
        # Check if token has already been used
        if token_data['used']:
            return jsonify({
                'success': False,
                'error': 'Token has already been used'
            }), 410
        
        # Extract customer information
        customer_name = form_data.get('customer_name', '').strip()
        customer_phone = form_data.get('customer_phone', '').strip()
        customer_email = form_data.get('customer_email', '').strip()
        customer_address = form_data.get('customer_address', '').strip()
        
        if not customer_name:
            return jsonify({
                'success': False,
                'error': 'Customer name is required'
            }), 400
        
        # Create new customer
        new_customer = Customer(
            name=customer_name,
            phone=customer_phone,
            address=customer_address,
            email=customer_email,
            status='New Lead'
        )
        
        # 🟢 FIX 5: Use db.session for Flask-SQLAlchemy transactions
        try:
            db.session.add(new_customer)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        
        # Mark token as used
        form_tokens[token]['used'] = True
        
        customer_id = new_customer.id
        print(f"✅ Created customer {customer_id}: {customer_name}")
        
        return jsonify({
            'success': True,
            'customer_id': customer_id,
            'message': 'Customer created successfully'
        }), 201
        
    except Exception as e:
        print(f"❌ Error submitting customer form: {str(e)}")
        # 🟢 FIX 6: Use db.session.rollback() for error handling
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Form submission failed: {str(e)}'
        }), 500

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

if __name__ == '__main__':
    print("🚀 Starting Minimal Backend Server...")
    print("=" * 50)
    
    # Create database tables
    with app.app_context():
        # 🟢 FIX 7: Use db.create_all() for Flask-SQLAlchemy metadata creation
        db.create_all()
        print("✅ Database tables created!")
        
        # Add some test data if no customers exist
        if Customer.query.count() == 0:
            test_customers = [
                Customer(name="John Smith", phone="123-456-7890", address="123 Main St", status="Active"),
                Customer(name="Jane Doe", phone="987-654-3210", address="456 Oak Ave", status="New Lead"),
            ]
            for customer in test_customers:
                # 🟢 FIX 8: Use db.session for inserting test data
                db.session.add(customer)
            
            db.session.commit()
            print("✅ Added test customers!")
    
    print("📍 Server starting at: http://127.0.0.1:5000")
    print("🧪 Test endpoint: http://127.0.0.1:5000/test")
    print("👥 Customers endpoint: http://127.0.0.1:5000/clients")
    print("🔗 Form link endpoint: http://127.0.0.1:5000/generate-form-link")
    print("=" * 50)
    
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    app.run(debug=debug_mode, host='127.0.0.1', port=5000)
