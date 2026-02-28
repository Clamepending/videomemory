import unittest
from unittest.mock import patch

from videomemory.integrations.openclaw_notifier import OpenClawWakeNotifier


class _Task:
    def __init__(self, task_id="1", io_id="net0", task_desc="Watch for package", done=False):
        self.task_id = task_id
        self.task_number = 0
        self.io_id = io_id
        self.task_desc = task_desc
        self.done = done
        self.status = "active"
        self.task_note = []


class _Note:
    def __init__(self, content, timestamp=1234.5):
        self.content = content
        self.timestamp = timestamp


class OpenClawNotifierTests(unittest.TestCase):
    def test_disabled_without_webhook_url(self):
        notifier = OpenClawWakeNotifier(webhook_url="")
        self.assertFalse(notifier.notify_task_update(_Task(), _Note("x")))

    @patch("videomemory.integrations.openclaw_notifier.requests.post")
    def test_sends_payload_and_auth_header(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"
        notifier = OpenClawWakeNotifier(
            webhook_url="http://openclaw:18789/v1/vision-alert",
            bearer_token="secret",
            dedupe_ttl_seconds=30,
        )
        task = _Task()
        note = _Note("Package detected")

        sent = notifier.notify_task_update(task, note)

        self.assertTrue(sent)
        self.assertEqual(mock_post.call_count, 1)
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["json"]["task_id"], "1")
        self.assertEqual(kwargs["json"]["note"], "Package detected")

    @patch("videomemory.integrations.openclaw_notifier.requests.post")
    def test_dedupes_same_note_within_ttl(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"
        notifier = OpenClawWakeNotifier(
            webhook_url="http://openclaw:18789/v1/vision-alert",
            dedupe_ttl_seconds=60,
        )
        task = _Task()
        note = _Note("Person entered")

        self.assertTrue(notifier.notify_task_update(task, note))
        self.assertFalse(notifier.notify_task_update(task, note))
        self.assertEqual(mock_post.call_count, 1)

    @patch("videomemory.integrations.openclaw_notifier.requests.post")
    def test_throttle_blocks_second_event(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"
        notifier = OpenClawWakeNotifier(
            webhook_url="http://openclaw:18789/v1/vision-alert",
            dedupe_ttl_seconds=0,
            min_interval_seconds=10,
        )
        task = _Task()

        first = notifier.notify_task_update(task, _Note("A"))
        second = notifier.notify_task_update(task, _Note("B"))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
