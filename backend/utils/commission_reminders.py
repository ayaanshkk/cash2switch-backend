from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text

from backend.models import (
    Client_Master,
    Commission_Payment,
    Employee_Master,
    Notification_Master,
    Supplier_Master,
)


FOLLOW_UP_STATUSES = ('Due', 'Partially Paid', 'Chasing Supplier')
NOTIFICATION_TYPE = 'commission_payment_follow_up'


@dataclass
class CommissionReminderResult:
    scheduled_to_pending: int = 0
    pending_to_due: int = 0
    follow_ups_checked: int = 0
    notifications_created: int = 0
    notifications_skipped_existing: int = 0
    follow_ups_rescheduled: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _tenant_filter(query, tenant_id: Optional[str]):
    if tenant_id in (None, ''):
        return query
    return query.filter(Commission_Payment.tenant_id == str(tenant_id))


def _notification_tenant_id(payment: Commission_Payment):
    if payment.tenant_id is None:
        return None
    return str(payment.tenant_id)


def _next_follow_up_date(payment: Commission_Payment, today: date) -> date:
    reminder_number = payment.follow_up_count or 0
    return today + timedelta(days=30 if reminder_number == 1 else 60)


def _payment_display_name(session, payment: Commission_Payment) -> str:
    client = None
    if payment.client_id:
        client = session.query(Client_Master).filter(Client_Master.client_id == payment.client_id).first()
    if client:
        return client.client_company_name or client.client_contact_name or f'Client #{payment.client_id}'
    return f'Client #{payment.client_id}' if payment.client_id else 'Unknown customer'


def _supplier_name(session, payment: Commission_Payment) -> str:
    if not payment.supplier_id:
        return 'Unknown supplier'
    supplier = session.query(Supplier_Master).filter(Supplier_Master.supplier_id == payment.supplier_id).first()
    return supplier.supplier_company_name if supplier and supplier.supplier_company_name else f'Supplier #{payment.supplier_id}'


def _employee_exists(session, employee_id: int) -> bool:
    if not employee_id:
        return False
    return session.query(Employee_Master.employee_id).filter(Employee_Master.employee_id == employee_id).first() is not None


def _notification_exists(session, payment: Commission_Payment, employee_id: int) -> bool:
    payment_marker = f'Payment ID: {payment.id}'
    existing = session.execute(text('''
        SELECT 1
        FROM "StreemLyne_MT"."Notification_Master"
        WHERE tenant_id = :tenant_id
          AND employee_id = :employee_id
          AND notification_type = :notification_type
          AND dismissed = false
          AND message LIKE :message_marker
        LIMIT 1
    '''), {
        'tenant_id': _notification_tenant_id(payment),
        'employee_id': employee_id,
        'notification_type': NOTIFICATION_TYPE,
        'message_marker': f'%{payment_marker}%',
    }).first()
    return existing is not None


def _create_follow_up_notification(session, payment: Commission_Payment, today: date) -> bool:
    employee_id = payment.employee_id
    if not employee_id or not _employee_exists(session, employee_id):
        return False

    if _notification_exists(session, payment, employee_id):
        return False

    customer_name = _payment_display_name(session, payment)
    supplier_name = _supplier_name(session, payment)
    due_date = payment.due_date.strftime('%d/%m/%Y') if payment.due_date else 'Not set'
    outstanding = payment.outstanding_amount or 0

    message = (
        "Commission payment follow-up due\n"
        f"Customer: {customer_name}\n"
        f"Supplier: {supplier_name}\n"
        f"Due date: {due_date}\n"
        f"Outstanding: £{outstanding}\n"
        f"Status: {payment.status}\n"
        f"Payment ID: {payment.id}"
    )

    session.add(Notification_Master(
        tenant_id=_notification_tenant_id(payment),
        employee_id=employee_id,
        client_id=payment.client_id,
        contract_id=payment.contract_id,
        notification_type=NOTIFICATION_TYPE,
        priority='urgent',
        message=message,
        read=False,
        dismissed=False,
        created_at=datetime.utcnow(),
    ))
    return True


def run_commission_reminders(session, tenant_id: Optional[str] = None, today: Optional[date] = None) -> CommissionReminderResult:
    """
    Advance commission payment statuses and create internal CRM follow-up notifications.

    The job is intentionally idempotent for same-day reruns:
    - status transitions are one-way for the matched states
    - follow-up notifications are only created when next_follow_up_date is due
    - after a follow-up is processed, next_follow_up_date is moved into the future
    - an existing undismissed notification containing the payment id is not duplicated
    """
    today = today or datetime.utcnow().date()
    result = CommissionReminderResult()

    scheduled_query = session.query(Commission_Payment).filter(
        Commission_Payment.status == 'Scheduled',
        Commission_Payment.due_date.isnot(None),
        Commission_Payment.due_date <= today + timedelta(days=30),
    )
    scheduled_query = _tenant_filter(scheduled_query, tenant_id)
    scheduled_payments = scheduled_query.all()
    for payment in scheduled_payments:
        payment.status = 'Pending'
        payment.updated_at = datetime.utcnow()
        result.scheduled_to_pending += 1

    pending_query = session.query(Commission_Payment).filter(
        Commission_Payment.status == 'Pending',
        Commission_Payment.due_date.isnot(None),
        Commission_Payment.due_date <= today,
    )
    pending_query = _tenant_filter(pending_query, tenant_id)
    pending_payments = pending_query.all()
    for payment in pending_payments:
        payment.status = 'Due'
        payment.next_follow_up_date = today
        payment.updated_at = datetime.utcnow()
        result.pending_to_due += 1

    session.flush()

    follow_up_query = session.query(Commission_Payment).filter(
        Commission_Payment.status.in_(FOLLOW_UP_STATUSES),
        Commission_Payment.next_follow_up_date.isnot(None),
        Commission_Payment.next_follow_up_date <= today,
    )
    follow_up_query = _tenant_filter(follow_up_query, tenant_id)
    follow_up_payments = follow_up_query.order_by(Commission_Payment.due_date.asc()).all()

    for payment in follow_up_payments:
        result.follow_ups_checked += 1
        created = _create_follow_up_notification(session, payment, today)
        if created:
            result.notifications_created += 1
        else:
            result.notifications_skipped_existing += 1

        payment.follow_up_count = (payment.follow_up_count or 0) + 1
        payment.next_follow_up_date = _next_follow_up_date(payment, today)
        payment.updated_at = datetime.utcnow()
        result.follow_ups_rescheduled += 1

    return result
