import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")
os.environ.setdefault("ANTHROPIC_BASE_URL", "http://127.0.0.1:15721")
os.environ.setdefault("ANTHROPIC_MODEL", "test-model")

import app as app_module
from ccswitch import extract_all_env, sanitize_env_for_display, _sanitize_model_name


class ConfigAndSecurityTests(unittest.TestCase):
    def test_extract_all_env_masks_sensitive_values(self):
        settings = {
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "sk-live-secret-token",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
                "ENABLE_TOOL_SEARCH": "1",
            }
        }

        env = extract_all_env(settings)

        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "<hidden>")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:15721")
        self.assertEqual(env["ENABLE_TOOL_SEARCH"], "1")

    def test_sanitize_env_for_display_masks_common_secret_keys(self):
        env = sanitize_env_for_display({
            "OPENAI_API_KEY": "sk-openai-secret",
            "DB_PASSWORD": "database-password",
            "CUSTOM_SECRET": "secret-value",
            "NORMAL_SETTING": "visible",
        })

        self.assertEqual(env["OPENAI_API_KEY"], "<hidden>")
        self.assertEqual(env["DB_PASSWORD"], "<hidden>")
        self.assertEqual(env["CUSTOM_SECRET"], "<hidden>")
        self.assertEqual(env["NORMAL_SETTING"], "visible")

    def test_sanitize_model_name_removes_context_suffix(self):
        self.assertEqual(_sanitize_model_name("deepseek-v4-pro[1M]"), "deepseek-v4-pro")
        self.assertEqual(_sanitize_model_name("claude-sonnet-4-6[128K]"), "claude-sonnet-4-6")

    def test_dashboard_does_not_render_secret_env_values(self):
        original_source = app_module.Config.CONFIG_SOURCE
        original_extra_env = app_module.Config.EXTRA_ENV
        app_module.Config.CONFIG_SOURCE = "ccswitch"
        app_module.Config.EXTRA_ENV = {
            "ANTHROPIC_AUTH_TOKEN": "sk-dashboard-secret-token",
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
        }

        try:
            response = app_module.app.test_client().get("/dashboard")
        finally:
            app_module.Config.CONFIG_SOURCE = original_source
            app_module.Config.EXTRA_ENV = original_extra_env

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", html)
        self.assertIn("hidden", html)
        self.assertNotIn("sk-dashboard-secret-token", html)

    def test_dashboard_requires_token_when_access_token_is_configured(self):
        original_token = app_module.Config.ACCESS_TOKEN
        app_module.Config.ACCESS_TOKEN = "dashboard-token"

        try:
            missing_token = app_module.app.test_client().get("/dashboard")
            valid_token = app_module.app.test_client().get(
                "/dashboard", query_string={"token": "dashboard-token"}
            )
        finally:
            app_module.Config.ACCESS_TOKEN = original_token

        self.assertEqual(missing_token.status_code, 403)
        self.assertEqual(valid_token.status_code, 200)

    def test_dashboard_actions_send_access_token_from_query_string(self):
        response = app_module.app.test_client().get("/dashboard")
        html = response.get_data(as_text=True)

        self.assertIn("new URLSearchParams(window.location.search)", html)
        self.assertIn("'X-Access-Token'", html)

    def test_health_hides_detailed_config_without_token_when_protected(self):
        original_token = app_module.Config.ACCESS_TOKEN
        app_module.Config.ACCESS_TOKEN = "health-token"

        try:
            public_response = app_module.app.test_client().get("/api/health")
            private_response = app_module.app.test_client().get(
                "/api/health", query_string={"token": "health-token"}
            )
        finally:
            app_module.Config.ACCESS_TOKEN = original_token

        public_data = public_response.get_json()
        private_data = private_response.get_json()
        self.assertEqual(public_response.status_code, 200)
        self.assertNotIn("base_url", public_data)
        self.assertNotIn("config_keys", public_data)
        self.assertEqual(public_data["details"], "protected")
        self.assertIn("base_url", private_data)

    def test_health_accepts_token_with_surrounding_whitespace(self):
        original_token = app_module.Config.ACCESS_TOKEN
        app_module.Config.ACCESS_TOKEN = "health-token"

        try:
            response = app_module.app.test_client().get(
                "/api/health", headers={"X-Access-Token": "  health-token  "}
            )
        finally:
            app_module.Config.ACCESS_TOKEN = original_token

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("base_url", data)
        self.assertNotIn("details", data)

    def test_stats_requires_access_token_when_configured(self):
        original_token = app_module.Config.ACCESS_TOKEN
        app_module.Config.ACCESS_TOKEN = "stats-token"

        try:
            response = app_module.app.test_client().get("/api/stats")
            authed_response = app_module.app.test_client().get(
                "/api/stats", query_string={"token": "stats-token"}
            )
        finally:
            app_module.Config.ACCESS_TOKEN = original_token

        self.assertEqual(response.status_code, 403)
        self.assertEqual(authed_response.status_code, 200)
        self.assertNotIn("api_key", authed_response.get_data(as_text=True).lower())

    def test_call_ai_uses_configured_max_tokens_by_default(self):
        captured = []

        class FakeMessages:
            def create(self, **kwargs):
                captured.append(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=" final answer ")]
                )

        original_client = app_module.client
        original_max_tokens = app_module.Config.MAX_TOKENS
        app_module.client = SimpleNamespace(messages=FakeMessages())
        app_module.Config.MAX_TOKENS = 777

        try:
            result = app_module._call_ai("question prompt")
        finally:
            app_module.client = original_client
            app_module.Config.MAX_TOKENS = original_max_tokens

        self.assertEqual(result, "final answer")
        self.assertEqual(captured[0]["max_tokens"], 777)

    def test_call_ai_respects_explicit_max_tokens(self):
        captured = []

        class FakeMessages:
            def create(self, **kwargs):
                captured.append(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=" final answer ")]
                )

        original_client = app_module.client
        app_module.client = SimpleNamespace(messages=FakeMessages())

        try:
            result = app_module._call_ai("question prompt", max_tokens=123)
        finally:
            app_module.client = original_client

        self.assertEqual(result, "final answer")
        self.assertEqual(captured[0]["max_tokens"], 123)

    def test_safer_bind_defaults_are_documented_in_code(self):
        # Live Config.HOST/DEBUG may be overridden by host .env; assert the
        # production default path in source and the operator-facing templates.
        from pathlib import Path
        import config as config_module

        source = Path(config_module.__file__).read_text(encoding="utf-8")
        self.assertIn('_env_str("HOST", "127.0.0.1")', source)
        self.assertIn('_env_bool("DEBUG", False)', source)
        example = Path(config_module.__file__).with_name(".env.example").read_text(encoding="utf-8")
        self.assertIn("HOST=127.0.0.1", example)
        self.assertIn("DEBUG=False", example)

    def test_short_answer_is_normalized_and_instructed(self):
        from utils import normalize_question_type, parse_question_and_options

        self.assertEqual(normalize_question_type("short-answer"), "short-answer")
        self.assertEqual(normalize_question_type("简答题"), "short-answer")
        prompt = parse_question_and_options("解释光合作用", "", "short-answer")
        self.assertIn("【简答题】", prompt)
        self.assertIn("简答题", prompt)

    def test_api_does_not_emit_cors_wildcard_header(self):
        client = app_module.app.test_client()
        response = client.get("/api/health")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_healthcheck_treats_degraded_as_alive(self):
        import healthcheck
        from unittest.mock import patch
        import json as json_module

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json_module.dumps({
                    "status": "degraded", "runtime_ready": False, "message": "not ready"
                }).encode("utf-8")

        with patch.object(healthcheck.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = FakeResponse()
            self.assertEqual(healthcheck.main(), 0)


if __name__ == "__main__":
    unittest.main()
