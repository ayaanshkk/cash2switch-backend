# Add these routes to your Flask app

from flask import request, jsonify
from functools import wraps

# Decorator to check if user is Manager or HR
def manager_or_hr_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'No token provided'}), 401
        
        try:
            token = token.replace('Bearer ', '')
            decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            user = User.query.get(decoded['user_id'])
            
            if not user or user.role not in ['Manager', 'HR']:
                return jsonify({'error': 'Unauthorized - Manager or HR access required'}), 403
            
            return f(user, *args, **kwargs)
        except:
            return jsonify({'error': 'Invalid token'}), 401
    
    return decorated_function


# 1. CREATE INVITE (Manager/HR only)
@app.route('/api/invites/create', methods=['POST'])
@manager_or_hr_required
def create_invite(current_user):
    try:
        data = request.get_json()
        email = data.get('email')
        role = data.get('role')
        
        if not email or not role:
            return jsonify({'error': 'Email and role are required'}), 400
        
        # Check if email already exists as a user
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({'error': 'User with this email already exists'}), 400
        
        # Check if there's already a pending invite for this email
        existing_invite = UserInvite.query.filter_by(
            email=email, 
            is_used=False
        ).first()
        
        if existing_invite and existing_invite.is_valid():
            return jsonify({'error': 'An active invite already exists for this email'}), 400
        
        # Create new invite
        invite = UserInvite(
            email=email,
            role=role,
            created_by=current_user.id,
            expires_in_days=7
        )
        
        db.session.add(invite)
        db.session.commit()
        
        # Generate registration link
        # In production, this should be your actual domain
        registration_link = f"{request.host_url}register?token={invite.token}"
        
        return jsonify({
            'message': 'Invite created successfully',
            'invite': {
                'id': invite.id,
                'email': invite.email,
                'role': invite.role,
                'token': invite.token,
                'registration_link': registration_link,
                'expires_at': invite.expires_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# 2. GET ALL INVITES (Manager/HR only)
@app.route('/api/invites', methods=['GET'])
@manager_or_hr_required
def get_invites(current_user):
    try:
        invites = UserInvite.query.order_by(UserInvite.created_at.desc()).all()
        
        invite_list = []
        for invite in invites:
            creator = User.query.get(invite.created_by)
            invite_list.append({
                'id': invite.id,
                'email': invite.email,
                'role': invite.role,
                'created_by': creator.name if creator else 'Unknown',
                'created_at': invite.created_at.isoformat(),
                'expires_at': invite.expires_at.isoformat(),
                'is_used': invite.is_used,
                'used_at': invite.used_at.isoformat() if invite.used_at else None,
                'is_valid': invite.is_valid(),
                'registration_link': f"{request.host_url}register?token={invite.token}"
            })
        
        return jsonify({'invites': invite_list}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 3. DELETE/REVOKE INVITE (Manager/HR only)
@app.route('/api/invites/<int:invite_id>', methods=['DELETE'])
@manager_or_hr_required
def delete_invite(current_user, invite_id):
    try:
        invite = UserInvite.query.get(invite_id)
        
        if not invite:
            return jsonify({'error': 'Invite not found'}), 404
        
        if invite.is_used:
            return jsonify({'error': 'Cannot delete a used invite'}), 400
        
        db.session.delete(invite)
        db.session.commit()
        
        return jsonify({'message': 'Invite deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# 4. VALIDATE INVITE TOKEN (Public - no auth required)
@app.route('/api/invites/validate/<token>', methods=['GET'])
def validate_invite(token):
    try:
        invite = UserInvite.query.filter_by(token=token).first()
        
        if not invite:
            return jsonify({'valid': False, 'error': 'Invalid invite token'}), 404
        
        if not invite.is_valid():
            error_msg = 'Invite already used' if invite.is_used else 'Invite expired'
            return jsonify({'valid': False, 'error': error_msg}), 400
        
        return jsonify({
            'valid': True,
            'email': invite.email,
            'role': invite.role,
            'expires_at': invite.expires_at.isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 5. REGISTER WITH INVITE TOKEN (Public - no auth required)
@app.route('/api/register', methods=['POST'])
def register_with_invite():
    try:
        data = request.get_json()
        token = data.get('token')
        name = data.get('name')
        password = data.get('password')
        
        if not token or not name or not password:
            return jsonify({'error': 'Token, name and password are required'}), 400
        
        # Validate invite
        invite = UserInvite.query.filter_by(token=token).first()
        
        if not invite:
            return jsonify({'error': 'Invalid invite token'}), 404
        
        if not invite.is_valid():
            error_msg = 'Invite already used' if invite.is_used else 'Invite expired'
            return jsonify({'error': error_msg}), 400
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=invite.email).first()
        if existing_user:
            return jsonify({'error': 'User already exists'}), 400
        
        # Create new user
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        new_user = User(
            name=name,
            email=invite.email,
            password=hashed_password,
            role=invite.role
        )
        
        db.session.add(new_user)
        
        # Mark invite as used
        invite.mark_as_used()
        
        db.session.commit()
        
        # Generate JWT token for immediate login
        token_payload = {
            'user_id': new_user.id,
            'exp': datetime.utcnow() + timedelta(days=30)
        }
        auth_token = jwt.encode(token_payload, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'message': 'Registration successful',
            'token': auth_token,
            'user': {
                'id': new_user.id,
                'name': new_user.name,
                'email': new_user.email,
                'role': new_user.role
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
