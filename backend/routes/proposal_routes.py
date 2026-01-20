from flask import Blueprint, request, jsonify, current_app
from ..db import SessionLocal
from ..models import Proposal
from .auth_helpers import token_required
from datetime import datetime
import json

proposal_bp = Blueprint('proposals', __name__)


def get_current_user_info():
    """Get current user's ID and name"""
    if hasattr(request, 'current_user'):
        return {
            'id': getattr(request.current_user, 'id', None),
            'name': getattr(request.current_user, 'full_name', 'System')
        }
    return {'id': None, 'name': 'System'}


@proposal_bp.route('/proposals', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_proposals():
    """GET all proposals or POST to create a new proposal"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            user_info = get_current_user_info()
            
            # Validate required fields
            if not data.get('customer_id'):
                return jsonify({'error': 'Customer ID is required'}), 400
            
            if not data.get('items') or len(data.get('items', [])) == 0:
                return jsonify({'error': 'At least one item is required'}), 400
            
            # Create new proposal
            proposal = Proposal(
                # Customer Information
                customer_id=data.get('customer_id'),
                customer_name=data.get('customer_name', ''),
                customer_designation=data.get('customer_designation'),
                customer_company=data.get('customer_company'),
                customer_address=data.get('customer_address'),
                customer_mobile=data.get('customer_mobile'),
                customer_email=data.get('customer_email'),
                
                # Proposal Details
                quotation_number=data.get('quotation_number'),
                date=datetime.fromisoformat(data['date']) if data.get('date') else datetime.utcnow(),
                ifo_number=data.get('ifo_number'),
                mode_of_enquiry=data.get('mode_of_enquiry', 'Email'),
                payment_terms=data.get('payment_terms'),
                
                # Items
                items=data.get('items', []),
                
                # Financial Details
                sub_total=float(data.get('sub_total', 0.0)),
                discount_percentage=float(data.get('discount_percentage', 0.0)),
                discount_amount=float(data.get('discount_amount', 0.0)),
                igst_percentage=float(data.get('igst_percentage', 18.0)),
                igst_amount=float(data.get('igst_amount', 0.0)),
                grand_total=float(data.get('grand_total', 0.0)),
                
                # Bank Details
                bank_name=data.get('bank_name'),
                branch_name=data.get('branch_name'),
                account_number=data.get('account_number'),
                ifsc_code=data.get('ifsc_code'),
                gst_number=data.get('gst_number'),
                
                # Terms & Conditions
                valid_for_days=int(data.get('valid_for_days', 30)),
                terms_conditions=data.get('terms_conditions', []),
                notes=data.get('notes'),
                
                # Status
                status=data.get('status', 'Draft'),
                
                # Audit
                created_by=user_info['id'],
                created_by_name=user_info['name'],
            )
            
            session.add(proposal)
            session.commit()
            
            current_app.logger.info(f"✅ Proposal created: {proposal.quotation_number}")
            
            return jsonify(proposal.to_dict()), 201

        # GET all proposals
        query = session.query(Proposal)
        
        # Filter by customer_id if provided
        customer_id = request.args.get('customer_id')
        if customer_id:
            query = query.filter_by(customer_id=customer_id)
        
        # Filter by status if provided
        status = request.args.get('status')
        if status:
            query = query.filter_by(status=status)
        
        # Order by created date (newest first)
        proposals = query.order_by(Proposal.created_at.desc()).all()
        
        # Convert to dict
        result = [proposal.to_dict() for proposal in proposals]
        
        return jsonify(result), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error in /proposals: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@proposal_bp.route('/proposals/<int:proposal_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_proposal(proposal_id):
    """GET, UPDATE, or DELETE a single proposal"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        proposal = session.query(Proposal).filter_by(id=proposal_id).first()
        
        if not proposal:
            return jsonify({'error': 'Proposal not found'}), 404
        
        if request.method == 'GET':
            return jsonify(proposal.to_dict()), 200
        
        elif request.method == 'PUT':
            # Update proposal
            data = request.json
            user_info = get_current_user_info()
            
            # Update customer information
            if 'customer_id' in data:
                proposal.customer_id = data['customer_id']
            if 'customer_name' in data:
                proposal.customer_name = data['customer_name']
            if 'customer_designation' in data:
                proposal.customer_designation = data['customer_designation']
            if 'customer_company' in data:
                proposal.customer_company = data['customer_company']
            if 'customer_address' in data:
                proposal.customer_address = data['customer_address']
            if 'customer_mobile' in data:
                proposal.customer_mobile = data['customer_mobile']
            if 'customer_email' in data:
                proposal.customer_email = data['customer_email']
            
            # Update proposal details
            if 'quotation_number' in data:
                proposal.quotation_number = data['quotation_number']
            if 'date' in data:
                proposal.date = datetime.fromisoformat(data['date']) if data['date'] else datetime.utcnow()
            if 'ifo_number' in data:
                proposal.ifo_number = data['ifo_number']
            if 'mode_of_enquiry' in data:
                proposal.mode_of_enquiry = data['mode_of_enquiry']
            if 'payment_terms' in data:
                proposal.payment_terms = data['payment_terms']
            
            # Update items
            if 'items' in data:
                proposal.items = data['items']
            
            # Update financial details
            if 'sub_total' in data:
                proposal.sub_total = float(data['sub_total'])
            if 'discount_percentage' in data:
                proposal.discount_percentage = float(data['discount_percentage'])
            if 'discount_amount' in data:
                proposal.discount_amount = float(data['discount_amount'])
            if 'igst_percentage' in data:
                proposal.igst_percentage = float(data['igst_percentage'])
            if 'igst_amount' in data:
                proposal.igst_amount = float(data['igst_amount'])
            if 'grand_total' in data:
                proposal.grand_total = float(data['grand_total'])
            
            # Update bank details
            if 'bank_name' in data:
                proposal.bank_name = data['bank_name']
            if 'branch_name' in data:
                proposal.branch_name = data['branch_name']
            if 'account_number' in data:
                proposal.account_number = data['account_number']
            if 'ifsc_code' in data:
                proposal.ifsc_code = data['ifsc_code']
            if 'gst_number' in data:
                proposal.gst_number = data['gst_number']
            
            # Update terms & conditions
            if 'valid_for_days' in data:
                proposal.valid_for_days = int(data['valid_for_days'])
            if 'terms_conditions' in data:
                proposal.terms_conditions = data['terms_conditions']
            if 'notes' in data:
                proposal.notes = data['notes']
            
            # Update status
            if 'status' in data:
                proposal.status = data['status']
            
            # Update audit fields
            proposal.updated_by = user_info['id']
            proposal.updated_by_name = user_info['name']
            proposal.updated_at = datetime.utcnow()
            
            session.commit()
            
            current_app.logger.info(f"✅ Proposal updated: {proposal.quotation_number}")
            
            return jsonify(proposal.to_dict()), 200
        
        elif request.method == 'DELETE':
            # Delete proposal
            quotation_number = proposal.quotation_number
            session.delete(proposal)
            session.commit()
            
            current_app.logger.info(f"✅ Deleted proposal: {quotation_number}")
            
            return jsonify({
                'success': True,
                'message': 'Proposal deleted successfully'
            }), 200
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error handling proposal {proposal_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@proposal_bp.route('/proposals/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_proposal_stats():
    """Get proposal statistics"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Count by status
        total_count = session.query(Proposal).count()
        draft_count = session.query(Proposal).filter_by(status='Draft').count()
        sent_count = session.query(Proposal).filter_by(status='Sent').count()
        pending_count = session.query(Proposal).filter_by(status='Pending').count()
        approved_count = session.query(Proposal).filter_by(status='Approved').count()
        rejected_count = session.query(Proposal).filter_by(status='Rejected').count()
        cancelled_count = session.query(Proposal).filter_by(status='Cancelled').count()
        
        # Total value
        from sqlalchemy import func
        total_value = session.query(func.sum(Proposal.grand_total)).scalar() or 0
        
        return jsonify({
            'total_proposals': total_count,
            'by_status': {
                'draft': draft_count,
                'sent': sent_count,
                'pending': pending_count,
                'approved': approved_count,
                'rejected': rejected_count,
                'cancelled': cancelled_count,
            },
            'total_value': float(total_value)
        }), 200
    
    except Exception as e:
        current_app.logger.error(f"❌ Error fetching stats: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@proposal_bp.route('/proposals/search', methods=['GET', 'OPTIONS'])
@token_required
def search_proposals():
    """Search proposals by quotation number or customer name"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        search_term = request.args.get('q', '').strip()
        
        if not search_term:
            return jsonify([]), 200
        
        # Search in quotation_number and customer_name
        proposals = session.query(Proposal).filter(
            (Proposal.quotation_number.ilike(f'%{search_term}%')) |
            (Proposal.customer_name.ilike(f'%{search_term}%'))
        ).order_by(Proposal.created_at.desc()).limit(20).all()
        
        result = [proposal.to_dict() for proposal in proposals]
        
        return jsonify(result), 200
    
    except Exception as e:
        current_app.logger.error(f"❌ Error searching proposals: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()