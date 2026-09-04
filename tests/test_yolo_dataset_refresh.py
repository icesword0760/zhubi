"""Regression coverage for rebuilding and splitting YOLO training datasets."""

import json
import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml
from PIL import Image

from backend.export_manager import ExportManager
from backend.yolo_train_manager import YoloTrainManager


class YoloDatasetRefreshTests(unittest.TestCase):
    """Exercise the training manager through an isolated on-disk project."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.data = self.root / "data"
        self.project = self.data / "projects" / "demo"
        self.images = self.project / "images"
        self.annotations = self.project / "annotations"
        self.models = self.data / "models"
        self.exports = self.data / "exports"
        self.active = self.models / "demo" / "yolo_data"

        self.images.mkdir(parents=True)
        self.annotations.mkdir()
        self.models.mkdir()
        self.exports.mkdir()
        (self.project / "project.json").write_text(
            json.dumps(
                {
                    "id": "demo",
                    "name": "demo",
                    "description": "isolated YOLO refresh fixture",
                    "categories": ["原始"],
                    "created_at": "2026-07-10T00:00:00",
                    "updated_at": "2026-07-10T00:00:00",
                    "image_count": 0,
                    "annotated_count": 0,
                    "version": 1,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.manager = YoloTrainManager(str(self.models), {})

    def tearDown(self):
        self._temporary_directory.cleanup()

    def add_domain_images(self, domain, count, size, start=0):
        """Add uniquely named, valid annotated PNG records to the project."""
        width, height = size
        for index in range(start, start + count):
            filename = f"{domain}_{index:04d}.png"
            image_id = Path(filename).stem
            image_path = self.images / filename
            annotation_path = self.annotations / f"{image_id}.json"
            self.assertFalse(
                image_path.exists(), f"fixture image already exists: {filename}"
            )
            self.assertFalse(
                annotation_path.exists(),
                f"fixture annotation already exists: {annotation_path.name}",
            )
            Image.new("RGB", size, color=(index % 256, 32, 64)).save(image_path)
            annotation = {
                "image_id": image_id,
                "image_filename": filename,
                "image_width": width,
                "image_height": height,
                "annotations": [
                    {
                        "bbox": [10, 10, max(1, width // 3), max(1, height // 3)],
                        "category": "原始",
                    }
                ],
                "annotated_at": "2026-07-10T00:00:00",
                "version": 1,
            }
            annotation_path.write_text(
                json.dumps(annotation, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def prepare_with_stats(self, split_ratios=(0.7, 0.2, 0.1)):
        """Call the approved three-value preparation contract with a clear RED."""
        result = self.manager._prepare_dataset("demo", split_ratios)
        self.assertIsInstance(result, tuple)
        self.assertEqual(
            len(result),
            3,
            "_prepare_dataset must return (success, error_message, verified_stats)",
        )
        return result

    def split_membership(self):
        return {
            split: {
                path.name
                for path in (self.active / "images" / split).glob("*.png")
            }
            for split in ("train", "val", "test")
        }

    def assert_no_split_overlap(self, membership):
        self.assertTrue(membership["train"].isdisjoint(membership["val"]))
        self.assertTrue(membership["train"].isdisjoint(membership["test"]))
        self.assertTrue(membership["val"].isdisjoint(membership["test"]))

    def split_domain_counts(self):
        """Count domains from the dimensions of the activated image files."""
        counts = {}
        for split in ("train", "val", "test"):
            split_counts = {"portrait": 0, "landscape": 0}
            for image_path in (self.active / "images" / split).glob("*.png"):
                with Image.open(image_path) as image:
                    ratio = image.width / image.height
                if ratio < 0.8:
                    split_counts["portrait"] += 1
                elif ratio > 1.25:
                    split_counts["landscape"] += 1
                else:
                    self.fail(
                        f"unexpected square-like fixture image: {image_path.name}"
                    )
            counts[split] = split_counts
        return counts

    def test_rebuild_includes_annotations_added_after_data_yaml_exists(self):
        self.add_domain_images("fullscreen", 50, (108, 240))
        self.add_domain_images("captcha", 50, (158, 105))

        ok, error, first = self.prepare_with_stats()
        self.assertTrue(ok, error)
        self.assertEqual(
            first["split_counts"], {"train": 70, "val": 20, "test": 10}
        )
        self.assertTrue((self.active / "data.yaml").exists())

        self.add_domain_images("fullscreen", 50, (108, 240), start=50)
        self.add_domain_images("captcha", 50, (158, 105), start=50)
        ok, error, second = self.prepare_with_stats()

        self.assertTrue(ok, error)
        self.assertEqual(second["source_count"], 200)
        self.assertEqual(
            second["split_counts"], {"train": 140, "val": 40, "test": 20}
        )
        membership = self.split_membership()
        self.assert_no_split_overlap(membership)
        self.assertEqual(
            {split: len(names) for split, names in membership.items()},
            {"train": 140, "val": 40, "test": 20},
        )
        active_filenames = set().union(*membership.values())
        source_filenames = {path.name for path in self.images.glob("*.png")}
        self.assertEqual(len(active_filenames), 200)
        self.assertEqual(active_filenames, source_filenames)
        self.assertTrue(
            {"fullscreen_0099.png", "captcha_0099.png"}.issubset(active_filenames)
        )
        self.assertNotIn("_source_manifest", second)
        train_info = self.manager._build_train_info(
            project_id="demo",
            train_config={"epochs": 1},
            final_metrics={},
            final_model_dir=str(self.models / "demo" / "yolo_final_model"),
            verified_stats=second,
        )
        self.assertNotIn("_source_manifest", train_info)

    def test_split_is_deterministic_disjoint_and_balanced_by_domain(self):
        self.add_domain_images("fullscreen", 100, (108, 240))
        self.add_domain_images("captcha", 100, (158, 105))

        ok, error, first = self.prepare_with_stats()
        self.assertTrue(ok, error)
        first_membership = self.split_membership()
        self.assert_no_split_overlap(first_membership)

        annotation_enumeration_intercepted = []

        class ReversedAnnotationEnumerationOS:
            """Proxy only the exporter's os binding, leaving other modules alone."""

            def __getattr__(proxy_self, name):
                return getattr(os, name)

            def listdir(proxy_self, path):
                entries = os.listdir(path)
                annotation_enumeration_intercepted.append(Path(path))
                return list(reversed(entries))

        with patch(
            "backend.export_manager.os",
            new=ReversedAnnotationEnumerationOS(),
        ):
            ok, error, second = self.prepare_with_stats()

        self.assertTrue(
            annotation_enumeration_intercepted,
            "second export did not enumerate annotations through export_manager.os.listdir",
        )
        self.assertTrue(ok, error)
        second_membership = self.split_membership()
        self.assertEqual(first_membership, second_membership)
        self.assert_no_split_overlap(second_membership)
        expected_domain_counts = {
            "train": {"portrait": 70, "landscape": 70},
            "val": {"portrait": 20, "landscape": 20},
            "test": {"portrait": 10, "landscape": 10},
        }
        self.assertEqual(first["domain_counts"], expected_domain_counts)
        self.assertEqual(second["domain_counts"], expected_domain_counts)
        self.assertEqual(self.split_domain_counts(), expected_domain_counts)

    def test_domain_split_uses_floor_floor_and_remainder(self):
        self.add_domain_images("fullscreen", 7, (108, 240))

        ok, error, stats = self.prepare_with_stats()

        self.assertTrue(ok, error)
        self.assertEqual(
            stats["split_counts"], {"train": 4, "val": 1, "test": 2}
        )
        self.assertEqual(
            stats["domain_counts"],
            {
                "train": {"portrait": 4},
                "val": {"portrait": 1},
                "test": {"portrait": 2},
            },
        )


class YoloExporterTests(unittest.TestCase):
    """Validate source records and side-effect-free downloadable exports."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.data = self.root / "data"
        self.projects = self.data / "projects"
        self.project = self.projects / "demo"
        self.images = self.project / "images"
        self.annotations = self.project / "annotations"
        self.exports = self.data / "exports"
        self.models = self.data / "models"
        self.active = self.models / "demo" / "yolo_data"
        self.images.mkdir(parents=True)
        self.annotations.mkdir()
        self.exports.mkdir()
        self.models.mkdir()
        self._write_project()
        self.exporter = ExportManager(str(self.projects), str(self.exports))

    def tearDown(self):
        self._temporary_directory.cleanup()

    def _write_project(self, project_id="demo"):
        project = self.projects / project_id
        project.mkdir(parents=True, exist_ok=True)
        (project / "images").mkdir(exist_ok=True)
        (project / "annotations").mkdir(exist_ok=True)
        (project / "project.json").write_text(
            json.dumps(
                {
                    "id": project_id,
                    "name": project_id,
                    "description": "isolated exporter fixture",
                    "categories": ["原始", "次要"],
                    "created_at": "2026-07-10T00:00:00",
                    "updated_at": "2026-07-10T00:00:00",
                    "image_count": 0,
                    "annotated_count": 0,
                    "version": 1,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _reset_demo_source(self):
        shutil.rmtree(self.images)
        shutil.rmtree(self.annotations)
        self.images.mkdir()
        self.annotations.mkdir()

    @staticmethod
    def _valid_record(filename="sample.png", image_id=None, size=(100, 80)):
        width, height = size
        return {
            "image_id": image_id or Path(filename).stem,
            "image_filename": filename,
            "image_width": width,
            "image_height": height,
            "annotations": [
                {"bbox": [10, 10, 20, 15], "category": "原始"}
            ],
        }

    def _write_record(
        self,
        record,
        *,
        annotation_filename=None,
        image_size=None,
        create_image=True,
        raw_json=None,
    ):
        annotation_filename = annotation_filename or (
            f"{record.get('image_id', 'record')}.json"
        )
        if create_image and isinstance(record.get("image_filename"), str):
            filename = record["image_filename"]
            if "/" not in filename and "\\" not in filename:
                size = image_size or (
                    record.get("image_width", 100),
                    record.get("image_height", 80),
                )
                if all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value > 0
                    for value in size
                ):
                    Image.new("RGB", size, color=(32, 64, 96)).save(
                        self.images / filename
                    )
        annotation_path = self.annotations / annotation_filename
        if raw_json is None:
            raw_json = json.dumps(record, ensure_ascii=False)
        annotation_path.write_text(raw_json, encoding="utf-8")
        return annotation_path

    def _install_active_marker(self, contents="keep-active"):
        self.active.mkdir(parents=True, exist_ok=True)
        marker = self.active / "marker.txt"
        marker.write_text(contents, encoding="utf-8")
        return marker

    def _assert_export_rejected_without_active_replacement(self, message_fragment):
        marker = self._install_active_marker()
        export_path = self.root / "attempted-export"
        export_path.mkdir()
        with self.assertRaisesRegex(ValueError, re.escape(message_fragment)):
            self.exporter._export_yolo(
                "demo", str(export_path), (0.7, 0.2, 0.1), False
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep-active")
        self.assertEqual(list(self.active.iterdir()), [marker])
        self.assertEqual(list(export_path.iterdir()), [])

    def test_rejects_malformed_or_wrongly_typed_source_records_atomically(self):
        cases = []

        def malformed_json():
            self._write_record({}, raw_json='{"image_id":')

        cases.append(("malformed JSON", "Invalid annotation", malformed_json))

        required_fields = {
            "image_id": 123,
            "image_filename": ["sample.png"],
            "image_width": "100",
            "image_height": True,
            "annotations": {},
        }
        for field, wrong_value in required_fields.items():
            def missing(field=field):
                record = self._valid_record()
                del record[field]
                self._write_record(record, annotation_filename=f"missing_{field}.json")

            def wrong_type(field=field, wrong_value=wrong_value):
                record = self._valid_record()
                record[field] = wrong_value
                self._write_record(record, annotation_filename=f"wrong_{field}.json")

            cases.extend(
                [
                    (
                        f"missing {field}",
                        (
                            "annotations must be a list"
                            if field == "annotations"
                            else "image_id must be a non-empty string"
                            if field == "image_id"
                            else "image_filename must be a basename"
                            if field == "image_filename"
                            else f"{field} must be a positive integer"
                        ),
                        missing,
                    ),
                    (
                        f"wrongly typed {field}",
                        (
                            "annotations must be a list"
                            if field == "annotations"
                            else "image_id must be a non-empty string"
                            if field == "image_id"
                            else "image_filename must be a basename"
                            if field == "image_filename"
                            else f"{field} must be a positive integer"
                        ),
                        wrong_type,
                    ),
                ]
            )

        special_cases = [
            (
                "traversal filename",
                "image_filename must be a basename",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "image_filename": "../outside.png",
                    },
                    create_image=False,
                ),
            ),
            (
                "missing image",
                "source image does not exist",
                lambda: self._write_record(
                    self._valid_record(), create_image=False
                ),
            ),
            (
                "stored versus real dimension mismatch",
                "stored dimensions",
                lambda: self._write_record(
                    self._valid_record(), image_size=(101, 80)
                ),
            ),
            (
                "zero stored image width",
                "image_width must be a positive integer",
                lambda: self._write_record(
                    {**self._valid_record(), "image_width": 0},
                    create_image=False,
                ),
            ),
            (
                "negative stored image height",
                "image_height must be a positive integer",
                lambda: self._write_record(
                    {**self._valid_record(), "image_height": -1},
                    create_image=False,
                ),
            ),
            (
                "annotation item is not an object",
                "expected an object",
                lambda: self._write_record(
                    {**self._valid_record(), "annotations": [None]}
                ),
            ),
            (
                "missing annotation category",
                "unknown category",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [{"bbox": [10, 10, 20, 15]}],
                    }
                ),
            ),
            (
                "missing annotation bbox",
                "bbox must be a four-element list",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [{"category": "原始"}],
                    }
                ),
            ),
            (
                "bbox is not a list",
                "bbox must be a four-element list",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": "10,10,20,15", "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "bbox has wrong length",
                "bbox must be a four-element list",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [10, 10, 20], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "unknown category",
                "unknown category",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [10, 10, 20, 15], "category": "未知"}
                        ],
                    }
                ),
            ),
            (
                "nonnumeric bbox",
                "bbox values must be finite numbers",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": ["10", 10, 20, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "boolean bbox number",
                "bbox values must be finite numbers",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [True, 10, 20, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "NaN bbox",
                "bbox values must be finite numbers",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [math.nan, 10, 20, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "infinite bbox",
                "bbox values must be finite numbers",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [10, 10, math.inf, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "zero bbox width",
                "bbox width and height must be positive",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [10, 10, 0, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "negative bbox height",
                "bbox width and height must be positive",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [10, 10, 20, -1], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "negative bbox origin",
                "outside",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [-1, 10, 20, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
            (
                "bbox extends beyond image",
                "outside",
                lambda: self._write_record(
                    {
                        **self._valid_record(),
                        "annotations": [
                            {"bbox": [90, 10, 20, 15], "category": "原始"}
                        ],
                    }
                ),
            ),
        ]
        cases.extend(special_cases)

        for name, message_fragment, prepare in cases:
            with self.subTest(case=name):
                self._reset_demo_source()
                if self.active.exists():
                    shutil.rmtree(self.active)
                attempted_export = self.root / "attempted-export"
                if attempted_export.exists():
                    shutil.rmtree(attempted_export)
                prepare()
                self._assert_export_rejected_without_active_replacement(
                    message_fragment
                )

    def test_rejects_duplicate_ids_filenames_and_label_stems_atomically(self):
        def duplicate_id():
            self._write_record(self._valid_record("first.png", image_id="same"), annotation_filename="a.json")
            self._write_record(self._valid_record("second.png", image_id="same"), annotation_filename="b.json")

        def duplicate_filename():
            self._write_record(self._valid_record("same.png", image_id="first"), annotation_filename="a.json")
            self._write_record(self._valid_record("same.png", image_id="second"), annotation_filename="b.json")

        def duplicate_label_stem():
            self._write_record(self._valid_record("sample.jpg", image_id="first"), annotation_filename="a.json")
            self._write_record(self._valid_record("sample.png", image_id="second"), annotation_filename="b.json")

        for name, message_fragment, prepare in [
            ("image_id", "duplicate image_id", duplicate_id),
            ("image_filename", "duplicate image_filename", duplicate_filename),
            ("label stem", "duplicate label stem", duplicate_label_stem),
        ]:
            with self.subTest(duplicate=name):
                self._reset_demo_source()
                if self.active.exists():
                    shutil.rmtree(self.active)
                attempted_export = self.root / "attempted-export"
                if attempted_export.exists():
                    shutil.rmtree(attempted_export)
                prepare()
                self._assert_export_rejected_without_active_replacement(
                    message_fragment
                )

    def test_rejects_casefolded_destination_collisions_atomically(self):
        def casefolded_image_id():
            self._write_record(
                self._valid_record("first.png", image_id="SampleID"),
                annotation_filename="a.json",
            )
            self._write_record(
                self._valid_record("second.png", image_id="sampleid"),
                annotation_filename="b.json",
            )

        def casefolded_image_filename():
            self._write_record(
                self._valid_record("sample.png", image_id="first"),
                annotation_filename="a.json",
            )
            self._write_record(
                self._valid_record("Sample.png", image_id="second"),
                annotation_filename="b.json",
            )

        def casefolded_label_stem():
            self._write_record(
                self._valid_record("sample.jpg", image_id="first"),
                annotation_filename="a.json",
            )
            self._write_record(
                self._valid_record("Sample.png", image_id="second"),
                annotation_filename="b.json",
            )

        for name, message_fragment, prepare in [
            ("image_id", "duplicate image_id", casefolded_image_id),
            (
                "image_filename",
                "duplicate image_filename",
                casefolded_image_filename,
            ),
            ("label stem", "duplicate label stem", casefolded_label_stem),
        ]:
            with self.subTest(collision=name):
                self._reset_demo_source()
                if self.active.exists():
                    shutil.rmtree(self.active)
                attempted_export = self.root / "attempted-export"
                if attempted_export.exists():
                    shutil.rmtree(attempted_export)
                prepare()
                self._assert_export_rejected_without_active_replacement(
                    message_fragment
                )

    def test_rejects_unicode_normalized_destination_collisions_atomically(self):
        composed = "café"
        decomposed = "cafe\u0301"

        def normalized_image_id():
            self._write_record(
                self._valid_record("first.png", image_id=f"{composed}-id"),
                annotation_filename="a.json",
            )
            self._write_record(
                self._valid_record("second.png", image_id=f"{decomposed}-id"),
                annotation_filename="b.json",
            )

        def normalized_image_filename():
            self._write_record(
                self._valid_record(f"{composed}.png", image_id="first"),
                annotation_filename="a.json",
            )
            self._write_record(
                self._valid_record(f"{decomposed}.png", image_id="second"),
                annotation_filename="b.json",
            )

        def normalized_label_stem():
            self._write_record(
                self._valid_record(f"{composed}.jpg", image_id="first"),
                annotation_filename="a.json",
            )
            self._write_record(
                self._valid_record(f"{decomposed}.png", image_id="second"),
                annotation_filename="b.json",
            )

        for name, message_fragment, prepare in [
            ("image_id", "duplicate image_id", normalized_image_id),
            (
                "image_filename",
                "duplicate image_filename",
                normalized_image_filename,
            ),
            ("label stem", "duplicate label stem", normalized_label_stem),
        ]:
            with self.subTest(collision=name):
                self._reset_demo_source()
                if self.active.exists():
                    shutil.rmtree(self.active)
                attempted_export = self.root / "attempted-export"
                if attempted_export.exists():
                    shutil.rmtree(attempted_export)
                prepare()
                self._assert_export_rejected_without_active_replacement(
                    message_fragment
                )

    def test_rejects_invalid_split_ratios_without_touching_active_dataset(self):
        invalid_ratios = [
            ("wrong length", (0.8, 0.2), "exactly three numbers"),
            ("negative", (0.8, 0.3, -0.1), "finite non-negative numbers"),
            ("NaN", (math.nan, 0.5, 0.5), "finite non-negative numbers"),
            ("infinite", (math.inf, 0.0, 0.0), "finite non-negative numbers"),
            ("boolean", (True, 0.0, 0.0), "finite non-negative numbers"),
            ("sum not one", (0.7, 0.2, 0.2), "sum to 1"),
        ]
        self._write_record(self._valid_record())

        for name, ratios, message_fragment in invalid_ratios:
            with self.subTest(case=name):
                if self.active.exists():
                    shutil.rmtree(self.active)
                marker = self._install_active_marker()
                export_path = self.root / f"ratio-{name}"
                export_path.mkdir()
                with self.assertRaisesRegex(
                    ValueError, re.escape(message_fragment)
                ):
                    self.exporter._export_yolo(
                        "demo", str(export_path), ratios, False
                    )
                self.assertEqual(
                    marker.read_text(encoding="utf-8"), "keep-active"
                )
                self.assertEqual(list(self.active.iterdir()), [marker])
                self.assertEqual(list(export_path.iterdir()), [])

    def test_split_is_deterministic_stratified_and_uses_test_remainder(self):
        records = []
        for prefix, size, count in [
            ("portrait", (40, 100), 7),
            ("square", (100, 100), 6),
            ("landscape", (150, 100), 5),
        ]:
            for index in range(count):
                records.append(
                    self._valid_record(
                        f"{prefix}_{index}.png", size=size
                    )
                )

        first, first_domains = self.exporter._split_yolo_dataset(
            records, (0.7, 0.2, 0.1), seed=17
        )
        second, second_domains = self.exporter._split_yolo_dataset(
            list(reversed(records)), (0.7, 0.2, 0.1), seed=17
        )

        membership = lambda splits: {
            split: [record["image_filename"] for record in split_records]
            for split, split_records in splits.items()
        }
        self.assertEqual(membership(first), membership(second))
        self.assertEqual(first_domains, second_domains)
        for split, filenames in membership(first).items():
            self.assertEqual(
                filenames,
                sorted(filenames),
                f"{split} records must be returned in canonical filename order",
            )
        self.assertEqual(
            {split: len(items) for split, items in first.items()},
            {"train": 11, "val": 3, "test": 4},
        )
        self.assertEqual(
            first_domains,
            {
                "train": {"landscape": 3, "portrait": 4, "square": 4},
                "val": {"landscape": 1, "portrait": 1, "square": 1},
                "test": {"landscape": 1, "portrait": 2, "square": 1},
            },
        )

    def test_source_enumeration_order_does_not_change_split_membership(self):
        self._add_export_records()
        canonical_records, _ = self.exporter._load_validated_yolo_source("demo")
        canonical_splits, _ = self.exporter._split_yolo_dataset(
            canonical_records, (0.7, 0.2, 0.1), seed=23
        )
        annotation_enumeration_intercepted = []
        real_listdir = os.listdir

        def reversed_listdir(path):
            annotation_enumeration_intercepted.append(Path(path))
            return list(reversed(real_listdir(path)))

        with patch(
            "backend.export_manager.os.listdir", side_effect=reversed_listdir
        ):
            reversed_records, _ = self.exporter._load_validated_yolo_source("demo")
        reversed_splits, _ = self.exporter._split_yolo_dataset(
            reversed_records, (0.7, 0.2, 0.1), seed=23
        )

        membership = lambda splits: {
            split: [record["image_filename"] for record in records]
            for split, records in splits.items()
        }
        self.assertTrue(
            annotation_enumeration_intercepted,
            "source loader did not enumerate annotations through export_manager.os.listdir",
        )
        self.assertEqual(membership(canonical_splits), membership(reversed_splits))

    def test_domain_boundaries_are_square_like(self):
        self.assertEqual(
            self.exporter._yolo_domain(
                self._valid_record(size=(79, 100))
            ),
            "portrait",
        )
        self.assertEqual(
            self.exporter._yolo_domain(
                self._valid_record(size=(80, 100))
            ),
            "square",
        )
        self.assertEqual(
            self.exporter._yolo_domain(
                self._valid_record(size=(125, 100))
            ),
            "square",
        )
        self.assertEqual(
            self.exporter._yolo_domain(
                self._valid_record(size=(126, 100))
            ),
            "landscape",
        )

    def _add_export_records(self, project_id="demo"):
        project = self.projects / project_id
        images = project / "images"
        annotations = project / "annotations"
        for index in range(10):
            filename = f"image_{index}.png"
            record = self._valid_record(filename, size=(100, 100))
            if index == 0:
                record["annotations"] = []
            Image.new("RGB", (100, 100), color=(index, 0, 0)).save(
                images / filename
            )
            (annotations / f"image_{index}.json").write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8"
            )

    def test_public_yolo_export_keeps_archive_layout_without_creating_model_data(self):
        self._add_export_records()

        zip_path = Path(self.exporter.export_project("demo", "yolo"))

        self.assertTrue(zip_path.is_file())
        self.assertEqual(zip_path.parent.resolve(), self.exports.resolve())
        self.assertFalse(self.active.exists())
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            yaml_data = yaml.safe_load(archive.read("data.yaml"))
            self.assertEqual(
                yaml_data,
                {
                    "path": str(zip_path.with_suffix("")),
                    "train": "images/train",
                    "val": "images/val",
                    "test": "images/test",
                    "names": {0: "原始", 1: "次要"},
                    "nc": 2,
                },
            )
            image_paths = {
                name
                for name in names
                if name.startswith("images/") and not name.endswith("/")
            }
            label_paths = {
                name
                for name in names
                if name.startswith("labels/") and not name.endswith("/")
            }
            directory_paths = {name for name in names if name.endswith("/")}
            self.assertEqual(
                {Path(name).name for name in image_paths},
                {f"image_{index}.png" for index in range(10)},
            )
            for split in ("train", "val", "test"):
                self.assertTrue(
                    any(name.startswith(f"images/{split}/") for name in image_paths),
                    f"missing images/{split} archive layout",
                )
                self.assertTrue(
                    any(name.startswith(f"labels/{split}/") for name in label_paths),
                    f"missing labels/{split} archive layout",
                )
            expected_label_paths = {
                f"labels/{Path(image_path).parts[1]}/{Path(image_path).stem}.txt"
                for image_path in image_paths
            }
            self.assertEqual(label_paths, expected_label_paths)
            self.assertEqual(
                names,
                {"data.yaml"}
                | image_paths
                | expected_label_paths
                | directory_paths,
            )
            self.assertTrue(
                {
                    "images/train/",
                    "images/val/",
                    "images/test/",
                    "labels/train/",
                    "labels/val/",
                    "labels/test/",
                }.issubset(directory_paths)
            )
            empty_label_name = next(
                name for name in names if name.endswith("/image_0.txt")
            )
            self.assertEqual(archive.read(empty_label_name), b"")

    def test_public_zip_lists_all_yolo_split_directories_when_two_splits_are_empty(self):
        self._write_record(self._valid_record())

        zip_path = Path(
            self.exporter.export_project(
                "demo", "yolo", split_ratios=(0, 0, 1)
            )
        )

        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            self.assertTrue(
                {
                    "images/train/",
                    "images/val/",
                    "images/test/",
                    "labels/train/",
                    "labels/val/",
                    "labels/test/",
                }.issubset(names)
            )
            self.assertIn("data.yaml", names)
            self.assertIn("images/test/sample.png", names)
            self.assertIn("labels/test/sample.txt", names)

    def test_public_export_preserves_primary_failure_when_all_cleanup_fails(self):
        self._add_export_records()
        captured = {}
        real_unlink = Path.unlink
        real_rmtree = shutil.rmtree

        def fail_zip_after_partial(source_dir, zip_path):
            captured["temporary"] = Path(source_dir)
            captured["zip"] = Path(zip_path)
            captured["zip"].write_bytes(b"partial")
            raise RuntimeError("primary ZIP failure")

        def fail_partial_zip_unlink(path, *args, **kwargs):
            if Path(path) == captured.get("zip"):
                raise PermissionError("zip unlink denied")
            return real_unlink(path, *args, **kwargs)

        def fail_temporary_rmtree(path, *args, **kwargs):
            if Path(path) == captured.get("temporary"):
                raise PermissionError("temporary rmtree denied")
            return real_rmtree(path, *args, **kwargs)

        try:
            with patch.object(
                self.exporter, "_create_zip", side_effect=fail_zip_after_partial
            ), patch.object(
                Path, "unlink", new=fail_partial_zip_unlink
            ), patch(
                "backend.export_manager.shutil.rmtree",
                side_effect=fail_temporary_rmtree,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "primary ZIP failure"
                ) as raised:
                    self.exporter.export_project("demo", "yolo")

            cleanup_report = "\n".join(
                getattr(raised.exception, "__notes__", [])
            )
            self.assertIn("zip unlink denied", cleanup_report)
            self.assertIn("temporary rmtree denied", cleanup_report)
            self.assertIn(str(captured["zip"]), cleanup_report)
            self.assertIn(str(captured["temporary"]), cleanup_report)
            self.assertTrue(captured["zip"].exists())
            self.assertTrue(captured["temporary"].exists())
        finally:
            if captured.get("zip") is not None:
                captured["zip"].unlink(missing_ok=True)
            if captured.get("temporary") is not None:
                shutil.rmtree(captured["temporary"], ignore_errors=True)

    def test_public_export_rejects_unsafe_project_ids_without_path_escape(self):
        unsafe_project_ids = [
            ("absolute", None),
            ("parent traversal", "../demo"),
            ("forward separator", "nested/demo"),
            ("backslash separator", r"nested\demo"),
            ("dot", "."),
            ("dot dot", ".."),
            ("normalizes to parent", "demo/.."),
        ]

        for name, unsafe_project_id in unsafe_project_ids:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                case_root = Path(directory)
                projects = case_root / "data" / "projects"
                project = projects / "demo"
                images = project / "images"
                annotations = project / "annotations"
                exports = case_root / "data" / "exports"
                images.mkdir(parents=True)
                annotations.mkdir()
                exports.mkdir()
                (project / "project.json").write_text(
                    json.dumps(
                        {
                            "id": "demo",
                            "name": "demo",
                            "categories": ["原始"],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                exporter = ExportManager(str(projects), str(exports))
                project_id = (
                    str(project) if unsafe_project_id is None else unsafe_project_id
                )
                before = {
                    path.relative_to(case_root) for path in case_root.rglob("*")
                }

                with self.assertRaisesRegex(ValueError, r"^Invalid project id:"):
                    exporter.export_project(project_id, "yolo")

                self.assertEqual(
                    {path.relative_to(case_root) for path in case_root.rglob("*")},
                    before,
                    f"unsafe project id {project_id!r} created an artifact",
                )

    def test_public_export_cleans_temp_tree_after_malformed_source(self):
        self._write_record({}, raw_json='{"image_id":')

        with self.assertRaisesRegex(ValueError, "Invalid annotation"):
            self.exporter.export_project("demo", "yolo")

        self.assertEqual(list(self.exports.iterdir()), [])

    def test_public_export_cleans_temp_tree_and_partial_zip_after_zip_failure(self):
        self._add_export_records()

        def fail_after_partial_zip(source_dir, zip_path):
            Path(zip_path).write_bytes(b"partial zip")
            raise RuntimeError("simulated ZIP failure")

        with patch.object(
            self.exporter, "_create_zip", side_effect=fail_after_partial_zip
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated ZIP failure"):
                self.exporter.export_project("demo", "yolo")

        self.assertEqual(list(self.exports.iterdir()), [])

    def test_public_export_cleans_partial_zip_when_interrupted(self):
        self._add_export_records()

        def interrupt_after_partial_zip(source_dir, zip_path):
            Path(zip_path).write_bytes(b"partial zip")
            raise KeyboardInterrupt("simulated cancellation")

        with patch.object(
            self.exporter,
            "_create_zip",
            side_effect=interrupt_after_partial_zip,
        ):
            with self.assertRaisesRegex(
                KeyboardInterrupt, "simulated cancellation"
            ):
                self.exporter.export_project("demo", "yolo")

        self.assertEqual(list(self.exports.iterdir()), [])

    def test_public_yolo_export_preserves_preexisting_active_marker(self):
        self._add_export_records()
        marker = self._install_active_marker("original-active")

        self.exporter.export_project("demo", "yolo")

        self.assertEqual(marker.read_text(encoding="utf-8"), "original-active")
        self.assertEqual(list(self.active.iterdir()), [marker])

    def test_internal_export_writes_optional_training_tree_and_reports_stats(self):
        self._add_export_records()
        export_path = self.root / "download"
        export_path.mkdir()
        staging = self.models / "demo" / ".yolo-staging"
        staging.mkdir(parents=True)
        future_active = self.models / "demo" / "yolo_data"

        stats = self.exporter._export_yolo(
            "demo",
            str(export_path),
            (0.7, 0.2, 0.1),
            False,
            training_data_path=str(staging),
            training_yaml_root=str(future_active),
            seed=0,
        )

        self.assertEqual(stats["source_count"], 10)
        self.assertEqual(stats["source_filenames"], sorted(stats["source_filenames"]))
        self.assertEqual(stats["split_counts"], {"train": 7, "val": 2, "test": 1})
        self.assertEqual(stats["categories"], ["原始", "次要"])
        manifest = stats["_source_manifest"]
        self.assertEqual(
            [entry["filename"] for entry in manifest], stats["source_filenames"]
        )
        self.assertEqual(len(manifest), 10)
        self.assertEqual(manifest[0]["dimensions"], [100, 100])
        self.assertRegex(manifest[0]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(manifest[0]["label_lines"], [])
        self._assert_exact_yolo_tree(export_path, str(export_path))
        self._assert_exact_yolo_tree(staging, str(future_active))
        for split in ("train", "val", "test"):
            self.assertEqual(
                {
                    path.name
                    for path in (export_path / "images" / split).iterdir()
                },
                {
                    path.name for path in (staging / "images" / split).iterdir()
                },
            )

    def _assert_exact_yolo_tree(self, root, expected_yaml_path):
        self.assertEqual(
            {path.name for path in root.iterdir()},
            {"images", "labels", "data.yaml"},
        )
        self.assertEqual(
            {path.name for path in (root / "images").iterdir()},
            {"train", "val", "test"},
        )
        self.assertEqual(
            {path.name for path in (root / "labels").iterdir()},
            {"train", "val", "test"},
        )
        all_images = set()
        for split in ("train", "val", "test"):
            image_names = {
                path.name for path in (root / "images" / split).iterdir()
            }
            label_names = {
                path.name for path in (root / "labels" / split).iterdir()
            }
            self.assertEqual(
                label_names,
                {f"{Path(filename).stem}.txt" for filename in image_names},
            )
            all_images.update(image_names)
        self.assertEqual(
            all_images, {f"image_{index}.png" for index in range(10)}
        )
        self.assertEqual(
            yaml.safe_load((root / "data.yaml").read_text(encoding="utf-8")),
            {
                "path": expected_yaml_path,
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": {0: "原始", 1: "次要"},
                "nc": 2,
            },
        )

    def test_internal_training_target_requires_yaml_root_and_empty_staging(self):
        self._add_export_records()
        cases = [
            ("missing yaml root", "training_yaml_root"),
            ("empty yaml root", "training_yaml_root"),
            ("nonempty staging", "YOLO target must be empty"),
        ]
        for case, message_fragment in cases:
            with self.subTest(case=case):
                export_path = self.root / f"download-{case}"
                export_path.mkdir()
                staging = self.root / f"staging-{case}"
                staging.mkdir()
                yaml_root = self.root / "future-active"
                if case == "nonempty staging":
                    (staging / "marker.txt").write_text("keep", encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, re.escape(message_fragment)
                ):
                    self.exporter._export_yolo(
                        "demo",
                        str(export_path),
                        (0.7, 0.2, 0.1),
                        False,
                        training_data_path=str(staging),
                        training_yaml_root=(
                            None
                            if case == "missing yaml root"
                            else ""
                            if case == "empty yaml root"
                            else str(yaml_root)
                        ),
                    )
                self.assertEqual(list(export_path.iterdir()), [])
                if case == "nonempty staging":
                    self.assertEqual(
                        (staging / "marker.txt").read_text(encoding="utf-8"),
                        "keep",
                    )

    def test_write_tree_rejects_nonempty_target_without_deleting_it(self):
        target = self.root / "nonempty-target"
        target.mkdir()
        marker = target / "marker.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "YOLO target must be empty"):
            self.exporter._write_yolo_tree(
                target,
                target,
                {"train": [], "val": [], "test": []},
                ["原始"],
            )

        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_source_overwrite_after_validation_fails_without_replacing_active(self):
        record = self._valid_record()
        self._write_record(record)
        marker = self._install_active_marker("old-active")
        manager = YoloTrainManager(str(self.models), {})
        source_path = self.images / record["image_filename"]
        real_copy2 = shutil.copy2
        copy_calls = 0

        def overwrite_before_copy(source, destination, *args, **kwargs):
            nonlocal copy_calls
            copy_calls += 1
            if copy_calls == 1:
                Image.new("RGB", (100, 80), color=(255, 0, 0)).save(source_path)
            return real_copy2(source, destination, *args, **kwargs)

        with patch(
            "backend.export_manager.shutil.copy2", side_effect=overwrite_before_copy
        ):
            ok, error, verified = manager._prepare_dataset("demo")

        self.assertFalse(ok)
        self.assertEqual(verified, {})
        self.assertIn("changed after validation", error)
        self.assertGreaterEqual(copy_calls, 1)
        self.assertEqual(marker.read_text(encoding="utf-8"), "old-active")
        self.assertEqual(list(self.active.iterdir()), [marker])
        self.assertEqual(
            list((self.models / "demo").glob(".yolo_data_staging_*")), []
        )
        self.assertEqual(list((self.models / "demo").glob(".yolo_export_*")), [])


class YoloDatasetActivationTests(unittest.TestCase):
    """Specify staging validation and recoverable atomic activation."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.data = self.root / "data"
        self.models = self.data / "models"
        self.project = self.data / "projects" / "demo"
        self.annotations = self.project / "annotations"
        self.exports = self.data / "exports"
        self.project_model = self.models / "demo"
        self.active = self.project_model / "yolo_data"
        self.annotations.mkdir(parents=True)
        self.exports.mkdir(parents=True)
        self.models.mkdir(parents=True)
        (self.annotations / "source.json").write_text("{}", encoding="utf-8")
        self.manager = YoloTrainManager(str(self.models), {})
        self.source_filenames = sorted(["train.png", "val.png", "test.png"])
        self.image_payloads = {
            split: self._png_bytes((index * 60, 32, 64))
            for index, split in enumerate(("train", "val", "test"), start=1)
        }
        self.export_stats = {
            "source_count": 3,
            "source_filenames": list(self.source_filenames),
            "split_counts": {"train": 1, "val": 1, "test": 1},
            "domain_counts": {
                "train": {"portrait": 1},
                "val": {"portrait": 1},
                "test": {"portrait": 1},
            },
            "categories": ["原始", "次要"],
            "_source_manifest": [
                {
                    "filename": f"{split}.png",
                    "sha256": hashlib.sha256(self.image_payloads[split]).hexdigest(),
                    "dimensions": [64, 48],
                    "label_lines": ["0 0.5 0.5 0.2 0.2"],
                }
                for split in ("test", "train", "val")
            ],
        }

    def tearDown(self):
        self._temporary_directory.cleanup()

    @staticmethod
    def _png_bytes(color, size=(64, 48)):
        payload = io.BytesIO()
        Image.new("RGB", size, color=color).save(payload, format="PNG")
        return payload.getvalue()

    def _write_valid_staging(self, staging, active_path=None):
        staging = Path(staging)
        active_path = Path(active_path or self.active)
        for split in ("train", "val", "test"):
            images = staging / "images" / split
            labels = staging / "labels" / split
            images.mkdir(parents=True, exist_ok=True)
            labels.mkdir(parents=True, exist_ok=True)
            filename = f"{split}.png"
            (images / filename).write_bytes(self.image_payloads[split])
            (labels / f"{Path(filename).stem}.txt").write_text(
                "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
            )
        (staging / "data.yaml").write_text(
            yaml.safe_dump(
                {
                    "path": str(active_path),
                    "train": "images/train",
                    "val": "images/val",
                    "test": "images/test",
                    "names": {0: "原始", 1: "次要"},
                    "nc": 2,
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _mock_export(self, captured):
        def export(*args, **kwargs):
            export_path = Path(kwargs["export_path"])
            staging_path = Path(kwargs["training_data_path"])
            captured["export"] = export_path
            captured["staging"] = staging_path
            captured["active"] = Path(kwargs["training_yaml_root"])
            (export_path / "throwaway.txt").write_text("remove", encoding="utf-8")
            self._write_valid_staging(staging_path, captured["active"])
            return dict(self.export_stats)

        return export

    def test_staging_validation_scans_staging_while_yaml_names_future_active(self):
        staging = self.project_model / ".manual-staging"
        staging.mkdir(parents=True)
        self.active.mkdir(parents=True)
        (self.active / "old-only-marker.txt").write_text("old", encoding="utf-8")
        self._write_valid_staging(staging)

        verified = self.manager._validate_staged_dataset(
            staging, self.active, self.export_stats
        )

        self.assertEqual(verified["source_count"], 3)
        self.assertEqual(
            verified["split_counts"], {"train": 1, "val": 1, "test": 1}
        )
        self.assertEqual(verified["source_filenames"], self.source_filenames)
        self.assertNotIn("_source_manifest", verified)

    def test_staging_validation_rejects_same_name_same_dimensions_image_hash_change(self):
        staging = self.project_model / ".invalid-image-hash"
        staging.mkdir(parents=True)
        self._write_valid_staging(staging)
        (staging / "images" / "train" / "train.png").write_bytes(
            self._png_bytes((1, 2, 3))
        )

        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.manager._validate_staged_dataset(
                staging, self.active, self.export_stats
            )

    def test_staging_validation_rejects_image_dimension_change(self):
        staging = self.project_model / ".invalid-image-dimensions"
        staging.mkdir(parents=True)
        self._write_valid_staging(staging)
        (staging / "images" / "train" / "train.png").write_bytes(
            self._png_bytes((60, 32, 64), size=(65, 48))
        )

        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.manager._validate_staged_dataset(
                staging, self.active, self.export_stats
            )

    def test_staging_validation_rejects_valid_but_unexpected_label_values(self):
        cases = (
            ("class", "1 0.5 0.5 0.2 0.2\n"),
            ("coordinates", "0 0.4 0.5 0.2 0.2\n"),
        )
        for case, label_content in cases:
            with self.subTest(case=case):
                staging = self.project_model / f".invalid-label-{case}"
                staging.mkdir(parents=True)
                self._write_valid_staging(staging)
                (staging / "labels" / "train" / "train.txt").write_text(
                    label_content, encoding="utf-8"
                )

                with self.assertRaisesRegex(ValueError, "expected content"):
                    self.manager._validate_staged_dataset(
                        staging, self.active, self.export_stats
                    )

    def test_staging_validation_rejects_malformed_nonfinite_and_out_of_range_labels(self):
        cases = (
            ("malformed", "0 0.5 0.5 0.2\n", "exactly 5"),
            ("nonfinite", "0 nan 0.5 0.2 0.2\n", "finite"),
            ("out-of-range", "0 1.1 0.5 0.2 0.2\n", "normalized"),
            ("zero-width", "0 0.5 0.5 0 0.2\n", "positive"),
        )
        for case, label_content, message in cases:
            with self.subTest(case=case):
                staging = self.project_model / f".invalid-label-{case}"
                staging.mkdir(parents=True)
                self._write_valid_staging(staging)
                (staging / "labels" / "train" / "train.txt").write_text(
                    label_content, encoding="utf-8"
                )

                with self.assertRaisesRegex(ValueError, message):
                    self.manager._validate_staged_dataset(
                        staging, self.active, self.export_stats
                    )

    def test_staging_validation_rejects_unexpected_pair_before_manifest_lookup(self):
        staging = self.project_model / ".unexpected-manifest-pair"
        staging.mkdir(parents=True)
        self._write_valid_staging(staging)
        (staging / "images" / "train" / "unexpected.png").write_bytes(
            self._png_bytes((9, 9, 9))
        )
        (staging / "labels" / "train" / "unexpected.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(ValueError, "source manifest"):
            self.manager._validate_staged_dataset(
                staging, self.active, self.export_stats
            )

    def test_staging_validation_rejects_missing_overlap_total_and_yaml_categories(self):
        cases = (
            ("missing label", "label", lambda staging, stats: (staging / "labels" / "val" / "val.txt").unlink()),
            (
                "duplicate split basename",
                "more than one split",
                lambda staging, stats: (
                    (staging / "images" / "val" / "train.jpg").write_bytes(b"duplicate"),
                    (staging / "labels" / "val" / "train.txt").write_text("", encoding="utf-8"),
                ),
            ),
            ("wrong total", "source total", lambda staging, stats: stats.update(source_count=4)),
            (
                "category mismatch",
                "names",
                lambda staging, stats: stats.update(categories=["不同类别"]),
            ),
            (
                "nc mismatch",
                "nc",
                lambda staging, stats: self._rewrite_yaml(staging, nc=1),
            ),
            (
                "names mismatch",
                "names",
                lambda staging, stats: self._rewrite_yaml(staging, names={0: "错误", 1: "次要"}),
            ),
        )
        for name, message_fragment, mutate in cases:
            with self.subTest(case=name):
                staging = self.project_model / f".invalid-{name.replace(' ', '-')}"
                staging.mkdir(parents=True)
                self._write_valid_staging(staging)
                stats = dict(self.export_stats)
                stats["split_counts"] = dict(self.export_stats["split_counts"])
                mutate(staging, stats)
                with self.assertRaisesRegex(ValueError, message_fragment):
                    self.manager._validate_staged_dataset(
                        staging, self.active, stats
                    )

    @staticmethod
    def _rewrite_yaml(staging, **changes):
        yaml_path = staging / "data.yaml"
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        payload.update(changes)
        yaml_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def test_no_active_activation_failure_preserves_staging_and_reports_path(self):
        captured = {}
        replace_calls = []

        def fail_first_replace(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            raise OSError("simulated staging rename failure")

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=fail_first_replace,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        self.assertFalse(ok)
        self.assertEqual(verified, {})
        self.assertEqual(len(replace_calls), 1)
        self.assertTrue(captured["staging"].is_dir())
        self.assertIn(str(captured["staging"]), error)
        self.assertFalse(captured["export"].exists())

    def test_activation_failure_restores_old_active_and_removes_staging(self):
        self.active.mkdir(parents=True)
        marker = self.active / "marker.txt"
        marker.write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        replace_calls = []

        def fail_activation_only(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            if len(replace_calls) == 2:
                raise OSError("simulated activation failure")
            return real_replace(source, destination)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=fail_activation_only,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        self.assertFalse(ok)
        self.assertEqual(verified, {})
        self.assertEqual(len(replace_calls), 3)
        self.assertIn("simulated activation failure", error)
        self.assertEqual(marker.read_text(encoding="utf-8"), "old-active")
        self.assertFalse(captured["staging"].exists())
        self.assertFalse(captured["export"].exists())
        self.assertEqual(list(self.project_model.glob(".yolo_data_backup_*")), [])

    def test_failed_activation_and_failed_rollback_preserve_and_report_recovery_paths(self):
        self.active.mkdir(parents=True)
        (self.active / "marker.txt").write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        replace_calls = []

        def fail_activation_and_rollback(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            if len(replace_calls) in {2, 3}:
                raise OSError(f"simulated rename failure {len(replace_calls)}")
            return real_replace(source, destination)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=fail_activation_and_rollback,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        backup = replace_calls[2][0]
        self.assertFalse(ok)
        self.assertEqual(verified, {})
        self.assertEqual(len(replace_calls), 3)
        self.assertTrue(backup.is_dir())
        self.assertTrue(captured["staging"].is_dir())
        self.assertIn(str(backup), error)
        self.assertIn(str(captured["staging"]), error)
        self.assertIn("simulated rename failure 2", error)
        self.assertIn("simulated rename failure 3", error)
        self.assertFalse(captured["export"].exists())

    def test_cancellation_during_activation_rolls_back_cleans_and_reraises(self):
        for cancellation in (KeyboardInterrupt(), SystemExit(23)):
            with self.subTest(cancellation=type(cancellation).__name__):
                if self.active.exists():
                    shutil.rmtree(self.active)
                self.active.mkdir(parents=True)
                marker = self.active / "marker.txt"
                marker.write_text("old-active", encoding="utf-8")
                captured = {}
                real_replace = os.replace
                replace_calls = []

                def interrupt_activation(source, destination):
                    replace_calls.append((Path(source), Path(destination)))
                    if len(replace_calls) == 2:
                        raise cancellation
                    return real_replace(source, destination)

                with patch(
                    "backend.export_manager.ExportManager._export_yolo",
                    side_effect=self._mock_export(captured),
                ), patch(
                    "backend.yolo_train_manager.os.replace",
                    side_effect=interrupt_activation,
                ):
                    with self.assertRaises(type(cancellation)):
                        self.manager._prepare_dataset("demo")

                self.assertEqual(len(replace_calls), 3)
                self.assertEqual(marker.read_text(encoding="utf-8"), "old-active")
                self.assertFalse(captured["staging"].exists())
                self.assertFalse(captured["export"].exists())
                self.assertEqual(
                    list(self.project_model.glob(".yolo_data_backup_*")), []
                )

    def test_cancellation_with_failed_rollback_preserves_and_reports_both_paths(self):
        self.active.mkdir(parents=True)
        (self.active / "marker.txt").write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        replace_calls = []

        def interrupt_then_fail_rollback(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            if len(replace_calls) == 2:
                raise KeyboardInterrupt()
            if len(replace_calls) == 3:
                raise RuntimeError("rollback runtime failure")
            return real_replace(source, destination)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=interrupt_then_fail_rollback,
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                self.manager._prepare_dataset("demo")

        backup = replace_calls[2][0]
        self.assertTrue(backup.is_dir())
        self.assertTrue(captured["staging"].is_dir())
        recovery_details = "\n".join(raised.exception.__notes__)
        self.assertIn("rollback runtime failure", recovery_details)
        self.assertIn(str(backup), recovery_details)
        self.assertIn(str(captured["staging"]), recovery_details)
        self.assertEqual(
            raised.exception.recovery_backup_path, str(backup)
        )
        self.assertEqual(
            raised.exception.recovery_staging_path, str(captured["staging"])
        )
        self.assertFalse(captured["export"].exists())

    def test_cancellation_during_first_rename_restores_or_keeps_active_and_cleans_staging(self):
        for cancellation_timing in ("before-effect", "after-effect"):
            with self.subTest(timing=cancellation_timing):
                if self.active.exists():
                    shutil.rmtree(self.active)
                self.active.mkdir(parents=True)
                marker = self.active / "marker.txt"
                marker.write_text("old-active", encoding="utf-8")
                captured = {}
                real_replace = os.replace
                replace_calls = []

                def interrupt_first_rename(source, destination):
                    replace_calls.append((Path(source), Path(destination)))
                    if len(replace_calls) == 1:
                        if cancellation_timing == "after-effect":
                            real_replace(source, destination)
                        raise KeyboardInterrupt(cancellation_timing)
                    return real_replace(source, destination)

                with patch(
                    "backend.export_manager.ExportManager._export_yolo",
                    side_effect=self._mock_export(captured),
                ), patch(
                    "backend.yolo_train_manager.os.replace",
                    side_effect=interrupt_first_rename,
                ):
                    with self.assertRaises(KeyboardInterrupt) as raised:
                        self.manager._prepare_dataset("demo")

                self.assertEqual(str(raised.exception), cancellation_timing)
                self.assertEqual(marker.read_text(encoding="utf-8"), "old-active")
                self.assertFalse(captured["staging"].exists())
                self.assertFalse(captured["export"].exists())
                self.assertEqual(
                    list(self.project_model.glob(".yolo_data_backup_*")), []
                )

    def test_cancellation_after_first_rename_with_failed_restore_preserves_paths_and_type(self):
        self.active.mkdir(parents=True)
        (self.active / "marker.txt").write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        replace_calls = []

        def interrupt_after_move_then_fail_restore(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            if len(replace_calls) == 1:
                real_replace(source, destination)
                raise KeyboardInterrupt("after active move")
            raise RuntimeError("first-rename restoration failed")

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=interrupt_after_move_then_fail_restore,
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                self.manager._prepare_dataset("demo")

        backup = replace_calls[0][1]
        recovery_details = "\n".join(raised.exception.__notes__)
        self.assertTrue(backup.is_dir())
        self.assertTrue(captured["staging"].is_dir())
        self.assertIn("first-rename restoration failed", recovery_details)
        self.assertIn(str(backup), recovery_details)
        self.assertIn(str(captured["staging"]), recovery_details)
        self.assertEqual(raised.exception.recovery_backup_path, str(backup))
        self.assertEqual(
            raised.exception.recovery_staging_path, str(captured["staging"])
        )
        self.assertFalse(captured["export"].exists())

    def test_system_exit_with_rollback_cleanup_failure_preserves_type_and_details(self):
        self.active.mkdir(parents=True)
        marker = self.active / "marker.txt"
        marker.write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        real_rmtree = shutil.rmtree
        replace_calls = []

        def exit_during_activation(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            if len(replace_calls) == 2:
                raise SystemExit(57)
            return real_replace(source, destination)

        def fail_staging_cleanup(path, *args, **kwargs):
            if Path(path) == captured.get("staging"):
                raise PermissionError("cancel cleanup denied")
            return real_rmtree(path, *args, **kwargs)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=exit_during_activation,
        ), patch(
            "backend.yolo_train_manager.shutil.rmtree",
            side_effect=fail_staging_cleanup,
        ):
            with self.assertRaises(SystemExit) as raised:
                self.manager._prepare_dataset("demo")

        recovery_details = "\n".join(raised.exception.__notes__)
        self.assertEqual(raised.exception.code, 57)
        self.assertEqual(marker.read_text(encoding="utf-8"), "old-active")
        self.assertTrue(captured["staging"].is_dir())
        self.assertIn("cancel cleanup denied", recovery_details)
        self.assertIn(str(captured["staging"]), recovery_details)
        self.assertEqual(
            raised.exception.recovery_staging_path, str(captured["staging"])
        )
        self.assertFalse(captured["export"].exists())

    def test_preactivation_cancellation_cleans_staging_and_export_then_reraises(self):
        captured = {}

        def interrupt_export(*args, **kwargs):
            captured["export"] = Path(kwargs["export_path"])
            captured["staging"] = Path(kwargs["training_data_path"])
            (captured["export"] / "partial.txt").write_text(
                "partial", encoding="utf-8"
            )
            (captured["staging"] / "partial.txt").write_text(
                "partial", encoding="utf-8"
            )
            raise SystemExit(41)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=interrupt_export,
        ):
            with self.assertRaises(SystemExit) as raised:
                self.manager._prepare_dataset("demo")

        self.assertEqual(raised.exception.code, 41)
        self.assertFalse(captured["staging"].exists())
        self.assertFalse(captured["export"].exists())

    def test_successful_rollback_cleanup_failure_reports_restored_state_and_staging(self):
        self.active.mkdir(parents=True)
        marker = self.active / "marker.txt"
        marker.write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        real_rmtree = shutil.rmtree
        replace_calls = []

        def fail_activation_with_runtime_error(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            if len(replace_calls) == 2:
                raise RuntimeError("activation runtime failure")
            return real_replace(source, destination)

        def fail_staging_cleanup(path, *args, **kwargs):
            if Path(path) == captured.get("staging"):
                raise PermissionError("staging cleanup denied")
            return real_rmtree(path, *args, **kwargs)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=fail_activation_with_runtime_error,
        ), patch(
            "backend.yolo_train_manager.shutil.rmtree",
            side_effect=fail_staging_cleanup,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        self.assertFalse(ok)
        self.assertEqual(verified, {})
        self.assertEqual(marker.read_text(encoding="utf-8"), "old-active")
        self.assertTrue(captured["staging"].is_dir())
        self.assertIn("restored", error)
        self.assertIn("staging cleanup denied", error)
        self.assertIn(str(captured["staging"]), error)
        self.assertFalse(captured["export"].exists())

    def test_backup_cleanup_failure_returns_committed_success_with_recovery_warning(self):
        self.active.mkdir(parents=True)
        (self.active / "marker.txt").write_text("old-active", encoding="utf-8")
        captured = {}
        real_replace = os.replace
        real_rmtree = shutil.rmtree
        replace_calls = []

        def record_replace(source, destination):
            replace_calls.append((Path(source), Path(destination)))
            return real_replace(source, destination)

        def fail_backup_cleanup(path, *args, **kwargs):
            if Path(path).name.startswith(".yolo_data_backup_"):
                raise PermissionError("backup cleanup denied")
            return real_rmtree(path, *args, **kwargs)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.os.replace",
            side_effect=record_replace,
        ), patch(
            "backend.yolo_train_manager.shutil.rmtree",
            side_effect=fail_backup_cleanup,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        backup = replace_calls[0][1]
        self.assertTrue(ok, error)
        self.assertEqual(error, "")
        self.assertTrue(verified["activation_committed"])
        self.assertIn("backup cleanup denied", verified["activation_warning"])
        self.assertEqual(verified["recovery_backup_path"], str(backup))
        self.assertTrue(backup.is_dir())
        self.assertTrue((backup / "marker.txt").exists())
        self.assertTrue((self.active / "data.yaml").exists())
        self.assertFalse((self.active / "marker.txt").exists())
        self.assertFalse(captured["export"].exists())

    def test_successful_activation_reports_throwaway_export_cleanup_failure(self):
        captured = {}
        real_rmtree = shutil.rmtree

        def fail_export_cleanup(path, *args, **kwargs):
            if Path(path) == captured.get("export"):
                raise PermissionError("throwaway export cleanup denied")
            return real_rmtree(path, *args, **kwargs)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=self._mock_export(captured),
        ), patch(
            "backend.yolo_train_manager.shutil.rmtree",
            side_effect=fail_export_cleanup,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        self.assertTrue(ok, error)
        self.assertEqual(error, "")
        self.assertTrue(verified["activation_committed"])
        self.assertIn("throwaway export cleanup denied", verified["cleanup_warning"])
        self.assertIn("throwaway export cleanup denied", verified["activation_warning"])
        self.assertEqual(verified["leftover_export_path"], str(captured["export"]))
        self.assertTrue(captured["export"].exists())
        self.assertTrue(self.active.is_dir())
        shutil.rmtree(captured["export"])

    def test_failed_preparation_appends_throwaway_export_cleanup_failure(self):
        captured = {}
        real_rmtree = shutil.rmtree

        def fail_export(*args, **kwargs):
            captured["export"] = Path(kwargs["export_path"])
            captured["staging"] = Path(kwargs["training_data_path"])
            (captured["export"] / "partial.txt").write_text(
                "partial", encoding="utf-8"
            )
            raise RuntimeError("primary preparation failure")

        def fail_export_cleanup(path, *args, **kwargs):
            if Path(path) == captured.get("export"):
                raise PermissionError("throwaway export cleanup denied")
            return real_rmtree(path, *args, **kwargs)

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=fail_export,
        ), patch(
            "backend.yolo_train_manager.shutil.rmtree",
            side_effect=fail_export_cleanup,
        ):
            ok, error, verified = self.manager._prepare_dataset("demo")

        self.assertFalse(ok)
        self.assertEqual(verified, {})
        self.assertIn("primary preparation failure", error)
        self.assertIn("throwaway export cleanup denied", error)
        self.assertIn(str(captured["export"]), error)
        self.assertTrue(captured["export"].exists())
        self.assertFalse(captured["staging"].exists())
        shutil.rmtree(captured["export"])

    def test_staging_validation_rejects_symlink_images_and_labels(self):
        outside_image = self.root / "outside.png"
        outside_label = self.root / "outside.txt"
        outside_image.write_bytes(b"outside")
        outside_label.write_text("", encoding="utf-8")
        for entry_kind, target in (
            ("image", outside_image),
            ("label", outside_label),
        ):
            with self.subTest(entry=entry_kind):
                staging = self.project_model / f".symlink-{entry_kind}"
                staging.mkdir(parents=True)
                self._write_valid_staging(staging)
                entry = (
                    staging / "images" / "train" / "train.png"
                    if entry_kind == "image"
                    else staging / "labels" / "train" / "train.txt"
                )
                entry.unlink()
                entry.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    self.manager._validate_staged_dataset(
                        staging, self.active, self.export_stats
                    )

    def test_staging_validation_rejects_structural_symlinks(self):
        for location in (
            "staging-root",
            "data-yaml",
            "images-root",
            "labels-root",
            "image-split",
            "label-split",
        ):
            with self.subTest(location=location):
                staging = self.project_model / f".structural-{location}"
                if location == "staging-root":
                    real_staging = self.project_model / f".real-{location}"
                    real_staging.mkdir(parents=True)
                    self._write_valid_staging(real_staging)
                    staging.symlink_to(real_staging, target_is_directory=True)
                else:
                    staging.mkdir(parents=True)
                    self._write_valid_staging(staging)
                    relative_path = {
                        "data-yaml": Path("data.yaml"),
                        "images-root": Path("images"),
                        "labels-root": Path("labels"),
                        "image-split": Path("images/train"),
                        "label-split": Path("labels/train"),
                    }[location]
                    original = staging / relative_path
                    outside = self.root / f"outside-{location}"
                    original.rename(outside)
                    original.symlink_to(
                        outside, target_is_directory=outside.is_dir()
                    )

                with self.assertRaisesRegex(ValueError, "symlink"):
                    self.manager._validate_staged_dataset(
                        staging, self.active, self.export_stats
                    )

    def test_same_project_preparations_do_not_overlap_activation(self):
        second_manager = YoloTrainManager(str(self.models), {})
        captured_exports = []
        first_entered = threading.Event()
        second_started = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()
        activation_guard = threading.Lock()
        activation_calls = 0
        results = []

        def export(*args, **kwargs):
            staging = Path(kwargs["training_data_path"])
            active = Path(kwargs["training_yaml_root"])
            captured_exports.append(Path(kwargs["export_path"]))
            self._write_valid_staging(staging, active)
            return dict(self.export_stats)

        def instrument_activation(manager, staging, active):
            nonlocal activation_calls
            with activation_guard:
                activation_calls += 1
                call_number = activation_calls
            if call_number == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(2), "first activation not released")
            else:
                second_entered.set()

        def prepare(manager, *, is_second=False):
            if is_second:
                second_started.set()
            results.append(manager._prepare_dataset("demo"))

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=export,
        ), patch.object(
            YoloTrainManager,
            "_activate_staged_dataset",
            new=instrument_activation,
        ):
            first = threading.Thread(target=prepare, args=(self.manager,))
            second = threading.Thread(
                target=prepare, args=(second_manager,), kwargs={"is_second": True}
            )
            first.start()
            self.assertTrue(first_entered.wait(2))
            second.start()
            self.assertTrue(second_started.wait(2))
            overlapped = second_entered.wait(0.25)
            release_first.set()
            first.join(2)
            second.join(2)

        self.assertFalse(overlapped, "same-project activation sections overlapped")
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result[0] for result in results), results)
        self.assertTrue(all(not path.exists() for path in captured_exports))

    def test_different_project_preparations_can_overlap_activation(self):
        other_annotations = self.data / "projects" / "other" / "annotations"
        other_annotations.mkdir(parents=True)
        (other_annotations / "source.json").write_text("{}", encoding="utf-8")
        other_manager = YoloTrainManager(str(self.models), {})
        first_entered = threading.Event()
        other_entered = threading.Event()
        release_first = threading.Event()
        activation_guard = threading.Lock()
        activation_calls = 0
        results = []

        def export(*args, **kwargs):
            staging = Path(kwargs["training_data_path"])
            active = Path(kwargs["training_yaml_root"])
            self._write_valid_staging(staging, active)
            return dict(self.export_stats)

        def instrument_activation(manager, staging, active):
            nonlocal activation_calls
            with activation_guard:
                activation_calls += 1
                call_number = activation_calls
            if call_number == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(2), "first activation not released")
            else:
                other_entered.set()

        def prepare(manager, project_id):
            results.append(manager._prepare_dataset(project_id))

        with patch(
            "backend.export_manager.ExportManager._export_yolo",
            side_effect=export,
        ), patch.object(
            YoloTrainManager,
            "_activate_staged_dataset",
            new=instrument_activation,
        ):
            first = threading.Thread(target=prepare, args=(self.manager, "demo"))
            other = threading.Thread(target=prepare, args=(other_manager, "other"))
            first.start()
            self.assertTrue(first_entered.wait(2))
            other.start()
            overlaps = other_entered.wait(1)
            release_first.set()
            first.join(2)
            other.join(2)

        self.assertTrue(overlaps, "different projects were serialized globally")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result[0] for result in results), results)


class YoloTrainingIntegrationTests(unittest.TestCase):
    """Verify training consumes one freshly activated dataset for its lifetime."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.models = self.root / "data" / "models"
        self.active = self.models / "demo" / "yolo_data"
        self.active.mkdir(parents=True)
        (self.active / "data.yaml").write_text(
            yaml.safe_dump(
                {
                    "path": str(self.active),
                    "train": "images/train",
                    "val": "images/val",
                    "test": "images/test",
                    "nc": 1,
                    "names": {0: "原始"},
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.manager = YoloTrainManager(str(self.models), {})

    def tearDown(self):
        self._temporary_directory.cleanup()

    @staticmethod
    def _verified_stats(**extra):
        stats = {
            "source_count": 200,
            "source_filenames": [f"sample_{index:03d}.png" for index in range(200)],
            "split_counts": {"train": 140, "val": 40, "test": 20},
            "domain_counts": {
                "train": {"portrait": 70, "landscape": 70},
                "val": {"portrait": 20, "landscape": 20},
                "test": {"portrait": 10, "landscape": 10},
            },
            "categories": ["原始"],
        }
        stats.update(extra)
        return stats

    @staticmethod
    def _guard_ultralytics_imports(attempted_imports):
        real_import = __import__

        def guarded_import(name, *args, **kwargs):
            if name == "ultralytics" or name.startswith("ultralytics."):
                attempted_imports.append(name)
                raise AssertionError("ultralytics imported before dataset summary")
            return real_import(name, *args, **kwargs)

        return guarded_import

    def _advance_through_dataset_summary(self, stream):
        events = []
        for _ in range(12):
            try:
                event = next(stream)
            except StopIteration:
                break
            events.append(event)
            if "landscape: train=70, val=20, test=10" in event.get("message", ""):
                break
        return events

    def _assert_project_lock_available(self):
        acquired = threading.Event()

        def acquire_lock():
            with self.manager._get_project_lock("demo"):
                acquired.set()

        contender = threading.Thread(target=acquire_lock)
        contender.start()
        self.assertTrue(acquired.wait(1), "same-project lock was not released")
        contender.join(1)
        self.assertFalse(contender.is_alive())

    @staticmethod
    def _fake_ultralytics(train_error=None):
        module = types.ModuleType("ultralytics")

        class FakeYOLO:
            def __init__(self, model_path):
                self.model_path = model_path

            def train(self, **kwargs):
                if train_error is not None:
                    raise train_error
                return object()

        module.YOLO = FakeYOLO
        return module

    def test_training_always_refreshes_and_summarizes_verified_dataset_before_import(self):
        stats = self._verified_stats(
            activation_committed=True,
            activation_warning="backup cleanup denied",
            recovery_backup_path=str(self.models / "demo" / ".yolo_data_backup_saved"),
        )
        attempted_imports = []
        stream = self.manager.start_training(
            "demo",
            {"train_split": 0.7, "val_split": 0.2, "test_split": 0.1},
        )
        try:
            with patch.object(
                self.manager,
                "_prepare_dataset_locked",
                return_value=(True, "", stats),
            ) as prepare, patch(
                "builtins.__import__",
                side_effect=self._guard_ultralytics_imports(attempted_imports),
            ):
                events = self._advance_through_dataset_summary(stream)

            prepare.assert_called_once_with("demo", (0.7, 0.2, 0.1))
            combined_logs = "".join(event.get("message", "") for event in events)
            for expected in (
                "源标注: 200",
                "训练集: 140",
                "验证集: 40",
                "测试集: 20",
                "总计: 200",
                "portrait: train=70, val=20, test=10",
                "landscape: train=70, val=20, test=10",
                "backup cleanup denied",
                stats["recovery_backup_path"],
            ):
                self.assertIn(expected, combined_logs)
            self.assertEqual(attempted_imports, [])
        finally:
            stream.close()

    def test_build_train_info_preserves_legacy_keys_and_adds_complete_counts(self):
        stats = self._verified_stats()
        final_model_dir = str(self.models / "demo" / "yolo_final_model")
        train_config = {"epochs": 3, "base_model": "yolov8n.pt"}
        final_metrics = {"mAP50": 0.75}

        train_info = self.manager._build_train_info(
            project_id="demo",
            train_config=train_config,
            final_metrics=final_metrics,
            final_model_dir=final_model_dir,
            verified_stats=stats,
            trained_at="2026-07-10T12:00:00",
        )

        legacy_values = {
            "model_type": "yolo",
            "project_id": "demo",
            "trained_at": "2026-07-10T12:00:00",
            "config": train_config,
            "train_samples": 140,
            "val_samples": 40,
            "final_metrics": final_metrics,
            "model_path": final_model_dir,
            "best_model": os.path.join(final_model_dir, "best.pt"),
        }
        for key, value in legacy_values.items():
            self.assertEqual(train_info[key], value)
        self.assertEqual(train_info["source_samples"], 200)
        self.assertEqual(train_info["test_samples"], 20)
        self.assertEqual(train_info["domain_counts"], stats["domain_counts"])

    def test_same_project_training_holds_refresh_lock_until_generator_close(self):
        second_manager = YoloTrainManager(str(self.models), {})
        stats = self._verified_stats()
        first_prepare_entered = threading.Event()
        second_prepare_entered = threading.Event()
        second_finished = threading.Event()
        call_guard = threading.Lock()
        call_count = 0

        def prepare_locked(manager, project_id, split_ratios):
            nonlocal call_count
            with call_guard:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                first_prepare_entered.set()
            else:
                second_prepare_entered.set()
            return True, "", stats

        def run_second_prepare():
            try:
                second_manager._prepare_dataset("demo")
            finally:
                second_finished.set()

        attempted_imports = []
        stream = self.manager.start_training("demo", {})
        second_thread = None
        try:
            with patch.object(
                YoloTrainManager,
                "_prepare_dataset_locked",
                autospec=True,
                side_effect=prepare_locked,
            ), patch(
                "builtins.__import__",
                side_effect=self._guard_ultralytics_imports(attempted_imports),
            ):
                events = self._advance_through_dataset_summary(stream)
                self.assertTrue(first_prepare_entered.is_set())
                self.assertIn(
                    "landscape: train=70, val=20, test=10",
                    "".join(event.get("message", "") for event in events),
                )

                second_thread = threading.Thread(target=run_second_prepare)
                second_thread.start()
                self.assertFalse(
                    second_prepare_entered.wait(0.25),
                    "same-project refresh entered while training generator was open",
                )

                stream.close()
                self.assertTrue(second_prepare_entered.wait(2))
                self.assertTrue(second_finished.wait(2))

            self.assertEqual(attempted_imports, [])
        finally:
            stream.close()
            if second_thread is not None:
                second_thread.join(2)
                self.assertFalse(second_thread.is_alive())

    def test_training_generator_can_be_closed_from_another_thread_and_unlocks(self):
        stats = self._verified_stats()
        stream = self.manager.start_training("demo", {})
        close_errors = []
        contender_acquired = threading.Event()
        project_lock = self.manager._get_project_lock("demo")

        def close_stream():
            try:
                stream.close()
            except BaseException as exc:
                close_errors.append(exc)

        def contend_for_lock():
            if project_lock.acquire(timeout=0.75):
                try:
                    contender_acquired.set()
                finally:
                    project_lock.release()

        with patch.object(
            YoloTrainManager,
            "_prepare_dataset_locked",
            autospec=True,
            return_value=(True, "", stats),
        ):
            events = self._advance_through_dataset_summary(stream)
            self.assertIn(
                "landscape: train=70, val=20, test=10",
                "".join(event.get("message", "") for event in events),
            )

            contender = threading.Thread(target=contend_for_lock)
            contender.start()
            self.assertFalse(contender_acquired.wait(0.1))

            closer = threading.Thread(target=close_stream)
            closer.start()
            closer.join(1)
            self.assertFalse(closer.is_alive())
            released_cross_thread = contender_acquired.wait(0.5)
            contender.join(1)

        if close_errors:
            # Clean up the old owner-bound RLock after recording the regression.
            try:
                project_lock.release()
            except RuntimeError:
                pass
        self.assertEqual(close_errors, [])
        self.assertTrue(released_cross_thread)
        self.assertFalse(contender.is_alive())

    def test_project_lock_releases_after_normal_generator_exhaustion(self):
        stats = self._verified_stats()
        fake_ultralytics = self._fake_ultralytics()
        with patch.object(
            YoloTrainManager,
            "_prepare_dataset_locked",
            autospec=True,
            return_value=(True, "", stats),
        ), patch.dict(sys.modules, {"ultralytics": fake_ultralytics}), patch.object(
            self.manager, "_get_device", return_value="cpu"
        ):
            events = list(self.manager.start_training("demo", {"epochs": 1}))

        self.assertTrue(any(event["type"] == "complete" for event in events))
        self._assert_project_lock_available()

    def test_project_lock_releases_after_prepare_failure(self):
        with patch.object(
            YoloTrainManager,
            "_prepare_dataset_locked",
            autospec=True,
            return_value=(False, "source validation failed", {}),
        ):
            events = list(self.manager.start_training("demo", {}))

        self.assertTrue(any("source validation failed" in event["message"] for event in events))
        self._assert_project_lock_available()

    def test_project_lock_releases_after_lazy_import_exception(self):
        stats = self._verified_stats()
        attempted_imports = []
        with patch.object(
            YoloTrainManager,
            "_prepare_dataset_locked",
            autospec=True,
            return_value=(True, "", stats),
        ), patch(
            "builtins.__import__",
            side_effect=self._guard_ultralytics_imports(attempted_imports),
        ):
            events = list(self.manager.start_training("demo", {}))

        self.assertEqual(attempted_imports, ["ultralytics"])
        self.assertTrue(any(event["type"] == "error" for event in events))
        self._assert_project_lock_available()

    def test_project_lock_releases_after_training_exception(self):
        stats = self._verified_stats()
        fake_ultralytics = self._fake_ultralytics(RuntimeError("mock training failed"))
        with patch.object(
            YoloTrainManager,
            "_prepare_dataset_locked",
            autospec=True,
            return_value=(True, "", stats),
        ), patch.dict(sys.modules, {"ultralytics": fake_ultralytics}), patch.object(
            self.manager, "_get_device", return_value="cpu"
        ):
            events = list(self.manager.start_training("demo", {}))

        self.assertTrue(any("mock training failed" in event["message"] for event in events))
        self._assert_project_lock_available()

    def test_module_import_does_not_eagerly_import_ultralytics(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import backend.yolo_train_manager; "
                    "assert 'ultralytics' not in sys.modules"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
