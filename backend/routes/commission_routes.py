from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import uuid

from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import String, asc, case, cast, desc, func, or_

from backend.db import SessionLocal
from backend.models import (
    Agent_Commission_Batch,
    Agent_Commission_Batch_Item,
    Client_Master,
    Commission_Payment,
    Commission_Payment_Receipt,
    Employee_Master,
    Energy_Contract_Master,
    Opportunity_Details,
    Project_Details,
    Services_Master,
    Supplier_Master,
)
from backend.routes.auth_helpers import token_required
from backend.crm.utils.role_helpers import is_admin_user
from backend.utils.commission_reminders import run_commission_reminders
from backend.utils.commission_schedule import generate_commission_schedule_for_project
from backend.utils.commission_backfill import backfill_commission_schedules


commission_bp = Blueprint('commission', __name__, url_prefix='/api/commission')

PAYMENT_STATUSES = {
    'Scheduled',
    'Pending',
    'Due',
    'Received',
    'Partially Paid',
    'Chasing Supplier',
    'Closed',
}

ADMIN_SET_STATUSES = {'Chasing Supplier', 'Closed'}
BATCH_STATUSES = {'Awaiting Payment', 'Commission Paid'}
COMMISSION_PAYMENT_TYPES = {
    'annual',
    'upfront_reconciliation',
    'monthly_actual',
    'quarterly_actual',
}


def _money(value) -> str:
    amount = Decimal(value or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return str(amount)


def _date(value):
    return value.isoformat() if value else None


def _datetime(value):
    return value.isoformat() if value else None


def _parse_date(value: str, field_name: str):
    if not value:
        return None, None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date(), None
    except ValueError:
        return None, f'{field_name} must be YYYY-MM-DD'


def _parse_positive_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _parse_month(value: str):
    if not value:
        return None, None, None
    try:
        month_start = datetime.strptime(value, '%Y-%m').date().replace(day=1)
    except ValueError:
        return None, None, 'month must be YYYY-MM'

    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return month_start, next_month, None


def _payment_base_query(session):
    return (
        session.query(
            Commission_Payment,
            Client_Master.client_company_name.label('customer_name'),
            Client_Master.client_contact_name.label('customer_contact_name'),
            Opportunity_Details.business_name.label('business_name'),
            Supplier_Master.supplier_company_name.label('supplier_name'),
            Employee_Master.employee_name.label('agent_name'),
            Energy_Contract_Master.mpan_number.label('mpan_number'),
            Energy_Contract_Master.mpan_bottom.label('mpan_bottom'),
            Energy_Contract_Master.contract_start_date.label('contract_start_date'),
            Energy_Contract_Master.contract_end_date.label('contract_end_date'),
            Energy_Contract_Master.service_id.label('contract_service_id'),
            Services_Master.service_title.label('service_title'),
        )
        .outerjoin(Client_Master, Commission_Payment.client_id == Client_Master.client_id)
        .outerjoin(Project_Details, Commission_Payment.project_id == Project_Details.project_id)
        .outerjoin(Opportunity_Details, Project_Details.opportunity_id == Opportunity_Details.opportunity_id)
        .outerjoin(Energy_Contract_Master, Commission_Payment.contract_id == Energy_Contract_Master.energy_contract_master_id)
        .outerjoin(Services_Master, Energy_Contract_Master.service_id == Services_Master.service_id)
        .outerjoin(Supplier_Master, Commission_Payment.supplier_id == Supplier_Master.supplier_id)
        .outerjoin(Employee_Master, Commission_Payment.employee_id == Employee_Master.employee_id)
    )


def _payment_payload(row) -> dict:
    payment = row.Commission_Payment
    customer_name = row.customer_name or row.customer_contact_name

    return {
        'id': payment.id,
        'tenant_id': payment.tenant_id,
        'client_id': payment.client_id,
        'project_id': payment.project_id,
        'contract_id': payment.contract_id,
        'supplier_id': payment.supplier_id,
        'employee_id': payment.employee_id,
        'instalment_year': payment.instalment_year,
        'payment_policy_type': payment.payment_policy_type,
        'payment_period_label': payment.payment_period_label or f'Year {payment.instalment_year}',
        'payment_period_start': _date(payment.payment_period_start),
        'payment_period_end': _date(payment.payment_period_end),
        'customer_name': customer_name,
        'business_name': row.business_name or customer_name,
        'supplier_name': row.supplier_name,
        'mpan_number': row.mpan_number,
        'mpan_bottom': row.mpan_bottom,
        'contract_start_date': _date(row.contract_start_date),
        'contract_end_date': _date(row.contract_end_date),
        'service_id': row.contract_service_id,
        'service_title': (
            'Water' if row.contract_service_id == 2 else
            'Utilities' if row.contract_service_id == 1 else
            row.service_title
        ),
        'aggregator': payment.aggregator,
        'agent_name': row.agent_name,
        'expected_gross_amount': _money(payment.expected_gross_amount),
        'expected_net_amount': _money(payment.expected_net_amount),
        'due_date': _date(payment.due_date),
        'amount_received': _money(payment.amount_received),
        'outstanding_amount': _money(payment.outstanding_amount),
        'status': payment.status,
        'last_checked_at': _datetime(payment.last_checked_at),
        'next_follow_up_date': _date(payment.next_follow_up_date),
        'follow_up_count': payment.follow_up_count,
        'created_at': _datetime(payment.created_at),
        'updated_at': _datetime(payment.updated_at),
    }


def _receipt_payload(receipt: Commission_Payment_Receipt, logged_by_name: str = None) -> dict:
    return {
        'id': receipt.id,
        'commission_payment_id': receipt.commission_payment_id,
        'tenant_id': receipt.tenant_id,
        'amount_received': _money(receipt.amount_received),
        'date_received': _date(receipt.date_received),
        'notes': receipt.notes,
        'logged_by': receipt.logged_by,
        'logged_by_name': logged_by_name,
        'created_at': _datetime(receipt.created_at),
    }


def _commission_amount(receipt_amount, commission_rate) -> Decimal:
    amount = Decimal(str(receipt_amount or 0))
    rate = Decimal(str(commission_rate or 0))
    return (amount * rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _employee_name(employee: Employee_Master) -> str:
    return employee.employee_name if employee and employee.employee_name else f'Agent #{employee.employee_id if employee else ""}'.strip()


def _client_name(client: Client_Master, fallback_id=None) -> str:
    if client:
        return client.client_company_name or client.client_contact_name or f'Client #{client.client_id}'
    return f'Client #{fallback_id}' if fallback_id else 'Unknown client'


def _batch_payload(batch: Agent_Commission_Batch, employee: Employee_Master, items: list, include_admin_fields: bool) -> dict:
    return {
        'id': batch.id,
        'tenant_id': batch.tenant_id if include_admin_fields else None,
        'employee_id': batch.employee_id if include_admin_fields else None,
        'agent_name': _employee_name(employee),
        'batch_month': _date(batch.batch_month),
        'total_amount': _money(batch.total_amount),
        'status': batch.status,
        'paid_at': _datetime(batch.paid_at),
        'paid_by': batch.paid_by if include_admin_fields else None,
        'created_at': _datetime(batch.created_at),
        'statement_url': f'/api/commission/batches/{batch.id}/statement',
        'items': items,
    }


def _status_count_payload(status: str, count: int, expected, received, outstanding) -> dict:
    return {
        'status': status,
        'count': int(count or 0),
        'total_expected': _money(expected),
        'total_received': _money(received),
        'total_outstanding': _money(outstanding),
    }


def _supplier_term_payload(supplier: Supplier_Master) -> dict:
    delay_days = supplier.commission_payment_delay_days
    payment_mode = supplier.multi_year_commission_payment_mode
    payment_type = supplier.commission_payment_type

    if payment_type == 'upfront_reconciliation':
        terms_configured = (
            supplier.upfront_percentage is not None
            and bool(supplier.reconciliation_required)
        )
    elif payment_type in ('monthly_actual', 'quarterly_actual'):
        terms_configured = all(value is not None for value in (
            supplier.invoice_delay_days,
            supplier.customer_payment_days,
            supplier.grace_days,
        ))
    elif payment_type == 'annual':
        terms_configured = delay_days is not None
    else:
        terms_configured = delay_days is not None and payment_mode in ('annual', 'upfront')

    return {
        'supplier_id': supplier.supplier_id,
        'supplier_company_name': supplier.supplier_company_name,
        'supplier_contact_name': supplier.supplier_contact_name,
        'commission_payment_delay_days': delay_days,
        'multi_year_commission_payment_mode': payment_mode,
        'commission_payment_type': payment_type,
        'upfront_percentage': _money(supplier.upfront_percentage) if supplier.upfront_percentage is not None else None,
        'reconciliation_required': supplier.reconciliation_required,
        'invoice_delay_days': supplier.invoice_delay_days,
        'customer_payment_days': supplier.customer_payment_days,
        'grace_days': supplier.grace_days,
        'commission_payment_frequency': supplier.commission_payment_frequency,
        'terms_configured': terms_configured,
    }


def _require_admin():
    user = getattr(request, 'current_user', None)
    if not is_admin_user(user):
        return jsonify({
            'error': 'Access denied',
            'message': 'Admin role required for this commission operation',
        }), 403
    return None


def _current_tenant_id():
    user = getattr(request, 'current_user', None)
    tenant_id = getattr(user, 'tenant_id', None)
    if tenant_id in ('', None):
        return None
    return str(tenant_id)


def _require_tenant_id():
    tenant_id = _current_tenant_id()
    if tenant_id is None:
        return None, (jsonify({
            'error': 'Tenant missing',
            'message': 'Authenticated token must include tenant_id',
        }), 401)
    return tenant_id, None


def _status_code_for_generation(status: str) -> int:
    if status == "not_found":
        return 404
    return 200


@commission_bp.route('/supplier-terms', methods=['GET'])
@token_required
def list_supplier_terms():
    admin_error = _require_admin()
    if admin_error:
        return admin_error

    session = SessionLocal()
    try:
        suppliers = (
            session.query(Supplier_Master)
            .order_by(asc(Supplier_Master.supplier_company_name), asc(Supplier_Master.supplier_id))
            .all()
        )

        return jsonify({
            'success': True,
            'suppliers': [_supplier_term_payload(supplier) for supplier in suppliers],
        }), 200
    finally:
        session.close()


@commission_bp.route('/supplier-terms/<int:supplier_id>', methods=['PUT'])
@token_required
def update_supplier_terms(supplier_id: int):
    admin_error = _require_admin()
    if admin_error:
        return admin_error

    data = request.get_json(force=True, silent=True) or {}
    delay_days = data.get('commission_payment_delay_days')
    payment_mode = data.get('multi_year_commission_payment_mode')
    payment_type = data.get('commission_payment_type')

    if payment_type in ('', None):
        payment_type = None
    elif payment_type not in COMMISSION_PAYMENT_TYPES:
        return jsonify({'error': 'Invalid commission_payment_type'}), 400

    def parse_non_negative_int(field_name):
        value = data.get(field_name)
        if value in ('', None):
            return None, None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None, f'{field_name} must be a whole number'
        if parsed < 0:
            return None, f'{field_name} cannot be negative'
        return parsed, None

    invoice_delay_days, parse_error = parse_non_negative_int('invoice_delay_days')
    if parse_error:
        return jsonify({'error': parse_error}), 400
    customer_payment_days, parse_error = parse_non_negative_int('customer_payment_days')
    if parse_error:
        return jsonify({'error': parse_error}), 400
    grace_days, parse_error = parse_non_negative_int('grace_days')
    if parse_error:
        return jsonify({'error': parse_error}), 400

    upfront_percentage = data.get('upfront_percentage')
    if upfront_percentage in ('', None):
        upfront_percentage = None
    else:
        try:
            upfront_percentage = Decimal(str(upfront_percentage))
        except Exception:
            return jsonify({'error': 'upfront_percentage must be a number'}), 400
        if upfront_percentage < 0 or upfront_percentage > 100:
            return jsonify({'error': 'upfront_percentage must be between 0 and 100'}), 400

    reconciliation_required = data.get('reconciliation_required')
    if reconciliation_required is not None and not isinstance(reconciliation_required, bool):
        return jsonify({'error': 'reconciliation_required must be true or false'}), 400

    if payment_type == 'upfront_reconciliation':
        if upfront_percentage is None:
            return jsonify({'error': 'upfront_percentage is required for upfront reconciliation'}), 400
        reconciliation_required = True
        payment_mode = 'upfront'
        delay_days = 0 if delay_days in ('', None) else delay_days
        frequency = 'upfront'
    elif payment_type in ('monthly_actual', 'quarterly_actual'):
        if any(value is None for value in (invoice_delay_days, customer_payment_days, grace_days)):
            return jsonify({'error': 'Invoice, customer payment and grace days are required'}), 400
        reconciliation_required = False
        upfront_percentage = None
        payment_mode = 'annual'
        delay_days = invoice_delay_days + customer_payment_days + grace_days
        frequency = 'monthly' if payment_type == 'monthly_actual' else 'quarterly'
    elif payment_type == 'annual':
        frequency = 'annual'
        payment_mode = 'annual'
    else:
        frequency = data.get('commission_payment_frequency')

    if delay_days in ('', None):
        delay_days = None
    else:
        try:
            delay_days = int(delay_days)
        except (TypeError, ValueError):
            return jsonify({'error': 'commission_payment_delay_days must be a whole number'}), 400

        if delay_days < 0:
            return jsonify({'error': 'commission_payment_delay_days cannot be negative'}), 400

    if payment_mode in ('', None):
        payment_mode = None
    elif payment_mode not in ('annual', 'upfront'):
        return jsonify({'error': "multi_year_commission_payment_mode must be 'annual' or 'upfront'"}), 400

    session = SessionLocal()
    try:
        supplier = session.query(Supplier_Master).filter_by(supplier_id=supplier_id).first()
        if not supplier:
            return jsonify({'error': 'Supplier not found'}), 404

        supplier.commission_payment_delay_days = delay_days
        supplier.multi_year_commission_payment_mode = payment_mode
        supplier.commission_payment_type = payment_type
        supplier.upfront_percentage = upfront_percentage
        supplier.reconciliation_required = reconciliation_required
        supplier.invoice_delay_days = invoice_delay_days
        supplier.customer_payment_days = customer_payment_days
        supplier.grace_days = grace_days
        supplier.commission_payment_frequency = frequency
        session.commit()
        session.refresh(supplier)

        return jsonify({
            'success': True,
            'supplier': _supplier_term_payload(supplier),
        }), 200
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/generate/<int:project_id>', methods=['POST'])
@token_required
def generate_commission_schedule(project_id: int):
    admin_error = _require_admin()
    if admin_error:
        return admin_error

    session = SessionLocal()
    try:
        result = generate_commission_schedule_for_project(session, project_id)
        if result.status == "created":
            session.commit()
        else:
            session.rollback()

        return jsonify(result.to_dict()), _status_code_for_generation(result.status)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/backfill', methods=['POST'])
@token_required
def backfill_existing_commission_schedules():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    data = request.get_json(force=True, silent=True) or {}
    dry_run = data.get('dry_run', True)
    if not isinstance(dry_run, bool):
        return jsonify({'error': 'dry_run must be true or false'}), 400

    raw_exclusions = data.get('excluded_project_ids') or []
    if not isinstance(raw_exclusions, list):
        return jsonify({'error': 'excluded_project_ids must be a list'}), 400
    try:
        excluded_project_ids = {int(value) for value in raw_exclusions}
    except (TypeError, ValueError):
        return jsonify({'error': 'excluded_project_ids must contain project IDs'}), 400

    session = SessionLocal()
    try:
        result = backfill_commission_schedules(
            session,
            tenant_id,
            dry_run=dry_run,
            excluded_project_ids=excluded_project_ids,
        )
        if dry_run:
            session.rollback()
        else:
            session.commit()
        return jsonify({
            'success': True,
            'message': 'Commission backfill preview complete' if dry_run else 'Commission backfill complete',
            'result': result,
        }), 200
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/run-reminders', methods=['POST'])
@token_required
def run_commission_payment_reminders():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    session = SessionLocal()
    try:
        result = run_commission_reminders(session, tenant_id=tenant_id)
        session.commit()

        return jsonify({
            'success': True,
            'message': 'Commission reminders processed',
            'result': result.to_dict(),
        }), 200
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/reports/summary', methods=['GET'])
@token_required
def commission_report_summary():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    today = date.today()
    session = SessionLocal()
    try:
        totals = (
            session.query(
                func.coalesce(func.sum(Commission_Payment.expected_net_amount), 0).label('total_expected'),
                func.coalesce(func.sum(Commission_Payment.amount_received), 0).label('total_received'),
                func.coalesce(func.sum(Commission_Payment.outstanding_amount), 0).label('total_outstanding'),
                func.count(Commission_Payment.id).label('payment_count'),
                func.coalesce(func.sum(
                    case(
                        (
                            (Commission_Payment.due_date < today)
                            & (~Commission_Payment.status.in_(('Received', 'Closed'))),
                            1,
                        ),
                        else_=0,
                    )
                ), 0).label('overdue_count'),
                func.coalesce(func.sum(
                    case(
                        (
                            (Commission_Payment.status.in_(('Partially Paid', 'Chasing Supplier')))
                            & (Commission_Payment.outstanding_amount > 0),
                            1,
                        ),
                        else_=0,
                    )
                ), 0).label('underpaid_count'),
            )
            .filter(Commission_Payment.tenant_id == tenant_id)
            .one()
        )

        status_rows = (
            session.query(
                Commission_Payment.status,
                func.count(Commission_Payment.id),
                func.coalesce(func.sum(Commission_Payment.expected_net_amount), 0),
                func.coalesce(func.sum(Commission_Payment.amount_received), 0),
                func.coalesce(func.sum(Commission_Payment.outstanding_amount), 0),
            )
            .filter(Commission_Payment.tenant_id == tenant_id)
            .group_by(Commission_Payment.status)
            .order_by(asc(Commission_Payment.status))
            .all()
        )

        return jsonify({
            'success': True,
            'summary': {
                'total_expected_commission': _money(totals.total_expected),
                'total_received': _money(totals.total_received),
                'total_outstanding': _money(totals.total_outstanding),
                'payment_count': int(totals.payment_count or 0),
                'overdue_count': int(totals.overdue_count or 0),
                'underpaid_count': int(totals.underpaid_count or 0),
                'by_status': [
                    _status_count_payload(status, count, expected, received, outstanding)
                    for status, count, expected, received, outstanding in status_rows
                ],
            },
        }), 200
    finally:
        session.close()


@commission_bp.route('/reports/by-supplier', methods=['GET'])
@token_required
def commission_report_by_supplier():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    today = date.today()
    session = SessionLocal()
    try:
        rows = (
            session.query(
                Commission_Payment.supplier_id,
                Supplier_Master.supplier_company_name.label('supplier_name'),
                func.coalesce(func.sum(Commission_Payment.expected_net_amount), 0).label('total_expected'),
                func.coalesce(func.sum(Commission_Payment.amount_received), 0).label('total_received'),
                func.coalesce(func.sum(Commission_Payment.outstanding_amount), 0).label('total_outstanding'),
                func.count(Commission_Payment.id).label('payment_count'),
                func.coalesce(func.sum(
                    case(
                        (
                            (Commission_Payment.status.in_(('Partially Paid', 'Chasing Supplier')))
                            & (Commission_Payment.outstanding_amount > 0),
                            1,
                        ),
                        else_=0,
                    )
                ), 0).label('underpaid_count'),
                func.coalesce(func.sum(
                    case(
                        (
                            (Commission_Payment.due_date < today)
                            & (~Commission_Payment.status.in_(('Received', 'Closed'))),
                            1,
                        ),
                        else_=0,
                    )
                ), 0).label('overdue_count'),
            )
            .outerjoin(Supplier_Master, Commission_Payment.supplier_id == Supplier_Master.supplier_id)
            .filter(Commission_Payment.tenant_id == tenant_id)
            .group_by(Commission_Payment.supplier_id, Supplier_Master.supplier_company_name)
            .order_by(desc(func.coalesce(func.sum(Commission_Payment.outstanding_amount), 0)))
            .all()
        )

        return jsonify({
            'success': True,
            'suppliers': [
                {
                    'supplier_id': supplier_id,
                    'supplier_name': supplier_name or (f'Supplier #{supplier_id}' if supplier_id else 'Unassigned supplier'),
                    'total_expected': _money(total_expected),
                    'total_received': _money(total_received),
                    'total_outstanding': _money(total_outstanding),
                    'payment_count': int(payment_count or 0),
                    'underpaid_count': int(underpaid_count or 0),
                    'overdue_count': int(overdue_count or 0),
                }
                for (
                    supplier_id,
                    supplier_name,
                    total_expected,
                    total_received,
                    total_outstanding,
                    payment_count,
                    underpaid_count,
                    overdue_count,
                ) in rows
            ],
        }), 200
    finally:
        session.close()


@commission_bp.route('/reports/by-agent', methods=['GET'])
@token_required
def commission_report_by_agent():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    session = SessionLocal()
    try:
        item_counts = (
            session.query(
                Agent_Commission_Batch_Item.batch_id.label('batch_id'),
                func.count(Agent_Commission_Batch_Item.id).label('item_count'),
            )
            .group_by(Agent_Commission_Batch_Item.batch_id)
            .subquery()
        )
        rows = (
            session.query(
                Agent_Commission_Batch.employee_id,
                Employee_Master.employee_name.label('agent_name'),
                Agent_Commission_Batch.batch_month,
                func.coalesce(func.sum(Agent_Commission_Batch.total_amount), 0).label('total_commission'),
                func.coalesce(func.sum(
                    case(
                        (Agent_Commission_Batch.status == 'Commission Paid', Agent_Commission_Batch.total_amount),
                        else_=0,
                    )
                ), 0).label('paid_commission'),
                func.coalesce(func.sum(
                    case(
                        (Agent_Commission_Batch.status == 'Awaiting Payment', Agent_Commission_Batch.total_amount),
                        else_=0,
                    )
                ), 0).label('awaiting_payment'),
                func.count(func.distinct(Agent_Commission_Batch.id)).label('batch_count'),
                func.coalesce(func.sum(item_counts.c.item_count), 0).label('item_count'),
            )
            .outerjoin(Employee_Master, Agent_Commission_Batch.employee_id == Employee_Master.employee_id)
            .outerjoin(item_counts, item_counts.c.batch_id == Agent_Commission_Batch.id)
            .filter(Agent_Commission_Batch.tenant_id == tenant_id)
            .group_by(
                Agent_Commission_Batch.employee_id,
                Employee_Master.employee_name,
                Agent_Commission_Batch.batch_month,
            )
            .order_by(desc(Agent_Commission_Batch.batch_month), asc(Employee_Master.employee_name))
            .all()
        )

        return jsonify({
            'success': True,
            'agents': [
                {
                    'employee_id': employee_id,
                    'agent_name': agent_name or (f'Agent #{employee_id}' if employee_id else 'Unassigned agent'),
                    'month': _date(batch_month),
                    'total_commission': _money(total_commission),
                    'paid_commission': _money(paid_commission),
                    'awaiting_payment': _money(awaiting_payment),
                    'batch_count': int(batch_count or 0),
                    'item_count': int(item_count or 0),
                }
                for (
                    employee_id,
                    agent_name,
                    batch_month,
                    total_commission,
                    paid_commission,
                    awaiting_payment,
                    batch_count,
                    item_count,
                ) in rows
            ],
        }), 200
    finally:
        session.close()


@commission_bp.route('/reports/underpaid', methods=['GET'])
@token_required
def commission_report_underpaid():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    session = SessionLocal()
    try:
        rows = (
            _payment_base_query(session)
            .filter(
                Commission_Payment.tenant_id == tenant_id,
                Commission_Payment.status.in_(('Partially Paid', 'Chasing Supplier')),
                Commission_Payment.outstanding_amount > 0,
            )
            .order_by(desc(Commission_Payment.outstanding_amount), asc(Commission_Payment.due_date))
            .all()
        )

        return jsonify({
            'success': True,
            'payments': [_payment_payload(row) for row in rows],
        }), 200
    finally:
        session.close()


@commission_bp.route('/agent-commissions', methods=['GET'])
@token_required
def list_agent_commissions():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    user = getattr(request, 'current_user', None)
    is_admin = is_admin_user(user)
    current_employee_id = getattr(user, 'employee_id', None)
    month_start, next_month, month_error = _parse_month(request.args.get('month'))
    if month_error:
        return jsonify({'error': month_error}), 400

    session = SessionLocal()
    try:
        batch_query = (
            session.query(Agent_Commission_Batch, Employee_Master)
            .outerjoin(Employee_Master, Agent_Commission_Batch.employee_id == Employee_Master.employee_id)
            .filter(Agent_Commission_Batch.tenant_id == tenant_id)
        )
        if month_start:
            batch_query = batch_query.filter(Agent_Commission_Batch.batch_month == month_start)
        if not is_admin:
            batch_query = batch_query.filter(Agent_Commission_Batch.employee_id == current_employee_id)

        batch_rows = (
            batch_query
            .order_by(desc(Agent_Commission_Batch.batch_month), asc(Employee_Master.employee_name))
            .all()
        )

        batch_ids = [batch.id for batch, _employee in batch_rows]
        item_rows_by_batch = {batch_id: [] for batch_id in batch_ids}
        if batch_ids:
            item_rows = (
                session.query(Agent_Commission_Batch_Item)
                .filter(Agent_Commission_Batch_Item.batch_id.in_(batch_ids))
                .order_by(asc(Agent_Commission_Batch_Item.client_name), asc(Agent_Commission_Batch_Item.created_at))
                .all()
            )
            for item in item_rows:
                payload = {
                    'id': item.id,
                    'client_name': item.client_name,
                    'commission_rate': _money(item.commission_rate_snapshot),
                    'commission_amount': _money(item.commission_amount),
                    'created_at': _datetime(item.created_at),
                }
                if is_admin:
                    payload.update({
                        'commission_payment_id': item.commission_payment_id,
                        'commission_payment_receipt_id': item.commission_payment_receipt_id,
                        'receipt_amount': _money(item.receipt_amount),
                    })
                item_rows_by_batch.setdefault(item.batch_id, []).append(payload)

        batches = [
            _batch_payload(batch, employee, item_rows_by_batch.get(batch.id, []), include_admin_fields=is_admin)
            for batch, employee in batch_rows
        ]

        receipt_query = (
            session.query(
                Commission_Payment_Receipt,
                Commission_Payment,
                Employee_Master,
                Client_Master,
                Agent_Commission_Batch,
            )
            .join(Commission_Payment, Commission_Payment_Receipt.commission_payment_id == Commission_Payment.id)
            .join(Employee_Master, Commission_Payment.employee_id == Employee_Master.employee_id)
            .outerjoin(Client_Master, Commission_Payment.client_id == Client_Master.client_id)
            .outerjoin(Agent_Commission_Batch_Item, Agent_Commission_Batch_Item.commission_payment_receipt_id == Commission_Payment_Receipt.id)
            .outerjoin(Agent_Commission_Batch, Agent_Commission_Batch_Item.batch_id == Agent_Commission_Batch.id)
            .filter(Commission_Payment.tenant_id == tenant_id)
        )
        if month_start:
            receipt_query = receipt_query.filter(
                Commission_Payment_Receipt.date_received >= month_start,
                Commission_Payment_Receipt.date_received < next_month,
            )
        if not is_admin:
            receipt_query = receipt_query.filter(Commission_Payment.employee_id == current_employee_id)

        receipt_rows = (
            receipt_query
            .order_by(desc(Commission_Payment_Receipt.date_received), asc(Client_Master.client_company_name))
            .all()
        )

        unbatched_items = []
        for receipt, payment, employee, client, batch in receipt_rows:
            rate = Decimal(str(employee.commission_percentage or 0))
            commission_amount = _commission_amount(receipt.amount_received, rate)
            status = batch.status if batch else 'Awaiting Payment'
            payload = {
                'commission_payment_receipt_id': receipt.id if is_admin else None,
                'commission_payment_id': payment.id if is_admin else None,
                'client_name': _client_name(client, payment.client_id),
                'agent_name': _employee_name(employee),
                'employee_id': payment.employee_id if is_admin else None,
                'date_received': _date(receipt.date_received),
                'commission_rate': _money(rate),
                'commission_amount': _money(commission_amount),
                'batch_id': batch.id if batch else None,
                'status': status,
            }
            if is_admin:
                payload['receipt_amount'] = _money(receipt.amount_received)
            unbatched_items.append(payload)

        return jsonify({
            'success': True,
            'is_admin': is_admin,
            'month': _date(month_start) if month_start else None,
            'batches': batches,
            'items': unbatched_items,
        }), 200
    finally:
        session.close()


@commission_bp.route('/batches/generate', methods=['POST'])
@token_required
def generate_agent_commission_batches():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    data = request.get_json(force=True, silent=True) or {}
    month_start, next_month, month_error = _parse_month(data.get('month'))
    if month_error or not month_start:
        return jsonify({'error': month_error or 'month is required as YYYY-MM'}), 400

    session = SessionLocal()
    try:
        receipt_rows = (
            session.query(Commission_Payment_Receipt, Commission_Payment, Employee_Master, Client_Master)
            .join(Commission_Payment, Commission_Payment_Receipt.commission_payment_id == Commission_Payment.id)
            .join(Employee_Master, Commission_Payment.employee_id == Employee_Master.employee_id)
            .outerjoin(Client_Master, Commission_Payment.client_id == Client_Master.client_id)
            .outerjoin(Agent_Commission_Batch_Item, Agent_Commission_Batch_Item.commission_payment_receipt_id == Commission_Payment_Receipt.id)
            .filter(
                Commission_Payment.tenant_id == tenant_id,
                Commission_Payment_Receipt.date_received >= month_start,
                Commission_Payment_Receipt.date_received < next_month,
                Agent_Commission_Batch_Item.id.is_(None),
            )
            .order_by(Commission_Payment.employee_id, Commission_Payment_Receipt.date_received)
            .all()
        )

        batches_created = 0
        items_created = 0
        skipped_existing = 0
        batches_by_employee = {}

        for receipt, payment, employee, client in receipt_rows:
            if not payment.employee_id:
                skipped_existing += 1
                continue

            existing_item = (
                session.query(Agent_Commission_Batch_Item.id)
                .filter(Agent_Commission_Batch_Item.commission_payment_receipt_id == receipt.id)
                .first()
            )
            if existing_item:
                skipped_existing += 1
                continue

            batch = batches_by_employee.get(payment.employee_id)
            if batch is None:
                batch = (
                    session.query(Agent_Commission_Batch)
                    .filter(
                        Agent_Commission_Batch.tenant_id == tenant_id,
                        Agent_Commission_Batch.employee_id == payment.employee_id,
                        Agent_Commission_Batch.batch_month == month_start,
                    )
                    .first()
                )
                if batch is None:
                    batch = Agent_Commission_Batch(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        employee_id=payment.employee_id,
                        batch_month=month_start,
                        total_amount=Decimal('0.00'),
                        status='Awaiting Payment',
                        created_at=datetime.utcnow(),
                    )
                    session.add(batch)
                    session.flush()
                    batches_created += 1
                batches_by_employee[payment.employee_id] = batch

            rate = Decimal(str(employee.commission_percentage or 0))
            commission_amount = _commission_amount(receipt.amount_received, rate)
            item = Agent_Commission_Batch_Item(
                id=str(uuid.uuid4()),
                batch_id=batch.id,
                commission_payment_id=payment.id,
                commission_payment_receipt_id=receipt.id,
                client_name=_client_name(client, payment.client_id),
                receipt_amount=Decimal(str(receipt.amount_received or 0)),
                commission_rate_snapshot=rate,
                commission_amount=commission_amount,
                created_at=datetime.utcnow(),
            )
            session.add(item)
            batch.total_amount = Decimal(str(batch.total_amount or 0)) + commission_amount
            items_created += 1

        session.commit()

        return jsonify({
            'success': True,
            'month': _date(month_start),
            'summary': {
                'batches_created': batches_created,
                'items_created': items_created,
                'skipped_existing': skipped_existing,
            },
        }), 200
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/batches/<batch_id>/mark-paid', methods=['POST'])
@token_required
def mark_agent_commission_batch_paid(batch_id: str):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    session = SessionLocal()
    try:
        batch = (
            session.query(Agent_Commission_Batch)
            .filter(Agent_Commission_Batch.id == batch_id, Agent_Commission_Batch.tenant_id == tenant_id)
            .first()
        )
        if not batch:
            return jsonify({'error': 'Commission batch not found'}), 404

        batch.status = 'Commission Paid'
        batch.paid_at = datetime.utcnow()
        batch.paid_by = getattr(request.current_user, 'employee_id', None)
        session.commit()

        return jsonify({
            'success': True,
            'batch': {
                'id': batch.id,
                'status': batch.status,
                'paid_at': _datetime(batch.paid_at),
                'paid_by': batch.paid_by,
            },
        }), 200
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/batches/<batch_id>/statement', methods=['GET'])
@token_required
def download_agent_commission_statement(batch_id: str):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    user = getattr(request, 'current_user', None)
    is_admin = is_admin_user(user)
    current_employee_id = getattr(user, 'employee_id', None)

    session = SessionLocal()
    try:
        batch_row = (
            session.query(Agent_Commission_Batch, Employee_Master)
            .outerjoin(Employee_Master, Agent_Commission_Batch.employee_id == Employee_Master.employee_id)
            .filter(Agent_Commission_Batch.id == batch_id, Agent_Commission_Batch.tenant_id == tenant_id)
            .first()
        )
        if not batch_row:
            return jsonify({'error': 'Commission batch not found'}), 404

        batch, employee = batch_row
        if not is_admin and batch.employee_id != current_employee_id:
            return jsonify({'error': 'Access denied'}), 403

        items = (
            session.query(Agent_Commission_Batch_Item)
            .filter(Agent_Commission_Batch_Item.batch_id == batch.id)
            .order_by(asc(Agent_Commission_Batch_Item.client_name))
            .all()
        )

        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except Exception:
            return jsonify({'error': 'PDF generation library is not available'}), 500

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = [
            Paragraph('Business Gas', styles['Title']),
            Paragraph('Agent Commission Statement', styles['Heading2']),
            Spacer(1, 12),
            Paragraph(f'Agent: {_employee_name(employee)}', styles['Normal']),
            Paragraph(f'Month: {batch.batch_month.strftime("%B %Y")}', styles['Normal']),
            Paragraph(f'Status: {batch.status}', styles['Normal']),
        ]
        if batch.paid_at:
            story.append(Paragraph(f'Paid date: {batch.paid_at.strftime("%d/%m/%Y")}', styles['Normal']))
        story.append(Spacer(1, 14))

        table_data = [['Client Name', 'Commission Rate', 'Commission Amount']]
        for item in items:
            table_data.append([
                item.client_name or 'Unknown client',
                f'{Decimal(str(item.commission_rate_snapshot or 0)).quantize(Decimal("0.01"))}%',
                f'£{_money(item.commission_amount)}',
            ])
        table_data.append(['Total', '', f'£{_money(batch.total_amount)}'])

        table = Table(table_data, colWidths=[260, 120, 120])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F8FAFC')]),
        ]))
        story.append(table)
        doc.build(story)
        buffer.seek(0)

        filename = f'agent-commission-{batch.employee_id}-{batch.batch_month.strftime("%Y-%m")}.pdf'
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)
    finally:
        session.close()


@commission_bp.route('/customer-log/<int:client_id>', methods=['GET'])
@token_required
def get_customer_commission_log(client_id: int):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    user = getattr(request, 'current_user', None)
    is_admin = is_admin_user(user)
    current_employee_id = getattr(user, 'employee_id', None)

    session = SessionLocal()
    try:
        payment_query = (
            _payment_base_query(session)
            .filter(
                Commission_Payment.tenant_id == tenant_id,
                Commission_Payment.client_id == client_id,
            )
        )
        if not is_admin:
            payment_query = payment_query.filter(Commission_Payment.employee_id == current_employee_id)

        payment_rows = (
            payment_query
            .order_by(
                asc(Commission_Payment.contract_id),
                asc(Commission_Payment.instalment_year),
                asc(Commission_Payment.due_date),
            )
            .all()
        )

        payments = []
        payment_ids = []
        for row in payment_rows:
            payment = row.Commission_Payment
            payment_ids.append(payment.id)
            payload = {
                'id': payment.id,
                'contract_id': payment.contract_id,
                'instalment_year': payment.instalment_year,
                'payment_policy_type': payment.payment_policy_type,
                'payment_period_label': payment.payment_period_label or f'Year {payment.instalment_year}',
                'payment_period_start': _date(payment.payment_period_start),
                'payment_period_end': _date(payment.payment_period_end),
                'supplier_name': row.supplier_name,
                'aggregator': payment.aggregator,
                'agent_name': row.agent_name,
                'due_date': _date(payment.due_date),
                'status': payment.status,
                'last_checked_at': _datetime(payment.last_checked_at),
                'next_follow_up_date': _date(payment.next_follow_up_date),
            }
            if is_admin:
                payload.update({
                    'expected_net_amount': _money(payment.expected_net_amount),
                    'amount_received': _money(payment.amount_received),
                    'outstanding_amount': _money(payment.outstanding_amount),
                })
            payments.append(payload)

        receipts = []
        agent_commissions = []
        if payment_ids:
            receipt_rows = (
                session.query(
                    Commission_Payment_Receipt,
                    Commission_Payment,
                    Employee_Master.employee_name.label('logged_by_name'),
                )
                .join(Commission_Payment, Commission_Payment_Receipt.commission_payment_id == Commission_Payment.id)
                .outerjoin(Employee_Master, Commission_Payment_Receipt.logged_by == Employee_Master.employee_id)
                .filter(
                    Commission_Payment_Receipt.commission_payment_id.in_(payment_ids),
                    Commission_Payment_Receipt.tenant_id == tenant_id,
                )
                .order_by(desc(Commission_Payment_Receipt.date_received), desc(Commission_Payment_Receipt.created_at))
                .all()
            )

            receipt_ids = []
            receipt_payment_map = {}
            for receipt, payment, logged_by_name in receipt_rows:
                receipt_ids.append(receipt.id)
                receipt_payment_map[receipt.id] = payment
                if is_admin:
                    receipts.append({
                        **_receipt_payload(receipt, logged_by_name),
                        'contract_id': payment.contract_id,
                        'instalment_year': payment.instalment_year,
                        'payment_period_label': payment.payment_period_label or f'Year {payment.instalment_year}',
                    })

            if receipt_ids:
                item_rows = (
                    session.query(Agent_Commission_Batch_Item, Agent_Commission_Batch)
                    .outerjoin(Agent_Commission_Batch, Agent_Commission_Batch_Item.batch_id == Agent_Commission_Batch.id)
                    .filter(Agent_Commission_Batch_Item.commission_payment_receipt_id.in_(receipt_ids))
                    .order_by(desc(Agent_Commission_Batch.batch_month), asc(Agent_Commission_Batch_Item.client_name))
                    .all()
                )
                for item, batch in item_rows:
                    payment = receipt_payment_map.get(item.commission_payment_receipt_id)
                    if not is_admin and payment and payment.employee_id != current_employee_id:
                        continue
                    payload = {
                        'id': item.id,
                        'commission_payment_id': item.commission_payment_id if is_admin else None,
                        'commission_payment_receipt_id': item.commission_payment_receipt_id if is_admin else None,
                        'contract_id': payment.contract_id if payment else None,
                        'instalment_year': payment.instalment_year if payment else None,
                        'payment_period_label': (
                            payment.payment_period_label or f'Year {payment.instalment_year}'
                            if payment else None
                        ),
                        'client_name': item.client_name,
                        'commission_rate': _money(item.commission_rate_snapshot),
                        'commission_amount': _money(item.commission_amount),
                        'batch_month': _date(batch.batch_month) if batch else None,
                        'status': batch.status if batch else 'Awaiting Payment',
                        'created_at': _datetime(item.created_at),
                    }
                    if is_admin:
                        payload['receipt_amount'] = _money(item.receipt_amount)
                    agent_commissions.append(payload)

        totals = {
            'payment_count': len(payments),
            'receipt_count': len(receipts),
            'agent_commission_count': len(agent_commissions),
        }
        if is_admin:
            totals.update({
                'total_expected': _money(sum(Decimal(str(p.get('expected_net_amount', 0))) for p in payments)),
                'total_received': _money(sum(Decimal(str(p.get('amount_received', 0))) for p in payments)),
                'total_outstanding': _money(sum(Decimal(str(p.get('outstanding_amount', 0))) for p in payments)),
            })

        return jsonify({
            'success': True,
            'is_admin': is_admin,
            'client_id': client_id,
            'totals': totals,
            'payments': payments,
            'receipts': receipts,
            'agent_commissions': agent_commissions,
        }), 200
    finally:
        session.close()


@commission_bp.route('/payments', methods=['GET'])
@token_required
def list_commission_payments():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    page = _parse_positive_int(request.args.get('page'), default=1, minimum=1, maximum=100000)
    page_size = _parse_positive_int(request.args.get('page_size'), default=25, minimum=1, maximum=100)
    status = (request.args.get('status') or '').strip()
    supplier_id = request.args.get('supplier')
    employee_id = request.args.get('agent')
    search = (request.args.get('search') or '').strip()
    due_from, due_from_error = _parse_date(request.args.get('due_from'), 'due_from')
    due_to, due_to_error = _parse_date(request.args.get('due_to'), 'due_to')

    if due_from_error:
        return jsonify({'error': due_from_error}), 400
    if due_to_error:
        return jsonify({'error': due_to_error}), 400
    if status and status not in PAYMENT_STATUSES:
        return jsonify({'error': 'Invalid payment status'}), 400

    session = SessionLocal()
    try:
        query = _payment_base_query(session).filter(Commission_Payment.tenant_id == tenant_id)

        if status:
            query = query.filter(Commission_Payment.status == status)
        if supplier_id:
            try:
                query = query.filter(Commission_Payment.supplier_id == int(supplier_id))
            except ValueError:
                return jsonify({'error': 'supplier must be an integer supplier_id'}), 400
        if employee_id:
            try:
                query = query.filter(Commission_Payment.employee_id == int(employee_id))
            except ValueError:
                return jsonify({'error': 'agent must be an integer employee_id'}), 400
        if due_from:
            query = query.filter(Commission_Payment.due_date >= due_from)
        if due_to:
            query = query.filter(Commission_Payment.due_date <= due_to)
        if search:
            search_pattern = f'%{search}%'
            query = query.filter(or_(
                Client_Master.client_company_name.ilike(search_pattern),
                Client_Master.client_contact_name.ilike(search_pattern),
                Opportunity_Details.business_name.ilike(search_pattern),
                Supplier_Master.supplier_company_name.ilike(search_pattern),
                Employee_Master.employee_name.ilike(search_pattern),
                Energy_Contract_Master.mpan_number.ilike(search_pattern),
                Energy_Contract_Master.mpan_bottom.ilike(search_pattern),
                Services_Master.service_title.ilike(search_pattern),
                cast(Commission_Payment.contract_id, String).ilike(search_pattern),
            ))

        summary_row = query.with_entities(
            func.coalesce(func.sum(Commission_Payment.expected_net_amount), 0).label('expected'),
            func.coalesce(func.sum(Commission_Payment.amount_received), 0).label('received'),
            func.coalesce(func.sum(Commission_Payment.outstanding_amount), 0).label('outstanding'),
        ).first()

        contract_groups = (
            query
            .filter(Commission_Payment.contract_id.isnot(None))
            .with_entities(
                Commission_Payment.contract_id.label('contract_id'),
                func.min(Commission_Payment.due_date).label('next_due_date'),
                func.max(Commission_Payment.updated_at).label('last_updated_at'),
            )
            .group_by(Commission_Payment.contract_id)
        )
        total = session.query(func.count()).select_from(contract_groups.subquery()).scalar() or 0
        contract_rows = (
            contract_groups
            .order_by(asc('next_due_date'), desc('last_updated_at'), asc(Commission_Payment.contract_id))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        contract_ids = [row.contract_id for row in contract_rows]
        rows = (
            query
            .filter(Commission_Payment.contract_id.in_(contract_ids))
            .order_by(
                asc(Commission_Payment.contract_id),
                asc(Commission_Payment.instalment_year),
                asc(Commission_Payment.due_date),
            )
            .all()
        )

        suppliers = (
            session.query(Supplier_Master.supplier_id, Supplier_Master.supplier_company_name)
            .join(Commission_Payment, Commission_Payment.supplier_id == Supplier_Master.supplier_id)
            .filter(Commission_Payment.tenant_id == tenant_id)
            .group_by(Supplier_Master.supplier_id, Supplier_Master.supplier_company_name)
            .order_by(asc(Supplier_Master.supplier_company_name), asc(Supplier_Master.supplier_id))
            .all()
        )
        agents = (
            session.query(Employee_Master.employee_id, Employee_Master.employee_name)
            .join(Commission_Payment, Commission_Payment.employee_id == Employee_Master.employee_id)
            .filter(Commission_Payment.tenant_id == tenant_id)
            .group_by(Employee_Master.employee_id, Employee_Master.employee_name)
            .order_by(asc(Employee_Master.employee_name), asc(Employee_Master.employee_id))
            .all()
        )

        return jsonify({
            'success': True,
            'payments': [_payment_payload(row) for row in rows],
            'summary': {
                'expected': _money(summary_row.expected),
                'received': _money(summary_row.received),
                'outstanding': _money(summary_row.outstanding),
            },
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': (total + page_size - 1) // page_size,
                'unit': 'renewals',
            },
            'filters': {
                'statuses': sorted(PAYMENT_STATUSES),
                'suppliers': [
                    {'supplier_id': supplier_id, 'supplier_name': supplier_name}
                    for supplier_id, supplier_name in suppliers
                ],
                'agents': [
                    {'employee_id': employee_id, 'employee_name': employee_name}
                    for employee_id, employee_name in agents
                ],
            },
        }), 200
    finally:
        session.close()


@commission_bp.route('/payments/<payment_id>', methods=['GET'])
@token_required
def get_commission_payment(payment_id: str):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    session = SessionLocal()
    try:
        row = (
            _payment_base_query(session)
            .filter(Commission_Payment.id == payment_id, Commission_Payment.tenant_id == tenant_id)
            .first()
        )
        if not row:
            return jsonify({'error': 'Commission payment not found'}), 404

        receipt_rows = (
            session.query(Commission_Payment_Receipt, Employee_Master.employee_name.label('logged_by_name'))
            .outerjoin(Employee_Master, Commission_Payment_Receipt.logged_by == Employee_Master.employee_id)
            .filter(Commission_Payment_Receipt.commission_payment_id == payment_id)
            .order_by(desc(Commission_Payment_Receipt.date_received), desc(Commission_Payment_Receipt.created_at))
            .all()
        )

        return jsonify({
            'success': True,
            'payment': _payment_payload(row),
            'receipts': [
                _receipt_payload(receipt, logged_by_name)
                for receipt, logged_by_name in receipt_rows
            ],
        }), 200
    finally:
        session.close()


@commission_bp.route('/payments/<payment_id>/receipts', methods=['POST'])
@token_required
def create_commission_payment_receipt(payment_id: str):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    data = request.get_json(force=True, silent=True) or {}

    try:
        amount_received = Decimal(str(data.get('amount_received', '')).strip())
    except Exception:
        return jsonify({'error': 'amount_received must be a valid number'}), 400

    if amount_received <= 0:
        return jsonify({'error': 'amount_received must be greater than 0'}), 400

    date_received, date_error = _parse_date(data.get('date_received'), 'date_received')
    if date_error:
        return jsonify({'error': date_error}), 400
    if date_received is None:
        date_received = datetime.utcnow().date()

    user = getattr(request, 'current_user', None)

    session = SessionLocal()
    try:
        payment = (
            session.query(Commission_Payment)
            .filter(Commission_Payment.id == payment_id, Commission_Payment.tenant_id == tenant_id)
            .first()
        )
        if not payment:
            return jsonify({'error': 'Commission payment not found'}), 404
        if payment.status == 'Closed':
            return jsonify({'error': 'Closed commission payments cannot receive receipts'}), 400

        receipt = Commission_Payment_Receipt(
            commission_payment_id=payment.id,
            tenant_id=payment.tenant_id,
            amount_received=amount_received,
            date_received=date_received,
            notes=(data.get('notes') or '').strip() or None,
            logged_by=getattr(user, 'employee_id', None),
        )
        session.add(receipt)
        session.flush()

        total_received = (
            session.query(func.coalesce(func.sum(Commission_Payment_Receipt.amount_received), 0))
            .filter(Commission_Payment_Receipt.commission_payment_id == payment.id)
            .scalar()
        )
        expected_net = Decimal(payment.expected_net_amount or 0)
        outstanding = max(expected_net - Decimal(total_received or 0), Decimal('0.00'))

        payment.amount_received = total_received
        payment.outstanding_amount = outstanding
        payment.status = 'Received' if outstanding == 0 else 'Partially Paid'
        payment.last_checked_at = datetime.utcnow()
        payment.updated_at = datetime.utcnow()

        session.commit()

        row = (
            _payment_base_query(session)
            .filter(Commission_Payment.id == payment_id, Commission_Payment.tenant_id == tenant_id)
            .first()
        )
        session.refresh(receipt)

        return jsonify({
            'success': True,
            'payment': _payment_payload(row),
            'receipt': _receipt_payload(receipt),
        }), 201
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@commission_bp.route('/payments/<payment_id>/status', methods=['PATCH'])
@token_required
def update_commission_payment_status(payment_id: str):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    tenant_id, tenant_error = _require_tenant_id()
    if tenant_error:
        return tenant_error

    data = request.get_json(force=True, silent=True) or {}
    status = (data.get('status') or '').strip()
    next_follow_up_date, follow_up_error = _parse_date(
        data.get('next_follow_up_date'),
        'next_follow_up_date',
    )

    if status not in ADMIN_SET_STATUSES:
        return jsonify({'error': "status must be 'Chasing Supplier' or 'Closed'"}), 400
    if follow_up_error:
        return jsonify({'error': follow_up_error}), 400

    session = SessionLocal()
    try:
        payment = (
            session.query(Commission_Payment)
            .filter(Commission_Payment.id == payment_id, Commission_Payment.tenant_id == tenant_id)
            .first()
        )
        if not payment:
            return jsonify({'error': 'Commission payment not found'}), 404

        payment.status = status
        payment.last_checked_at = datetime.utcnow()
        payment.updated_at = datetime.utcnow()
        if status == 'Chasing Supplier':
            payment.follow_up_count = (payment.follow_up_count or 0) + 1
            if next_follow_up_date:
                payment.next_follow_up_date = next_follow_up_date
        elif status == 'Closed':
            payment.next_follow_up_date = None

        session.commit()

        row = (
            _payment_base_query(session)
            .filter(Commission_Payment.id == payment_id, Commission_Payment.tenant_id == tenant_id)
            .first()
        )
        return jsonify({
            'success': True,
            'payment': _payment_payload(row),
        }), 200
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
