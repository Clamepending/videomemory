import unittest

from videomemory.cloud_event_server import create_app


class CloudEventServerTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_http_queue_roundtrip(self):
        r = self.client.post("/api/event/triggers", json={"edge_id": "edge-1", "event_type": "task_update", "note": "x"})
        self.assertEqual(r.status_code, 200)

        r = self.client.post(
            "/api/event/commands",
            json={"edge_id": "edge-1", "action": "list_devices", "args": {}},
        )
        self.assertEqual(r.status_code, 201)
        queued = r.get_json()
        self.assertEqual(queued["status"], "queued")

        r = self.client.post("/api/event/commands/pull", json={"edge_id": "edge-1", "max_commands": 1})
        self.assertEqual(r.status_code, 200)
        pulled = r.get_json()
        self.assertEqual(len(pulled["commands"]), 1)
        self.assertEqual(pulled["commands"][0]["action"], "list_devices")

        r = self.client.post(
            "/api/event/commands/result",
            json={"edge_id": "edge-1", "request_id": pulled["commands"][0]["request_id"], "status": "success"},
        )
        self.assertEqual(r.status_code, 200)

        r = self.client.get("/api/event/results")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(len(data["results"]), 1)

        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Cloud VideoMemory Server", r.data)

    def test_mcp_enqueue_and_list_edges(self):
        r = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["result"]["serverInfo"]["name"], "videomemory-cloud-mcp")

        r = self.client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "enqueue_edge_command",
                    "arguments": {"edge_id": "edge-42", "action": "list_tasks", "args": {"io_id": "0"}},
                },
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()["result"]
        self.assertFalse(body["isError"])
        self.assertEqual(body["structuredContent"]["status"], "queued")

        r = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_edges"}})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()["result"]
        self.assertFalse(body["isError"])
        self.assertTrue(any(e["edge_id"] == "edge-42" for e in body["structuredContent"]["edges"]))


if __name__ == "__main__":
    unittest.main()
