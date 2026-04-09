import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flask_app.app as app_module
from videomemory.system.database import TaskDatabase
from videomemory.system.usage import estimate_model_cost_usd


class UsageApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "usage-test.db")
        self.db = TaskDatabase(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _seed_usage_events(self, now_ts: float) -> None:
        self.db.save_model_usage_event(
            {
                "created_at": now_ts - 1800,
                "provider_name": "OpenAIGPT4oMiniProvider",
                "model_name": "gpt-4o-mini",
                "api_model_name": "gpt-4o-mini-2024-07-18",
                "source": "caption_frame",
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
                "estimated_cost_usd": 0.000036,
                "latency_ms": 842.0,
                "was_success": True,
            }
        )
        self.db.save_model_usage_event(
            {
                "created_at": now_ts - 3 * 3600,
                "provider_name": "Gemini25FlashProvider",
                "model_name": "gemini-2.5-flash",
                "api_model_name": "gemini-2.5-flash",
                "source": "task_ingestor",
                "input_tokens": 400,
                "output_tokens": 80,
                "total_tokens": 480,
                "estimated_cost_usd": 0.00032,
                "latency_ms": 1333.0,
                "was_success": True,
            }
        )
        self.db.save_model_usage_event(
            {
                "created_at": now_ts - 10 * 24 * 3600,
                "provider_name": "LocalVLLMProvider",
                "model_name": "local-vllm",
                "api_model_name": "Qwen/Qwen3-VL-8B-Instruct-FP8",
                "source": "task_ingestor",
                "input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 60,
                "estimated_cost_usd": 0.0,
                "latency_ms": 512.0,
                "was_success": False,
            }
        )

    def test_usage_api_returns_summary_and_recent_events_for_selected_range(self):
        now_ts = 1_775_700_000.0
        self._seed_usage_events(now_ts)

        with (
            patch.object(app_module, "db", self.db),
            patch("time.time", return_value=now_ts),
        ):
            resp = self.client.get("/api/usage?range=week")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["range"], "week")
        self.assertEqual(body["summary"]["calls"], 2)
        self.assertEqual(body["summary"]["success_calls"], 2)
        self.assertEqual(body["summary"]["input_tokens"], 520)
        self.assertEqual(body["summary"]["output_tokens"], 110)
        self.assertAlmostEqual(body["summary"]["estimated_cost_usd"], 0.000356, places=9)
        self.assertEqual(len(body["recent_events"]), 2)
        self.assertEqual(body["recent_events"][0]["model_name"], "gpt-4o-mini")
        self.assertEqual(body["recent_events"][1]["model_name"], "gemini-2.5-flash")
        self.assertTrue(any(model["model_name"] == "gpt-4o-mini" for model in body["models"]))

    def test_usage_csv_export_matches_time_range_filter(self):
        now_ts = 1_775_700_000.0
        self._seed_usage_events(now_ts)

        with (
            patch.object(app_module, "db", self.db),
            patch("time.time", return_value=now_ts),
        ):
            resp = self.client.get("/api/usage/export.csv?range=day")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        rows = list(csv.reader(resp.get_data(as_text=True).splitlines()))
        self.assertEqual(rows[0][0], "timestamp")
        self.assertEqual(len(rows), 3)
        exported_models = {rows[1][2], rows[2][2]}
        self.assertEqual(exported_models, {"gpt-4o-mini", "gemini-2.5-flash"})

    def test_estimate_model_cost_uses_current_claude_opus_46_pricing(self):
        cost = estimate_model_cost_usd(
            "claude-opus-4-6",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        self.assertAlmostEqual(cost, 30.0, places=8)


if __name__ == "__main__":
    unittest.main()
