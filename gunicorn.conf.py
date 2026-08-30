# One worker: jobs run in an in-process thread + Queue and are not shared across workers.
bind = "0.0.0.0:5001"
workers = 1
threads = 8
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
