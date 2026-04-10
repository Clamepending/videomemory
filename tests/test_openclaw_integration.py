import unittest

from videomemory.system.openclaw_integration import OpenClawWebhookConfig, OpenClawWebhookDispatcher
from videomemory.system.task_types import NoteEntry, Task


class _MockResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"status": "ok"}
        self.text = "ok"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _MockHttpClient:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def post(self, url, json, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return _MockResponse(payload={"status": "hooked"})


class OpenClawWebhookDispatcherTests(unittest.TestCase):
    def _task(self, *, bot_id="openclaw"):
        return Task(
            task_id="task-1",
            task_number=0,
            task_desc="Notify me when you see a red marker",
            task_note=[],
            done=False,
            io_id="net0",
            bot_id=bot_id,
        )

    def test_dispatch_disabled_without_webhook_url(self):
        client = _MockHttpClient()
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="",
                token="",
                timeout_s=3.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="openclaw",
            ),
            http_client=client,
        )

        result = dispatcher.dispatch_task_update(self._task(), NoteEntry("red marker visible"))

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(client.calls, [])

    def test_dispatch_posts_expected_payload(self):
        client = _MockHttpClient()
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="shared-token",
                timeout_s=5.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="openclaw",
                videomemory_base_url="http://127.0.0.1:5050",
            ),
            http_client=client,
            clock=lambda: 1_700_000_100.0,
        )

        task = self._task(bot_id="owner-bot")
        note = NoteEntry("red marker visible", timestamp=1_700_000_000.0)
        result = dispatcher.dispatch_task_update(task, note)

        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["url"], "http://openclaw:18789/hooks/videomemory-alert")
        self.assertEqual(call["timeout"], 5.0)
        self.assertEqual(call["headers"]["Authorization"], "Bearer shared-token")
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["json"]["bot_id"], "owner-bot")
        self.assertEqual(call["json"]["io_id"], "net0")
        self.assertEqual(call["json"]["task_id"], "task-1")
        self.assertEqual(call["json"]["task_description"], "Notify me when you see a red marker")
        self.assertEqual(call["json"]["note"], "red marker visible")
        self.assertEqual(call["json"]["task_api_url"], "http://127.0.0.1:5050/api/task/task-1")
        self.assertTrue(str(call["json"]["event_id"]).startswith("vm-"))

    def test_dispatch_includes_saved_note_frame_metadata(self):
        client = _MockHttpClient()
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="shared-token",
                timeout_s=5.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="openclaw",
                videomemory_base_url="http://127.0.0.1:5050",
            ),
            http_client=client,
            clock=lambda: 1_700_000_100.0,
        )

        task = self._task(bot_id="owner-bot")
        note = NoteEntry(
            "red marker visible",
            timestamp=1_700_000_000.0,
            note_id=42,
            frame_path="task_note_frames/task-1/note_42.jpg",
        )
        result = dispatcher.dispatch_task_update(task, note)

        self.assertEqual(result["status"], "sent")
        call = client.calls[0]
        self.assertEqual(call["json"]["note_id"], 42)
        self.assertTrue(call["json"]["note_has_frame"])
        self.assertEqual(call["json"]["note_frame_api_path"], "/api/task-note/42/frame")
        self.assertEqual(call["json"]["note_frame_api_url"], "http://127.0.0.1:5050/api/task-note/42/frame")

    def test_dispatch_suppresses_duplicate_note_within_ttl(self):
        client = _MockHttpClient()
        times = iter([100.0, 105.0])
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="",
                timeout_s=5.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="openclaw",
            ),
            http_client=client,
            clock=lambda: next(times),
        )

        task = self._task()
        note = NoteEntry("same note", timestamp=90.0)

        first = dispatcher.dispatch_task_update(task, note)
        second = dispatcher.dispatch_task_update(task, note)

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "suppressed")
        self.assertEqual(second["reason"], "duplicate")
        self.assertEqual(len(client.calls), 1)

    def test_dispatch_uses_default_bot_id_when_task_bot_id_missing(self):
        client = _MockHttpClient()
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="",
                timeout_s=5.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="fallback-bot",
            ),
            http_client=client,
        )

        task = self._task(bot_id="")
        result = dispatcher.dispatch_task_update(task, NoteEntry("red marker visible"))

        self.assertEqual(result["status"], "sent")
        self.assertEqual(client.calls[0]["json"]["bot_id"], "fallback-bot")

    def test_dispatch_skips_without_note_change_until_task_done(self):
        client = _MockHttpClient()
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="",
                timeout_s=5.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="openclaw",
            ),
            http_client=client,
        )

        task = self._task()
        skipped = dispatcher.dispatch_task_update(task, None)
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], "no note change")
        self.assertEqual(client.calls, [])

        task.done = True
        task.status = "done"
        task.task_note.append(NoteEntry("final observation", timestamp=95.0))
        sent = dispatcher.dispatch_task_update(task, None)

        self.assertEqual(sent["status"], "sent")
        self.assertEqual(client.calls[0]["json"]["note"], "final observation")
        self.assertTrue(client.calls[0]["json"]["task_done"])

    def test_dispatch_rate_limits_successive_updates(self):
        client = _MockHttpClient()
        times = iter([100.0, 101.0])
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="",
                timeout_s=5.0,
                dedupe_ttl_s=0.0,
                min_interval_s=10.0,
                default_bot_id="openclaw",
            ),
            http_client=client,
            clock=lambda: next(times),
        )

        first = dispatcher.dispatch_task_update(self._task(), NoteEntry("first"))
        second = dispatcher.dispatch_task_update(self._task(), NoteEntry("second"))

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "suppressed")
        self.assertEqual(second["reason"], "rate_limited")
        self.assertEqual(len(client.calls), 1)

    def test_dispatch_retries_after_http_failure(self):
        client = _MockHttpClient(responses=[_MockResponse(status_code=500), _MockResponse(payload={"status": "hooked"})])
        dispatcher = OpenClawWebhookDispatcher(
            config_loader=lambda: OpenClawWebhookConfig(
                url="http://openclaw:18789/hooks/videomemory-alert",
                token="",
                timeout_s=5.0,
                dedupe_ttl_s=30.0,
                min_interval_s=0.0,
                default_bot_id="openclaw",
            ),
            http_client=client,
            clock=lambda: 100.0,
        )

        task = self._task()
        note = NoteEntry("same note", timestamp=90.0)

        with self.assertRaises(RuntimeError):
            dispatcher.dispatch_task_update(task, note)
        second = dispatcher.dispatch_task_update(task, note)

        self.assertEqual(second["status"], "sent")
        self.assertEqual(len(client.calls), 2)


if __name__ == "__main__":
    unittest.main()
