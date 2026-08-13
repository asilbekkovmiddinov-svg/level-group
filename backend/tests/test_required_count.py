import unittest
from app.routers.subscription import REQUIRED_CHANNELS

class RequiredCountTest(unittest.TestCase):
    def test_value(self):
        self.assertEqual(2, len(REQUIRED_CHANNELS))
