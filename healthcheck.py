import json
import urllib.error
import urllib.request

from config import Config


def main() -> int:
    try:
        host = Config.HOST.strip('[]')
        host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
        if ':' in host:
            host = f'[{host}]'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://{host}:{Config.PORT}/api/health', timeout=3) as response:
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
    raise SystemExit(main())
