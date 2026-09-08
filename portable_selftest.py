"""All checks use generated fixtures, a loopback provider and disposable data."""

from dataclasses import replace
from contextlib import contextmanager
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import platform
import ssl
import sys
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


def run():
    report = {"passed": False, "checks": [], "python": platform.python_version(),
              "windows": platform.platform(), "machine": platform.machine(),
              "frozen": bool(getattr(sys, "frozen", False))}
    controller = provider = root = None
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)

    @contextmanager
    def workspace():
        with tempfile.TemporaryDirectory(prefix="edubrain-selftest-") as directory:
            try:
                yield directory
            finally:
                errors = []
                for resource, cleanup in ((root, lambda: root.destroy()),
                                          (controller, lambda: controller.close()),
                                          (provider, lambda: (provider.shutdown(), provider.server_close()))):
                    if resource is not None:
                        try:
                            cleanup()
                        except Exception as exc:
                            errors.append(type(exc).__name__)
                # Windows cannot remove the temporary log directory while its
                # handlers are open. Remove them before the directory context exits.
                loggers = [logging.getLogger()] + [value for value in logging.Logger.manager.loggerDict.values()
                                                   if isinstance(value, logging.Logger)]
                for logger in loggers:
                    for handler in list(logger.handlers):
                        filename = getattr(handler, "baseFilename", None)
                        if filename and Path(filename).resolve().is_relative_to(Path(directory).resolve()):
                            logger.removeHandler(handler)
                            handler.close()
                if errors:
                    raise RuntimeError("Self-test cleanup failed: " + ", ".join(errors))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path == "/v1/responses":
                value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Alpha"}]}]}
            elif self.path == "/v1/chat/completions":
                value = {"choices": [{"message": {"content": "Alpha"}}]}
            elif self.path == "/v1/messages":
                value = {"id": "msg_synthetic", "type": "message", "role": "assistant", "model": body.get("model", "fixture"),
                         "content": [{"type": "text", "text": "Alpha"}], "stop_reason": "end_turn", "stop_sequence": None,
                         "usage": {"input_tokens": 1, "output_tokens": 1}}
            else:
                self.send_error(404, "Unknown synthetic provider endpoint")
                return
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    try:
        with workspace() as directory:
            import portable_paths
            portable_paths.activate(data=Path(directory) / "data")
            os.environ["ANTHROPIC_API_KEY"] = "SYNTHETIC_HOST_VALUE_MUST_NOT_LOAD"
            os.environ["PORT"] = "1"
            from portable_settings import Preferences, ProfileStore
            from portable_controller import PortableController
            preferences = Preferences(port=0, max_retries=0, timeout=5)
            controller = PortableController(preferences, data=Path(directory) / "data")
            check("host_environment_isolation", controller.config.ANTHROPIC_API_KEY == "" and controller.config.PORT == 0)
            check("loopback_binding", controller.server.effective_host == "127.0.0.1")
            health = controller.status()
            check("unconfigured_http_responds", health.get("runtime_ready") is False)
            cookies = CookieJar()
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
            session_request = Request(controller.url + "/api/session",
                                      json.dumps({"token": controller.access_token}).encode(),
                                      {"Content-Type": "application/json"}, method="POST")
            with opener.open(session_request, timeout=10) as response:
                check("browser_session_created", response.status == 200 and bool(list(cookies)))
            for path in ("/", "/dashboard", "/docs"):
                with opener.open(controller.url + path, timeout=10) as response:
                    text = response.read().decode("utf-8")
                    check("page_" + path, response.status == 200 and bool(text))
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
            check("bundled_ca_certificates", context.cert_store_stats()["x509_ca"] > 0)
            provider = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=provider.serve_forever, daemon=True).start()
            for protocol in ("openai_responses", "openai_chat", "anthropic"):
                base_path = "" if protocol == "anthropic" else "/v1"
                preferences = replace(preferences, protocol=protocol, base_url=f"http://127.0.0.1:{provider.server_port}{base_path}",
                                      model="gpt-6-astra" if protocol != "anthropic" else "fixture-model")
                controller.apply(preferences, "SYNTHETIC_SELFTEST_KEY", "SYNTHETIC_LOCAL_TOKEN")
                result = controller.ask("Synthetic question", ["Alpha", "Beta"], "single")
                check("provider_" + protocol, "Alpha" in json.dumps(result))
                controller.clear_cache()
            try:
                opener.open(controller.url + "/dashboard", timeout=10)
            except HTTPError as exc:
                check("browser_session_revoked_after_token_change", exc.code == 403)
                exc.close()
            else:
                raise AssertionError("browser_session_revoked_after_token_change")
            integration = controller.integration_config()
            check("ocs_integration_schema", isinstance(integration, list) and len(integration) == 1
                  and integration[0]["data"]["title"] == "${title}"
                  and integration[0]["data"]["options"] == "${options}"
                  and integration[0]["data"]["token"] == controller.access_token
                  and integration[0]["handler"] == "return (res)=> res.code === 1 ? [res.question, res.answer] : [res.msg, undefined]")
            old_model, old_client, old_cache = controller.config.ANTHROPIC_MODEL, controller.module.client, controller.module.cache
            original_builder = controller.module.build_ai_client
            def failed_builder():
                raise ValueError("Synthetic client initialization failure")
            controller.module.build_ai_client = failed_builder
            try:
                try:
                    controller.apply(replace(preferences, model="broken-synthetic-model"), "SYNTHETIC_CHANGED_KEY", "SYNTHETIC_CHANGED_TOKEN")
                except RuntimeError:
                    check("failed_configuration_is_transactional", controller.config.ANTHROPIC_MODEL == old_model
                          and controller.module.client is old_client and controller.module.cache is old_cache
                          and controller.config.ANTHROPIC_API_KEY == "SYNTHETIC_SELFTEST_KEY"
                          and controller.config.ACCESS_TOKEN == "SYNTHETIC_LOCAL_TOKEN")
                else:
                    raise AssertionError("failed_configuration_is_transactional")
            finally:
                controller.module.build_ai_client = original_builder
            store = ProfileStore(Path(directory) / "profile.json")
            credentials = {"api_key": "SYNTHETIC_SELFTEST_KEY", "access_token": "SYNTHETIC_LOCAL_TOKEN"}
            store.save(preferences, credentials=credentials, password="synthetic-password-123")
            check("encrypted_profile_roundtrip", store.unlock("synthetic-password-123") == credentials)
            check("no_plaintext_credentials", "SYNTHETIC_SELFTEST_KEY" not in store.path.read_text(encoding="utf-8"))
            check("profile_preferences_roundtrip", store.load_preferences() == preferences)
            try:
                store.unlock("incorrect-password")
            except ValueError:
                check("wrong_password_rejected", True)
            else:
                raise AssertionError("wrong_password_rejected")
            import tkinter as tk
            from portable_app import PortableWindow
            root = tk.Tk()
            root.withdraw()
            window = PortableWindow(root, controller, store)
            root.update_idletasks()
            check("native_tk_interface", len(window.notebook.tabs()) == 4)
            check("tk_runtime", bool(root.tk.call("info", "patchlevel")))
            root.destroy()
            root = None
            controller.close()
            check("http_thread_stopped", not controller.thread.is_alive())
            controller = None
            provider.shutdown()
            provider.server_close()
            provider = None
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
    return report
