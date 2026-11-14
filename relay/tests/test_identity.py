import base64
import unittest
from unittest.mock import patch
from article_identity import resolve_article_identity,ArticleIdentityError

class Response:
    status_code=200
    url='https://mp.weixin.qq.com/s/example'
    text=''
    def raise_for_status(self):pass

class IdentityTests(unittest.TestCase):
    def source(self,body):
        return '<meta property="og:title" content="Article"><meta property="og:article:author" content="Writer"><meta property="og:image" content="https://mmbiz.qpic.cn/article-cover/0"><script>var biz="'+base64.b64encode(b'123456789').decode()+'";</script>'+body

    def test_long_url_fetches_official_profile(self):
        Response.text=self.source('<a id="js_name">Official account</a><script>var round_head_img="http://mmbiz.qpic.cn/account-head/0";</script>')
        biz=base64.b64encode(b'123456789').decode().rstrip('=')
        with patch('article_identity.requests.get',return_value=Response()) as get:
            identity=resolve_article_identity(f'https://mp.weixin.qq.com/s?__biz={biz}&mid=1')
        self.assertTrue(get.called)
        self.assertEqual(identity.book_id,'MP_WXS_123456789')
        self.assertEqual(identity.account_name,'Official account')
        self.assertEqual(identity.cover,'https://mmbiz.qpic.cn/account-head/0')
        self.assertEqual(identity.intro,'')

    def test_js_nickname_fallback_uses_head_not_cover(self):
        Response.text=self.source('<script>var nickname=htmlDecode("A &amp; B");var round_head_img="https://mmbiz.qpic.cn/head/0";</script>')
        with patch('article_identity.requests.get',return_value=Response()):identity=resolve_article_identity(Response.url)
        self.assertEqual(identity.account_name,'A & B');self.assertEqual(identity.cover,'https://mmbiz.qpic.cn/head/0')

    def test_new_template_profile_fields(self):
        Response.text=self.source("<script>var profile={nick_name: 'Founder Park', round_head_img: 'http://mmbiz.qpic.cn/founder/0'};</script>")
        with patch('article_identity.requests.get',return_value=Response()):identity=resolve_article_identity(Response.url)
        self.assertEqual(identity.account_name,'Founder Park');self.assertEqual(identity.cover,'https://mmbiz.qpic.cn/founder/0')

    def test_missing_name_does_not_use_article_author(self):
        Response.text=self.source('')
        with patch('article_identity.requests.get',return_value=Response()),self.assertRaises(ArticleIdentityError):resolve_article_identity(Response.url)

    def test_missing_avatar_stays_empty(self):
        Response.text=self.source('<a id="js_name">Official</a>')
        with patch('article_identity.requests.get',return_value=Response()):identity=resolve_article_identity(Response.url)
        self.assertEqual(identity.cover,'')

    def test_other_host_rejected_without_fetch(self):
        with patch('article_identity.requests.get') as get,self.assertRaises(ArticleIdentityError):resolve_article_identity('https://example.com/s/no')
        get.assert_not_called()

if __name__=='__main__':unittest.main()
