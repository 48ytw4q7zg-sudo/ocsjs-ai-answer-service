"""Credential-free regressions for the health smoke CLI and report contract."""

import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import health_smoke as smoke


def healthy_payload(**changes):
    payload = {
        "status": "ok", "version": "test-version", "runtime_ready": True,
        "cache_enabled": True, "cache_size": 0, "uptime_seconds": 1.5,
        "config_source": "synthetic-test",
    }
    payload.update(changes)
    return payload


class HealthSmokeTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix=".health-smoke-test-", dir=Path(__file__).parent)
        self.addCleanup(self.work.cleanup)
        self.output = Path(self.work.name) / "report.json"
        self.clean_env = {
            name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP")
            if name in os.environ
        }
        environment = patch.dict(os.environ, self.clean_env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def run_main(self, *extra, output=True, json_output=True):
        args = ["--host", "127.0.0.1", "--port", "5000"]
        if json_output:
            args.append("--json")
        if output:
            args.extend(["--output", str(self.output)])
        args.extend(extra)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = smoke.main(args)
        report = json.loads(stdout.getvalue()) if json_output else stdout.getvalue()
        return code, report, stderr.getvalue()

    def assert_saved_result(self, code, report, expected_code):
        self.assertEqual(code, expected_code)
        self.assertEqual(report["exit_code"], code)
        self.assertIs(report["ok"], code == 0)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), report)

    def wire(self, body=None, error=None):
        opener = MagicMock()
        if error is not None:
            opener.open.side_effect = error
        else:
            opener.open.return_value.__enter__.return_value.read.return_value = body
        return patch.object(smoke.urllib.request, "build_opener", return_value=opener)

    def test_http_200_invalid_shapes_fail_probe_and_saved_report(self):
        cases = [
            {}, healthy_payload(status="unexpected"), healthy_payload(version=True),
            healthy_payload(version=" "), healthy_payload(runtime_ready=1),
            healthy_payload(cache_enabled=0), healthy_payload(cache_size=True),
            healthy_payload(cache_size=-1), healthy_payload(uptime_seconds=True),
            healthy_payload(uptime_seconds=-1), healthy_payload(uptime_seconds=float("inf")),
            healthy_payload(config_source=""), healthy_payload(details="protected"),
            [], None, "not an object",
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.wire(json.dumps(payload).encode()):
                code, report, stderr = self.run_main()
            self.assert_saved_result(code, report, 1)
            self.assertEqual(report["failure_reasons"], ["invalid_payload"])
            self.assertFalse(report["checks"]["anonymous"]["ok"])
            self.assertEqual(report["checks"]["anonymous"]["error_code"], "invalid_payload")
            self.assertEqual(report["probe_order"], ["anonymous"])
            self.assertEqual(report["probe_count"], 1)
            self.assertEqual(report["checks_count"], 1)
            self.assertEqual(stderr, "")

    def test_invalid_json_has_stable_failure_reason(self):
        with self.wire(b"not JSON"):
            code, report, _ = self.run_main()
        self.assert_saved_result(code, report, 1)
        self.assertEqual(report["failure_reasons"], ["invalid_payload"])

    def test_invalid_utf8_nonfinite_numbers_surrogates_and_oversize_are_rejected(self):
        cases = [
            json.dumps(healthy_payload()).encode().replace(b"test-version", b"\xff"),
            json.dumps(healthy_payload(diagnostic=float("nan"))).encode(),
            json.dumps(healthy_payload(diagnostic=float("inf"))).encode(),
            json.dumps(healthy_payload(diagnostic="overflow")).encode().replace(b'"overflow"', b"1e9999"),
            json.dumps(healthy_payload(version="\ud800")).encode(),
            json.dumps(healthy_payload(diagnostic="\ud800")).encode(),
            b" " * (smoke._MAX_HEALTH_BODY_BYTES + 1),
        ]
        for index, body in enumerate(cases):
            with self.subTest(case=index), self.wire(body):
                code, report, _ = self.run_main()
            self.assert_saved_result(code, report, 1)
            self.assertEqual(report["failure_reasons"], ["invalid_payload"])

    def test_http_protocol_failures_do_not_echo_received_data(self):
        for error in (
            http.client.BadStatusLine("synthetic-private-marker"),
            http.client.IncompleteRead(b"synthetic-private-marker", 100),
            http.client.RemoteDisconnected("synthetic-private-marker"),
        ):
            with self.subTest(error=type(error).__name__), self.wire(error=error):
                code, report, stderr = self.run_main()
            self.assert_saved_result(code, report, 1)
            self.assertEqual(report["failure_reasons"], ["http_error"])
            self.assertNotIn("synthetic-private-marker", json.dumps(report) + stderr)

    def test_valid_health_and_degraded_liveness_are_supported(self):
        for payload in (healthy_payload(), healthy_payload(status="degraded", runtime_ready=False)):
            with self.subTest(payload=payload), self.wire(json.dumps(payload).encode()):
                code, report, stderr = self.run_main()
            self.assert_saved_result(code, report, 0)
            self.assertEqual(report["failure_reasons"], [])
            self.assertEqual(report["checks_count"], 1)
            self.assertEqual(stderr, "")

    def test_require_ready_fails_consistently(self):
        with self.wire(json.dumps(healthy_payload(runtime_ready=False)).encode()):
            code, report, _ = self.run_main("--require-ready")
        self.assert_saved_result(code, report, 1)
        self.assertFalse(report["checks"]["anonymous"]["ok"])
        self.assertTrue(report["failure_reasons"])

    def test_wrong_token_response_shape_only_fails_token_probe(self):
        protected = healthy_payload(details="protected", config_source=None)
        with self.wire(json.dumps(protected).encode()):
            code, report, _ = self.run_main("--token", "synthetic-test-token", "--check-protected")
        self.assert_saved_result(code, report, 1)
        self.assertTrue(report["checks"]["anonymous"]["ok"])
        self.assertFalse(report["checks"]["token"]["ok"])
        self.assertEqual(report["failure_reasons"], ["invalid_payload"])
        self.assertEqual(report["probe_order"], ["anonymous", "token"])
        self.assertNotIn("synthetic-test-token", json.dumps(report))

    def test_missing_protection_configuration_is_reported_without_request(self):
        with patch.object(smoke, "_fetch") as fetch:
            code, report, _ = self.run_main("--check-protected")
        self.assert_saved_result(code, report, 1)
        self.assertEqual(report["failure_reasons"], ["config_error"])
        self.assertEqual(report["checks_count"], 1)
        self.assertEqual(report["probe_count"], 0)
        fetch.assert_not_called()

    def test_network_and_timeouts_are_not_http_errors(self):
        cases = [
            (urllib.error.URLError(ConnectionRefusedError("synthetic refusal")), "network_error"),
            (urllib.error.URLError(socket.gaierror("synthetic DNS failure")), "network_error"),
            (urllib.error.URLError(socket.timeout("synthetic timeout")), "timeout"),
            (socket.timeout("synthetic timeout"), "timeout"),
            (ConnectionResetError("synthetic reset"), "network_error"),
        ]
        for error, reason in cases:
            with self.subTest(reason=reason, error=type(error).__name__), self.wire(error=error):
                code, report, _ = self.run_main()
            self.assert_saved_result(code, report, 1)
            self.assertEqual(report["failure_reasons"], [reason])
            self.assertEqual(report["checks"]["anonymous"]["error_code"], reason)

    def test_http_and_auth_failures_do_not_echo_error_bodies(self):
        for status, reason in ((401, "auth_error"), (403, "auth_error"), (500, "http_error"), (503, "http_error")):
            response_body = io.BytesIO(b"synthetic-private-marker")
            error = urllib.error.HTTPError("http://127.0.0.1/api/health", status, "test", {}, response_body)
            with self.subTest(status=status), self.wire(error=error):
                code, report, stderr = self.run_main()
            self.assert_saved_result(code, report, 1)
            self.assertEqual(report["failure_reasons"], [reason])
            self.assertNotIn("synthetic-private-marker", json.dumps(report) + stderr)
            self.assertTrue(response_body.closed)

    def test_output_parent_failure_preserves_machine_readable_stdout(self):
        parent_file = self.output.parent / "not-a-directory"
        parent_file.write_text("keep", encoding="utf-8")
        self.output = parent_file / "report.json"
        with self.wire(json.dumps(healthy_payload()).encode()):
            code, report, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(report["exit_code"], 1)
        self.assertFalse(report["ok"])
        self.assertTrue(report["checks"]["anonymous"]["ok"])
        self.assertEqual(report["failure_reasons"], ["output_write_failed"])
        self.assertEqual(report["error"], "output_write_failed")
        self.assertIn("output write failed", stderr)
        self.assertEqual(parent_file.read_text(encoding="utf-8"), "keep")

    def test_replace_failure_preserves_prior_report_and_cleans_owned_temporary(self):
        self.output.write_text("prior report", encoding="utf-8")
        unrelated_temp = self.output.with_suffix(".json.tmp")
        unrelated_temp.write_text("other writer", encoding="utf-8")
        with self.wire(b"{}"), patch.object(Path, "replace", side_effect=PermissionError("synthetic denial")):
            code, report, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failure_reasons"], ["invalid_payload", "output_write_failed"])
        self.assertEqual(self.output.read_text(encoding="utf-8"), "prior report")
        self.assertEqual(unrelated_temp.read_text(encoding="utf-8"), "other writer")
        self.assertEqual(list(self.output.parent.glob(".report.json.*.tmp")), [])
        self.assertIn("output write failed", stderr)

    def test_output_failure_summary_is_failure(self):
        with self.wire(json.dumps(healthy_payload()).encode()), patch.object(
            smoke.tempfile, "NamedTemporaryFile", side_effect=OSError("synthetic full disk")
        ):
            code, summary, stderr = self.run_main("--print-summary", json_output=False)
        self.assertEqual(code, 1)
        self.assertEqual(summary.strip(), "health_smoke: FAIL reason=output_write_failed")
        self.assertIn("output write failed", stderr)

    def test_stdout_failure_updates_the_saved_report(self):
        class FailedOutput:
            def write(self, text):
                raise OSError("synthetic stdout failure")

            def flush(self):
                pass

        stderr = io.StringIO()
        with self.wire(json.dumps(healthy_payload()).encode()), contextlib.redirect_stdout(FailedOutput()), contextlib.redirect_stderr(stderr):
            code = smoke.check_health("127.0.0.1", 5000, None, False, dump_json=True, output=self.output)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(report["exit_code"], 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failure_reasons"], ["stdout_write_failed"])
        self.assertIn("stdout write failed", stderr.getvalue())

    def test_successful_write_does_not_touch_another_writers_tempfile(self):
        unrelated_temp = self.output.with_suffix(".json.tmp")
        unrelated_temp.write_text("other writer", encoding="utf-8")
        with self.wire(json.dumps(healthy_payload()).encode()):
            code, report, _ = self.run_main()
        self.assert_saved_result(code, report, 0)
        self.assertEqual(unrelated_temp.read_text(encoding="utf-8"), "other writer")
        self.assertEqual(list(self.output.parent.glob(".report.json.*.tmp")), [])

    def test_json_option_does_not_change_future_invocations(self):
        with self.wire(json.dumps(healthy_payload()).encode()):
            self.run_main(output=False)
            code, summary, _ = self.run_main("--print-summary", output=False, json_output=False)
        self.assertEqual(code, 0)
        self.assertEqual(summary.strip(), "health_smoke: OK")
        self.assertNotIn("HSMOKEE_DUMP", os.environ)

    def test_real_cli_exit_stdout_and_file_agree_against_loopback_http(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(self.server.test_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(self.server.test_body) + self.server.extra_length))
                self.end_headers()
                self.wfile.write(self.server.test_body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            cases = [
                (200, healthy_payload(), 0, [], 0), (200, {}, 1, ["invalid_payload"], 0),
                (503, {}, 1, ["http_error"], 0),
                (200, healthy_payload(config_source="\u6d4b\u8bd5"), 0, [], 0),
                (200, healthy_payload(), 1, ["http_error"], 64),
            ]
            for status, body, expected_code, reasons, extra_length in cases:
                with self.subTest(status=status, expected_code=expected_code):
                    server.test_status, server.test_body = status, json.dumps(body).encode()
                    server.extra_length = extra_length
                    process = subprocess.run(
                        [sys.executable, str(Path(smoke.__file__).resolve()), "--host", "127.0.0.1",
                         "--port", str(server.server_address[1]), "--json", "--output", str(self.output)],
                        env={**self.clean_env, "PYTHONIOENCODING": "cp1252:strict"},
                        capture_output=True, text=True, encoding="utf-8", timeout=15,
                    )
                    report = json.loads(process.stdout)
                    self.assert_saved_result(process.returncode, report, expected_code)
                    self.assertEqual(report["failure_reasons"], reasons)
                    self.assertEqual(process.stderr, "")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_real_closed_stdout_pipe_retains_exit_code_one(self):
        ready_to_respond = threading.Event()
        body = json.dumps(healthy_payload()).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                ready_to_respond.wait(timeout=10)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, str(Path(smoke.__file__).resolve()), "--host", "127.0.0.1",
                 "--port", str(server.server_address[1]), "--json", "--output", str(self.output)],
                env=self.clean_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8",
            )
            process.stdout.close()
            process.stdout = None
            ready_to_respond.set()
            _, stderr = process.communicate(timeout=15)
            report = json.loads(self.output.read_text(encoding="utf-8"))
            self.assertEqual(process.returncode, 1)
            self.assertEqual(report["exit_code"], process.returncode)
            self.assertFalse(report["ok"])
            self.assertEqual(report["failure_reasons"], ["stdout_write_failed"])
            self.assertNotIn("while flushing", stderr)
            self.assertNotIn("Exception ignored", stderr)
        finally:
            ready_to_respond.set()
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
