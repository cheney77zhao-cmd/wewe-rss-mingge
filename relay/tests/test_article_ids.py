import unittest
from weread_client import WeReadClient, wechat_article_id


class ArticleIdTests(unittest.TestCase):
    def test_prefixed_link(self):
        actual = wechat_article_id('MP_WXS_123_demo_A-b~c')
        self.assertEqual('https://mp.weixin.qq.com/s/' + actual,
                         'https://mp.weixin.qq.com/s/demo_A-b~c')

    def test_preserves_token_characters_and_is_idempotent(self):
        for token in ('a_b_c', 'example~token', '-a_b~c', 'normal'):
            with self.subTest(token=token):
                self.assertEqual(wechat_article_id('MP_WXS_123_' + token), token)
                self.assertEqual(wechat_article_id(wechat_article_id('MP_WXS_123_' + token)), token)

    def test_both_payload_formats_produce_short_ids(self):
        review = {'reviewId': 'MP_WXS_123_a_b', 'title': 'Example',
                  'mpInfo': {'time': 1234567890, 'pic_url': 'https://example.org/cover'}}
        for payload in ({'data': [review]}, {'reviews': [{'subReviews': [{'review': review}]}]}):
            with self.subTest(payload=payload):
                articles = WeReadClient._parse_articles(payload)
                self.assertEqual(len(articles), 1)
                self.assertEqual(articles[0].article_id, 'a_b')
                self.assertEqual(articles[0].publish_time, 1234567890)


if __name__ == '__main__':
    unittest.main()
