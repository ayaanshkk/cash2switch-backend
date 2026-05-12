"""
Display Order Calculation Utilities
Shared across multiple route files to avoid circular imports
"""

from sqlalchemy import text
from flask import current_app


def recalculate_display_order(session, tenant_id, employee_id=None):
    """
    Recalculate display_order starting from 1 PER EMPLOYEE.
    Uses ROW_NUMBER() OVER (PARTITION BY assigned_employee_id ORDER BY created_at)
    so each salesperson's list always starts at 1.
    """
    if employee_id:
        # Recalculate only for this specific employee
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Client_Master" cm
            SET display_order = sub.rn
            FROM (
                SELECT client_id,
                       ROW_NUMBER() OVER (ORDER BY created_at ASC) AS rn
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                  AND assigned_employee_id = :employee_id
                  AND is_deleted = FALSE
                  AND is_archived = FALSE
            ) sub
            WHERE cm.client_id = sub.client_id
        """), {'tenant_id': tenant_id, 'employee_id': employee_id})
    else:
        # Recalculate for ALL employees at once using PARTITION BY
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Client_Master" cm
            SET display_order = sub.rn
            FROM (
                SELECT client_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY assigned_employee_id
                           ORDER BY created_at ASC
                       ) AS rn
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_archived = FALSE
            ) sub
            WHERE cm.client_id = sub.client_id
        """), {'tenant_id': tenant_id})
    
    session.flush()
    current_app.logger.info(
        f"✅ Recalculated display_order per-employee "
        f"(tenant={tenant_id}, employee={employee_id or 'ALL'})"
    )