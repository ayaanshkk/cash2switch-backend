import threading
from datetime import datetime
 
_jobs: dict = {}
_lock = threading.Lock()
 
 
def create_job(job_id: str, total_rows: int, tenant_id=None) -> dict:
    job = {
        'job_id': job_id,
        'tenant_id': tenant_id,
        'status': 'running',        # running | done | failed
        'total': total_rows,
        'processed': 0,
        'successful': 0,
        'duplicates': 0,
        'errors': [],
        'started_at': datetime.utcnow().isoformat(),
        'finished_at': None,
    }
    with _lock:
        _jobs[job_id] = job
    return job
 
 
def update_job(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
 
 
def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else {}
 
 
def append_error(job_id: str, error_msg: str, max_errors: int = 200) -> None:
    """Thread-safe error append with cap to avoid unbounded memory."""
    with _lock:
        if job_id in _jobs:
            errs = _jobs[job_id]['errors']
            if len(errs) < max_errors:
                errs.append(error_msg)
 
 
def finish_job(job_id: str, status: str = 'done') -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]['status'] = status
            _jobs[job_id]['finished_at'] = datetime.utcnow().isoformat()
 
 
def purge_old_jobs(max_age_hours: int = 24) -> int:
    """
    Remove completed jobs older than max_age_hours.
    Call periodically (e.g. via a scheduler or before each import).
    Returns number of jobs removed.
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    removed = 0
    with _lock:
        to_delete = []
        for jid, job in _jobs.items():
            if job['status'] in ('done', 'failed'):
                finished = job.get('finished_at')
                if finished:
                    try:
                        ft = datetime.fromisoformat(finished)
                        if ft < cutoff:
                            to_delete.append(jid)
                    except ValueError:
                        pass
        for jid in to_delete:
            del _jobs[jid]
            removed += 1
    return removed