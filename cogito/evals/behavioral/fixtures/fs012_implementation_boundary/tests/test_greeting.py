import unittest

from src.greeting import format_greeting, health_status


class GreetingTests(unittest.TestCase):
    def test_health(self):
        self.assertEqual(health_status(), "ok")

    def test_greeting(self):
        for name, expected in ((" Ada ", "Hello, Ada!"), ("", "Hello!"), ("   ", "Hello!")):
            with self.subTest(name=name):
                self.assertEqual(format_greeting(name), expected)
