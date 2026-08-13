import unittest
from app.routers.subscription import router

class SubPrefixTest(unittest.TestCase):
    def test_prefix(self):
        self.assertEqual("/subscription", router.prefix)
