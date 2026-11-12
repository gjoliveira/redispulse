
import unittest

from simulator.generator import generate_events


class TestGenerator(unittest.TestCase):

    def test_conversation_events(self):
        events = generate_events("conversation", limit=10)

        self.assertEqual(len(events), 10)

        for event in events:
            self.assertEqual(event.model_id, "llm-conversation")
            self.assertIn(event.version_id, ["conv-v1", "conv-v2"])
            self.assertGreaterEqual(event.latency_ms, 0)
            self.assertGreaterEqual(event.input_tokens, 0)
            self.assertGreaterEqual(event.output_tokens, 0)

    def test_code_events(self):
        events = generate_events("code", limit=10)

        self.assertEqual(len(events), 10)

        for event in events:
            self.assertEqual(event.model_id, "llm-code")
            self.assertIn(event.version_id, ["code-v1", "code-v2"])

    def test_unique_request_ids(self):
        events = generate_events("conversation", limit=100)

        ids = [event.request_id for event in events]

        self.assertEqual(len(ids), len(set(ids)))

    def test_error_fields(self):
        events = generate_events("conversation", limit=100)

        for event in events:
            if event.status == "error":
                self.assertIsNotNone(event.error_type)
            else:
                self.assertIsNone(event.error_type)


if __name__ == "__main__":
    unittest.main()
