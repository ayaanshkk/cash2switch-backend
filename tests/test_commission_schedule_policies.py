import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from backend.models import (
    Client_Master,
    Commission_Payment,
    Energy_Contract_Master,
    Opportunity_Details,
    Project_Details,
    Supplier_Master,
)
from backend.utils.commission_schedule import generate_commission_schedule_for_project


class FakeQuery:
    def __init__(self, value=None, count_value=None):
        self.value = value
        self.count_value = count_value

    def filter_by(self, **_kwargs):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return self.value

    def count(self):
        return self.count_value if self.count_value is not None else 0


class FakeSession:
    def __init__(self, supplier):
        self.added = []
        self.values = {
            Project_Details: SimpleNamespace(
                project_id=101,
                client_id=201,
                opportunity_id=301,
                assigned_employee_id=8,
                employee_id=8,
                Misc_Col2=None,
            ),
            Energy_Contract_Master: SimpleNamespace(
                energy_contract_master_id=401,
                project_id=101,
                employee_id=8,
                supplier_id=501,
                contract_start_date=date(2026, 1, 1),
                contract_end_date=date(2026, 12, 31),
                term_sold=1,
                net_notch=None,
                aggregator="Test Aggregator",
            ),
            Client_Master: SimpleNamespace(client_id=201, tenant_id=2),
            Opportunity_Details: SimpleNamespace(
                opportunity_id=301,
                client_id=201,
                annual_usage=Decimal("100000"),
                uplift=Decimal("2.00"),
                term_sold=1,
            ),
            Supplier_Master: supplier,
        }

    def query(self, model):
        if model is Commission_Payment:
            return FakeQuery(count_value=0)
        return FakeQuery(value=self.values.get(model))

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None


def supplier(policy, **overrides):
    values = {
        "supplier_id": 501,
        "commission_payment_type": policy,
        "commission_payment_delay_days": 0,
        "multi_year_commission_payment_mode": "annual",
        "upfront_percentage": None,
        "reconciliation_required": False,
        "invoice_delay_days": None,
        "customer_payment_days": None,
        "grace_days": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class CommissionSchedulePolicyTests(unittest.TestCase):
    def test_upfront_reconciliation_creates_70_and_30_percent_rows(self):
        session = FakeSession(supplier(
            "upfront_reconciliation",
            multi_year_commission_payment_mode="upfront",
            upfront_percentage=Decimal("70.00"),
            reconciliation_required=True,
        ))

        result = generate_commission_schedule_for_project(session, 101)

        self.assertEqual(result.status, "created")
        self.assertEqual(result.rows_created, 2)
        self.assertEqual(session.added[0].payment_period_label, "70.00% upfront")
        self.assertEqual(session.added[1].payment_period_label, "Final reconciliation")
        self.assertEqual(session.added[0].expected_net_amount, Decimal("1120.00"))
        self.assertEqual(session.added[1].expected_net_amount, Decimal("480.00"))
        self.assertEqual(session.added[1].due_date, date(2026, 12, 31))

    def test_monthly_actual_creates_12_periods_with_44_day_timing(self):
        session = FakeSession(supplier(
            "monthly_actual",
            invoice_delay_days=21,
            customer_payment_days=21,
            grace_days=2,
        ))

        result = generate_commission_schedule_for_project(session, 101)

        self.assertEqual(result.rows_created, 12)
        self.assertEqual(session.added[0].payment_period_label, "Jan 2026")
        self.assertEqual(session.added[0].payment_period_end, date(2026, 1, 31))
        self.assertEqual(session.added[0].due_date, date(2026, 3, 16))
        self.assertEqual(session.added[-1].payment_period_label, "Dec 2026")
        self.assertEqual(sum(row.expected_net_amount for row in session.added), Decimal("1600.00"))

    def test_quarterly_actual_creates_four_periods_and_preserves_total(self):
        session = FakeSession(supplier(
            "quarterly_actual",
            invoice_delay_days=21,
            customer_payment_days=21,
            grace_days=2,
        ))

        result = generate_commission_schedule_for_project(session, 101)

        self.assertEqual(result.rows_created, 4)
        self.assertEqual(session.added[0].payment_period_label, "Quarter 1 (Jan 2026-Mar 2026)")
        self.assertEqual(session.added[-1].payment_period_label, "Quarter 4 (Oct 2026-Dec 2026)")
        self.assertEqual(sum(row.expected_net_amount for row in session.added), Decimal("1600.00"))
        self.assertEqual(session.added[0].status, "Pending")
        self.assertTrue(all(row.status == "Scheduled" for row in session.added[1:]))

    def test_historical_contract_uses_net_notch_and_contract_dates(self):
        session = FakeSession(supplier(
            "monthly_actual",
            invoice_delay_days=21,
            customer_payment_days=21,
            grace_days=2,
        ))
        session.values[Opportunity_Details].uplift = None
        session.values[Energy_Contract_Master].net_notch = Decimal("0.50")
        session.values[Energy_Contract_Master].term_sold = None
        session.values[Energy_Contract_Master].contract_end_date = date(2028, 12, 31)

        result = generate_commission_schedule_for_project(session, 101)

        self.assertEqual(result.rows_created, 36)
        self.assertEqual(session.added[0].uplift, Decimal("0.5000"))
        self.assertEqual(session.added[0].contract_term_years, 3)
        self.assertEqual(sum(row.expected_net_amount for row in session.added), Decimal("1200.00"))


if __name__ == "__main__":
    unittest.main()
