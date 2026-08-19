import unittest

from app.routers.subscription import REQUIRED_CHANNELS


class SubscriptionConfigTest(unittest.TestCase):
    def test_channels(self):
        self.assertEqual(len(REQUIRED_CHANNELS), 3)


if __name__ == "__main__":
    unittest.main()
