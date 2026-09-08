import os
import threading
import io
import runpy
from pathlib import Path
import unittest
from unittest.mock import patch

with patch('dotenv.load_dotenv', return_value=False), patch('ccswitch.get_ccswitch_config', return_value=None), patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'unit-test-placeholder', 'ANTHROPIC_BASE_URL': 'http://127.0.0.1:1', 'ACCESS_TOKEN': ''}):
    import app as service
    import config

from utils import SimpleCache, extract_answer
from ccswitch import _resolve_model, extract_all_env, get_ccswitch_config


class RuntimeCompletionTests(unittest.TestCase):
    def setUp(self):
        self.config = {key: value for key, value in vars(service.Config).items() if key.isupper()}
        self.runtime = service.client, service.cache, service._runtime_init_error
        self.records = list(service.qa_records)
        service.Config.ACCESS_TOKEN = None
        service.client = object()
        service.cache = SimpleCache(60)
        service._runtime_init_error = None
        self.http = service.app.test_client()

    def tearDown(self):
        for key, value in self.config.items():
            setattr(service.Config, key, value)
        service.client, service.cache, service._runtime_init_error = self.runtime
        service.qa_records.clear()
        service.qa_records.extend(self.records)

    def test_cache_write_and_update_complete_without_eviction(self):
        cache = SimpleCache(60, max_size=2)
        thread = threading.Thread(target=lambda: cache.set('first', 'one'), daemon=True)
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive(), 'cache writer deadlocked')
        cache.set('second', 'two')
        cache.set('first', 'updated')
        self.assertEqual(cache.get('second'), 'two')

    def test_cache_fields_do_not_collide_on_separator(self):
        cache = SimpleCache(60)
        self.assertNotEqual(cache._generate_key('a|b', 'c', 'd'), cache._generate_key('a', 'b', 'c|d'))

    def test_unicode_and_nonstring_tokens_are_rejected_normally(self):
        service.Config.ACCESS_TOKEN = 'unit-test-placeholder'
        for token in ('中文', {'bad': 'value'}, ['bad']):
            with self.subTest(token=token):
                response = self.http.post('/api/search', json={'question': 'test', 'token': token})
                self.assertEqual(response.status_code, 403)
                self.assertTrue(response.is_json)

    def test_reload_failure_preserves_client_cache_and_configuration(self):
        old_client, old_cache, old_model = service.client, service.cache, service.Config.ANTHROPIC_MODEL
        def change_config():
            service.Config.ANTHROPIC_MODEL = 'new-model'
            return True
        with patch('app.reload_config', side_effect=change_config), patch('app.build_ai_client', side_effect=ValueError('sensitive upstream detail')):
            response = self.http.post('/api/config/reload')
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertTrue(response.json['runtime_ready'])
        self.assertIs(service.client, old_client)
        self.assertIs(service.cache, old_cache)
        self.assertEqual(service.Config.ANTHROPIC_MODEL, old_model)
        self.assertNotIn('sensitive upstream detail', response.get_data(as_text=True))

    def test_config_read_exception_returns_json(self):
        with patch('app.reload_config', side_effect=ValueError('bad configuration')):
            response = self.http.post('/api/config/reload')
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)

    def test_degraded_runtime_keeps_health_and_home_available(self):
        service.client = None
        service.cache = None
        service.Config.ANTHROPIC_API_KEY = ''
        self.assertFalse(service._initialize_runtime_if_needed())
        self.assertEqual(self.http.get('/').status_code, 200)
        response = self.http.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['runtime_ready'])
        self.assertEqual(self.http.get('/api/search?question=test').status_code, 503)

    def test_dashboard_renders_both_configuration_sources(self):
        for source in ('.env', 'ccswitch'):
            service.Config.CONFIG_SOURCE = source
            service.Config.EXTRA_ENV = {'ANTHROPIC_AUTH_TOKEN': 'private-placeholder', 'ANTHROPIC_MODEL': 'model'}
            response = self.http.get('/dashboard')
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('private-placeholder', response.get_data(as_text=True))

    def test_nonfinite_configuration_uses_default(self):
        for value in ('nan', 'inf', '-inf'):
            with patch.dict(os.environ, {'API_TIMEOUT': value}):
                self.assertEqual(config._env_float('API_TIMEOUT', 30, 1, 600), 30)

    def test_ccswitch_prefers_model_id_over_display_name(self):
        self.assertEqual(_resolve_model({'model': 'opus'}, {'ANTHROPIC_DEFAULT_OPUS_MODEL': 'api-model-id', 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME': 'Display label'}), 'api-model-id')
        self.assertEqual(extract_all_env([]), {})
        self.assertEqual(extract_all_env({'env': {'ANTHROPIC_AUTH_TOKEN': 123}}), {})

    def test_structured_question_is_rejected_before_ai_call(self):
        with patch('app._call_ai', return_value='answer') as ai:
            response = self.http.post('/api/search', json={'question': {'nested': 'invalid'}})
        self.assertEqual(response.status_code, 400)
        ai.assert_not_called()

    def test_reload_does_not_put_old_answer_into_new_cache(self):
        new_cache = SimpleCache(60)
        def replace_runtime(_):
            service.cache = new_cache
            return 'answer'
        with patch('app._call_ai', side_effect=replace_runtime):
            response = self.http.post('/api/search', json={'question': 'cache generation check'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(new_cache.get('cache generation check'))

    def test_single_answers_preserve_exact_long_and_article_options(self):
        self.assertEqual(extract_answer('北京大学', 'single', 'A. 北京\nB. 北京大学'), '北京大学')
        self.assertEqual(extract_answer('A banana', 'single', 'A. An apple\nB. A banana'), 'A banana')
        self.assertEqual(extract_answer('北京大学，因为题目指向高校', 'single', 'A. 北京\nB. 北京大学'), '北京大学')

    def test_multiple_answers_preserve_option_internal_spaces(self):
        options = 'A. New York\nB. Los Angeles'
        self.assertEqual(extract_answer('New York, Los Angeles', 'multiple', options), 'New York#Los Angeles')
        self.assertEqual(extract_answer('New York Los Angeles', 'multiple', options), 'New York#Los Angeles')
        self.assertEqual(extract_answer('A banana#An apple', 'multiple', 'A. An apple\nB. A banana'), 'A banana#An apple')

    def test_multiple_option_segmentation_can_recover_from_long_prefix(self):
        self.assertEqual(extract_answer('New York City', 'multiple', 'A. New\nB. New York\nC. York City'), 'New#York City')

    def test_single_option_body_precedes_label_with_explanation(self):
        self.assertEqual(extract_answer('A. Einstein，因为题目如此', 'single', 'A. 牛顿\nB. A. Einstein'), 'A. Einstein')

    def test_invalid_unicode_token_is_rejected_as_json(self):
        service.Config.ACCESS_TOKEN = 'unit-test-placeholder'
        response = self.http.post('/api/search', json={'question': 'test', 'token': '\ud800'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.is_json)

    def test_valid_unicode_token_works_in_json(self):
        service.Config.ACCESS_TOKEN = '中文令牌'
        with patch('app._call_ai', return_value='answer'):
            response = self.http.post('/api/search', json={'question': 'test', 'token': '中文令牌'})
        self.assertEqual(response.status_code, 200)

    def test_config_decode_failure_falls_back(self):
        settings_path = unittest.mock.MagicMock()
        settings_path.read_text.side_effect = UnicodeDecodeError('utf8', b'\xff', 0, 1, 'invalid byte')
        self.assertIsNone(get_ccswitch_config(settings_path))

    def test_runtime_snapshot_waits_for_reload_to_commit(self):
        started = threading.Event()
        release = threading.Event()
        observed = threading.Event()
        result = {}
        old_model = service.Config.ANTHROPIC_MODEL
        def change_config():
            service.Config.ANTHROPIC_MODEL = 'candidate-model'
            return True
        def fail_candidate():
            started.set()
            release.wait(2)
            raise ValueError('candidate unavailable')
        def reload():
            with service.app.test_client() as client:
                client.post('/api/config/reload')
        def observe():
            result.update(service._runtime_info())
            observed.set()
        with patch('app.reload_config', side_effect=change_config), patch('app.build_ai_client', side_effect=fail_candidate):
            reload_thread = threading.Thread(target=reload)
            read_thread = threading.Thread(target=observe)
            reload_thread.start()
            self.assertTrue(started.wait(1))
            read_thread.start()
            self.assertFalse(observed.wait(0.02), 'uncommitted configuration became visible')
            release.set()
            reload_thread.join(2)
            read_thread.join(2)
        self.assertTrue(observed.is_set())
        self.assertEqual(result['model'], old_model)

    def test_container_healthcheck_requires_ready_runtime(self):
        import healthcheck
        for payload, expected in ((b'{"runtime_ready":true}',0),(b'{"runtime_ready":false}',1),(b'{}',1),(b'not json',1)):
            opener = unittest.mock.MagicMock()
            opener.open.return_value = io.BytesIO(payload)
            with patch('healthcheck.urllib.request.build_opener', return_value=opener):
                self.assertEqual(healthcheck.main(), expected)

    def test_container_healthcheck_uses_configured_port(self):
        import healthcheck
        service.Config.PORT = 5123
        opener = unittest.mock.MagicMock()
        opener.open.return_value = io.BytesIO(b'{"runtime_ready":true}')
        with patch('healthcheck.urllib.request.build_opener', return_value=opener):
            self.assertEqual(healthcheck.main(), 0)
        opener.open.assert_called_once_with('http://127.0.0.1:5123/api/health', timeout=3)

    def test_container_healthcheck_matches_ipv6_and_specific_bind_addresses(self):
        import healthcheck
        for host, target in (('::1','[::1]'),('::','[::1]'),('[::]','[::1]'),('192.0.2.10','192.0.2.10')):
            service.Config.HOST = host
            service.Config.PORT = 5123
            opener = unittest.mock.MagicMock()
            opener.open.return_value = io.BytesIO(b'{"runtime_ready":true}')
            with patch('healthcheck.urllib.request.build_opener', return_value=opener):
                self.assertEqual(healthcheck.main(), 0)
            opener.open.assert_called_once_with(f'http://{target}:5123/api/health', timeout=3)

    def test_gunicorn_configuration_keeps_cache_state_in_one_process(self):
        service.Config.HOST = '::1'
        service.Config.PORT = 5123
        settings = runpy.run_path(str(Path(__file__).with_name('gunicorn.conf.py')))
        self.assertEqual(settings['bind'], '[::1]:5123')
        self.assertEqual(settings['workers'], 1)
        self.assertGreater(settings['threads'], 1)
        self.assertEqual(settings['worker_class'], 'gthread')


if __name__ == '__main__':
    unittest.main()
