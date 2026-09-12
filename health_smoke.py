"""Health endpoint smoke test for the local service.

The script intentionally performs minimal, deterministic checks and exits with
non-zero on protocol or connectivity failures. It does not depend on any
external accounts or credentials.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode


_SCHEMA_VERSION = "health-smoke/v1"
_MAX_HEALTH_BODY_BYTES = 1024 * 1024


class _HealthProtocolError(ConnectionError):
    """An HTTP framing failure with no server-controlled message."""


def _reject_json_constant(value: str) -> None:
    raise ValueError("health response contains a non-finite JSON number")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("health response contains a non-finite JSON number")
    return number


def _parse_http_status_text(message: str) -> Optional[int]:
    if not message:
        return None
    parts = message.split(":", 1)[0].strip().split()
    if len(parts) >= 2 and parts[0] == "HTTP":
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


def _is_auth_failure(exc: Exception) -> bool:
    if not isinstance(exc, ConnectionError):
        return False
    status = _parse_http_status_text(str(exc))
    return status in {401, 403}


def _base_url(host: str, port: int) -> str:
    if host in {"0.0.0.0", "::"}:
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/api/health"


def _fetch(url: str, timeout: int = 3, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            expected_length = getattr(response, "length", None)
            raw_body = response.read(_MAX_HEALTH_BODY_BYTES + 1)
            if len(raw_body) > _MAX_HEALTH_BODY_BYTES:
                raise ValueError("health response exceeds the 1 MiB limit")
            if isinstance(expected_length, int) and len(raw_body) < expected_length:
                raise _HealthProtocolError("HTTP protocol error: truncated health response")
            body = raw_body.decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Error pages can echo request credentials; only retain the HTTP status.
        exc.close()
        raise ConnectionError(f"HTTP {exc.code}: health request failed") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError("request timeout") from exc
        raise ConnectionError("network error: health endpoint is unreachable") from exc
    except http.client.HTTPException as exc:
        raise _HealthProtocolError("HTTP protocol error: health request failed") from exc
    except socket.timeout as exc:
        raise TimeoutError("request timeout") from exc

    try:
        payload = json.loads(body, parse_constant=_reject_json_constant, parse_float=_parse_finite_float)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("health response is not a JSON object")
    # Reject unpaired Unicode surrogates, including those in optional fields.
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError) as exc:
        raise ValueError("health response contains invalid JSON text") from exc
    return payload


def _fetch_with_token(url: str, token: str, timeout: int = 3) -> Tuple[Dict[str, Any], str]:
    strategies: List[Dict[str, Any]] = [
        {"name": "header_x_access_token", "url": url, "headers": {"X-Access-Token": token}},
        {"name": "header_authorization_bearer", "url": url, "headers": {"Authorization": f"Bearer {token}"}},
        {"name": "query_token", "url": f"{url}?{urlencode({'token': token})}", "headers": {}},
        {"name": "query_access_token", "url": f"{url}?{urlencode({'access_token': token})}", "headers": {}},
    ]
    last_auth_error: Optional[ConnectionError] = None
    last_auth_error_strategy: Optional[str] = None

    for strategy in strategies:
        try:
            return _fetch(strategy["url"], timeout=timeout, headers=strategy["headers"]), strategy["name"]
        except ConnectionError as exc:
            last_auth_error_strategy = strategy["name"]
            if not _is_auth_failure(exc):
                raise
            last_auth_error = exc
            continue
    if last_auth_error is None:
        raise ConnectionError("token mode failed")
    if last_auth_error_strategy is None:
        raise last_auth_error
    raise ConnectionError(
        f"{last_auth_error} [token probe failed, last strategy={last_auth_error_strategy}]"
    ) from last_auth_error


def _assert_payload_shape(
    payload: Dict[str, Any],
    expect_tokened: bool,
    expect_protected: bool = False,
) -> bool:
    def _is_int(value: object, *, allow_zero: bool = True) -> bool:
        if not (isinstance(value, int) and not isinstance(value, bool)):
            return False
        return value >= 0 if allow_zero else value > 0

    def _is_number(value: object) -> bool:
        return (
            isinstance(value, int) and not isinstance(value, bool)
        ) or (isinstance(value, float) and math.isfinite(value))

    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("status"), str):
        return False
    if payload["status"] not in {"ok", "degraded"}:
        return False
    if not isinstance(payload.get("version"), str) or not payload["version"].strip():
        return False
    if not isinstance(payload.get("runtime_ready"), bool):
        return False
    if not isinstance(payload.get("cache_enabled"), bool):
        return False
    if not _is_int(payload.get("cache_size"), allow_zero=True):
        return False
    if not _is_number(payload.get("uptime_seconds")) or payload["uptime_seconds"] < 0:
        return False

    config_source = payload.get("config_source")
    details = payload.get("details")
    if expect_tokened:
        if details is not None:
            return False
        return isinstance(config_source, str) and bool(config_source.strip())

    if expect_protected:
        return details == "protected" and config_source is None

    if details is None:
        return isinstance(config_source, str) and bool(config_source.strip())
    if not isinstance(details, str):
        return False
    return details == "protected" and config_source is None


def _classify_exception(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, _HealthProtocolError):
        return "http_error"
    if isinstance(exc, ConnectionError):
        if _is_auth_failure(exc):
            return "auth_error"
        return "http_error" if _parse_http_status_text(str(exc)) is not None else "network_error"
    if isinstance(exc, ValueError):
        return "invalid_payload"
    if isinstance(exc, EnvironmentError):
        return "io_error"
    return "unexpected_error"


def _safe_output_path(raw_output: Optional[str]) -> Optional[Path]:
    if not raw_output:
        return None
    output = Path(raw_output).expanduser()
    if not output.is_absolute():
        output = Path(__file__).resolve().parent / output
    return output


def _write_report(output: Path, report: Dict[str, Any], checks: List[str]) -> bool:
    tmp_output = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as stream:
            tmp_output = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        tmp_output.replace(output)
        return True
    except (OSError, ValueError) as exc:
        print(f"health_smoke: output write failed: {exc}", file=sys.stderr)
        return False
    finally:
        if tmp_output is not None:
            try:
                tmp_output.unlink(missing_ok=True)
            except OSError:
                pass


def _silence_failed_stdout() -> None:
    """Avoid a second failed flush changing the CLI exit status to 120."""
    try:
        output_fd = sys.stdout.fileno()
        with open(os.devnull, "w", encoding="ascii") as sink:
            os.dup2(sink.fileno(), output_fd)
        sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        pass


def _emit_result(
    result: Dict[str, Any],
    output: Optional[Path],
    dump_json: bool,
    print_summary: bool,
    start_time: float,
    checks: List[str],
) -> int:
    result["checks_count"] = len(result["checks"])
    result["elapsed_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
    result["output"] = str(output) if output else None
    result["exit_code"] = 1 if not result.get("ok") else 0
    result["failure_reasons"] = sorted(set(result.get("failure_reasons", [])).union(checks))
    if output is not None:
        if not _write_report(output, result, checks):
            result["ok"] = False
            result["error"] = "output_write_failed"
            result["exit_code"] = 1
            result["failure_reasons"] = sorted(set(result["failure_reasons"]) | {"output_write_failed"})

    try:
        if dump_json:
            # ASCII escapes keep JSON valid on legacy Windows console encodings.
            print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2), flush=True)
        elif print_summary:
            if result.get("ok"):
                print("health_smoke: OK", flush=True)
            else:
                reasons = ",".join(result.get("failure_reasons", []))
                print(f"health_smoke: FAIL reason={reasons or 'unknown'}", flush=True)
    except (OSError, UnicodeError):
        _silence_failed_stdout()
        result["ok"] = False
        result["error"] = "stdout_write_failed"
        result["exit_code"] = 1
        result["failure_reasons"] = sorted(set(result["failure_reasons"]) | {"stdout_write_failed"})
        if output is not None and not _write_report(output, result, checks):
            result["failure_reasons"] = sorted(set(result["failure_reasons"]) | {"output_write_failed"})
        print("health_smoke: stdout write failed", file=sys.stderr)
    return result["exit_code"]


def check_health(
    host: str,
    port: int,
    token: Optional[str],
    check_protected: bool,
    timeout: int = 3,
    require_ready: bool = False,
    dump_json: bool = False,
    output: Optional[Path] = None,
    print_summary: bool = False,
) -> int:
    url = _base_url(host.strip(), port)
    start_time = time.perf_counter()
    result: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "url": url,
        "checks": {},
        "probe_order": [],
        "ok": True,
        "probe_count": 0,
        "failure_reasons": [],
    }
    checks: List[str] = []

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
            result["checks"]["token"] = {
                "ok": False,
                "error": "check_protected is enabled but no token is configured",
                "error_code": "config_error",
            }
            result["ok"] = False
            result["failure_reasons"] = ["config_error"]
            return _emit_result(result, output, dump_json, print_summary, start_time=start_time, checks=checks)

    ok = True
    for current in test_tokens:
        is_token_probe = current is not None
        probe_name = "token" if is_token_probe else "anonymous"
        result["probe_order"].append(probe_name)
        probe_started = time.perf_counter()
        strategy = "token_probe" if is_token_probe else "query_path"
        try:
            if current:
                payload, token_strategy = _fetch_with_token(url, current, timeout=timeout)
                strategy = token_strategy
            else:
                payload = _fetch(url, timeout=timeout)
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
            result["checks"][probe_name] = {
                "ok": True,
                "payload": payload,
                "strategy": strategy,
                "duration_ms": round((time.perf_counter() - probe_started) * 1000, 2),
            }
            ok = ok and has_expected_shape
        except Exception as exc:
            code = _classify_exception(exc)
            result["checks"][probe_name] = {
                "ok": False,
                "error": str(exc),
                "error_code": code,
                "strategy": strategy,
                "duration_ms": round((time.perf_counter() - probe_started) * 1000, 2),
            }
            checks.append(code)
            ok = False

    result["probe_count"] = len(result["checks"])
    result["failure_reasons"] = sorted(set(checks))
    result["ok"] = bool(ok)
    return _emit_result(result, output, dump_json, print_summary, start_time, checks)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test /api/health endpoint")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Service host")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "5000")),
        help="Service port",
    )
    parser.add_argument("--token", default=os.environ.get("ACCESS_TOKEN"), help="Token used for auth probe")
    parser.add_argument(
        "--check-protected",
        action="store_true",
        help="If enabled, require anonymous response to be protected when token is configured",
    )
    parser.add_argument("--timeout", type=int, default=3, help="Request timeout in seconds")
    parser.add_argument("--require-ready", action="store_true", help="Require runtime_ready to be True")
    parser.add_argument("--dump", action="store_true", help="Print detailed JSON report")
    parser.add_argument("--json", action="store_true", help="Print JSON report (machine-readable)")
    parser.add_argument("--output", help="Write detailed JSON report to file")
    parser.add_argument("--print-summary", action="store_true", help="Print one-line summary")
    options = parser.parse_args(argv)

    host = options.host.strip()
    if not host:
        parser.error("--host cannot be empty")

    dump_json = bool(
        options.dump
        or options.json
        or os.environ.get("HSMOKEE_DUMP", "").strip().lower() in {"1", "true", "yes"}
    )
    if options.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if options.port < 1 or options.port > 65535:
        parser.error("--port must be between 1 and 65535")
    output = _safe_output_path(options.output or os.environ.get("HSMOKEE_OUTPUT"))

    return check_health(
        host=host,
        port=options.port,
        token=options.token.strip() if options.token else None,
        check_protected=options.check_protected,
        timeout=options.timeout,
        require_ready=options.require_ready,
        dump_json=dump_json,
        output=output,
        print_summary=options.print_summary,
    )


if __name__ == "__main__":
    raise SystemExit(main())
