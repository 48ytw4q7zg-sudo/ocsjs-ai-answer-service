from math import ceil

from config import Config, request_budget_seconds

host = Config.HOST
if ':' in host and not host.startswith('['):
    host = f'[{host}]'
bind = f'{host}:{Config.PORT}'

# Keep cache and dashboard state in one process while AI I/O uses worker threads.
workers = 1
worker_class = 'gthread'
threads = 4
# worker 超时 = 单次答题最坏耗时（见 config.request_budget_seconds）+ 120 秒余量；
# 注意 OCS 客户端自身约 60 秒放弃等待，上游长时间无响应时应调低 API_TIMEOUT/API_MAX_RETRIES。
timeout = max(120, ceil(request_budget_seconds(Config.API_TIMEOUT, Config.API_MAX_RETRIES) + 120))
limit_request_line = 16380
