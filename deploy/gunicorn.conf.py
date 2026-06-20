# Gunicorn configuration for Sightline
# Usage: gunicorn -c deploy/gunicorn.conf.py server:app

import os

# Server socket
bind = "127.0.0.1:5001"
backlog = 2048

# Worker processes
workers = 1          # Single worker — SQLite + ChromaDB don't support multi-process well
threads = 4          # Threading for concurrent requests
worker_class = "gthread"
worker_connections = 1000
timeout = 120        # Long timeout for SITREP pipeline SSE streams
keepalive = 5
graceful_timeout = 30
max_requests = 1000  # Restart workers after N requests (prevents memory leaks)
max_requests_jitter = 50

# Logging
accesslog = "/var/log/reliefagent/access.log"
errorlog = "/var/log/reliefagent/error.log"
loglevel = "info"
capture_output = True

# Custom access log format — omits query string to prevent leaking
# ?nonce= / ?token= / ?api_key= secrets to log files.
# Standard Combined Log Format but with path only (no query string).
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Security
limit_request_line = 8190    # Max size of HTTP request line
limit_request_fields = 100   # Max number of HTTP header fields
limit_request_field_size = 8190  # Max size of HTTP header field value