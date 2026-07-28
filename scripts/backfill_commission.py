import argparse
from collections import Counter

from sqlalchemy import String, cast

from backend.db import SessionLocal
from backend.models import Client_Master, Project_Details
from backend.utils.commission_backfill import backfill_commission_schedules


def main():
    parser = argparse.ArgumentParser(description='Backfill commission schedules for Already Renewed projects.')
    parser.add_argument('--tenant-id', required=True)
    parser.add_argument('--execute', action='store_true', help='Commit generated schedules. Default is preview only.')
    parser.add_argument('--exclude-project', action='append', type=int, default=[])
    args = parser.parse_args()

    excluded = set(args.exclude_project)

    if args.execute:
        scope_session = SessionLocal()
        try:
            project_ids = [
                row.project_id
                for row in (
                    scope_session.query(Project_Details.project_id)
                    .join(Client_Master, Project_Details.client_id == Client_Master.client_id)
                    .filter(
                        cast(Client_Master.tenant_id, String) == str(args.tenant_id),
                        Project_Details.status == 'Already Renewed',
                    )
                    .order_by(Project_Details.project_id)
                    .all()
                )
            ]
        finally:
            scope_session.close()

        result = {
            'dry_run': False,
            'tenant_id': str(args.tenant_id),
            'projects_checked': 0,
            'projects_created': 0,
            'payment_rows_created': 0,
            'projects_existing': 0,
            'projects_missing_data': 0,
            'projects_not_found': 0,
            'projects_excluded': 0,
            'details': [],
        }
        batch_size = 25
        for start in range(0, len(project_ids), batch_size):
            batch_ids = set(project_ids[start:start + batch_size])
            batch_session = SessionLocal()
            try:
                batch_result = backfill_commission_schedules(
                    batch_session,
                    args.tenant_id,
                    dry_run=False,
                    excluded_project_ids=excluded,
                    included_project_ids=batch_ids,
                )
                batch_session.commit()
            except Exception:
                batch_session.rollback()
                raise
            finally:
                batch_session.close()

            for key in (
                'projects_checked',
                'projects_created',
                'payment_rows_created',
                'projects_existing',
                'projects_missing_data',
                'projects_not_found',
                'projects_excluded',
            ):
                result[key] += batch_result[key]
            result['details'].extend(batch_result['details'])
            print(f"Committed: {min(start + batch_size, len(project_ids))}/{len(project_ids)}", flush=True)
    else:
        session = SessionLocal()
        try:
            result = backfill_commission_schedules(
                session,
                args.tenant_id,
                dry_run=True,
                excluded_project_ids=excluded,
                progress_callback=lambda current, total: print(
                    f'Progress: {current}/{total}',
                    flush=True,
                ),
            )
            session.rollback()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        warnings = Counter(
            warning
            for detail in result['details']
            for warning in detail['warnings']
        )
        print(f"Mode: {'EXECUTE' if args.execute else 'PREVIEW'}")
        print(f"Projects checked: {result['projects_checked']}")
        print(f"Projects created: {result['projects_created']}")
        print(f"Payment rows created: {result['payment_rows_created']}")
        print(f"Already existing: {result['projects_existing']}")
        print(f"Missing data: {result['projects_missing_data']}")
        print(f"Not found: {result['projects_not_found']}")
        print(f"Excluded: {result['projects_excluded']}")
        print('Warnings:')
        for warning, count in warnings.most_common():
            print(f"  {count}: {warning}")
        print('First creatable projects:')
        creatable = [item for item in result['details'] if item['status'] == 'created']
        for detail in creatable[:10]:
            print(f"  {detail['project_id']}: {detail['client_name']} ({detail['rows']} rows)")
    except Exception:
        raise


if __name__ == '__main__':
    main()
