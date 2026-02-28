import json
import unittest

from videomemory.mcp_server import ApiError, VideoMemoryMcpServer


class FakeApi:
    base_url = "http://videomemory:5050"

    def health(self):
        return {"status": "ok", "service": "videomemory"}

    def list_devices(self):
        return {"devices": {"camera": [{"io_id": "net0", "name": "Front Door"}]}}

    def create_rtmp_camera(self, device_name=None, name=None):
        return {"status": "success", "rtmp_url": "rtmp://videomemory:1935/live/front", "device": {"io_id": "net0"}}

    def analyze_feed(self, io_id, prompt):
        return {"status": "success", "io_id": io_id, "prompt": prompt, "analysis": "A person in a black hoodie is near the doorway."}

    def add_network_camera(self, url, name=None):
        return {"status": "success", "device": {"io_id": "net1", "url": url, "name": name}}

    def remove_network_camera(self, io_id):
        return {"status": "success", "io_id": io_id}

    def list_tasks(self, io_id=None):
        tasks = [{"task_id": "1", "task_desc": "Watch for package", "io_id": "net0", "status": "active"}]
        if io_id:
            tasks = [t for t in tasks if t["io_id"] == io_id]
        return {"status": "success", "tasks": tasks, "count": len(tasks)}

    def create_task(self, io_id, task_description):
        return {"status": "success", "task_id": "1", "io_id": io_id, "task_description": task_description}

    def get_task(self, task_id):
        if task_id == "404":
            raise ApiError("Task not found", status_code=404, payload={"error": "Task not found"})
        return {"status": "success", "task": {"task_id": task_id, "task_desc": "Watch for package"}}

    def update_task(self, task_id, new_description):
        return {"status": "success", "task_id": task_id, "new_description": new_description}

    def stop_task(self, task_id):
        return {"status": "success", "task_id": task_id}

    def delete_task(self, task_id):
        return {"status": "success", "task_id": task_id}

    def get_settings(self):
        return {"settings": {"GOOGLE_API_KEY": {"is_set": False}}}

    def update_setting(self, key, value):
        return {"status": "saved", "key": key, "value": value}

class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.server = VideoMemoryMcpServer(FakeApi())

    def _call(self, method, params=None, msg_id=1):
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        return self.server.handle_message(msg)

    def test_initialize(self):
        resp = self._call("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(resp["result"]["serverInfo"]["name"], "videomemory-mcp")

    def test_tools_list_contains_rtmp_tool(self):
        resp = self._call("tools/list")
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("create_rtmp_camera", names)
        self.assertNotIn("create_srt_camera", names)
        self.assertNotIn("create_whip_camera", names)

    def test_tools_call_hidden_srt_tool_returns_error(self):
        resp = self._call("tools/call", {"name": "create_srt_camera", "arguments": {}})
        result = resp["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Unknown tool", str(result["structuredContent"]["error"]))

    def test_tools_call_hidden_whip_tool_returns_error(self):
        resp = self._call("tools/call", {"name": "create_whip_camera", "arguments": {}})
        result = resp["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Unknown tool", str(result["structuredContent"]["error"]))

    def test_tools_call_success(self):
        resp = self._call(
            "tools/call",
            {"name": "create_task", "arguments": {"io_id": "net0", "task_description": "Watch for package"}},
        )
        result = resp["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["task_id"], "1")

    def test_tools_call_analyze_feed(self):
        resp = self._call(
            "tools/call",
            {
                "name": "analyze_feed",
                "arguments": {"io_id": "net0", "prompt": "Describe the person in frame"},
            },
        )
        result = resp["result"]
        self.assertFalse(result["isError"])
        self.assertIn("analysis", result["structuredContent"])

    def test_tools_call_api_error_returns_tool_error(self):
        resp = self._call("tools/call", {"name": "get_task", "arguments": {"task_id": "404"}})
        result = resp["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["status_code"], 404)

    def test_resources_read_task(self):
        resp = self._call("resources/read", {"uri": "videomemory://task/1"})
        contents = resp["result"]["contents"]
        self.assertEqual(contents[0]["mimeType"], "application/json")
        decoded = json.loads(contents[0]["text"])
        self.assertEqual(decoded["task"]["task_id"], "1")

    def test_unknown_method(self):
        resp = self._call("nope/method")
        self.assertEqual(resp["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
