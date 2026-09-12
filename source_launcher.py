"""Start the source application with its existing Config and bounded readiness.

This entry uses app.py and its source configuration; it does not activate
portable mode. Importing this helper alone does not load configuration.
"""
import argparse
import http.client
import json
import math
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


class StartupError(RuntimeError):
    pass


def _create_server():
    from config import Config
    from app import app
    from werkzeug.serving import WSGIRequestHandler, make_server

    class RequestHandler(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            # Query strings can contain the local access token.
            pass

    app.debug = Config.DEBUG
    host = Config.HOST.strip().strip("[]")
    return make_server(host, Config.PORT, app, threaded=True, request_handler=RequestHandler), host


def _browser_url(host, port):
    host = {"0.0.0.0": "127.0.0.1", "::": "::1", "localhost": "127.0.0.1"}.get(host, host)
    if ":" in host:
        host = "[" + host + "]"
    return f"http://{host}:{port}"


def _probe_health(url, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "/api/health", timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                return False
            value = json.loads(body)
        return (isinstance(value, dict) and value.get("status") in ("ok", "degraded")
                and isinstance(value.get("runtime_ready"), bool))
    except (OSError, ValueError, http.client.HTTPException):
        return False


def main(argv=None, *, block=True):
    parser = argparse.ArgumentParser(description="Start the source-configured OCSJS service")
    parser.add_argument("--timeout", type=float, default=20.0, help="Maximum startup/readiness wait in seconds")
    parser.add_argument("--no-browser", action="store_true", help="Keep the service in this console without opening a browser")
    options = parser.parse_args(argv)
    if not math.isfinite(options.timeout) or options.timeout <= 0:
        parser.error("--timeout must be a positive finite number")

    outcome = queue.Queue()
    cancelled = threading.Event()
    state_lock = threading.Lock()
    owned = {}

    def serve():
        try:
            server, host = _create_server()
            with state_lock:
                if cancelled.is_set():
                    server.server_close()
                    return
                owned["server"] = server
                outcome.put(("server", (server, host)))
            server.serve_forever(poll_interval=0.1)
        except BaseException as exc:
            outcome.put(("error", type(exc).__name__))

    deadline = time.monotonic() + options.timeout
    worker = threading.Thread(target=serve, name="source-http", daemon=True)
    worker.start()
    try:
        try:
            kind, value = outcome.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise StartupError("Startup timed out") from None
        if kind == "error":
            raise StartupError("Service initialization failed (" + value + ")")
        server, host = value
        url = _browser_url(host, server.server_port)
        while worker.is_alive() and time.monotonic() < deadline:
            if _probe_health(url, min(1.0, max(0.01, deadline - time.monotonic()))):
                break
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        else:
            raise StartupError("Service did not become HTTP-ready before the deadline")
        if not worker.is_alive():
            raise StartupError("Service stopped during startup")
        print("Service ready: " + url, flush=True)
        print("Press Ctrl+C in this window to stop the service.", flush=True)
        if not options.no_browser:
            try:
                opened = webbrowser.open(url)
            except Exception:
                opened = False
            if not opened:
                print("Browser could not be opened. Use the service URL above.", file=sys.stderr)
        if block:
            while worker.is_alive():
                worker.join(timeout=0.2)
            raise StartupError("Service stopped unexpectedly")
        return 0
    except KeyboardInterrupt:
        return 0
    except StartupError as exc:
        print("source_launcher: " + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print("source_launcher: startup failed (" + type(exc).__name__ + ")", file=sys.stderr)
        return 1
    finally:
        cancelled.set()
        with state_lock:
            server = owned.get("server")
        if server is not None:
            if worker.is_alive():
                server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
