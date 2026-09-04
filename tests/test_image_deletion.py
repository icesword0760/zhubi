"""Isolated regression tests for transactional project-image deletion."""

import json
import importlib.util
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.project_manager import ProjectManager


class ImageDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.projects = self.root / "projects"
        self.project = self.projects / "demo"
        self.images = self.project / "images"
        self.annotations = self.project / "annotations"
        self.images.mkdir(parents=True)
        self.annotations.mkdir()
        self.manager = ProjectManager(str(self.projects))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_image(self, filename="screen.png", annotation=True, skipped=True):
        image_id = Path(filename).stem
        image_path = self.images / filename
        image_path.write_bytes(b"image")
        if annotation:
            (self.annotations / f"{image_id}.json").write_text(
                json.dumps({"image_id": image_id}), encoding="utf-8"
            )
        if skipped:
            (self.project / "skipped.json").write_text(
                json.dumps(
                    {
                        "skipped_images": ["keep", image_id],
                        "metadata": "preserved",
                    }
                ),
                encoding="utf-8",
            )
        return image_path

    def tombstones(self):
        return list(self.project.rglob("*.delete-*.tombstone"))

    def recovery_files(self):
        return list(self.project.rglob("*.rollback-recovery-*"))

    def pending_files(self):
        return list(self.project.rglob("*.delete-*.pending"))

    def test_deletes_exact_image_annotation_and_skipped_entry(self):
        image = self.add_image()

        self.assertTrue(self.manager.delete_image("demo", "screen"))

        self.assertFalse(image.exists())
        self.assertFalse((self.annotations / "screen.json").exists())
        skipped = json.loads((self.project / "skipped.json").read_text("utf-8"))
        self.assertEqual(skipped["skipped_images"], ["keep"])
        self.assertEqual(skipped["metadata"], "preserved")
        self.assertEqual(self.tombstones(), [])

    def test_missing_image_raises_without_mutation(self):
        existing = self.add_image("other.png")
        unrelated_tombstone = self.images / "old.png.delete-stale.tombstone"
        unrelated_tombstone.write_bytes(b"unrelated")
        before = (self.project / "skipped.json").read_bytes()

        with self.assertRaises(FileNotFoundError):
            self.manager.delete_image("demo", "missing")

        self.assertTrue(existing.exists())
        self.assertTrue(unrelated_tombstone.exists())
        self.assertEqual((self.project / "skipped.json").read_bytes(), before)

    def test_same_stem_with_multiple_supported_suffixes_is_ambiguous(self):
        png = self.add_image("screen.png", annotation=False, skipped=False)
        jpg = self.add_image("screen.jpg", annotation=False, skipped=False)
        unrelated_tombstone = self.images / "old.png.delete-stale.tombstone"
        unrelated_tombstone.write_bytes(b"unrelated")

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "screen")

        self.assertTrue(png.exists())
        self.assertTrue(jpg.exists())
        self.assertTrue(unrelated_tombstone.exists())

    def test_traversal_like_project_and_image_ids_are_rejected(self):
        image = self.add_image()
        for project_id, image_id in (
            ("../demo", "screen"),
            ("demo/../demo", "screen"),
            ("demo", "../screen"),
            ("demo", "nested/screen"),
            ("demo", "..\\screen"),
        ):
            with self.subTest(project_id=project_id, image_id=image_id):
                with self.assertRaises(ValueError):
                    self.manager.delete_image(project_id, image_id)
        self.assertTrue(image.exists())

    def test_project_symlink_escape_is_rejected(self):
        outside = self.root / "outside-project"
        (outside / "images").mkdir(parents=True)
        (outside / "annotations").mkdir()
        escaped_image = outside / "images" / "screen.png"
        escaped_image.write_bytes(b"outside")
        os.symlink(outside, self.projects / "linked")

        with self.assertRaises(ValueError):
            self.manager.delete_image("linked", "screen")

        self.assertTrue(escaped_image.exists())

    def test_in_tree_project_directory_symlink_is_rejected(self):
        real_project = self.projects / "real-project"
        real_images = real_project / "images"
        real_annotations = real_project / "annotations"
        real_images.mkdir(parents=True)
        real_annotations.mkdir()
        target = real_images / "screen.png"
        target.write_bytes(b"target")
        os.symlink(real_project.name, self.projects / "linked")

        with self.assertRaises(ValueError):
            self.manager.delete_image("linked", "screen")

        self.assertEqual(target.read_bytes(), b"target")
        self.assertTrue((self.projects / "linked").is_symlink())

    def test_in_tree_images_directory_symlink_is_rejected(self):
        self.images.rmdir()
        real_images = self.project / "real-images"
        real_images.mkdir()
        target = real_images / "screen.png"
        target.write_bytes(b"target")
        os.symlink(real_images.name, self.images)

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "screen")

        self.assertEqual(target.read_bytes(), b"target")
        self.assertTrue(self.images.is_symlink())

    def test_in_tree_annotations_directory_symlink_is_rejected(self):
        image = self.add_image("screen.png", annotation=False, skipped=False)
        self.annotations.rmdir()
        real_annotations = self.project / "real-annotations"
        real_annotations.mkdir()
        target = real_annotations / "screen.json"
        target.write_text('{"target": true}', encoding="utf-8")
        os.symlink(real_annotations.name, self.annotations)

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "screen")

        self.assertTrue(image.exists())
        self.assertEqual(target.read_text("utf-8"), '{"target": true}')
        self.assertTrue(self.annotations.is_symlink())

    def test_image_symlink_escape_is_rejected(self):
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside")
        os.symlink(outside, self.images / "screen.png")

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "screen")

        self.assertTrue(outside.exists())
        self.assertTrue((self.images / "screen.png").is_symlink())

    def test_in_tree_image_symlink_source_is_rejected_without_mutation(self):
        target = self.images / "target.png"
        target.write_bytes(b"target")
        symlink = self.images / "alias.png"
        os.symlink(target.name, symlink)

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "alias")

        self.assertTrue(symlink.is_symlink())
        self.assertEqual(target.read_bytes(), b"target")

    def test_in_tree_annotation_symlink_is_rejected_without_mutation(self):
        image = self.add_image("screen.png", annotation=False, skipped=False)
        target = self.annotations / "victim.json"
        target.write_text('{"victim": true}', encoding="utf-8")
        symlink = self.annotations / "screen.json"
        os.symlink(target.name, symlink)

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "screen")

        self.assertTrue(image.exists())
        self.assertTrue(symlink.is_symlink())
        self.assertEqual(target.read_text("utf-8"), '{"victim": true}')

    def test_in_tree_skipped_file_symlink_is_rejected_without_mutation(self):
        image = self.add_image("screen.png", annotation=False, skipped=False)
        target = self.project / "victim.json"
        original = '{"skipped_images": ["screen"], "victim": true}'
        target.write_text(original, encoding="utf-8")
        symlink = self.project / "skipped.json"
        os.symlink(target.name, symlink)

        with self.assertRaises(ValueError):
            self.manager.delete_image("demo", "screen")

        self.assertTrue(image.exists())
        self.assertTrue(symlink.is_symlink())
        self.assertEqual(target.read_text("utf-8"), original)

    def test_unsafe_tombstone_symlink_does_not_block_valid_deletion(self):
        image = self.add_image("screen.png", annotation=False, skipped=False)
        outside = self.root / "outside.tombstone"
        outside.write_bytes(b"outside")
        unsafe_tombstone = self.images / "old.png.delete-stale.tombstone"
        os.symlink(outside, unsafe_tombstone)

        self.assertTrue(self.manager.delete_image("demo", "screen"))

        self.assertFalse(image.exists())
        self.assertTrue(unsafe_tombstone.is_symlink())
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_in_tree_tombstone_symlink_is_skipped_without_unlinking_victim(self):
        image = self.add_image("screen.png", annotation=False, skipped=False)
        victim = self.images / "victim.png"
        victim.write_bytes(b"victim")
        tombstone_symlink = self.images / "old.png.delete-stale.tombstone"
        os.symlink(victim.name, tombstone_symlink)

        self.assertTrue(self.manager.delete_image("demo", "screen"))

        self.assertFalse(image.exists())
        self.assertTrue(tombstone_symlink.is_symlink())
        self.assertEqual(victim.read_bytes(), b"victim")

    def test_precommit_filesystem_failure_rolls_back_staged_files(self):
        image = self.add_image()
        annotation = self.annotations / "screen.json"
        skipped_path = self.project / "skipped.json"
        skipped_before = skipped_path.read_bytes()
        real_replace = os.replace

        def fail_skipped_commit(source, destination):
            if Path(destination).name == "skipped.json":
                raise OSError("injected skipped replacement failure")
            return real_replace(source, destination)

        with patch("backend.project_manager.os.replace", side_effect=fail_skipped_commit):
            with self.assertRaises(OSError):
                self.manager.delete_image("demo", "screen")

        self.assertTrue(image.exists())
        self.assertTrue(annotation.exists())
        self.assertEqual(skipped_path.read_bytes(), skipped_before)
        self.assertEqual(self.tombstones(), [])

    def test_rollback_failure_reports_stranded_tombstone_and_recovery_path(self):
        image = self.add_image("screen.png", annotation=True, skipped=False)
        annotation = self.annotations / "screen.json"
        real_replace = os.replace

        def fail_annotation_stage_and_image_restore(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if source_path.name == "screen.json" and source_path.parent.name == "annotations":
                raise OSError("injected annotation staging failure")
            if (
                ".delete-" in source_path.name
                and destination_path.name == "screen.png"
                and destination_path.parent.name == "images"
            ):
                raise OSError("injected image restoration failure")
            return real_replace(source, destination)

        with patch(
            "backend.project_manager.os.replace",
            side_effect=fail_annotation_stage_and_image_restore,
        ):
            with self.assertRaises(RuntimeError) as raised:
                self.manager.delete_image("demo", "screen")

        error = raised.exception
        self.assertIsInstance(error.__cause__, OSError)
        self.assertIn("annotation staging failure", str(error.__cause__))
        self.assertIn("rollback", str(error).lower())
        self.assertIn("screen.png.delete-", str(error))
        self.assertIn(os.path.realpath(image), str(error))
        self.assertIn("rollback-recovery-", str(error))
        self.assertEqual(self.tombstones(), [])
        recovery_files = self.recovery_files()
        self.assertEqual(len(recovery_files), 1)
        self.assertFalse(image.exists())
        self.assertTrue(annotation.exists())

        self.manager.get_project_images("demo")
        self.assertEqual(self.recovery_files(), recovery_files)
        self.assertEqual(recovery_files[0].read_bytes(), b"image")

    def test_committed_tombstone_cleanup_is_retried_by_listing_and_delete(self):
        first = self.add_image("first.png", annotation=False, skipped=False)
        real_unlink = os.unlink

        def fail_tombstone_cleanup(path, *args, **kwargs):
            if os.fspath(path).endswith(".tombstone"):
                raise OSError("injected cleanup failure")
            return real_unlink(path, *args, **kwargs)

        with patch("backend.project_manager.os.unlink", side_effect=fail_tombstone_cleanup):
            self.assertTrue(self.manager.delete_image("demo", "first"))

        self.assertFalse(first.exists())
        self.assertTrue(self.tombstones())
        self.manager.get_project_images("demo")
        self.assertEqual(self.tombstones(), [])

        second = self.add_image("second.png", annotation=False, skipped=False)
        stale = self.images / "old.png.delete-stale.tombstone"
        stale.write_bytes(b"stale")
        self.assertTrue(self.manager.delete_image("demo", "second"))
        self.assertFalse(second.exists())
        self.assertFalse(stale.exists())

    def test_listing_waits_for_active_delete_transaction(self):
        self.add_image("screen.png", annotation=False, skipped=False)
        staged = threading.Event()
        release_delete = threading.Event()
        listing_done = threading.Event()
        delete_errors = []
        listing_results = []
        real_replace = os.replace

        def block_after_image_stage(source, destination):
            result = real_replace(source, destination)
            if Path(source).name == "screen.png" and str(destination).endswith(".pending"):
                staged.set()
                release_delete.wait(2)
            return result

        def run_delete():
            try:
                self.manager.delete_image("demo", "screen")
            except Exception as error:
                delete_errors.append(error)

        def run_listing():
            listing_results.append(self.manager.get_project_images("demo"))
            listing_done.set()

        with patch("backend.project_manager.os.replace", side_effect=block_after_image_stage):
            delete_thread = threading.Thread(target=run_delete)
            delete_thread.start()
            self.assertTrue(staged.wait(1), "delete never reached pending stage")
            listing_thread = threading.Thread(target=run_listing)
            listing_thread.start()
            self.assertFalse(
                listing_done.wait(0.1),
                "listing interleaved with an active project deletion",
            )
            release_delete.set()
            delete_thread.join(2)
            listing_thread.join(2)

        self.assertEqual(delete_errors, [])
        self.assertTrue(listing_done.is_set())
        self.assertEqual(listing_results[0]["total"], 0)

    def test_skip_update_waits_for_delete_and_preserves_unrelated_update(self):
        self.add_image("screen.png", annotation=False, skipped=True)
        self.add_image("new-image.png", annotation=False, skipped=False)
        staged = threading.Event()
        release_delete = threading.Event()
        skip_done = threading.Event()
        real_replace = os.replace

        def block_after_stage(source, destination):
            result = real_replace(source, destination)
            if Path(source).name == "screen.png" and str(destination).endswith(".pending"):
                staged.set()
                release_delete.wait(2)
            return result

        with patch("backend.project_manager.os.replace", side_effect=block_after_stage):
            delete_thread = threading.Thread(
                target=self.manager.delete_image, args=("demo", "screen")
            )
            delete_thread.start()
            self.assertTrue(staged.wait(1))
            skip_thread = threading.Thread(
                target=lambda: (
                    self.manager.set_image_skipped("demo", "new-image", True),
                    skip_done.set(),
                )
            )
            skip_thread.start()
            self.assertFalse(skip_done.wait(0.1))
            release_delete.set()
            delete_thread.join(2)
            skip_thread.join(2)

        skipped = json.loads((self.project / "skipped.json").read_text("utf-8"))
        self.assertEqual(set(skipped["skipped_images"]), {"keep", "new-image"})

    def test_skip_queued_after_same_image_delete_returns_false(self):
        self.add_image("screen.png", annotation=False, skipped=True)
        staged = threading.Event()
        release_delete = threading.Event()
        result = []
        real_replace = os.replace

        def block_after_stage(source, destination):
            value = real_replace(source, destination)
            if Path(source).name == "screen.png" and str(destination).endswith(".pending"):
                staged.set()
                release_delete.wait(2)
            return value

        with patch("backend.project_manager.os.replace", side_effect=block_after_stage):
            delete_thread = threading.Thread(
                target=self.manager.delete_image, args=("demo", "screen")
            )
            delete_thread.start()
            self.assertTrue(staged.wait(1))
            skip_thread = threading.Thread(
                target=lambda: result.append(
                    self.manager.set_image_skipped("demo", "screen", True)
                )
            )
            skip_thread.start()
            release_delete.set()
            delete_thread.join(2)
            skip_thread.join(2)

        self.assertEqual(result, [False])
        skipped = json.loads((self.project / "skipped.json").read_text("utf-8"))
        self.assertNotIn("screen", skipped["skipped_images"])

    def test_webp_is_listable_and_deletable(self):
        image = self.add_image("screen.webp", annotation=True, skipped=False)
        listed = self.manager.get_project_images("demo")
        self.assertEqual([item["filename"] for item in listed["images"]], ["screen.webp"])
        self.assertTrue(listed["images"][0]["annotated"])
        self.assertTrue(self.manager.delete_image("demo", "screen"))
        self.assertFalse(image.exists())

    def test_annotation_manager_resolves_exact_webp_source(self):
        self.add_image("screen.webp", annotation=False, skipped=False)

        class OpenedImage:
            size = (320, 240)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        pil = types.ModuleType("PIL")
        pil.Image = types.SimpleNamespace(open=lambda path: OpenedImage())
        annotation_path = Path(__file__).parents[1] / "backend" / "annotation_manager.py"
        spec = importlib.util.spec_from_file_location(
            "webp_test_annotation_manager", annotation_path
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"PIL": pil}):
            spec.loader.exec_module(module)
        manager = module.AnnotationManager(str(self.projects))

        result = manager.save_annotation("demo", "screen", [])

        self.assertEqual(result["image_filename"], "screen.webp")
        self.assertEqual(result["image_width"], 320)
        self.assertTrue((self.annotations / "screen.json").exists())

    def seed_delete_journal(self, phase, artifact_kind, skipped_images):
        token = "crash"
        original = "screen.png"
        artifact = f"{original}.delete-{token}.{artifact_kind}"
        (self.images / artifact).write_bytes(b"image")
        marker = self.project / f".delete-transaction-{token}.json"
        marker.write_text(json.dumps({
            "token": token,
            "image_id": "screen",
            "remove_skipped": True,
            "phase": phase,
            "records": [{
                "directory": "images",
                "original": original,
                "pending": f"{original}.delete-{token}.pending",
                "tombstone": f"{original}.delete-{token}.tombstone",
            }],
        }), encoding="utf-8")
        (self.project / "skipped.json").write_text(
            json.dumps({"skipped_images": skipped_images}), encoding="utf-8"
        )
        return marker

    def test_recovers_committed_journal_before_skipped_update(self):
        marker = self.seed_delete_journal("committed", "tombstone", ["screen", "keep"])
        result = self.manager.get_project_images("demo")
        skipped = json.loads((self.project / "skipped.json").read_text("utf-8"))
        self.assertEqual(result["total"], 0)
        self.assertEqual(skipped["skipped_images"], ["keep"])
        self.assertFalse(marker.exists())
        self.assertEqual(self.tombstones(), [])

    def test_recovers_committed_journal_after_skipped_update(self):
        marker = self.seed_delete_journal("committed", "tombstone", ["keep"])
        self.manager.get_project_images("demo")
        skipped = json.loads((self.project / "skipped.json").read_text("utf-8"))
        self.assertEqual(skipped["skipped_images"], ["keep"])
        self.assertFalse(marker.exists())
        self.assertEqual(self.tombstones(), [])

    def test_recovers_precommit_journal_by_restoring_pending_source(self):
        marker = self.seed_delete_journal("precommit", "pending", ["screen"])
        result = self.manager.get_project_images("demo")
        self.assertEqual([item["filename"] for item in result["images"]], ["screen.png"])
        self.assertEqual((self.images / "screen.png").read_bytes(), b"image")
        self.assertFalse(marker.exists())
        self.assertEqual(self.pending_files(), [])

    def test_annotation_delete_waits_for_image_delete_transaction(self):
        self.add_image("screen.png", annotation=True, skipped=False)
        pil = types.ModuleType("PIL")
        pil.Image = object
        annotation_path = Path(__file__).parents[1] / "backend" / "annotation_manager.py"
        spec = importlib.util.spec_from_file_location(
            "image_deletion_test_annotation_manager", annotation_path
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"PIL": pil}):
            spec.loader.exec_module(module)
        annotation_manager = module.AnnotationManager(str(self.projects))

        staged = threading.Event()
        release_delete = threading.Event()
        annotation_done = threading.Event()
        annotation_results = []
        real_replace = os.replace

        def block_after_stage(source, destination):
            result = real_replace(source, destination)
            if Path(source).name == "screen.png" and str(destination).endswith(".pending"):
                staged.set()
                release_delete.wait(2)
            return result

        def remove_annotation():
            annotation_results.append(
                annotation_manager.delete_annotation("demo", "screen")
            )
            annotation_done.set()

        with patch("backend.project_manager.os.replace", side_effect=block_after_stage):
            delete_thread = threading.Thread(
                target=self.manager.delete_image, args=("demo", "screen")
            )
            delete_thread.start()
            self.assertTrue(staged.wait(1))
            annotation_thread = threading.Thread(target=remove_annotation)
            annotation_thread.start()
            self.assertFalse(annotation_done.wait(0.1))
            release_delete.set()
            delete_thread.join(2)
            annotation_thread.join(2)

        self.assertEqual(annotation_results, [False])

    def test_listing_recovers_orphan_pending_file_instead_of_deleting_it(self):
        pending = self.images / "screen.png.delete-crash.pending"
        pending.write_bytes(b"only-copy")

        result = self.manager.get_project_images("demo")

        restored = self.images / "screen.png"
        self.assertEqual(restored.read_bytes(), b"only-copy")
        self.assertFalse(pending.exists())
        self.assertEqual([item["id"] for item in result["images"]], ["screen"])

    def test_pending_recovery_conflict_is_preserved_under_recovery_name(self):
        original = self.images / "screen.png"
        original.write_bytes(b"current")
        pending = self.images / "screen.png.delete-crash.pending"
        pending.write_bytes(b"orphan")

        self.manager.get_project_images("demo")

        self.assertEqual(original.read_bytes(), b"current")
        self.assertFalse(pending.exists())
        recovery_files = self.recovery_files()
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(recovery_files[0].read_bytes(), b"orphan")

    def test_listing_percent_encodes_dynamic_url_segments_only(self):
        project_id = "项目 #?%"
        project = self.projects / project_id
        images = project / "images"
        annotations = project / "annotations"
        images.mkdir(parents=True)
        annotations.mkdir()
        filename = "图 #?% space.png"
        (images / filename).write_bytes(b"image")

        result = self.manager.get_project_images(project_id)

        self.assertEqual(result["total"], 1)
        item = result["images"][0]
        self.assertEqual(item["id"], "图 #?% space")
        self.assertEqual(item["filename"], filename)
        self.assertEqual(
            item["path"],
            "/api/projects/%E9%A1%B9%E7%9B%AE%20%23%3F%25/images/"
            "%E5%9B%BE%20%23%3F%25%20space.png",
        )


class ImageDeletionRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        data_root = Path(cls.temporary_directory.name)

        class FakeFlask:
            def __init__(self, *args, **kwargs):
                self.config = {}
                self.routes = {}

            def route(self, rule, **options):
                def decorator(function):
                    self.routes[(rule, tuple(options.get("methods", [])))] = function
                    return function

                return decorator

            def run(self, *args, **kwargs):
                raise AssertionError("test import must not start the server")

        flask_module = types.ModuleType("flask")
        flask_module.Flask = FakeFlask
        flask_module.request = types.SimpleNamespace()
        flask_module.jsonify = lambda value=None, **kwargs: value if value is not None else kwargs
        flask_module.send_file = lambda *args, **kwargs: None
        flask_module.send_from_directory = lambda *args, **kwargs: None
        flask_module.Response = object

        yaml_module = types.ModuleType("yaml")
        yaml_module.safe_load = lambda stream: {
            "server": {"secret_key": "test", "host": "127.0.0.1", "port": 0, "debug": False},
            "data": {
                "max_upload_size": 1,
                "projects_dir": str(data_root / "projects"),
                "models_dir": str(data_root / "models"),
                "exports_dir": str(data_root / "exports"),
                "logs_dir": str(data_root / "logs"),
                "allowed_extensions": ["png", "webp"],
            },
        }

        class DummyManager:
            def __init__(self, *args, **kwargs):
                pass

        module_stubs = {
            "yaml": yaml_module,
            "flask": flask_module,
            "flask_cors": types.SimpleNamespace(CORS=lambda app: None),
            "werkzeug.utils": types.SimpleNamespace(secure_filename=lambda name: name),
            "PIL": types.SimpleNamespace(Image=object),
        }
        for module_name, class_name in (
            ("backend.annotation_manager", "AnnotationManager"),
            ("backend.export_manager", "ExportManager"),
            ("backend.train_manager", "TrainManager"),
            ("backend.yolo_train_manager", "YoloTrainManager"),
            ("backend.model_validator", "ModelValidator"),
        ):
            stub = types.ModuleType(module_name)
            setattr(stub, class_name, DummyManager)
            module_stubs[module_name] = stub

        app_path = Path(__file__).parents[1] / "app.py"
        spec = importlib.util.spec_from_file_location("image_deletion_test_app", app_path)
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, module_stubs):
            spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def request_with_result(self, result):
        with patch.object(self.module.project_manager, "delete_image", side_effect=result):
            return self.module.delete_image("demo", "screen")

    def test_delete_route_returns_success_json(self):
        with patch.object(self.module.project_manager, "delete_image", return_value=True):
            response = self.module.delete_image("demo", "screen")

        self.assertEqual(response, {"success": True})

    def test_delete_route_maps_missing_ambiguous_and_unexpected_errors(self):
        cases = (
            (FileNotFoundError("missing"), 404),
            (ValueError("ambiguous or invalid"), 400),
        )
        for error, expected_status in cases:
            with self.subTest(error=type(error).__name__):
                response = self.request_with_result(error)
                payload, status = response
                self.assertEqual(status, expected_status)
                self.assertFalse(payload["success"])

    def test_delete_route_logs_unexpected_error_and_returns_generic_500(self):
        secret = "/tmp/private/project/images/screen.png.delete-secret.tombstone"
        with patch.object(
            self.module.project_manager,
            "delete_image",
            side_effect=RuntimeError(f"rollback failed: {secret}"),
        ), patch.object(self.module.traceback, "print_exc") as print_exc:
            payload, status = self.module.delete_image("demo", "screen")

        self.assertEqual(status, 500)
        self.assertEqual(payload, {"success": False, "error": "服务器内部错误"})
        self.assertNotIn("/tmp/", str(payload))
        self.assertNotIn("delete-secret", str(payload))
        print_exc.assert_called_once_with()

    def test_upload_holds_project_lock_across_save_and_verification(self):
        state = {"locked": False, "saved": False, "verified": False}

        class LockContext:
            def __enter__(self):
                state["locked"] = True

            def __exit__(self, *args):
                state["locked"] = False

        class Upload:
            filename = "screen.webp"

            def save(self, path):
                self_path = Path(path)
                self_path.parent.mkdir(parents=True, exist_ok=True)
                self.assert_locked()
                self_path.write_bytes(b"webp")
                state["saved"] = True

            @staticmethod
            def assert_locked():
                if not state["locked"]:
                    raise AssertionError("upload save ran outside project lock")

        class Files:
            def __contains__(self, key):
                return key == "images"

            def getlist(self, key):
                return [Upload()]

        def open_image(path):
            self.assertTrue(state["locked"])

            class Verification:
                def verify(inner_self):
                    self.assertTrue(state["locked"])
                    state["verified"] = True

            return Verification()

        original_files = self.module.request.__dict__.get("files")
        self.module.request.files = Files()
        try:
            with patch.object(
                self.module.project_manager,
                "project_lock",
                return_value=LockContext(),
            ) as project_lock, patch.object(
                self.module, "Image", new=types.SimpleNamespace(open=open_image)
            ):
                response = self.module.upload_images("demo")
        finally:
            if original_files is None:
                del self.module.request.files
            else:
                self.module.request.files = original_files

        self.assertTrue(state["saved"])
        self.assertTrue(state["verified"])
        self.assertFalse(state["locked"])
        project_lock.assert_called_once_with("demo")
        self.assertEqual(response["uploaded"], 1)


if __name__ == "__main__":
    unittest.main()
