from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from sqlalchemy import String, cast

from backend.models import Client_Master, Project_Details
from backend.utils.commission_schedule import generate_commission_schedule_for_project


def backfill_commission_schedules(
    session,
    tenant_id: str,
    *,
    dry_run: bool = True,
    excluded_project_ids: set[int] | None = None,
    included_project_ids: set[int] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    excluded_project_ids = excluded_project_ids or set()

    project_query = (
        session.query(
            Project_Details.project_id,
            Project_Details.client_id,
            Client_Master.client_company_name,
        )
        .join(Client_Master, Project_Details.client_id == Client_Master.client_id)
        .filter(
            cast(Client_Master.tenant_id, String) == str(tenant_id),
            Project_Details.status == 'Already Renewed',
        )
    )
    if included_project_ids is not None:
        project_query = project_query.filter(Project_Details.project_id.in_(included_project_ids))
    project_rows = project_query.order_by(Project_Details.project_id).all()

    counts: Counter[str] = Counter()
    rows_created = 0
    details = []

    for index, (project_id, client_id, client_name) in enumerate(project_rows, start=1):
        if progress_callback and (index == 1 or index % 25 == 0 or index == len(project_rows)):
            progress_callback(index, len(project_rows))
        if project_id in excluded_project_ids:
            counts['excluded'] += 1
            details.append({
                'project_id': project_id,
                'client_id': client_id,
                'client_name': client_name,
                'status': 'excluded',
                'rows': 0,
                'warnings': [],
            })
            continue

        savepoint = session.begin_nested() if dry_run else None
        try:
            result = generate_commission_schedule_for_project(session, project_id)
            result_payload = result.to_dict()
        finally:
            if savepoint is not None and savepoint.is_active:
                savepoint.rollback()

        counts[result_payload['status']] += 1
        rows_created += int(result_payload.get('rows_created') or 0)
        details.append({
            'project_id': project_id,
            'client_id': client_id,
            'client_name': client_name,
            'contract_id': result_payload.get('contract_id'),
            'status': result_payload['status'],
            'rows': int(result_payload.get('rows_created') or 0),
            'warnings': result_payload.get('warnings') or [],
        })

    return {
        'dry_run': dry_run,
        'tenant_id': str(tenant_id),
        'projects_checked': len(project_rows),
        'projects_created': counts['created'],
        'payment_rows_created': rows_created,
        'projects_existing': counts['skipped_existing'],
        'projects_missing_data': counts['skipped_missing_data'],
        'projects_before_2022': counts['skipped_before_2022'],
        'projects_not_found': counts['not_found'],
        'projects_excluded': counts['excluded'],
        'details': details,
    }
