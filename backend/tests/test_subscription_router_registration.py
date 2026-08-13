import pathlib
import unittest

class SubscriptionRouterRegistrationTest(unittest.TestCase):
    def test_router_registered(self):
        text = pathlib.Path("backend/app/main.py").read_text(encoding="utf-8")
        self.assertIn("subscription_router", text)
