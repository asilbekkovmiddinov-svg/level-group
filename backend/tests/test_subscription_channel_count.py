import unittest

from app.routers.subscription import REQUIRED_CHANNELS


class RequiredChannelCountTest(unittest.TestCase):
    def test_three_channels_required(self):
        self.assertEqual(3, len(REQUIRED_CHANNELS))
