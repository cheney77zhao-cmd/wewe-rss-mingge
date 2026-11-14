import os
import gc
import tempfile
import threading
import time
import unittest
import requests
from unittest.mock import Mock, patch
from cryptography.fernet import Fernet

TEST_DIR = tempfile.TemporaryDirectory()
os.environ['PLATFORM_SECRET'] = Fernet.generate_key().decode()
os.environ['PLATFORM_DB'] = TEST_DIR.name + '/initial.db'
import platform_service as service
from weread_client import (Article, ArticleValidationError, AuthExpiredError,
                           Credentials, RiskControlError, WeReadClient, WeReadError)


class ErrorHandlingTests(unittest.TestCase):
    def test_original_url_reuses_pause_and_auth_protection(self):
        self.client.web_article_url.side_effect = RiskControlError('HTTP 429')
        for _ in range(2):
            with self.assertRaises(RiskControlError):
                self.app.article_url(self.headers, 'MP_WXS_1', 'WR' + 'a' * 70)
        self.assertEqual(self.client.web_article_url.call_count, 1)
        self.client.web_articles.assert_not_called()

    def test_original_url_renews_once_and_returns_url(self):
        url = 'https://mp.weixin.qq.com/s/f9NSNDchorq7YgSdx9_TqA'
        self.client.web_article_url.side_effect = [AuthExpiredError('expired'), (url, self.credentials)]
        self.client.renew_web.return_value = self.credentials
        self.assertEqual(self.app.article_url(self.headers, 'MP_WXS_1', 'WR' + 'a' * 70), {'url': url})
        self.client.renew_web.assert_called_once()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        os.environ['PLATFORM_DB'] = self.directory.name + '/platform.db'
        self.app = service.Application()
        self.credentials = Credentials('123', 'test-access', cookies={'wr_skey': 'test-key'})
        self.token = self.app.store.create(self.credentials)
        self.headers = {'Authorization': 'Bearer ' + self.token, 'xid': '123'}
        self.client = self.app.client = Mock()
        self.ok = ([Article('a_b~c', 'title', '', 123)], self.credentials)

    def tearDown(self):
        # SQLite connections become collectible after context-manager use;
        # collect before removing temporary files on Windows. Runtime unchanged.
        gc.collect()
        self.directory.cleanup()

    def test_validation_is_feed_scoped_and_retries_do_not_call_upstream(self):
        self.client.web_articles.side_effect = [ArticleValidationError('-2041'), self.ok]
        for _ in range(4):
            with self.assertRaises(ArticleValidationError):
                self.app.articles(self.headers, 'MP_WXS_1', 1)
        self.assertEqual(self.client.web_articles.call_count, 1)
        self.assertEqual(self.app.store.stats()['blockedSessions'], 0)
        self.assertEqual(self.app.articles(self.headers, 'MP_WXS_2', 1)[0]['id'], 'a_b~c')
        self.client.renew_web.assert_not_called()

    def test_real_rate_limit_stops_other_feeds_and_never_retries(self):
        self.client.web_articles.side_effect = RiskControlError('HTTP 429')
        for feed in ['MP_WXS_1', 'MP_WXS_2']:
            with self.assertRaises(RiskControlError):
                self.app.articles(self.headers, feed, 1)
        self.assertEqual(self.client.web_articles.call_count, 1)
        self.client.renew_web.assert_not_called()

    def test_expired_web_session_uses_web_renewal_once(self):
        self.client.web_articles.side_effect = [AuthExpiredError('expired'), self.ok]
        self.client.renew_web.return_value = self.credentials
        self.assertEqual(len(self.app.articles(self.headers, 'MP_WXS_1', 1)), 1)
        self.client.renew_web.assert_called_once()
        self.client.refresh.assert_not_called()

    def test_failed_auth_is_not_rate_limit(self):
        self.client.web_articles.side_effect = AuthExpiredError('expired')
        self.client.renew_web.side_effect = AuthExpiredError('expired')
        for _ in range(4):
            with self.assertRaises(AuthExpiredError):
                self.app.articles(self.headers, 'MP_WXS_1', 1)
        self.assertEqual(self.client.web_articles.call_count, 1)
        self.assertEqual(self.app.store.stats()['blockedSessions'], 0)

    def test_renewal_rate_limit_is_preserved(self):
        self.client.web_articles.side_effect = AuthExpiredError('expired')
        self.client.renew_web.side_effect = RiskControlError('429')
        with self.assertRaises(RiskControlError):
            self.app.articles(self.headers, 'MP_WXS_1', 1)
        self.assertEqual(self.app.store.stats()['blockedSessions'], 1)

    def test_renewal_validation_is_not_account_block(self):
        self.client.web_articles.side_effect = AuthExpiredError('expired')
        self.client.renew_web.side_effect = ArticleValidationError('-2041')
        with self.assertRaises(ArticleValidationError):
            self.app.articles(self.headers, 'MP_WXS_1', 1)
        self.assertEqual(self.app.store.stats()['blockedSessions'], 0)

    def test_parallel_retries_only_fetch_once(self):
        def fail(*args):
            time.sleep(.03)
            raise ArticleValidationError('-2041')
        self.client.web_articles.side_effect = fail
        errors = []
        def call():
            try:
                self.app.articles(self.headers, 'MP_WXS_1', 1)
            except ArticleValidationError:
                errors.append(True)
        threads = [threading.Thread(target=call) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(errors), 4)
        self.assertEqual(self.client.web_articles.call_count, 1)

    def test_error_http_responses_are_distinct(self):
        for error, status in [(ArticleValidationError('validation'), 422),
                              (AuthExpiredError('auth'), 401), (RiskControlError('rate'), 429)]:
            handler = object.__new__(service.Handler)
            handler.path = '/api/v2/platform/mps/MP_WXS_1/articles?page=1'
            handler.headers = self.headers
            handler.send_json = Mock()
            with patch.object(service.APP, 'articles', side_effect=error):
                handler.do_GET()
            self.assertEqual(handler.send_json.call_args.args[0], status)


class ClientTests(unittest.TestCase):
    def test_article_response_classification_and_optional_ticket(self):
        cases = [(200, {'errcode': -2041}, ArticleValidationError),
                 (200, {'errcode': -2010}, ArticleValidationError),
                 (200, {'errcode': -2012}, AuthExpiredError),
                 (403, {}, ArticleValidationError), (401, {}, AuthExpiredError),
                 (429, {}, RiskControlError), (200, {'reviews': []}, None)]
        for status, payload, error in cases:
            with self.subTest(status=status, payload=payload), patch('weread_client.requests.Session') as factory:
                response = Mock(status_code=status, headers={})
                response.json.return_value = payload
                factory.return_value.get.return_value = response
                factory.return_value.cookies = requests.cookies.RequestsCookieJar()
                client = WeReadClient(min_interval=0)
                client.renew_web = Mock(side_effect=AssertionError('missing ticket must not force renewal'))
                credentials = Credentials('123', 'access')
                if error:
                    with self.assertRaises(error): client.web_articles(credentials, 'MP_WXS_1', 1)
                else:
                    self.assertEqual(client.web_articles(credentials, 'MP_WXS_1', 1)[0], [])
                client.renew_web.assert_not_called()

    def test_renewal_classification(self):
        for status, payload, error in [(429, {}, RiskControlError),
                                       (200, {'errcode': -2041}, ArticleValidationError),
                                       (401, {'errcode': -2012}, AuthExpiredError)]:
            with self.subTest(status=status), patch('weread_client.requests.Session') as factory:
                response = Mock(status_code=status, headers={}, ok=status < 400)
                response.json.return_value = payload
                factory.return_value.post.return_value = response
                with self.assertRaises(error):
                    WeReadClient(min_interval=0).renew_web(Credentials('123', 'access'))


class HTTPRouteTests(unittest.TestCase):
    """Real local HTTP, mocked upstream/application; never contacts WeRead."""
    def setUp(self):
        self.mock_app = Mock()
        self.patcher = patch.object(service, 'APP', self.mock_app)
        self.patcher.start()
        self.server = service.ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.http = requests.Session()
        self.http.trust_env = False

    def tearDown(self):
        self.http.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.patcher.stop()

    def test_health(self):
        self.mock_app.store.stats.return_value = {'sessions': 0, 'blockedSessions': 0}
        result = self.http.get(self.base + '/health', timeout=5)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'ok': True, 'sessions': 0, 'blockedSessions': 0})

    def test_original_url_route_and_pause_response(self):
        wr = 'WR' + 'a' * 70
        self.mock_app.article_url.return_value = {'url': 'https://mp.weixin.qq.com/s/f9NSNDchorq7YgSdx9_TqA'}
        result = self.http.get(self.base + '/api/v2/platform/mps/MP_WXS_456/article-url', params={'id': wr}, timeout=5)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), self.mock_app.article_url.return_value)
        self.assertEqual(self.mock_app.article_url.call_args.args[1:], ('MP_WXS_456', wr))
        self.mock_app.article_url.side_effect = RiskControlError('paused')
        result = self.http.get(self.base + '/api/v2/platform/mps/MP_WXS_456/article-url', params={'id': wr}, timeout=5)
        self.assertEqual(result.status_code, 429)

    def test_article_json_and_pagination(self):
        expected = [{'id': 'demo_A-b~c', 'title': 'Example', 'picUrl': '', 'publishTime': 123}]
        self.mock_app.articles.return_value = expected
        result = self.http.get(self.base + '/api/v2/platform/mps/MP_WXS_123/articles?page=2', timeout=5)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), expected)
        self.assertEqual(self.mock_app.articles.call_args.args[1:], ('MP_WXS_123', 2))

    def test_auth_rejection(self):
        self.mock_app.articles.side_effect = PermissionError('missing token')
        result = self.http.get(self.base + '/api/v2/platform/mps/MP_WXS_123/articles', timeout=5)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.json()['message'], 'missing token')

    def test_mock_login_routes(self):
        self.mock_app.start_login.return_value = {'uuid': 'demo', 'scanUrl': 'https://example.org/scan'}
        self.mock_app.login_result.return_value = {'vid': 123, 'token': 'fake-token', 'username': 'Example'}
        result = self.http.get(self.base + '/api/v2/login/platform', timeout=5)
        self.assertEqual(result.json()['uuid'], 'demo')
        result = self.http.get(self.base + '/api/v2/login/platform/demo', timeout=5)
        self.assertEqual(result.json()['token'], 'fake-token')
        self.mock_app.login_result.assert_called_once_with('demo')

    def test_url_conversion(self):
        self.mock_app.url_to_mp.return_value = [{'id': 'MP_WXS_123', 'name': 'Example'}]
        url = 'https://mp.weixin.qq.com/s/demo'
        result = self.http.post(self.base + '/api/v2/platform/wxs2mp', json={'url': url}, timeout=5)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()[0]['id'], 'MP_WXS_123')
        self.assertEqual(self.mock_app.url_to_mp.call_args.args[1], url)


if __name__ == '__main__':
    unittest.main()
