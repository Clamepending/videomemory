import unittest
from unittest.mock import patch

import numpy as np

from videomemory.system.stream_ingestors import semantic_filter


class FakeDinoRuntime:
    def __init__(self, max_score: float):
        self.max_score = max_score
        self.encoded_keywords = []

    def encode_texts(self, keywords):
        self.encoded_keywords = list(keywords)
        return np.ones((len(keywords), 4), dtype=np.float32)

    def score_image_embeddings(self, image_rgb, text_embeddings):
        scores = np.full((256, text_embeddings.shape[0]), 0.10, dtype=np.float32)
        scores[42, 0] = self.max_score
        return scores


class SemanticFilterDinoBackendTests(unittest.TestCase):
    def test_default_threshold_is_point_three(self):
        config = semantic_filter.coerce_config({})

        self.assertAlmostEqual(config.threshold, 0.30)

    def _score_with_fake_runtime(self, max_score: float):
        runtime = FakeDinoRuntime(max_score)
        frame_filter = semantic_filter.SemanticFrameFilter(
            semantic_filter.SemanticFilterConfig(
                enabled=True,
                keywords="person",
                backend="dino_clip_adapter",
                threshold=0.50,
            )
        )
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        with patch.object(semantic_filter, "load_dino_clip_adapter_runtime", return_value=runtime) as loader:
            result = frame_filter.score(frame)
        return result, runtime, loader

    def test_dino_backend_keeps_frame_when_any_patch_crosses_threshold(self):
        result, runtime, loader = self._score_with_fake_runtime(0.80)

        self.assertTrue(result.should_keep)
        self.assertEqual(result.backend, "dino_clip_adapter")
        self.assertEqual(result.model, semantic_filter.DEFAULT_SEMANTIC_FILTER_MODEL)
        self.assertEqual(runtime.encoded_keywords, ["person"])
        self.assertEqual(loader.call_count, 1)
        self.assertIsNotNone(result.overlay_frame)

    def test_dino_backend_skips_frame_when_no_patch_crosses_threshold(self):
        result, _, _ = self._score_with_fake_runtime(0.20)

        self.assertFalse(result.should_keep)
        self.assertAlmostEqual(result.threshold, 0.50)
        self.assertLess(result.score, 0.50)


if __name__ == "__main__":
    unittest.main()
