from math import ceil

from config import Config

host = Config.HOST
if ':' in host and not host.startswith('['):
    host = f'[{host}]'
bind = f'{host}:{Config.PORT}'

# Keep cache and dashboard state in one process while AI I/O uses worker threads.
workers = 1
worker_class = 'gthread'
threads = 4
timeout = max(120, ceil(Config.API_TIMEOUT * (Config.API_MAX_RETRIES + 1) * 2 + 120))
limit_request_line = 16380
