import json
import sys
import urllib.error
import urllib.request

from config import Config


def _base_url() -> str:
    host = Config.HOST.strip('[]')
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
    if ':' in host:
        host = f'[{host}]'
    return f'http://{host}:{Config.PORT}'


def readiness() -> int:
    """就绪检查：AI 运行时可用才返回 0（适合编排器 readiness probe）。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'{_base_url()}/api/ready', timeout=3) as response:
            status = json.load(response)
        return 0 if isinstance(status, dict) and status.get('ready') is True else 1
    except (OSError, ValueError, urllib.error.URLError):
        return 1


def main(argv=None) -> int:
    args = [] if argv is None else list(argv)
    if '--ready' in args:
        return readiness()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'{_base_url()}/api/health', timeout=3) as response:
            status = json.load(response)
        # Degraded still means the HTTP service is up; do not restart-loop
        # containers just because provider credentials are not configured yet.
        if not isinstance(status, dict):
            return 1
        ready = status.get('runtime_ready')
        details = status.get('details')
        # Degraded still means the HTTP service is up; do not restart-loop
        # containers just because provider credentials are not configured yet.
        if ready is True or details == 'protected' or status.get('status') == 'degraded':
            return 0
        return 1
    except (OSError, ValueError, urllib.error.URLError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
