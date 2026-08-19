import unittest

from app.routers.subscription import REQUIRED_CHANNELS


class SubscriptionUrlsTest(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(len([channel["url"] for channel in REQUIRED_CHANNELS]), 3)
