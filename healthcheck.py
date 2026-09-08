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
        return 0 if isinstance(status, dict) and status.get('runtime_ready') is True else 1
    except (OSError, ValueError, urllib.error.URLError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
