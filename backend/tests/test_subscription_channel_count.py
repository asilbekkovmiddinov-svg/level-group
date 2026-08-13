import unittest
from app.routers.subscription import REQUIRED_CHANNELS

class RequiredChannelCountTest(unittest.TestCase):
    def test_two_channels_required(self):
        self.assertEqual(2, len(REQUIRED_CHANNELS))
