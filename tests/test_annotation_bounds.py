"""Regression tests for rejecting invalid boxes before annotation data is saved."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.annotation_manager import AnnotationManager


class AnnotationBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.projects = Path(self.temporary_directory.name)
        self.project = self.projects / "demo"
        self.images = self.project / "images"
        self.annotations = self.project / "annotations"
        self.images.mkdir(parents=True)
        self.annotations.mkdir()
        Image.new("RGB", (20, 10), color=(20, 40, 60)).save(
            self.images / "sample.png"
        )
        self.manager = AnnotationManager(str(self.projects))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_out_of_bounds_save_is_rejected_without_overwriting_valid_data(self):
        valid = [{"bbox": [1, 1, 5, 5], "category": "原始"}]
        self.manager.save_annotation("demo", "sample", valid)
        annotation_path = self.annotations / "sample.json"
        original = annotation_path.read_text(encoding="utf-8")

        with self.assertRaisesRegex(
            ValueError,
            r"annotation 0: bbox .* is outside 20x10 image bounds",
        ):
            self.manager.save_annotation(
                "demo",
                "sample",
                [{"bbox": [2, 9, 5, 2], "category": "原始"}],
            )

        self.assertEqual(annotation_path.read_text(encoding="utf-8"), original)

    def test_nonfinite_bbox_is_rejected_before_json_serialization(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    r"annotation 0: bbox values must be finite numbers",
                ):
                    self.manager.save_annotation(
                        "demo",
                        "sample",
                        [{"bbox": [0, 0, value, 2], "category": "原始"}],
                    )

        self.assertFalse((self.annotations / "sample.json").exists())


if __name__ == "__main__":
    unittest.main()
