import unittest
from app.routers.subscription import REQUIRED_CHANNELS

class RequiredMetadataTest(unittest.TestCase):
    def test_metadata(self):
        self.assertTrue(all("url" in item for item in REQUIRED_CHANNELS))
