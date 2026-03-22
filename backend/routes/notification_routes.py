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


def create_assignment_notification(session, tenant_id: int, client_id: int, assigned_employee_id: int, assigned_by_name: str, display_id: int = None):
    """
    Helper: create a notification when a record is assigned to an employee.
    Called from energy_renewals_routes.py whenever assigned_to_id changes.
    """
    try:
        # Get client info
        sql = text('''
            SELECT
                cm.client_company_name,
                cm.client_contact_name,
                COALESCE(ecr.display_order, ecr.display_id, cm.client_id) AS display_id
            FROM "StreemLyne_MT"."Client_Master" cm
            LEFT JOIN (
                SELECT client_id,
                       ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY client_id) AS display_order,
                       client_id AS display_id
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
            ) ecr ON ecr.client_id = cm.client_id
            WHERE cm.client_id = :client_id
            LIMIT 1
        ''')
        result = session.execute(sql, {'client_id': client_id, 'tenant_id': tenant_id}).mappings().first()
        if not result:
            return

        name = result['client_company_name'] or result['client_contact_name'] or f'Client #{client_id}'
        did = display_id or result['display_id'] or client_id

        message = (
            f"📋 New record assigned to you\n"
            f"👤 Customer: {name}\n"
            f"🆔 ID: {did}\n"
            f"👤 Assigned by: {assigned_by_name}"
        )

        notification = Notification_Master(
            tenant_id=tenant_id,
            employee_id=assigned_employee_id,
            client_id=client_id,
            contract_id=None,
            notification_type='assignment',
            priority='normal',
            message=message,
            read=False,
            dismissed=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        # Caller is responsible for session.commit()
        logger.info('Assignment notification created for employee_id=%s client_id=%s', assigned_employee_id, client_id)
    except Exception as e:
        logger.exception('create_assignment_notification failed: %s', e)


@notification_bp.route('/generate-contract-notifications', methods=['POST'])
@token_required
def generate_contract_notifications():
    """
    Generate notifications for contracts expiring in 0-30 days and 31-60 days.
    Called by: Daily cron job or manual trigger by admin.
    Clears stale notifications for contracts no longer in range before inserting new ones.
    """
    session = SessionLocal()

    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        today = datetime.utcnow().date()
        date_30 = today + timedelta(days=30)
        date_60 = today + timedelta(days=60)

        # Find contracts expiring within 60 days (two buckets: 0-30, 31-60)
        sql = text('''
            SELECT
                ecm.energy_contract_master_id AS contract_id,
                ecm.contract_end_date,
                ecm.mpan_number,
                cm.client_id,
                cm.client_company_name,
                cm.client_phone,
                COALESCE(ec.display_order, cm.client_id) AS display_id,
                ec.assigned_to_id       AS assigned_employee_id,
                em.employee_name        AS assigned_to
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            JOIN "StreemLyne_MT"."Project_Details" pd
                ON ecm.project_id = pd.project_id
            JOIN "StreemLyne_MT"."Client_Master" cm
                ON pd.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Clients_Raw" ec
                ON ec.client_id = cm.client_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em
                ON ec.assigned_to_id = em.employee_id
            WHERE cm.tenant_id = :tenant_id
              AND ecm.contract_end_date BETWEEN :today AND :end_date
              AND ecm.service_id = 1
            ORDER BY ecm.contract_end_date ASC
        ''')

        contracts = session.execute(sql, {
            'tenant_id': tenant_id,
            'today': today,
            'end_date': date_60,
        }).mappings().all()

        notifications_created = 0

        for contract in contracts:
            end_date = contract['contract_end_date']
            days_until_expiry = (end_date - today).days

            # Bucket 1: 0-30 days (most urgent)
            # Bucket 2: 31-60 days
            if days_until_expiry <= 30:
                notification_type = 'contract_expiry_0_30'
                priority = 'urgent'
                urgency_text = '🚨 URGENT'
                days_range = f'{days_until_expiry} day{"s" if days_until_expiry != 1 else ""}'
            elif days_until_expiry <= 60:
                notification_type = 'contract_expiry_31_60'
                priority = 'urgent'
                urgency_text = '⚠️ ACTION NEEDED'
                days_range = f'{days_until_expiry} days'
            else:
                continue

            # Skip if this exact notification already exists (un-dismissed)
            existing = session.execute(text('''
                SELECT 1 FROM "StreemLyne_MT"."Notification_Master"
                WHERE tenant_id = :tid
                  AND contract_id = :cid
                  AND notification_type = :ntype
                  AND dismissed = false
                LIMIT 1
            '''), {
                'tid': tenant_id,
                'cid': contract['contract_id'],
                'ntype': notification_type,
            }).first()

            if existing:
                continue

            display_id = contract.get('display_id') or contract['client_id']

            message = (
                f"{urgency_text}: Contract expiring in {days_range}\n"
                f"📋 Customer: {contract['client_company_name']}\n"
                f"🆔 ID: {display_id}\n"
                f"📅 Expiry: {end_date.strftime('%d/%m/%Y')}\n"
                f"📞 Phone: {contract['client_phone'] or '—'}"
            )
            if contract.get('mpan_number'):
                message += f"\n🔌 MPAN: {contract['mpan_number']}"

            assigned_employee_id = contract.get('assigned_employee_id')

            # Notify assigned salesperson
            if assigned_employee_id:
                session.add(Notification_Master(
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
                ))
                notifications_created += 1

            # Also notify admins (employee_id=None means all admins see it)
            session.add(Notification_Master(
                tenant_id=tenant_id,
                employee_id=None,
                client_id=contract['client_id'],
                contract_id=contract['contract_id'],
                notification_type=notification_type,
                priority=priority,
                message=message,
                read=False,
                dismissed=False,
                created_at=datetime.utcnow()
            ))
            notifications_created += 1

        session.commit()

        return jsonify({
            'success': True,
            'message': f'{notifications_created} notifications created',
            'contracts_checked': len(contracts),
        }), 200

    except Exception as e:
        session.rollback()
        logger.exception('Error generating contract notifications: %s', e)
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
        employee_id = getattr(request.current_user, 'employee_id', None)
        user_role = getattr(request.current_user, 'role', None) or ''
        is_admin = 'admin' in user_role.lower()

        # Auto-generate contract notifications on every fetch (cheap dedup check inside)
        try:
            _auto_generate_contract_notifications(session, tenant_id)
            session.commit()
        except Exception as gen_err:
            session.rollback()
            logger.warning('Auto-generate notifications failed (non-fatal): %s', gen_err)

        if is_admin:
            notifications = session.execute(text('''
                SELECT * FROM "StreemLyne_MT"."Notification_Master"
                WHERE tenant_id = :tid AND dismissed = false
                ORDER BY
                    CASE WHEN priority = 'urgent' THEN 0 ELSE 1 END,
                    created_at DESC
            '''), {'tid': tenant_id}).mappings().all()
        else:
            notifications = session.execute(text('''
                SELECT * FROM "StreemLyne_MT"."Notification_Master"
                WHERE tenant_id = :tid
                  AND (employee_id = :eid OR employee_id IS NULL)
                  AND dismissed = false
                ORDER BY
                    CASE WHEN priority = 'urgent' THEN 0 ELSE 1 END,
                    created_at DESC
            '''), {'tid': tenant_id, 'eid': employee_id}).mappings().all()

        def _serial(v):
            if v is None:
                return None
            if hasattr(v, 'isoformat'):
                return v.isoformat()
            return v

        notifications_data = [
            {
                'id': str(r['notification_id']),
                'client_id': r['client_id'],
                'contract_id': r['contract_id'],
                'message': r['message'],
                'priority': r['priority'],
                'notification_type': r['notification_type'],
                'read': r['read'],
                'dismissed': r['dismissed'],
                'created_at': _serial(r['created_at']),
            }
            for r in notifications
        ]

        unread_count = sum(1 for n in notifications_data if not n['read'])

        return jsonify({
            'notifications': notifications_data,
            'unread_count': unread_count,
        }), 200

    except Exception as e:
        logger.exception('Error fetching notifications: %s', e)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def _auto_generate_contract_notifications(session, tenant_id: int):
    """
    Internal helper — runs the same dedup-safe contract notification logic
    without going through HTTP. Called from get_production_notifications.
    """
    today = datetime.utcnow().date()
    date_60 = today + timedelta(days=60)

    sql = text('''
        SELECT
            ecm.energy_contract_master_id AS contract_id,
            ecm.contract_end_date,
            ecm.mpan_number,
            cm.client_id,
            cm.client_company_name,
            cm.client_phone,
            COALESCE(cm.display_order, cm.client_id) AS display_id,
            pd.assigned_employee_id AS assigned_employee_id
        FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
        JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
        JOIN "StreemLyne_MT"."Client_Master" cm ON pd.client_id = cm.client_id
        WHERE cm.tenant_id = :tenant_id
        AND ecm.contract_end_date BETWEEN :today AND :end_date
        AND ecm.service_id = 1
        ORDER BY ecm.contract_end_date ASC
    ''')

    contracts = session.execute(sql, {
        'tenant_id': tenant_id,
        'today': today,
        'end_date': date_60,
    }).mappings().all()

    for contract in contracts:
        end_date = contract['contract_end_date']
        days = (end_date - today).days

        if days <= 30:
            ntype = 'contract_expiry_0_30'
            urgency_text = '🚨 URGENT'
        elif days <= 60:
            ntype = 'contract_expiry_31_60'
            urgency_text = '⚠️ ACTION NEEDED'
        else:
            continue

        existing = session.execute(text('''
            SELECT 1 FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tid AND contract_id = :cid
              AND notification_type = :ntype AND dismissed = false
            LIMIT 1
        '''), {'tid': tenant_id, 'cid': contract['contract_id'], 'ntype': ntype}).first()

        if existing:
            continue

        display_id = contract.get('display_id') or contract['client_id']
        message = (
            f"{urgency_text}: Contract expiring in {days} day{'s' if days != 1 else ''}\n"
            f" Customer: {contract['client_company_name']}\n"
            f" ID: {display_id}\n"
            f" Expiry: {end_date.strftime('%d/%m/%Y')}\n"
            f" Phone: {contract['client_phone'] or '—'}"
        )
        if contract.get('mpan_number'):
            message += f"\n🔌 MPAN: {contract['mpan_number']}"

        if contract.get('assigned_employee_id'):
            session.add(Notification_Master(
                tenant_id=tenant_id,
                employee_id=contract['assigned_employee_id'],
                client_id=contract['client_id'],
                contract_id=contract['contract_id'],
                notification_type=ntype,
                priority='urgent',
                message=message,
                read=False, dismissed=False,
                created_at=datetime.utcnow()
            ))

        # Admin copy
        session.add(Notification_Master(
            tenant_id=tenant_id,
            employee_id=None,
            client_id=contract['client_id'],
            contract_id=contract['contract_id'],
            notification_type=ntype,
            priority='urgent',
            message=message,
            read=False, dismissed=False,
            created_at=datetime.utcnow()
        ))


@notification_bp.route('/mark-read/<int:notification_id>', methods=['PATCH'])
@token_required
def mark_notification_read(notification_id):
    session = SessionLocal()
    try:
        n = session.query(Notification_Master).filter_by(notification_id=notification_id).first()
        if not n:
            return jsonify({'error': 'Notification not found'}), 404
        n.read = True
        n.read_at = datetime.utcnow()
        session.commit()
        return jsonify({'message': 'Notification marked as read'}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/mark-all-read', methods=['PATCH'])
@token_required
def mark_all_notifications_read():
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employee_id = getattr(request.current_user, 'employee_id', None)
        is_admin = 'admin' in (getattr(request.current_user, 'role', '') or '').lower()

        q = session.query(Notification_Master).filter(Notification_Master.tenant_id == tenant_id)
        if not is_admin:
            q = q.filter(Notification_Master.employee_id == employee_id)
        q.update({'read': True, 'read_at': datetime.utcnow()})
        session.commit()
        return jsonify({'message': 'All notifications marked as read'}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/dismiss/<int:notification_id>', methods=['PATCH'])
@token_required
def dismiss_notification(notification_id):
    session = SessionLocal()
    try:
        n = session.query(Notification_Master).filter_by(notification_id=notification_id).first()
        if not n:
            return jsonify({'error': 'Notification not found'}), 404
        n.dismissed = True
        session.commit()
        return jsonify({'message': 'Notification dismissed'}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/delete/<int:notification_id>', methods=['DELETE'])
@token_required
def delete_notification(notification_id):
    session = SessionLocal()
    try:
        n = session.query(Notification_Master).filter_by(notification_id=notification_id).first()
        if not n:
            return jsonify({'error': 'Notification not found'}), 404
        session.delete(n)
        session.commit()
        return jsonify({'message': 'Notification deleted'}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/clear-all', methods=['DELETE'])
@token_required
def clear_all_notifications():
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employee_id = getattr(request.current_user, 'employee_id', None)
        is_admin = 'admin' in (getattr(request.current_user, 'role', '') or '').lower()

        q = session.query(Notification_Master).filter(Notification_Master.tenant_id == tenant_id)
        if not is_admin:
            q = q.filter(Notification_Master.employee_id == employee_id)
        q.delete()
        session.commit()
        return jsonify({'message': 'All notifications cleared'}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()