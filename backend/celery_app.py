# # backend/celery_app.py
# """
# Celery Configuration for StreemLyne CRM
# Handles async task processing for bulk imports and assignments
# """
# from celery import Celery
# import os
# import logging

# # Configure logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# # Redis URL - supports both local and production
# REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# # Initialize Celery app
# celery_app = Celery(
#     'streemlyne_tasks',
#     broker=REDIS_URL,
#     backend=REDIS_URL,
# )

# # Celery Configuration
# celery_app.conf.update(
#     # Serialization
#     task_serializer='json',
#     accept_content=['json'],
#     result_serializer='json',
    
#     # Timezone
#     timezone='UTC',
#     enable_utc=True,
    
#     # Task execution
#     task_track_started=True,
#     task_time_limit=600,  # 10 minutes max
#     task_soft_time_limit=540,  # 9 minutes soft limit
    
#     # Result backend
#     result_expires=7200,  # Keep results for 2 hours
#     result_persistent=True,
    
#     # Worker settings
#     worker_prefetch_multiplier=1,
#     worker_max_tasks_per_child=1000,
#     worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
#     worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s',
    
#     # Retry settings
#     task_acks_late=True,
#     task_reject_on_worker_lost=True,
    
#     # Broker settings
#     broker_connection_retry_on_startup=True,
#     broker_connection_retry=True,
#     broker_connection_max_retries=10,
# )

# # Auto-discover tasks
# celery_app.autodiscover_tasks(['backend.tasks'])

# logger.info(f"✅ Celery initialized with broker: {REDIS_URL}")

# @celery_app.task(bind=True)
# def debug_task(self):
#     """Debug task to test Celery setup"""
#     print(f'Request: {self.request!r}')
#     return {'status': 'ok', 'message': 'Celery is working!'}