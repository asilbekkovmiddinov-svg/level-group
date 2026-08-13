import unittest
from unittest.mock import patch
from app.routers.subscription import _is_member

class SubscriptionFailClosedTest(unittest.TestCase):
    @patch("app.routers.subscription.TELEGRAM_BOT_TOKEN", "")
    def test_missing_token_rejected(self):
        with self.assertRaises(RuntimeError):
            _is_member("@KingPessser", 123)

if __name__ == "__main__":
    unittest.main()
