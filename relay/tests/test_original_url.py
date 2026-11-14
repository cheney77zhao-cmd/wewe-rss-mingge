import unittest
from unittest.mock import Mock, patch
import requests
from weread_client import (original_url_from_html, WeReadClient, Credentials,
                           WeReadError, RiskControlError, AuthExpiredError, ArticleValidationError)

WR = 'WR' + 'a' * 70
SHORT = 'https://mp.weixin.qq.com/s/f9NSNDchorq7YgSdx9_TqA'
LONG = 'https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=def#rd'


class OriginalUrlTests(unittest.TestCase):
    def test_metadata_short_long_and_script(self):
        for markup, expected in [
            (f'<meta content="{SHORT}" property="og:url">', SHORT),
            (f'<link rel="canonical" href="{LONG.replace("&", "&amp;")}">', LONG),
            ('var msg_link = "' + LONG.replace('&', r'\x26') + '";', LONG),
        ]:
            self.assertEqual(original_url_from_html(markup), expected)

    def test_reject_body_link_wrong_host_and_opaque_metadata(self):
        for markup in [f'<a href="{SHORT}">推荐文章</a>',
                       f'<meta property="og:url" content="https://mp.weixin.qq.com/s/{WR}">',
                       '<meta property="og:url" content="https://mp.weixin.qq.com.evil/s/abc">',
                       '<meta property="og:url" content="https://u:p@mp.weixin.qq.com/s/abc">',
                       '<meta property="og:url" content="https://mp.weixin.qq.com/s?mid=1">',
                       '操作频繁，请稍后再试']:
            with self.assertRaises(WeReadError): original_url_from_html(markup)

    def request(self, response, book='MP_WXS_123', article=WR):
        session = Mock()
        session.cookies = requests.cookies.RequestsCookieJar()
        session.get.return_value = response
        with patch('weread_client.requests.Session', return_value=session):
            result = WeReadClient(min_interval=0).web_article_url(Credentials('123', 'test'), book, article)
        return result, session

    def response(self, code=200, payload=None):
        response = Mock(status_code=code, headers={})
        response.json.return_value = payload if payload is not None else {'html': f'<meta property="og:url" content="{SHORT}">'}
        return response

    def test_multiple_accounts_and_prefixed_ids(self):
        for book, article in [('MP_WXS_123', WR), ('MP_WXS_456', 'MP_WXS_456_' + WR)]:
            (url, _), session = self.request(self.response(), book, article)
            self.assertEqual(url, SHORT)
            self.assertEqual(session.get.call_args.kwargs['params']['reviewId'], book + '_' + WR)
            self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    def test_errors_are_not_synthetic_urls(self):
        for status, payload, error in [(429, {}, RiskControlError), (403, {}, ArticleValidationError),
                                       (401, {}, AuthExpiredError), (200, {'errCode': -2012}, AuthExpiredError),
                                       (200, {'errcode': -2041}, ArticleValidationError), (500, {}, WeReadError),
                                       (200, {'html': 'not found'}, WeReadError)]:
            with self.assertRaises(error): self.request(self.response(status, payload))

    def test_raw_html_and_account_mismatch(self):
        response = self.response()
        response.json.side_effect = ValueError()
        response.text = f'<meta property="og:url" content="{SHORT}">'
        self.assertEqual(self.request(response)[0][0], SHORT)
        with self.assertRaises(WeReadError):
            self.request(self.response(), 'MP_WXS_123', 'MP_WXS_456_' + WR)


if __name__ == '__main__': unittest.main()
