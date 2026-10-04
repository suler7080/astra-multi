import unittest

from app import health


class HealthTest(unittest.TestCase):
    def test_health(self):
        self.assertEqual(health(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
