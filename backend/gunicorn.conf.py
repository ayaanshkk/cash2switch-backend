# Gunicorn configuration file
import multiprocessing

# Timeout settings - CRITICAL for bulk imports
timeout = 300  # 5 minutes per request
graceful_timeout = 120  # 2 minutes for graceful shutdown
keepalive = 5

# Worker settings
workers = 2
threads = 4
worker_class = 'sync'

# Logging
loglevel = 'info'
accesslog = '-'
errorlog = '-'

# Binding
bind = '0.0.0.0:10000'