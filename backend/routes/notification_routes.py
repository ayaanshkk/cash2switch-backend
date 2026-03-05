from flask import Blueprint, jsonify, request, current_app
from datetime import datetime, timedelta
from sqlalchemy import text, and_, or_
from ..models import (
    Notification_Master, Energy_Contract_Master, Client_Master,
    Project_Details, Employee_Master, Opportunity_Details
)
from .auth_helpers import token_required
from ..db import SessionLocal
import logging

logger = logging.getLogger(__name__)
notification_bp = Blueprint('notification', __name__, url_prefix='/notifications')


def get_tenant_id_from_user(user):
    """Get tenant_id from authenticated user"""
    if hasattr(user, 'tenant_id') and user.tenant_id is not None:
        return user.tenant_id
    session = SessionLocal()
    try:
        employee = session.query(Employee_Master).filter_by(employee_id=user.employee_id).first()
        return employee.tenant_id if employee else None
    finally:
        session.close()


@notification_bp.route('/generate-contract-notifications', methods=['POST'])
@token_required
def generate_contract_notifications():
    """
    Generate notifications for contracts expiring in 30-60 and 61-90 days
    Called by: Daily cron job or manual trigger by admin
    """
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        today = datetime.utcnow().date()
        date_30_days = today + timedelta(days=30)
        date_60_days = today + timedelta(days=60)
        date_90_days = today + timedelta(days=90)
        
        # Find contracts expiring in 30-90 days
        sql = text('''
            SELECT 
                ecm.energy_contract_master_id as contract_id,
                ecm.contract_end_date,
                ecm.mpan_number,
                cm.client_id,
                cm.client_company_name,
                cm.client_phone,
                od.opportunity_owner_employee_id as assigned_employee_id,
                em.employee_name as assigned_to
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
            JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Opportunity_Details" od ON cm.client_id = od.client_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od.opportunity_owner_employee_id = em.employee_id
            WHERE cm.tenant_id = :tenant_id
            AND ecm.contract_end_date BETWEEN :start_date AND :end_date
            AND ecm.service_id = 1
            ORDER BY ecm.contract_end_date ASC
        ''')
        
        contracts = session.execute(sql, {
            'tenant_id': tenant_id,
            'start_date': date_30_days,
            'end_date': date_90_days
        }).mappings().all()
        
        notifications_created = 0
        
        for contract in contracts:
            end_date = contract['contract_end_date']
            days_until_expiry = (end_date - today).days
            
            # Determine notification type and priority
            if 30 <= days_until_expiry <= 60:
                notification_type = 'contract_expiry_30_60'
                priority = 'urgent'
                urgency_text = '🚨 URGENT'
                days_range = '30-60 days'
            elif 61 <= days_until_expiry <= 90:
                notification_type = 'contract_expiry_61_90'
                priority = 'urgent'
                urgency_text = '⚠️ URGENT'
                days_range = '61-90 days'
            else:
                continue
            
            # Check if notification already exists for this contract
            existing = session.query(Notification_Master).filter_by(
                tenant_id=tenant_id,
                contract_id=contract['contract_id'],
                notification_type=notification_type,
                dismissed=False
            ).first()
            
            if existing:
                continue  # Skip if already notified
            
            # Create message
            message = f"{urgency_text}: Contract expiring in {days_until_expiry} days ({days_range})\n"
            message += f"📋 Customer: {contract['client_company_name']}\n"
            message += f"📅 Expiry Date: {end_date.strftime('%d/%m/%Y')}\n"
            message += f"📞 Phone: {contract['client_phone']}\n"
            if contract.get('mpan_number'):
                message += f"🔌 MPAN: {contract['mpan_number']}"
            
            # Create notification for assigned salesperson
            assigned_employee_id = contract.get('assigned_employee_id')
            
            if assigned_employee_id:
                notification = Notification_Master(
                    tenant_id=tenant_id,
                    employee_id=assigned_employee_id,
                    client_id=contract['client_id'],
                    contract_id=contract['contract_id'],
                    notification_type=notification_type,
                    priority=priority,
                    message=message,
                    read=False,
                    dismissed=False,
                    created_at=datetime.utcnow()
                )
                session.add(notification)
                notifications_created += 1
            
            # Also create notification for Platform Admin (employee_id = NULL)
            admin_notification = Notification_Master(
                tenant_id=tenant_id,
                employee_id=None,  # Admin sees all
                client_id=contract['client_id'],
                contract_id=contract['contract_id'],
                notification_type=notification_type,
                priority=priority,
                message=message,
                read=False,
                dismissed=False,
                created_at=datetime.utcnow()
            )
            session.add(admin_notification)
            notifications_created += 1
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{notifications_created} notifications created',
            'contracts_expiring_soon': len(contracts)
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error generating notifications: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/production', methods=['GET'])
@token_required
def get_production_notifications():
    """Get notifications for current user (production endpoint)"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employee_id = request.current_user.employee_id
        
        # Get user role from JWT
        user_role = getattr(request.current_user, 'role', None)
        is_admin = user_role and 'admin' in user_role.lower()
        
        # Build query based on role
        if is_admin:
            # Admin sees ALL notifications (employee_id IS NULL OR assigned to anyone)
            notifications = session.query(Notification_Master).filter(
                and_(
                    Notification_Master.tenant_id == tenant_id,
                    Notification_Master.dismissed == False
                )
            ).order_by(
                Notification_Master.priority.desc(),
                Notification_Master.created_at.desc()
            ).all()
        else:
            # Salesperson sees only their assigned notifications
            notifications = session.query(Notification_Master).filter(
                and_(
                    Notification_Master.tenant_id == tenant_id,
                    Notification_Master.employee_id == employee_id,
                    Notification_Master.dismissed == False
                )
            ).order_by(
                Notification_Master.priority.desc(),
                Notification_Master.created_at.desc()
            ).all()
        
        # Format notifications
        notifications_data = []
        for n in notifications:
            notifications_data.append({
                'id': str(n.notification_id),
                'client_id': n.client_id,
                'contract_id': n.contract_id,
                'message': n.message,
                'priority': n.priority,
                'notification_type': n.notification_type,
                'read': n.read,
                'dismissed': n.dismissed,
                'created_at': n.created_at.isoformat() if n.created_at else None,
            })
        
        unread_count = sum(1 for n in notifications_data if not n['read'])
        
        return jsonify({
            'notifications': notifications_data,
            'unread_count': unread_count
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/mark-read/<int:notification_id>', methods=['PATCH'])
@token_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    session = SessionLocal()
    
    try:
        notification = session.query(Notification_Master).filter_by(
            notification_id=notification_id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        notification.read = True
        notification.read_at = datetime.utcnow()
        session.commit()
        
        return jsonify({'message': 'Notification marked as read'}), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error marking notification as read: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/mark-all-read', methods=['PATCH'])
@token_required
def mark_all_notifications_read():
    """Mark all notifications as read for current user"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employee_id = request.current_user.employee_id
        
        user_role = getattr(request.current_user, 'role', None)
        is_admin = user_role and 'admin' in user_role.lower()
        
        if is_admin:
            # Mark all tenant notifications as read
            session.query(Notification_Master).filter(
                Notification_Master.tenant_id == tenant_id
            ).update({'read': True, 'read_at': datetime.utcnow()})
        else:
            # Mark only user's notifications as read
            session.query(Notification_Master).filter(
                and_(
                    Notification_Master.tenant_id == tenant_id,
                    Notification_Master.employee_id == employee_id
                )
            ).update({'read': True, 'read_at': datetime.utcnow()})
        
        session.commit()
        
        return jsonify({'message': 'All notifications marked as read'}), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error marking all notifications as read: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/dismiss/<int:notification_id>', methods=['PATCH'])
@token_required
def dismiss_notification(notification_id):
    """Dismiss a notification from sidebar"""
    session = SessionLocal()
    
    try:
        notification = session.query(Notification_Master).filter_by(
            notification_id=notification_id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        notification.dismissed = True
        session.commit()
        
        return jsonify({'message': 'Notification dismissed'}), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error dismissing notification: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/delete/<int:notification_id>', methods=['DELETE'])
@token_required
def delete_notification(notification_id):
    """Permanently delete a notification"""
    session = SessionLocal()
    
    try:
        notification = session.query(Notification_Master).filter_by(
            notification_id=notification_id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        session.delete(notification)
        session.commit()
        
        return jsonify({'message': 'Notification deleted'}), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting notification: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/clear-all', methods=['DELETE'])
@token_required
def clear_all_notifications():
    """Clear all notifications for current user"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employee_id = request.current_user.employee_id
        
        user_role = getattr(request.current_user, 'role', None)
        is_admin = user_role and 'admin' in user_role.lower()
        
        if is_admin:
            session.query(Notification_Master).filter(
                Notification_Master.tenant_id == tenant_id
            ).delete()
        else:
            session.query(Notification_Master).filter(
                and_(
                    Notification_Master.tenant_id == tenant_id,
                    Notification_Master.employee_id == employee_id
                )
            ).delete()
        
        session.commit()
        
        return jsonify({'message': 'All notifications cleared'}), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error clearing notifications: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()