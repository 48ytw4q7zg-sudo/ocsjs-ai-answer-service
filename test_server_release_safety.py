"""Focused release regressions. Run this module alone in a fresh Python process.

The fixture blocks credential files and non-loopback sockets before importing
the service. All keys, provider responses and launcher configuration are synthetic.
"""
import contextlib
import importlib
import io
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
service = None
_fixture = None
_patches = None


def setUpModule():
    global service, _fixture, _patches
    if "app" in sys.modules or "config" in sys.modules:
        raise RuntimeError("Run test_server_release_safety alone in a fresh process")
    safe = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
    os.environ.clear()
    os.environ.update(safe)
    _fixture = tempfile.TemporaryDirectory(prefix=".server-release-test-", dir=ROOT)
    os.environ.update(
        ANTHROPIC_CONFIG_DIR=str(Path(_fixture.name) / "empty-sdk-config"),
        ANTHROPIC_API_KEY="SYNTHETIC_BOOT_KEY",
        ANTHROPIC_BASE_URL="http://provider.invalid",
        ANTHROPIC_MODEL="synthetic-model",
        API_MAX_RETRIES="0",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )

    def guard(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            name = os.fsdecode(args[0]).replace("\\", "/").lower()
            if name.rsplit("/", 1)[-1].startswith(".env") or "/.claude/" in name or "/.cc-switch/" in name:
                raise PermissionError("Credential-file access blocked by test")
        if event == "socket.connect" and isinstance(args[1], tuple):
            if args[1][0] not in ("127.0.0.1", "::1"):
                raise RuntimeError("Non-loopback connection blocked by test")
        if event == "socket.getaddrinfo" and args[0] not in ("127.0.0.1", "::1", "localhost", None):
            raise RuntimeError("External name lookup blocked by test")

    sys.addaudithook(guard)
    _patches = contextlib.ExitStack()
    _patches.enter_context(patch("dotenv.load_dotenv", return_value=False))
    _patches.enter_context(patch("ccswitch._find_settings_path", return_value=None))
    import config
    config.Config.LOG_DIR = str(Path(_fixture.name) / "logs")
    service = importlib.import_module("app")
    if service.client is not None:
        service.client.close()
    service.client = None


def tearDownModule():
    if _patches is not None:
        _patches.close()
    if _fixture is not None:
        for logger in [logging.getLogger()] + [
            value for value in logging.Logger.manager.loggerDict.values() if isinstance(value, logging.Logger)
        ]:
            for handler in list(logger.handlers):
                filename = getattr(handler, "baseFilename", None)
                if filename and Path(filename).resolve().is_relative_to(Path(_fixture.name)):
                    logger.removeHandler(handler)
                    handler.close()
        _fixture.cleanup()


def response_body(protocol, text="complete answer", truncated=False):
    if protocol == "openai_chat":
        result = {"choices": [{"message": {"content": text}}]}
        if truncated:
            result["choices"][0]["finish_reason"] = "length"
        return result
    if protocol == "openai_responses":
        result = {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
        if truncated:
            result.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        return result
    result = {
        "id": "msg_synthetic", "type": "message", "role": "assistant", "model": "synthetic-model",
        "content": [{"type": "text", "text": text}], "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    if truncated:
        result["stop_reason"] = "max_tokens"
    return result


class ServerReleaseSafetyTests(unittest.TestCase):
    def setUp(self):
        from utils import SimpleCache
        self.configuration = {key: value for key, value in vars(service.Config).items() if key.isupper()}
        self.runtime = service.client, service.cache, service._runtime_init_error
        self.generations = getattr(service, "_client_generations", {}).copy()
        self.epoch = getattr(service, "_cache_epoch", 0)
        service.Config.ACCESS_TOKEN = None
        service.Config.API_MAX_RETRIES = 0
        service.Config.ANTHROPIC_MODEL = "synthetic-model"
        service.Config.ANTHROPIC_API_KEY = "SYNTHETIC_USER_KEY"
        service.Config.ANTHROPIC_BASE_URL = "http://provider.invalid"
        service.Config.ENABLE_CACHE = True
        service.Config.IS_PORTABLE = False
        service.cache = SimpleCache(60)
        service._runtime_init_error = None
        self.http = service.app.test_client()
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        for key, value in self.configuration.items():
            setattr(service.Config, key, value)
        service.client, service.cache, service._runtime_init_error = self.runtime
        if hasattr(service, "_client_generations"):
            service._client_generations = self.generations
            service._cache_epoch = self.epoch

    def transport(self, protocol, body, status=200):
        import httpx
        import anthropic
        try:
            import httpx2
        except ImportError:
            httpx2 = httpx
        library = httpx2 if protocol == "anthropic" else httpx
        requests = []

        def handle(request):
            requests.append(request)
            return library.Response(status, json=body, request=request)

        return library.Client(transport=library.MockTransport(handle)), requests

    def client(self, protocol, body, status=200):
        import anthropic
        from provider_clients import OpenAICompatibleClient
        http, requests = self.transport(protocol, body, status)
        if protocol == "anthropic":
            client = anthropic.Anthropic(
                api_key="SYNTHETIC_USER_KEY", base_url="http://provider.invalid", max_retries=0, http_client=http,
            )
        else:
            client = OpenAICompatibleClient(
                "SYNTHETIC_USER_KEY", "http://provider.invalid/v1", protocol, max_retries=0, http_client=http,
            )
        self.clients.append(client)
        return client, requests

    def test_portable_headers_and_auth_are_isolated_without_environment_mutation(self):
        import anthropic
        service.Config.IS_PORTABLE = True
        ambient = {
            "ANTHROPIC_AUTH_TOKEN": "SYNTHETIC_HOST_AUTH",
            "ANTHROPIC_CUSTOM_HEADERS": (
                "Authorization: Bearer SYNTHETIC_CUSTOM_AUTH\n"
                "authorization: Bearer SYNTHETIC_OTHER_AUTH\n"
                "X-Api-Key: SYNTHETIC_CUSTOM_KEY\nx-api-key: SYNTHETIC_OTHER_KEY\n"
                "X-Host-Secret: SYNTHETIC_PRIVATE_VALUE\nanthropic-version: INVALID_HOST_VERSION"
            ),
        }
        http, requests = self.transport("anthropic", response_body("anthropic"))
        with patch.dict(os.environ, ambient):
            previous_environment = dict(os.environ)
            with patch.object(anthropic, "DefaultHttpxClient", return_value=http):
                client = service.build_ai_client()
            self.clients.append(client)
            service.client = client
            self.assertEqual(service._call_ai("synthetic isolation"), "complete answer")
            self.assertEqual(dict(os.environ), previous_environment)
            self.assertNotEqual(client.auth_token, ambient["ANTHROPIC_AUTH_TOKEN"])
        headers = requests[0].headers
        self.assertEqual(headers["x-api-key"], "SYNTHETIC_USER_KEY")
        self.assertNotIn("authorization", headers)
        self.assertNotIn("x-host-secret", headers)
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("SYNTHETIC_CUSTOM", str(headers))
        self.assertNotIn("SYNTHETIC_OTHER", str(headers))

    def test_source_mode_retains_explicit_environment_header_semantics(self):
        import anthropic
        http, requests = self.transport("anthropic", response_body("anthropic"))
        constructor = anthropic.Anthropic

        def build(**kwargs):
            return constructor(**kwargs, http_client=http)

        with patch.dict(os.environ, {"ANTHROPIC_CUSTOM_HEADERS": "X-Source-Setting: synthetic-source"}):
            with patch.object(anthropic, "Anthropic", side_effect=build):
                client = service.build_ai_client()
            self.clients.append(client)
            service.client = client
            service._call_ai("synthetic source mode")
        self.assertEqual(requests[0].headers["x-source-setting"], "synthetic-source")

    def test_upstream_errors_and_unexpected_exceptions_never_echo_log_bodies(self):
        marker = "SYNTHETIC_PRIVATE_ERROR_BODY"
        api_client, _ = self.client("anthropic", {"type": "error", "error": {"type": "permission_error", "message": marker}}, 403)
        for exception in (None, RuntimeError(marker), ValueError(marker)):
            with self.subTest(exception=type(exception).__name__):
                if exception is None:
                    service.client = api_client
                else:
                    def create(**kwargs):
                        raise exception
                    service.client = SimpleNamespace(messages=SimpleNamespace(create=create))
                stream = io.StringIO()
                with patch.object(service.logger, "handlers", [logging.StreamHandler(stream)]), patch.object(service.time, "sleep", return_value=None):
                    result = self.http.post("/api/search", json={"question": "synthetic error " + type(exception).__name__})
                self.assertGreaterEqual(result.status_code, 500)
                self.assertNotIn(marker, stream.getvalue())
                self.assertNotIn("Traceback", stream.getvalue())
                self.assertNotIn(marker, result.get_data(as_text=True))

    def test_all_three_protocols_reject_explicit_truncation_without_caching(self):
        from utils import SimpleCache
        for protocol in ("anthropic", "openai_chat", "openai_responses"):
            with self.subTest(protocol=protocol):
                service.client, requests = self.client(protocol, response_body(protocol, "The causes are", True))
                service.cache = SimpleCache(60)
                question = "synthetic incomplete " + protocol
                response = self.http.post("/api/search", json={"question": question, "type": "short-answer"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json["code"], 0)
                self.assertEqual(response.json["error_code"], "incomplete_response")
                self.assertIsNone(service.cache.get(question, "short-answer", ""))

    def test_missing_optional_completion_markers_remain_compatible(self):
        for protocol in ("anthropic", "openai_chat", "openai_responses"):
            with self.subTest(protocol=protocol):
                service.client, _ = self.client(protocol, response_body(protocol))
                response = self.http.post("/api/search", json={"question": "synthetic complete " + protocol})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["answer"], "complete answer")

    def test_incomplete_responses_message_is_rejected_without_top_level_marker(self):
        body = response_body("openai_responses", "partial")
        body["output"][0]["status"] = "incomplete"
        service.client, _ = self.client("openai_responses", body)
        response = self.http.post("/api/search", json={"question": "synthetic incomplete message"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error_code"], "incomplete_response")
        self.assertEqual(len(service.cache), 0)

    def test_reload_keeps_leased_client_alive_and_does_not_repopulate_either_cache(self):
        import httpx
        from provider_clients import OpenAICompatibleClient
        selected, release = threading.Event(), threading.Event()

        class PausingClient(OpenAICompatibleClient):
            @property
            def messages(self):
                selected.set()
                if not release.wait(3):
                    raise RuntimeError("Synthetic scheduling timeout")
                return self

        http, _ = self.transport("openai_chat", response_body("openai_chat"))
        old = PausingClient("SYNTHETIC_KEY", "http://provider.invalid/v1", "openai_chat", max_retries=0, http_client=http)
        replacement, _ = self.client("openai_chat", response_body("openai_chat"))
        self.clients.append(old)
        service.client = old
        old_cache = service.cache
        observed = {}

        def ask():
            response = service.app.test_client().post("/api/search", json={"question": "synthetic reload window"})
            observed["status"] = response.status_code

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        try:
            self.assertTrue(selected.wait(2))
            with patch.object(service, "build_ai_client", return_value=replacement):
                service._runtime_initialize()
            self.assertFalse(http.is_closed)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed["status"], 200)
        self.assertTrue(http.is_closed)
        self.assertEqual(len(old_cache), 0)
        self.assertEqual(len(service.cache), 0)

    def test_retired_client_closes_after_failed_inflight_call(self):
        entered, release = threading.Event(), threading.Event()

        class Client:
            closes = 0
            @property
            def messages(self):
                return self
            def create(self, **kwargs):
                entered.set()
                release.wait(3)
                raise ValueError("SYNTHETIC_INFLIGHT_FAILURE")
            def close(self):
                self.closes += 1

        old = Client()
        replacement, _ = self.client("openai_chat", response_body("openai_chat"))
        service.client = old
        observed = {}
        worker = threading.Thread(target=lambda: observed.update(
            status=service.app.test_client().post("/api/search", json={"question": "synthetic failing inflight"}).status_code
        ), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with patch.object(service, "build_ai_client", return_value=replacement):
                service._runtime_initialize()
            self.assertEqual(old.closes, 0)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(old.closes, 1)
        self.assertEqual(observed["status"], 500)

    def test_network_calls_remain_parallel(self):
        both, release = threading.Event(), threading.Event()
        count, lock = [0], threading.Lock()

        def create(**kwargs):
            with lock:
                count[0] += 1
                if count[0] == 2:
                    both.set()
            release.wait(3)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="complete answer")])

        service.client = SimpleNamespace(messages=SimpleNamespace(create=create))
        answers = []
        workers = [threading.Thread(target=lambda: answers.append(service._call_ai("synthetic parallel")), daemon=True) for _ in range(2)]
        for worker in workers:
            worker.start()
        try:
            self.assertTrue(both.wait(2), "Provider calls were serialized")
        finally:
            release.set()
            for worker in workers:
                worker.join(3)
        self.assertEqual(answers, ["complete answer", "complete answer"])

    def test_cache_clear_discards_an_already_running_answer(self):
        entered, release = threading.Event(), threading.Event()

        def create(**kwargs):
            entered.set()
            release.wait(3)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="complete answer")])

        service.client = SimpleNamespace(messages=SimpleNamespace(create=create))
        worker = threading.Thread(target=lambda: service.app.test_client().post(
            "/api/search", json={"question": "synthetic clear window"}
        ), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.http.post("/api/cache/clear").status_code, 200)
        finally:
            release.set()
            worker.join(3)
        self.assertIsNone(service.cache.get("synthetic clear window"))

    def test_failed_candidate_initialization_closes_candidate_only(self):
        old = SimpleNamespace(close=lambda: None)
        candidate = SimpleNamespace(close=unittest.mock.Mock())
        service.client = old
        with patch.object(service, "build_ai_client", return_value=candidate), patch.object(service, "SimpleCache", side_effect=ValueError("synthetic cache failure")):
            with self.assertRaises(ValueError):
                service._runtime_initialize()
        candidate.close.assert_called_once()
        self.assertIs(service.client, old)


    def _assert_provider_state(self, protocol, body, case, *, accepted=False):
        from utils import SimpleCache
        service.client, requests = self.client(protocol, body)
        service.cache = SimpleCache(60)
        question = "synthetic final-state " + case
        responses = [
            self.http.post("/api/search", json={"question": question, "type": "short-answer"})
            for _ in range(2)
        ]
        self.assertEqual(len(requests), 1 if accepted else 2,
                         "A rejected state was cached, or provider retries were added")
        for response in responses:
            self.assertEqual(response.status_code, 200 if accepted else 503)
            self.assertEqual(response.json["code"], 1 if accepted else 0)
            if accepted:
                self.assertEqual(response.json["answer"], "complete answer")
            else:
                self.assertEqual(response.json["error_code"], "incomplete_response")
                self.assertNotIn("SYNTHETIC_UNKNOWN_STATE", response.get_data(as_text=True))
        cached = service.cache.get(question, "short-answer", "")
        self.assertEqual(cached, "complete answer" if accepted else None)

    @staticmethod
    def _state_body(protocol, state, *, message_level=False):
        body = response_body(protocol)
        if protocol == "anthropic":
            body["stop_reason"] = state
        elif protocol == "openai_chat":
            body["choices"][0]["finish_reason"] = state
        elif message_level:
            body["output"][0]["status"] = state
        else:
            body["status"] = state
        return body

    def test_reported_nine_nonfinal_states_never_succeed_or_hit_cache(self):
        cases = [
            ("openai_responses", state, False)
            for state in ("failed", "cancelled", "in_progress", "queued")
        ] + [
            ("openai_responses", "in_progress", True),
            ("anthropic", "pause_turn", False),
            ("anthropic", "tool_use", False),
            ("openai_chat", "content_filter", False),
            ("openai_chat", "tool_calls", False),
        ]
        for index, (protocol, state, message_level) in enumerate(cases):
            with self.subTest(protocol=protocol, state=state, message_level=message_level):
                body = self._state_body(protocol, state, message_level=message_level)
                self._assert_provider_state(protocol, body, "reported-" + str(index))

    def test_unknown_or_empty_explicit_states_fail_closed(self):
        levels = [
            ("anthropic", False), ("openai_chat", False),
            ("openai_responses", False), ("openai_responses", True),
        ]
        for index, (protocol, message_level) in enumerate(levels):
            for state in ("SYNTHETIC_UNKNOWN_STATE", ""):
                with self.subTest(protocol=protocol, message_level=message_level, state=state):
                    body = self._state_body(protocol, state, message_level=message_level)
                    self._assert_provider_state(protocol, body, "unknown-" + str(index) + "-" + state)

    def test_explicit_final_none_and_omitted_states_still_succeed_and_cache(self):
        controls = []
        for protocol, states in (
            ("anthropic", ("end_turn", "stop_sequence", None)),
            ("openai_chat", ("stop", None)),
            ("openai_responses", ("completed", None)),
        ):
            for state in states:
                body = self._state_body(protocol, state)
                if protocol == "openai_responses":
                    body["output"][0]["status"] = state
                controls.append((protocol, body))
            controls.append((protocol, response_body(protocol)))
        for index, (protocol, body) in enumerate(controls):
            with self.subTest(protocol=protocol, case=index):
                self._assert_provider_state(protocol, body, "control-" + str(index), accepted=True)

    def test_pending_tool_payloads_are_not_final_text_answers(self):
        cases = []
        body = response_body("anthropic")
        body["content"].append({"type": "tool_use", "id": "tool_synthetic", "name": "synthetic", "input": {}})
        cases.append(("anthropic", body))
        body = response_body("openai_chat")
        body["choices"][0]["message"]["tool_calls"] = [
            {"id": "call_synthetic", "type": "function", "function": {"name": "synthetic", "arguments": "{}"}}
        ]
        cases.append(("openai_chat", body))
        body = response_body("openai_chat")
        body["choices"][0]["message"]["function_call"] = {"name": "synthetic", "arguments": "{}"}
        cases.append(("openai_chat", body))
        for kind in ("function_call", "custom_tool_call"):
            body = response_body("openai_responses")
            body["status"] = body["output"][0]["status"] = "completed"
            body["output"].append({
                "type": kind, "id": "tool_synthetic", "call_id": "call_synthetic",
                "name": "synthetic", "arguments": "{}", "input": "", "status": "completed",
            })
            cases.append(("openai_responses", body))
        for index, (protocol, body) in enumerate(cases):
            with self.subTest(protocol=protocol, case=index):
                self._assert_provider_state(protocol, body, "pending-tool-" + str(index))


class SourceLauncherTests(unittest.TestCase):
    def launch_stub(self, *, valid=True, port=0, broken_import=False):
        launcher = importlib.import_module("source_launcher")
        with tempfile.TemporaryDirectory(prefix="launcher-", dir=_fixture.name) as folder:
            root = Path(folder)
            shutil.copyfile(launcher.__file__, root / "source_launcher.py")
            (root / "config.py").write_text(
                "class Config:\n    HOST = '127.0.0.1'\n    PORT = " + str(port) + "\n    DEBUG = False\n", encoding="utf-8")
            if broken_import:
                app = "raise ImportError('SYNTHETIC_PRIVATE_IMPORT_DETAIL')\n"
            else:
                body = json.dumps({"status": "degraded", "runtime_ready": False} if valid else {"wrong": True})
                app = (
                    "def app(environ, start_response):\n"
                    "    body = " + repr(body.encode()) + "\n"
                    "    start_response('200 OK', [('Content-Type','application/json'),('Content-Length',str(len(body)))])\n"
                    "    return [body]\n"
                )
            (root / "app.py").write_text(app, encoding="utf-8")
            code = "import source_launcher; raise SystemExit(source_launcher.main(['--no-browser','--timeout','2'], block=False))"
            return subprocess.run([sys.executable, "-B", "-c", code], cwd=root,
                                  env=dict(os.environ), capture_output=True, text=True, encoding="utf-8", timeout=8)

    def test_actual_source_stub_port_and_degraded_liveness_are_used(self):
        result = self.launch_stub()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"Service ready: http://127\.0\.0\.1:[1-9][0-9]+")
        self.assertNotIn(":0\n", result.stdout)

    def test_invalid_health_never_reports_success(self):
        result = self.launch_stub(valid=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Service ready:", result.stdout)

    def test_source_import_failure_is_visible_safe_and_nonzero(self):
        result = self.launch_stub(broken_import=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ImportError", result.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE_IMPORT_DETAIL", result.stderr)
        self.assertNotIn("Service ready:", result.stdout)

    def test_busy_source_port_is_not_mistaken_for_existing_service_success(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            result = self.launch_stub(port=listener.getsockname()[1])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Service ready:", result.stdout)

    def test_browser_opens_only_after_own_server_is_ready(self):
        launcher = importlib.import_module("source_launcher")
        from werkzeug.serving import make_server

        def application(environ, start_response):
            body = b'{"status":"degraded","runtime_ready":false}'
            start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
            return [body]

        server = make_server("127.0.0.1", 0, application, threaded=True)
        calls = []

        def open_browser(url):
            self.assertTrue(launcher._probe_health(url, 1))
            calls.append(url)
            return True

        with patch.object(launcher, "_create_server", return_value=(server, "127.0.0.1")), patch.object(launcher.webbrowser, "open", side_effect=open_browser):
            self.assertEqual(launcher.main(["--timeout", "2"], block=False), 0)
        self.assertEqual(calls, [f"http://127.0.0.1:{server.server_port}"])

    def test_browser_not_opened_after_start_failure(self):
        launcher = importlib.import_module("source_launcher")
        with patch.object(launcher, "_create_server", side_effect=RuntimeError("SYNTHETIC_PRIVATE_FAILURE")), patch.object(launcher.webbrowser, "open") as browser:
            self.assertEqual(launcher.main(["--timeout", "1"], block=False), 1)
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
