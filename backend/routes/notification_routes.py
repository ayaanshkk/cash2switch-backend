from flask import Blueprint, jsonify, request, current_app
from datetime import datetime, timedelta
from sqlalchemy import text
from ..models import Notification_Master, Energy_Contract_Master, Client_Master, Project_Details, Employee_Master
from .auth_helpers import token_required
from ..db import SessionLocal
import logging

logger = logging.getLogger(__name__)
notification_bp = Blueprint('notification', __name__, url_prefix='/notifications')

# ✅ Throttle: only auto-generate once per hour per tenant (prevents pool exhaustion)
_last_auto_generate: dict = {}


def get_tenant_id_from_user(user):
    if hasattr(user, 'tenant_id') and user.tenant_id is not None:
        return user.tenant_id
    session = SessionLocal()
    try:
        employee = session.query(Employee_Master).filter_by(employee_id=user.employee_id).first()
        return employee.tenant_id if employee else None
    finally:
        session.close()


def create_assignment_notification(session, tenant_id: int, client_id: int, assigned_employee_id: int, assigned_by_name: str, display_id: int = None):
    """Create a notification when a record is assigned to an employee."""
    try:
        sql = text('''
            SELECT
                cm.client_company_name,
                cm.client_contact_name,
                COALESCE(cm.display_order, cm.client_id) AS display_id
            FROM "StreemLyne_MT"."Client_Master" cm
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

        session.add(Notification_Master(
            tenant_id=tenant_id,
            employee_id=assigned_employee_id,  # ✅ Always targeted — never None
            client_id=client_id,
            contract_id=None,
            notification_type='assignment',
            priority='normal',
            message=message,
            read=False,
            dismissed=False,
            created_at=datetime.utcnow()
        ))
        logger.info('Assignment notification created for employee_id=%s client_id=%s', assigned_employee_id, client_id)
    except Exception as e:
        logger.exception('create_assignment_notification failed: %s', e)


@notification_bp.route('/generate-contract-notifications', methods=['POST'])
@token_required
def generate_contract_notifications():
    """Manual trigger — generate contract expiry notifications for the current tenant."""
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        count = _generate_notifications_for_tenant(session, tenant_id)
        session.commit()

        return jsonify({
            'success': True,
            'message': f'{count} notifications created',
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
    """Get notifications for the current user only."""
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employee_id = getattr(request.current_user, 'employee_id', None)

        # ✅ Throttle: only auto-generate once per hour per tenant
        now = datetime.utcnow()
        last_run = _last_auto_generate.get(tenant_id)
        if not last_run or (now - last_run).total_seconds() > 3600:
            try:
                _generate_notifications_for_tenant(session, tenant_id)
                session.commit()
                _last_auto_generate[tenant_id] = now
            except Exception as gen_err:
                session.rollback()
                logger.warning('Auto-generate notifications failed (non-fatal): %s', gen_err)

        # ✅ Everyone sees only their own notifications — no admin catch-all
        notifications = session.execute(text('''
            SELECT * FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tid
              AND employee_id = :eid
              AND dismissed = false
            ORDER BY
                CASE WHEN priority = 'urgent' THEN 0 ELSE 1 END,
                created_at DESC
        '''), {'tid': tenant_id, 'eid': employee_id}).mappings().all()

        def _serial(v):
            if v is None: return None
            if hasattr(v, 'isoformat'): return v.isoformat()
            return v

        notifications_data = [{
            'id': str(r['notification_id']),
            'client_id': r['client_id'],
            'contract_id': r['contract_id'],
            'message': r['message'],
            'priority': r['priority'],
            'notification_type': r['notification_type'],
            'read': r['read'],
            'dismissed': r['dismissed'],
            'created_at': _serial(r['created_at']),
        } for r in notifications]

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


def _generate_notifications_for_tenant(session, tenant_id: int) -> int:
    """
    Core logic: generate contract expiry notifications for a tenant.
    Only notifies the assigned employee — no admin broadcast.
    Returns number of notifications created.
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
          AND cm.is_deleted = false
          AND cm.is_archived = false
          AND ecm.contract_end_date BETWEEN :today AND :end_date
          AND ecm.service_id = 1
        ORDER BY ecm.contract_end_date ASC
    ''')

    contracts = session.execute(sql, {
        'tenant_id': tenant_id,
        'today': today,
        'end_date': date_60,
    }).mappings().all()

    count = 0

    for contract in contracts:
        assigned_employee_id = contract.get('assigned_employee_id')
        if not assigned_employee_id:
            continue  # ✅ Skip unassigned contracts — no broadcast

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

        # ✅ Dedup check per employee — don't spam the same notification
        existing = session.execute(text('''
            SELECT 1 FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tid
              AND contract_id = :cid
              AND employee_id = :eid
              AND notification_type = :ntype
              AND dismissed = false
            LIMIT 1
        '''), {
            'tid': tenant_id,
            'cid': contract['contract_id'],
            'eid': assigned_employee_id,
            'ntype': ntype,
        }).first()

        if existing:
            continue

        display_id = contract.get('display_id') or contract['client_id']
        message = (
            f"{urgency_text}: Contract expiring in {days} day{'s' if days != 1 else ''}\n"
            f"📋 Customer: {contract['client_company_name']}\n"
            f"🆔 ID: {display_id}\n"
            f"📅 Expiry: {end_date.strftime('%d/%m/%Y')}\n"
            f"📞 Phone: {contract['client_phone'] or '—'}"
        )
        if contract.get('mpan_number'):
            message += f"\n🔌 MPAN: {contract['mpan_number']}"

        # ✅ Only notify the assigned employee — no admin copy with employee_id=None
        session.add(Notification_Master(
            tenant_id=tenant_id,
            employee_id=assigned_employee_id,
            client_id=contract['client_id'],
            contract_id=contract['contract_id'],
            notification_type=ntype,
            priority='urgent',
            message=message,
            read=False,
            dismissed=False,
            created_at=datetime.utcnow()
        ))
        count += 1

    return count


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

        session.query(Notification_Master).filter(
            Notification_Master.tenant_id == tenant_id,
            Notification_Master.employee_id == employee_id
        ).update({'read': True, 'read_at': datetime.utcnow()})
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

        # ✅ Only clear the current user's own notifications
        session.query(Notification_Master).filter(
            Notification_Master.tenant_id == tenant_id,
            Notification_Master.employee_id == employee_id
        ).delete()
        session.commit()
        return jsonify({'message': 'All notifications cleared'}), 200
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()