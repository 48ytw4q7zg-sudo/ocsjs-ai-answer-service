"""Health endpoint smoke test for the local service.

The script intentionally performs minimal, deterministic checks and exits with
non-zero on protocol or connectivity failures. It does not depend on any
external accounts or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional


def _base_url(host: str, port: int) -> str:
    if host in {"0.0.0.0", "::"}:
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/api/health"


def _fetch(url: str, token: Optional[str] = None, timeout: int = 3) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("X-Access-Token", token)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("health response is not a JSON object")
        return payload


def _assert_payload_shape(payload: Dict[str, Any], expect_tokened: bool, expect_protected: bool = False) -> bool:
    if not isinstance(payload.get("status"), str):
        return False
    if payload["status"] not in {"ok", "degraded"}:
        return False
    if payload.get("version") is None:
        return False
    if not isinstance(payload.get("runtime_ready"), bool):
        return False
    if not isinstance(payload.get("cache_enabled"), bool):
        return False
    if not isinstance(payload.get("cache_size"), int) or payload["cache_size"] < 0:
        return False
    if not isinstance(payload.get("uptime_seconds"), (int, float)):
        return False

    if expect_tokened:
        if payload.get("details") is not None:
            return False
        return bool(payload.get("config_source"))

    details = payload.get("details")
    if expect_protected:
        return details == "protected" and payload.get("config_source") is None

    if details is None:
        return bool(payload.get("config_source"))
    return details == "protected" and payload.get("config_source") is None


def check_health(
    host: str,
    port: int,
    token: Optional[str],
    check_protected: bool,
    timeout: int = 3,
    require_ready: bool = False,
) -> int:
    url = _base_url(host, port)
    if os.environ.get("HSMOKEE_NO_TOKEN", "").strip().lower() in {"1", "true", "yes", "y"}:
        test_tokens = [None]
    else:
        query_token = os.environ.get("ACCESS_TOKEN", "")
        query_token = query_token.strip() if isinstance(query_token, str) else ""
        provided_token = token.strip() if isinstance(token, str) else None
        effective_token = provided_token or query_token
        test_tokens = [None]
        if effective_token:
            test_tokens.append(effective_token)
        elif check_protected:
            raise ValueError("check_protected is enabled but no token is configured")

    result = {"url": url, "checks": {}}
    ok = True
    for current in test_tokens:
        is_token_probe = current is not None
        try:
            request_url = url
            request_token = current
            if current:
                request_url = f"{url}?{urlencode({'token': current})}"
                request_token = None
            payload = _fetch(request_url, request_token, timeout=timeout)
            has_expected_shape = _assert_payload_shape(
                payload,
                expect_tokened=is_token_probe,
                expect_protected=(current is None and check_protected),
            )
            if not has_expected_shape:
                raise ValueError("health response shape/protection is unexpected")
            runtime_ready = payload.get("runtime_ready")
            if require_ready and runtime_ready is not True:
                raise ValueError("runtime is not ready")
            result["checks"][current or "anonymous"] = {
                "ok": has_expected_shape,
                "payload": payload,
            }
            ok = ok and has_expected_shape
        except Exception as exc:
            result["checks"][current or "anonymous"] = {"ok": False, "error": str(exc)}
            ok = False

    if os.environ.get("HSMOKEE_DUMP", "").lower() in {"1", "true", "yes"}:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test /api/health endpoint")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Service host")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")), help="Service port")
    parser.add_argument("--token", default=os.environ.get("ACCESS_TOKEN"), help="Token used for auth probe")
    parser.add_argument(
        "--check-protected",
        action="store_true",
        help="If enabled, require anonymous response to be protected when token is configured",
    )
    parser.add_argument("--timeout", type=int, default=3, help="Request timeout in seconds")
    parser.add_argument("--require-ready", action="store_true", help="Require runtime_ready to be True")
    parser.add_argument("--dump", action="store_true", help="Print detailed JSON report")
    options = parser.parse_args(argv)
    if options.dump:
        os.environ["HSMOKEE_DUMP"] = "1"
    if options.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    return check_health(
        options.host.strip(),
        options.port,
        options.token.strip() if options.token else None,
        options.check_protected,
        options.timeout,
        options.require_ready,
    )


if __name__ == "__main__":
    raise SystemExit(main())
