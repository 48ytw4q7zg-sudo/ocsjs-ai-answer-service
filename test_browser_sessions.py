"""Browser navigation auth checks in an isolated, credential-free process."""

import importlib
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from itsdangerous import BadSignature


class BrowserSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="browser-session-tests-")
        import portable_paths
        portable_paths.activate(data=Path(cls.temporary.name))
        from config import Config
        Config.ANTHROPIC_API_KEY = "SYNTHETIC_SESSION_TEST_KEY"
        Config.ANTHROPIC_BASE_URL = "http://127.0.0.1:9/v1"
        Config.ANTHROPIC_MODEL = "synthetic-model"
        cls.module = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls):
        if cls.module.client is not None:
            cls.module.client.close()
        for logger in [logging.getLogger()] + [value for value in logging.Logger.manager.loggerDict.values()
                                              if isinstance(value, logging.Logger)]:
            for handler in list(logger.handlers):
                filename = getattr(handler, "baseFilename", None)
                if filename and Path(filename).resolve().is_relative_to(Path(cls.temporary.name).resolve()):
                    logger.removeHandler(handler)
                    handler.close()
        cls.temporary.cleanup()

    def setUp(self):
        self.client = self.module.app.test_client()
        self.token = "SYNTHETIC_BROWSER_ACCESS_TOKEN"
        self.access_patch = patch.object(self.module.Config, "ACCESS_TOKEN", self.token)
        self.access_patch.start()
        self.addCleanup(self.access_patch.stop)

    def login(self, **kwargs):
        return self.client.post("/api/session", json={"token": self.token}, **kwargs)

    def test_session_opens_dashboard_without_query_token(self):
        self.assertEqual(self.client.get("/dashboard").status_code, 403)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Max-Age=3600", cookie)
        self.assertNotIn(self.token, cookie)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_wrong_token_cannot_create_session(self):
        response = self.client.post("/api/session", json={"token": "wrong"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Set-Cookie", response.headers)

    def test_explicit_wrong_token_is_not_bypassed_by_cookie(self):
        self.login()
        response = self.client.get("/api/stats", headers={"X-Access-Token": "wrong"})
        self.assertEqual(response.status_code, 403)

    def test_token_rotation_revokes_existing_cookie(self):
        self.login()
        with patch.object(self.module.Config, "ACCESS_TOKEN", "SYNTHETIC_NEW_TOKEN"):
            self.assertEqual(self.client.get("/dashboard").status_code, 403)

    def test_expired_or_invalid_signature_is_rejected(self):
        self.login()
        with patch.object(self.module._browser_session_serializer, "loads", side_effect=BadSignature("synthetic")):
            self.assertEqual(self.client.get("/dashboard").status_code, 403)

    def test_cross_origin_cannot_create_or_use_cookie_session(self):
        self.assertEqual(self.login(headers={"Origin": "https://example.invalid"}).status_code, 403)
        self.login()
        for headers in ({"Origin": "https://example.invalid"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Sec-Fetch-Site": "same-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post("/api/cache/clear", json={}, headers=headers).status_code, 403)

    def test_same_origin_cookie_authorizes_existing_post_route(self):
        self.assertEqual(self.login(headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}).status_code, 200)
        response = self.client.post("/api/cache/clear", json={}, headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 200)

    def test_https_cookie_is_secure(self):
        response = self.login(base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["Set-Cookie"])

    def test_legacy_explicit_tokens_still_work(self):
        self.assertEqual(self.client.get("/api/stats", headers={"X-Access-Token": self.token}).status_code, 200)
        self.assertEqual(self.client.get("/api/stats", query_string={"token": self.token}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
