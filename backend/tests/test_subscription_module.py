import unittest
from app.routers import subscription

class SubscriptionModuleTest(unittest.TestCase):
    def test_module(self):
        self.assertIsNotNone(subscription.router)
