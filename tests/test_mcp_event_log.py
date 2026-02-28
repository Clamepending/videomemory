import unittest

from videomemory.mcp_server import McpEventLog, VideoMemoryMcpServer


class _Api:
    def health(self):
        return {"status": "ok"}

    def list_devices(self):
        return {"devices": {}}

    def analyze_feed(self, io_id, prompt):
        return {"status": "success", "io_id": io_id, "prompt": prompt}

    def create_rtmp_camera(self, device_name=None, name=None):
        return {"status": "success"}

    def create_srt_camera(self, device_name=None, name=None):
        return {"status": "success"}

    def create_whip_camera(self, device_name=None, name=None):
        return {"status": "success"}

    def add_network_camera(self, url, name=None):
        return {"status": "success"}

    def remove_network_camera(self, io_id):
        return {"status": "success"}

    def list_tasks(self, io_id=None):
        return {"status": "success", "tasks": []}

    def create_task(self, io_id, task_description):
        return {"status": "success"}

    def get_task(self, task_id):
        return {"status": "success"}

    def update_task(self, task_id, new_description):
        return {"status": "success"}

    def stop_task(self, task_id):
        return {"status": "success"}

    def delete_task(self, task_id):
        return {"status": "success"}

    def get_settings(self):
        return {"settings": {}}

    def update_setting(self, key, value):
        return {"status": "saved"}


class McpEventLogTests(unittest.TestCase):
    def test_handle_message_records_event(self):
        event_log = McpEventLog(max_events=20)
        server = VideoMemoryMcpServer(_Api(), event_log=event_log)

        resp = server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            transport="http",
            remote_addr="127.0.0.1",
        )

        self.assertIn("result", resp)
        events = event_log.list(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["method"], "tools/list")
        self.assertEqual(events[0]["transport"], "http")
        self.assertEqual(events[0]["remote_addr"], "127.0.0.1")

    def test_tools_call_validation_error_is_logged(self):
        event_log = McpEventLog(max_events=20)
        server = VideoMemoryMcpServer(_Api(), event_log=event_log)

        server.handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "analyze_feed", "arguments": {"io_id": "0"}}},
            transport="http",
        )

        events = event_log.list(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["method"], "tools/call")
        self.assertEqual(events[0]["status"], "tool_error")


if __name__ == "__main__":
    unittest.main()
