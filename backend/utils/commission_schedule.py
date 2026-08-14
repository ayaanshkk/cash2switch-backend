from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from backend.models import (
    Client_Master,
    Commission_Payment,
    Energy_Contract_Master,
    Opportunity_Details,
    Project_Details,
    Supplier_Master,
)


MONEY_PLACES = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")
COMMISSION_PAYMENT_CUTOFF_DATE = date(2022, 1, 1)


@dataclass
class CommissionGenerationResult:
    success: bool
    status: str
    message: str
    project_id: int | None = None
    contract_id: int | None = None
    rows_created: int = 0
    payments: list[dict[str, Any]] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "project_id": self.project_id,
            "contract_id": self.contract_id,
            "rows_created": self.rows_created,
            "payments": self.payments or [],
            "warnings": self.warnings or [],
        }


def _to_decimal(value: Any, field_name: str, warnings: list[str]) -> Decimal | None:
    if value is None or value == "":
        warnings.append(f"{field_name} is missing")
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        warnings.append(f"{field_name} is invalid: {value}")
        return None


def _to_term_years(value: Any, warnings: list[str]) -> int | None:
    term = _to_decimal(value, "contract term", warnings)
    if term is None:
        return None
    if term <= 0:
        warnings.append("contract term must be greater than zero")
        return None
    if term != term.to_integral_value():
        warnings.append(f"contract term must be a whole number of years: {value}")
        return None
    return int(term)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    month_days = (next_month - timedelta(days=1)).day
    return date(year, month, min(value.day, month_days))


def _allocate_amount(total: Decimal, count: int) -> list[Decimal]:
    if count <= 0:
        return []
    regular = _money(total / Decimal(count))
    amounts = [regular for _ in range(count)]
    amounts[-1] = _money(total - sum(amounts[:-1], Decimal("0.00")))
    return amounts


def _contract_term_months(contract, opportunity, warnings: list[str]) -> int | None:
    start_date = contract.contract_start_date
    end_date = contract.contract_end_date
    if start_date and end_date:
        if end_date < start_date:
            warnings.append("contract end date is before the start date")
            return None
        months = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month
        if _add_months(start_date, months) < end_date:
            months += 1
        return max(months, 1)

    raw_term = contract.term_sold if contract.term_sold is not None else (
        opportunity.term_sold if opportunity else None
    )
    term = _to_decimal(raw_term, "contract term", warnings)
    if term is None:
        return None
    if term <= 0 or term != term.to_integral_value():
        warnings.append(f"contract term must be a positive whole number: {raw_term}")
        return None

    # Current CRM forms store years (for example 3); older imports often store months (for example 12/24/36).
    return int(term) if term > 10 else int(term) * 12


def _payment_payload(payment: Commission_Payment) -> dict[str, Any]:
    return {
        "id": payment.id,
        "instalment_year": payment.instalment_year,
        "payment_policy_type": payment.payment_policy_type,
        "payment_period_label": payment.payment_period_label,
        "payment_period_start": payment.payment_period_start.isoformat() if payment.payment_period_start else None,
        "payment_period_end": payment.payment_period_end.isoformat() if payment.payment_period_end else None,
        "expected_gross_amount": str(payment.expected_gross_amount),
        "expected_net_amount": str(payment.expected_net_amount),
        "due_date": payment.due_date.isoformat() if payment.due_date else None,
        "status": payment.status,
    }


def generate_commission_schedule_for_project(session, project_id: int) -> CommissionGenerationResult:
    warnings: list[str] = []

    project = session.query(Project_Details).filter_by(project_id=project_id).first()
    if not project:
        return CommissionGenerationResult(
            success=False,
            status="not_found",
            message="Project not found",
            project_id=project_id,
        )

    contract = (
        session.query(Energy_Contract_Master)
        .filter_by(project_id=project.project_id)
        .order_by(Energy_Contract_Master.energy_contract_master_id.desc())
        .first()
    )
    if not contract:
        return CommissionGenerationResult(
            success=False,
            status="not_found",
            message="Contract not found for project",
            project_id=project.project_id,
        )

    existing_count = (
        session.query(Commission_Payment)
        .filter_by(contract_id=contract.energy_contract_master_id)
        .count()
    )
    if existing_count > 0:
        return CommissionGenerationResult(
            success=True,
            status="skipped_existing",
            message="Commission payment schedule already exists for this contract",
            project_id=project.project_id,
            contract_id=contract.energy_contract_master_id,
        )

    client = session.query(Client_Master).filter_by(client_id=project.client_id).first()
    opportunity = None
    if project.opportunity_id:
        opportunity = (
            session.query(Opportunity_Details)
            .filter_by(opportunity_id=project.opportunity_id)
            .first()
        )
    if not opportunity and project.client_id:
        opportunity = (
            session.query(Opportunity_Details)
            .filter_by(client_id=project.client_id)
            .order_by(Opportunity_Details.opportunity_id.desc())
            .first()
        )

    supplier = None
    if contract.supplier_id:
        supplier = session.query(Supplier_Master).filter_by(supplier_id=contract.supplier_id).first()

    if not client:
        warnings.append("client is missing")
    if not supplier:
        warnings.append("supplier is missing")
    if not contract.contract_start_date:
        warnings.append("contract_start_date/live date is missing")

    delay_days = supplier.commission_payment_delay_days if supplier else None
    payment_mode = supplier.multi_year_commission_payment_mode if supplier else None
    payment_type = supplier.commission_payment_type if supplier else None
    effective_policy = payment_type

    # Preserve schedules for suppliers configured before the policy migration.
    if not effective_policy and payment_mode == "annual":
        effective_policy = "annual"
    elif not effective_policy and payment_mode == "upfront":
        effective_policy = "legacy_upfront"

    if supplier:
        if effective_policy not in (
            "annual",
            "legacy_upfront",
            "upfront_reconciliation",
            "monthly_actual",
            "quarterly_actual",
        ):
            warnings.append("supplier commission payment policy is not configured")
        elif effective_policy in ("annual", "legacy_upfront") and delay_days is None:
            warnings.append("supplier commission payment delay is not configured")
        elif effective_policy == "upfront_reconciliation" and supplier.upfront_percentage is None:
            warnings.append("supplier upfront percentage is not configured")
        elif effective_policy in ("monthly_actual", "quarterly_actual") and any(
            value is None
            for value in (supplier.invoice_delay_days, supplier.customer_payment_days, supplier.grace_days)
        ):
            warnings.append("supplier invoice, customer payment or grace days are not configured")

    annual_usage_source = (
        opportunity.annual_usage
        if opportunity and opportunity.annual_usage is not None
        else project.Misc_Col2
    )
    uplift_source = (
        opportunity.uplift
        if opportunity and opportunity.uplift is not None
        else contract.net_notch
    )

    annual_usage = _to_decimal(annual_usage_source, "annual usage", warnings)
    uplift = _to_decimal(uplift_source, "uplift", warnings)
    term_months = _contract_term_months(contract, opportunity, warnings)

    if warnings:
        return CommissionGenerationResult(
            success=True,
            status="skipped_missing_data",
            message="Commission schedule was not created because required data is missing",
            project_id=project.project_id,
            contract_id=contract.energy_contract_master_id,
            warnings=warnings,
        )

    live_date = contract.contract_start_date
    employee_id = contract.employee_id or project.assigned_employee_id or project.employee_id
    expected_gross_per_year = _money((annual_usage * uplift) / Decimal("100"))
    expected_net_per_year = _money(expected_gross_per_year * Decimal("0.80"))
    term_years = (term_months + 11) // 12
    term_fraction = Decimal(term_months) / Decimal("12")
    expected_gross_total = _money(expected_gross_per_year * term_fraction)
    expected_net_total = _money(expected_net_per_year * term_fraction)
    tenant_id = str(client.tenant_id) if client.tenant_id is not None else None
    contract_end_date = contract.contract_end_date or (_add_months(live_date, term_months) - timedelta(days=1))

    def make_row(
        sequence: int,
        label: str,
        period_start: date,
        period_end: date,
        due_date: date,
        gross_amount: Decimal,
        net_amount: Decimal,
        status: str,
    ) -> Commission_Payment:
        return Commission_Payment(
            tenant_id=tenant_id,
            client_id=project.client_id,
            project_id=project.project_id,
            contract_id=contract.energy_contract_master_id,
            supplier_id=contract.supplier_id,
            employee_id=employee_id,
            instalment_year=sequence,
            payment_policy_type=payment_type or ("upfront" if effective_policy == "legacy_upfront" else effective_policy),
            payment_period_label=label,
            payment_period_start=period_start,
            payment_period_end=period_end,
            aggregator=contract.aggregator,
            annual_usage=_money(annual_usage),
            uplift=_rate(uplift),
            contract_term_years=term_years,
            live_date=live_date,
            expected_gross_amount=_money(gross_amount),
            expected_net_amount=_money(net_amount),
            due_date=due_date,
            amount_received=Decimal("0.00"),
            outstanding_amount=_money(net_amount),
            status=status,
            follow_up_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    rows_to_create: list[Commission_Payment] = []
    if effective_policy == "legacy_upfront":
        rows_to_create.append(make_row(
            1,
            "Full contract upfront",
            live_date,
            contract_end_date,
            live_date + timedelta(days=int(delay_days)),
            expected_gross_total,
            expected_net_total,
            "Pending",
        ))
    elif effective_policy == "upfront_reconciliation":
        upfront_rate = Decimal(str(supplier.upfront_percentage)) / Decimal("100")
        upfront_gross = _money(expected_gross_total * upfront_rate)
        upfront_net = _money(expected_net_total * upfront_rate)
        rows_to_create.extend([
            make_row(
                1,
                f'{_money(upfront_rate * Decimal("100"))}% upfront',
                live_date,
                live_date,
                live_date + timedelta(days=int(delay_days or 0)),
                upfront_gross,
                upfront_net,
                "Pending",
            ),
            make_row(
                2,
                "Final reconciliation",
                live_date,
                contract_end_date,
                contract_end_date,
                _money(expected_gross_total - upfront_gross),
                _money(expected_net_total - upfront_net),
                "Scheduled",
            ),
        ])
    elif effective_policy in ("monthly_actual", "quarterly_actual"):
        months_per_period = 1 if effective_policy == "monthly_actual" else 3
        period_count = (term_months + months_per_period - 1) // months_per_period
        gross_amounts = _allocate_amount(expected_gross_total, period_count)
        net_amounts = _allocate_amount(expected_net_total, period_count)
        payment_delay = int(
            supplier.invoice_delay_days + supplier.customer_payment_days + supplier.grace_days
        )

        for index in range(period_count):
            period_start = _add_months(live_date, index * months_per_period)
            period_end = min(
                _add_months(live_date, (index + 1) * months_per_period) - timedelta(days=1),
                contract_end_date,
            )
            if effective_policy == "monthly_actual":
                label = period_start.strftime("%b %Y")
            else:
                label = (
                    f'Quarter {index + 1} '
                    f'({period_start.strftime("%b %Y")}-{period_end.strftime("%b %Y")})'
                )
            rows_to_create.append(make_row(
                index + 1,
                label,
                period_start,
                period_end,
                period_end + timedelta(days=payment_delay),
                gross_amounts[index],
                net_amounts[index],
                "Pending" if index == 0 else "Scheduled",
            ))
    else:
        year_one_due_date = live_date + timedelta(days=int(delay_days))
        gross_amounts = _allocate_amount(expected_gross_total, term_years)
        net_amounts = _allocate_amount(expected_net_total, term_years)
        for instalment_year in range(1, term_years + 1):
            period_start = _add_years(live_date, instalment_year - 1)
            period_end = min(_add_years(live_date, instalment_year) - timedelta(days=1), contract_end_date)
            rows_to_create.append(make_row(
                instalment_year,
                f"Year {instalment_year}",
                period_start,
                period_end,
                _add_years(year_one_due_date, instalment_year - 1),
                gross_amounts[instalment_year - 1],
                net_amounts[instalment_year - 1],
                "Pending" if instalment_year == 1 else "Scheduled",
            ))

    for row in rows_to_create:
        if row.due_date and row.due_date < COMMISSION_PAYMENT_CUTOFF_DATE:
            continue
        session.add(row)
    session.flush()

    created_rows = [row for row in rows_to_create if row.due_date is None or row.due_date >= COMMISSION_PAYMENT_CUTOFF_DATE]
    if not created_rows:
        return CommissionGenerationResult(
            success=True,
            status="skipped_before_2022",
            message="Commission schedule was not created because all payment rows are before 2022",
            project_id=project.project_id,
            contract_id=contract.energy_contract_master_id,
            warnings=["payment rows before 2022 are excluded"],
        )

    return CommissionGenerationResult(
        success=True,
        status="created",
        message=f"Created {len(created_rows)} commission payment row(s)",
        project_id=project.project_id,
        contract_id=contract.energy_contract_master_id,
        rows_created=len(created_rows),
        payments=[_payment_payload(row) for row in created_rows],
    )
