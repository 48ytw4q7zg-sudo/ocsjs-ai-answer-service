"""Portable configuration and provider boundary tests, using invented credentials."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import anthropic
import httpx

from portable_settings import Preferences, ProfileStore, write_json_atomic
from provider_clients import OpenAICompatibleClient


class PreferencesTests(unittest.TestCase):
    def test_default_and_known_fields_roundtrip(self):
        preferences = Preferences.from_mapping({"port": 0, "max_retries": 0, "unrelated": "ignored"})
        self.assertEqual(preferences.port, 0)
        self.assertEqual(preferences.max_retries, 0)

    def test_urls_cannot_embed_credentials(self):
        for value in ("https://user:secret@example.test/v1", "https://example.test/v1?key=secret",
                      "https://example.test/v1#secret", "file:///tmp/a", "https://example.test:bad/v1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(Preferences(), base_url=value).validate()

    def test_nonfinite_and_boolean_numbers_rejected(self):
        for values in ({"timeout": float("inf")}, {"temperature": float("nan")}, {"port": True},
                       {"max_retries": -1}, {"max_tokens": 0}, {"cache_enabled": "true"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Preferences.from_mapping(values)

    def test_url_and_model_normalization(self):
        preferences = Preferences(base_url=" https://example.test/v1/ ", model=" fixture-model ")
        preferences.validate()
        self.assertEqual(preferences.base_url, "https://example.test/v1")
        self.assertEqual(preferences.model, "fixture-model")

    def test_atomic_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            write_json_atomic(path, {"old": True})
            with patch("portable_settings.os.replace", side_effect=PermissionError("synthetic failure")):
                with self.assertRaises(PermissionError):
                    write_json_atomic(path, {"new": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(list(path.parent.glob(".profile-*.tmp")), [])

    def test_password_profile_is_machine_independent_and_not_plaintext(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(Path(temporary) / "profile.json")
            credentials = {"api_key": "synthetic-key-not-real", "access_token": "synthetic-local-token"}
            preferences = Preferences(max_retries=0)
            store.save(preferences, credentials, "synthetic-password")
            encoded = store.path.read_text(encoding="utf-8")
            self.assertNotIn(credentials["api_key"], encoded)
            self.assertNotIn("synthetic-password", encoded)
            moved = ProfileStore(Path(temporary) / "moved" / "profile.json")
            moved.path.parent.mkdir()
            moved.path.write_text(encoded, encoding="utf-8")
            self.assertEqual(moved.unlock("synthetic-password"), credentials)
            self.assertEqual(moved.load_preferences(), preferences)
            with self.assertRaises(ValueError):
                moved.unlock("incorrect-password")
            store.save(preferences)
            self.assertFalse(store.has_credentials())

    def test_invalid_or_oversized_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(Path(temporary) / "profile.json")
            for text in ("not json", "[]", '{"version":2}', "x" * 65537):
                store.path.write_text(text, encoding="utf-8")
                with self.subTest(length=len(text)), self.assertRaises(ValueError):
                    store.load_preferences()


class ProviderTests(unittest.TestCase):
    def make_client(self, protocol, payload, status=200, **kwargs):
        self.requests = []
        def handle(request):
            self.requests.append(request)
            if isinstance(payload, Exception):
                raise payload
            return httpx.Response(status, json=payload, request=request)
        client = OpenAICompatibleClient("synthetic-key-not-real", "https://provider.test/v1", protocol,
                                        max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handle)), **kwargs)
        self.addCleanup(client.close)
        return client

    @staticmethod
    def ask(client, model="gpt-6-astra[1M]"):
        return client.messages.create(model=model, max_tokens=128, temperature=0.7,
                                      system="Synthetic system", messages=[{"role": "user", "content": "Synthetic question"}])

    def test_responses_request_and_text(self):
        client = self.make_client("openai_responses", {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Alpha"}]}]}, reasoning_effort="max")
        self.assertEqual(self.ask(client).content[0].text, "Alpha")
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "https://provider.test/v1/responses")
        self.assertEqual(body["model"], "gpt-6-astra")
        self.assertEqual(body["reasoning"], {"effort": "max"})
        self.assertFalse(body["store"])
        self.assertNotIn("temperature", body)

    def test_chat_reasoning_parameters(self):
        client = self.make_client("openai_chat", {"choices": [{"message": {"content": "Alpha"}}]}, reasoning_effort="max")
        self.assertEqual(self.ask(client).content[0].text, "Alpha")
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["max_completion_tokens"], 128)
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertNotIn("temperature", body)

    def test_chat_ordinary_model_parameters(self):
        client = self.make_client("openai_chat", {"choices": [{"message": {"content": [{"type": "text", "text": "Alpha"}]}}]})
        self.assertEqual(self.ask(client, model="ordinary-model").content[0].text, "Alpha")
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["max_tokens"], 128)
        self.assertEqual(body["temperature"], 0.7)
        self.assertNotIn("reasoning_effort", body)

    def test_http_errors_have_compatible_safe_error_type(self):
        client = self.make_client("openai_responses", {"error": "synthetic-private-upstream-detail"}, status=401)
        with self.assertRaises(anthropic.APIStatusError) as raised:
            self.ask(client)
        self.assertEqual(raised.exception.status_code, 401)
        self.assertNotIn("synthetic-private-upstream-detail", str(raised.exception))
        self.assertNotIn("synthetic-key-not-real", str(raised.exception))

    def test_network_errors_are_compatible(self):
        client = self.make_client("openai_responses", httpx.ConnectError("synthetic connection failure"))
        with self.assertRaises(anthropic.APIConnectionError):
            self.ask(client)

    def test_non_object_json_is_rejected(self):
        client = self.make_client("openai_responses", [])
        with self.assertRaises(anthropic.APIConnectionError):
            self.ask(client)

    def test_missing_text_returns_no_answer(self):
        client = self.make_client("openai_responses", {"output": []})
        self.assertEqual(self.ask(client).content, [])


if __name__ == "__main__":
    unittest.main()
