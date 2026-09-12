# -*- coding: utf-8 -*-
"""Safety regression tests for app-level configuration and dashboard behavior."""
import json
import logging
import tempfile
import unittest
from unittest.mock import patch

import app as app_module
from logger import setup_logger
from utils import SimpleCache, extract_answer, normalize_options, normalize_question_type


class AppSafetyTests(unittest.TestCase):
    def setUp(self):
        self._original_access_token = app_module.Config.ACCESS_TOKEN
        self._original_config_source = app_module.Config.CONFIG_SOURCE
        self._original_extra_env = app_module.Config.EXTRA_ENV
        self._original_client = app_module.client
        self._original_api_key = app_module.Config.ANTHROPIC_API_KEY
        app_module.Config.ACCESS_TOKEN = None

    def tearDown(self):
        app_module.Config.ACCESS_TOKEN = self._original_access_token
        app_module.Config.CONFIG_SOURCE = self._original_config_source
        app_module.Config.EXTRA_ENV = self._original_extra_env
        app_module.client = self._original_client
        app_module.Config.ANTHROPIC_API_KEY = self._original_api_key

    def test_access_token_rejects_missing_or_wrong_token(self):
        app_module.Config.ACCESS_TOKEN = "expected-token"

        with app_module.app.test_request_context("/api/stats"):
            self.assertFalse(app_module.verify_access_token(app_module.request))

        with app_module.app.test_request_context(
            "/api/stats", headers={"X-Access-Token": "wrong-token"}
        ):
            self.assertFalse(app_module.verify_access_token(app_module.request))

        with app_module.app.test_request_context(
            "/api/stats", headers={"X-Access-Token": "expected-token"}
        ):
            self.assertTrue(app_module.verify_access_token(app_module.request))

    def test_dashboard_masks_sensitive_ccswitch_values(self):
        app_module.Config.CONFIG_SOURCE = "ccswitch"
        app_module.Config.EXTRA_ENV = {
            "ANTHROPIC_AUTH_TOKEN": "sk-test-secret-value",
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
            "ANTHROPIC_MODEL": "deepseek-v4-pro",
        }

        response = app_module.app.test_client().get("/dashboard")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", html)
        self.assertIn(app_module._SENSITIVE_CONFIG_MARKER, html)
        self.assertNotIn("sk-test-secret-value", html)
        self.assertIn("http://127.0.0.1:15721", html)

    def test_dashboard_respects_access_token_when_configured(self):
        app_module.Config.ACCESS_TOKEN = "expected-token"

        missing = app_module.app.test_client().get("/dashboard")
        allowed = app_module.app.test_client().get("/dashboard?token=expected-token")

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("X-Access-Token", allowed.get_data(as_text=True))

    def test_config_reload_rebuilds_client_after_env_fallback(self):
        replacement_client = object()
        app_module.Config.ANTHROPIC_API_KEY = "test-key"

        with patch.object(app_module, "reload_config", return_value=False), \
             patch.object(app_module, "build_ai_client", return_value=replacement_client):
            response = app_module.app.test_client().post("/api/config/reload")

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["config_source"], app_module.Config.CONFIG_SOURCE)
        self.assertIs(app_module.client, replacement_client)

    def test_setup_logger_does_not_duplicate_messages_through_root_logger(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logger = setup_logger(
                "test_no_root_propagation", log_dir=log_dir, level=logging.INFO
            )
            try:
                self.assertFalse(logger.propagate)
            finally:
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)

    def test_answer_cleanup_keeps_english_option_text(self):
        self.assertEqual(extract_answer("Apple", "single"), "Apple")
        self.assertEqual(extract_answer("A. Apple", "single"), "Apple")
        self.assertEqual(extract_answer("Apple#Banana", "multiple"), "Apple#Banana")
        self.assertEqual(extract_answer("A#B", "multiple"), "A#B")
        self.assertEqual(extract_answer("A. Apple#B. Banana", "multiple"), "Apple#Banana")

    def test_short_answer_type_is_supported_end_to_end(self):
        self.assertEqual(normalize_question_type("short-answer"), "short-answer")
        self.assertEqual(extract_answer("答案：光合作用产生氧气。", "short-answer"), "光合作用产生氧气")

    def test_normalize_options_removes_blank_lines_and_unifies_newlines(self):
        self.assertEqual(
            normalize_options("  A. 上海  \r\n\r\n B. 北京 \n C. 广州  "),
            "A. 上海\nB. 北京\nC. 广州",
        )
        self.assertEqual(
            normalize_options([" A. 上海 ", "", None, " B. 北京 "]),
            "A. 上海\nB. 北京",
        )

    def test_normalize_options_accepts_ocs_object_shapes(self):
        self.assertEqual(
            normalize_options([
                {"label": "A", "text": "上海"},
                {"label": "B", "content": "北京"},
                {"label": "C", "value": "广州"},
            ]),
            "A. 上海\nB. 北京\nC. 广州",
        )
        self.assertEqual(
            normalize_options({"A": "上海", "B": "北京", "C": "广州"}),
            "A. 上海\nB. 北京\nC. 广州",
        )
        self.assertEqual(
            normalize_options([
                {"key": "A)", "value": "上海"},
                {"letter": "B", "title": "北京"},
            ]),
            "A. 上海\nB. 北京",
        )

    def test_cache_key_uses_normalized_options_for_equivalent_inputs(self):
        cache = SimpleCache()
        normalized = normalize_options("A. 上海\r\nB. 北京\n")
        equivalent = normalize_options([" A. 上海 ", "B. 北京"])

        cache.set("中国的首都是哪个城市？", "北京", "single", normalized)

        self.assertEqual(
            cache.get("中国的首都是哪个城市？", "single", equivalent),
            "北京",
        )

    def test_answer_cleanup_maps_option_letters_to_current_option_text(self):
        options = "A. 上海\nB. 北京\nC. 广州\nD. 深圳"

        self.assertEqual(extract_answer("B", "single", options), "北京")
        self.assertEqual(extract_answer("b", "single", options), "北京")
        self.assertEqual(extract_answer("答案：B", "single", options), "北京")
        self.assertEqual(extract_answer("B，因为北京是中国首都。", "single", options), "北京")
        self.assertEqual(extract_answer("北京，因为北京是中国首都。", "single", options), "北京")

    def test_single_answer_explanation_does_not_prefix_match_short_option(self):
        options = "A. A\nB. Apple\nC. Banana"

        self.assertEqual(extract_answer("Apple, because it is a fruit.", "single", options), "Apple")

    def test_multiple_answer_cleanup_maps_letters_to_current_option_text(self):
        options = "A. 北京\nB. 上海\nC. 广州\nD. 深圳\nE. 成都"

        self.assertEqual(extract_answer("A,C,D", "multiple", options), "北京#广州#深圳")
        self.assertEqual(extract_answer("a,c,d", "multiple", options), "北京#广州#深圳")
        self.assertEqual(extract_answer("A#C#D", "multiple", options), "北京#广州#深圳")
        self.assertEqual(extract_answer("A. 北京, C. 广州, D. 深圳", "multiple", options), "北京#广州#深圳")
        self.assertEqual(extract_answer("A. 北京\nC. 广州\nD. 深圳", "multiple", options), "北京#广州#深圳")

    def test_search_route_keeps_english_option_text(self):
        with patch.object(app_module, "_call_ai", return_value="A. Apple#B. Banana"):
            response = app_module.app.test_client().get(
                "/api/search",
                query_string={
                    "title": "Which words are fruits?",
                    "type": "multiple",
                    "options": "A. Apple\nB. Banana\nC. Carrot",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "Apple#Banana")

    def test_search_route_maps_option_letter_answer_to_option_text(self):
        with patch.object(app_module, "_call_ai", return_value="B"):
            response = app_module.app.test_client().get(
                "/api/search",
                query_string={
                    "title": "中国的首都是哪个城市？",
                    "type": "single",
                    "options": "A. 上海\nB. 北京\nC. 广州\nD. 深圳",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京")

    def test_search_route_accepts_question_alias_across_request_sources(self):
        options = "A. 上海\nB. 北京\nC. 广州\nD. 深圳"
        cases = [
            (
                "get",
                lambda client: client.get(
                    "/api/search",
                    query_string={
                        "question": "GET 别名：中国的首都是哪个城市？",
                        "type": "single",
                        "options": options,
                    },
                ),
            ),
            (
                "form",
                lambda client: client.post(
                    "/api/search",
                    data={
                        "question": "Form 别名：中国的首都是哪个城市？",
                        "type": "single",
                        "options": options,
                    },
                ),
            ),
            (
                "json",
                lambda client: client.post(
                    "/api/search",
                    json={
                        "question": "JSON 别名：中国的首都是哪个城市？",
                        "type": "single",
                        "options": options,
                    },
                ),
            ),
        ]

        with patch.object(app_module, "_call_ai", return_value="B"):
            client = app_module.app.test_client()
            for source, send_request in cases:
                with self.subTest(source=source):
                    response = send_request(client)
                    data = response.get_json()

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(data["code"], 1)
                    self.assertEqual(data["answer"], "北京")

    def test_search_route_rejects_blank_question_before_calling_ai(self):
        with patch.object(app_module, "_call_ai") as call_ai:
            response = app_module.app.test_client().get(
                "/api/search",
                query_string={"title": "   ", "type": "single"},
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(data["code"], 0)
        call_ai.assert_not_called()

    def test_search_route_rejects_non_object_json_payload(self):
        with patch.object(app_module, "_call_ai") as call_ai:
            response = app_module.app.test_client().post(
                "/api/search",
                json=["not", "an", "object"],
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(data["code"], 0)
        call_ai.assert_not_called()

    def test_search_route_accepts_json_options_array(self):
        with patch.object(app_module, "_call_ai", return_value="B"):
            response = app_module.app.test_client().post(
                "/api/search",
                json={
                    "title": "中国的首都是哪个城市？",
                    "type": "single",
                    "options": ["A. 上海", "B. 北京", "C. 广州", "D. 深圳"],
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京")

    def test_search_route_accepts_vendor_json_mimetype(self):
        payload = {
            "title": "中国的首都是哪个城市？",
            "type": "single",
            "options": {"A": "上海", "B": "北京", "C": "广州"},
        }
        with patch.object(app_module, "_call_ai", return_value="B"):
            response = app_module.app.test_client().post(
                "/api/search",
                data=json.dumps(payload),
                content_type="application/vnd.ocs+json",
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京")

    def test_search_route_accepts_json_options_object_array(self):
        with patch.object(app_module, "_call_ai", return_value="B"):
            response = app_module.app.test_client().post(
                "/api/search",
                json={
                    "title": "中国的首都是哪个城市？",
                    "type": "single",
                    "options": [
                        {"label": "A", "text": "上海"},
                        {"label": "B", "text": "北京"},
                        {"label": "C", "text": "广州"},
                    ],
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京")

    def test_search_route_accepts_common_json_field_aliases(self):
        with patch.object(app_module, "_call_ai", return_value="B"):
            response = app_module.app.test_client().post(
                "/api/search",
                json={
                    "q": "别名字段测试：中国的首都是哪个城市？",
                    "questionType": "single",
                    "choices": [
                        {"label": "A", "text": "上海"},
                        {"label": "B", "text": "北京"},
                        {"label": "C", "text": "广州"},
                    ],
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京")

    def test_search_route_accepts_numeric_single_type_from_ocs_config(self):
        with patch.object(app_module, "_call_ai", return_value="B"):
            response = app_module.app.test_client().post(
                "/api/search",
                json={
                    "title": "中国的首都是哪个城市？",
                    "type": 1,
                    "options": "A. 上海\nB. 北京\nC. 广州\nD. 深圳",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京")

    def test_search_route_accepts_numeric_multiple_type_from_ocs_config(self):
        with patch.object(app_module, "_call_ai", return_value="A,C"):
            response = app_module.app.test_client().post(
                "/api/search",
                json={
                    "title": "以下哪些是中国城市？",
                    "type": 2,
                    "options": "A. 北京\nB. 苹果\nC. 广州\nD. 香蕉",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["code"], 1)
        self.assertEqual(data["answer"], "北京#广州")

    def test_call_ai_uses_configured_max_tokens_by_default(self):
        captured = {}

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                block = type("Block", (), {"type": "text", "text": "北京"})()
                return type("Response", (), {"content": [block]})()

        class FakeClient:
            messages = FakeMessages()

        original_max_tokens = app_module.Config.MAX_TOKENS
        app_module.Config.MAX_TOKENS = 777
        app_module.client = FakeClient()

        try:
            self.assertEqual(app_module._call_ai("prompt"), "北京")
        finally:
            app_module.Config.MAX_TOKENS = original_max_tokens

        self.assertEqual(captured["max_tokens"], 777)


if __name__ == "__main__":
    unittest.main()
