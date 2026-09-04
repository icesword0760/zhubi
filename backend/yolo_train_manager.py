"""
YOLO训练管理模块
管理YOLO模型的增量训练
"""

import os
import json
import hashlib
import math
import yaml
import shutil
import tempfile
import threading
import unicodedata
from datetime import datetime
from typing import Dict, Optional, Generator
from pathlib import Path


class _DatasetActivationError(RuntimeError):
    """Activation failed after recovery paths were deliberately handled."""

    def __init__(self, message: str, *, preserve_staging: bool):
        super().__init__(message)
        self.preserve_staging = preserve_staging


class YoloTrainManager:
    """YOLO训练管理器"""

    # This registry is intentionally process-local. The current application is a
    # single-process local runtime; cross-process filesystem locking is out of scope.
    # A primitive Lock is ownership-neutral, so a suspended training generator may
    # be finalized safely by a different request-cleanup thread.
    _project_locks = {}
    _project_locks_registry_lock = threading.Lock()
    
    def __init__(self, models_dir: str, config: Dict):
        self.models_dir = models_dir
        self.config = config
        os.makedirs(models_dir, exist_ok=True)

    @classmethod
    def _get_project_lock(cls, project_id: str):
        """Return one ownership-neutral lock per normalized project id."""
        normalized_project_id = unicodedata.normalize("NFC", project_id).casefold()
        with cls._project_locks_registry_lock:
            lock = cls._project_locks.get(normalized_project_id)
            if lock is None:
                lock = threading.Lock()
                cls._project_locks[normalized_project_id] = lock
            return lock
    
    def _validate_staged_dataset(self, staging_path, active_path, export_stats):
        """Validate the staged tree directly without following its YAML path."""
        staging_path = Path(staging_path)
        active_path = Path(active_path)
        if staging_path.is_symlink():
            raise ValueError(f"YOLO staging root cannot be a symlink: {staging_path}")
        if not staging_path.is_dir():
            raise ValueError(f"YOLO staging directory does not exist: {staging_path}")
        if not isinstance(export_stats, dict):
            raise ValueError("YOLO export stats must be an object")

        expected_source_count = export_stats.get("source_count")
        expected_source_filenames = export_stats.get("source_filenames")
        expected_split_counts = export_stats.get("split_counts")
        categories = export_stats.get("categories")
        source_manifest = export_stats.get("_source_manifest")
        if (
            not isinstance(expected_source_count, int)
            or isinstance(expected_source_count, bool)
            or expected_source_count < 0
        ):
            raise ValueError("YOLO export source total must be a non-negative integer")
        if (
            not isinstance(expected_source_filenames, list)
            or any(
                not isinstance(filename, str) or not filename
                for filename in expected_source_filenames
            )
            or len(set(expected_source_filenames)) != len(expected_source_filenames)
            or len(expected_source_filenames) != expected_source_count
        ):
            raise ValueError("YOLO export source filenames do not match source total")
        if (
            not isinstance(expected_split_counts, dict)
            or set(expected_split_counts) != {"train", "val", "test"}
            or any(
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
                for count in expected_split_counts.values()
            )
        ):
            raise ValueError("YOLO export split counts are invalid")
        if (
            not isinstance(categories, list)
            or any(not isinstance(category, str) or not category for category in categories)
        ):
            raise ValueError("YOLO export categories are invalid")
        if not isinstance(source_manifest, list):
            raise ValueError("YOLO export source manifest is missing or invalid")

        manifest_by_filename = {}
        for entry in source_manifest:
            if not isinstance(entry, dict):
                raise ValueError("YOLO export source manifest entries must be objects")
            filename = entry.get("filename")
            digest = entry.get("sha256")
            dimensions = entry.get("dimensions")
            label_lines = entry.get("label_lines")
            if (
                not isinstance(filename, str)
                or not filename
                or filename in manifest_by_filename
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or not isinstance(dimensions, list)
                or len(dimensions) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value <= 0
                    for value in dimensions
                )
                or not isinstance(label_lines, list)
                or any(not isinstance(line, str) for line in label_lines)
            ):
                raise ValueError("YOLO export source manifest entry is invalid")
            manifest_by_filename[filename] = entry
        if sorted(manifest_by_filename) != expected_source_filenames:
            raise ValueError(
                "YOLO export source manifest filenames do not match source filenames"
            )

        actual_split_counts = {}
        actual_source_filenames = []
        basename_owner = {}
        filename_owner = {}
        images_root = staging_path / "images"
        labels_root = staging_path / "labels"
        if images_root.is_symlink() or labels_root.is_symlink():
            raise ValueError("YOLO staging images/labels roots cannot be symlinks")
        for split in ("train", "val", "test"):
            images_path = images_root / split
            labels_path = labels_root / split
            if images_path.is_symlink() or labels_path.is_symlink():
                raise ValueError(
                    f"YOLO staging {split} images/labels directories cannot be symlinks"
                )
            if not images_path.is_dir() or not labels_path.is_dir():
                raise ValueError(
                    f"YOLO staging split is incomplete: {split} images/labels"
                )

            image_entries = sorted(images_path.iterdir(), key=lambda path: path.name)
            label_entries = sorted(labels_path.iterdir(), key=lambda path: path.name)
            if any(path.is_symlink() for path in image_entries):
                raise ValueError(f"YOLO staging images/{split} contains a symlink")
            if any(path.is_symlink() for path in label_entries):
                raise ValueError(f"YOLO staging labels/{split} contains a symlink")
            if any(not path.is_file() for path in image_entries):
                raise ValueError(f"YOLO staging images/{split} contains a non-file entry")
            if any(not path.is_file() or path.suffix != ".txt" for path in label_entries):
                raise ValueError(
                    f"YOLO staging labels/{split} must contain only .txt label files"
                )

            image_names = [path.name for path in image_entries]
            image_stems = [path.stem for path in image_entries]
            label_stems = [path.stem for path in label_entries]
            if len(set(image_stems)) != len(image_stems):
                raise ValueError(
                    f"YOLO staging images/{split} has duplicate image basenames"
                )
            if len(set(label_stems)) != len(label_stems):
                raise ValueError(
                    f"YOLO staging labels/{split} has duplicate label basenames"
                )
            if set(image_stems) != set(label_stems) or len(image_stems) != len(label_stems):
                raise ValueError(
                    f"YOLO staging {split} does not have exactly one label per image"
                )

            for image_name, image_stem in zip(image_names, image_stems):
                previous_split = basename_owner.get(image_stem)
                if previous_split is not None:
                    raise ValueError(
                        f"YOLO image basename {image_stem!r} appears in more than one split: "
                        f"{previous_split}, {split}"
                    )
                basename_owner[image_stem] = split
                previous_split = filename_owner.get(image_name)
                if previous_split is not None:
                    raise ValueError(
                        f"YOLO image {image_name!r} appears in more than one split: "
                        f"{previous_split}, {split}"
                    )
                filename_owner[image_name] = split

                image_path = images_path / image_name
                if image_name not in manifest_by_filename:
                    raise ValueError(
                        f"YOLO staging image {image_name!r} is not present in "
                        "the source manifest"
                    )
                manifest_entry = manifest_by_filename[image_name]
                try:
                    with image_path.open("rb") as image_file:
                        staged_digest = self._sha256_stream(image_file)
                        image_file.seek(0)
                        from PIL import Image

                        with Image.open(image_file) as image:
                            actual_dimensions = list(image.size)
                            image.verify()
                        image_file.seek(0)
                        confirmed_digest = self._sha256_stream(image_file)
                except (OSError, ValueError) as exc:
                    raise ValueError(
                        f"YOLO staging image {image_name} is unreadable: {exc}"
                    ) from exc
                if actual_dimensions != manifest_entry["dimensions"]:
                    raise ValueError(
                        f"YOLO staging image {image_name} dimensions mismatch: "
                        f"expected {manifest_entry['dimensions']}, found {actual_dimensions}"
                    )
                if staged_digest != confirmed_digest:
                    raise ValueError(
                        f"YOLO staging image {image_name} changed during validation"
                    )
                if staged_digest != manifest_entry["sha256"]:
                    raise ValueError(
                        f"YOLO staging image {image_name} SHA-256 does not match "
                        "the validated source"
                    )

                label_path = labels_path / f"{image_stem}.txt"
                try:
                    label_content = label_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise ValueError(
                        f"YOLO staging label {label_path.name} is unreadable: {exc}"
                    ) from exc
                label_lines = label_content.splitlines()
                for line_number, line in enumerate(label_lines, start=1):
                    fields = line.split()
                    location = f"{label_path.name} line {line_number}"
                    if len(fields) != 5:
                        raise ValueError(
                            f"YOLO staging label {location} must contain exactly 5 fields"
                        )
                    try:
                        class_id = int(fields[0])
                    except ValueError as exc:
                        raise ValueError(
                            f"YOLO staging label {location} class ID must be an integer"
                        ) from exc
                    try:
                        coordinates = [float(value) for value in fields[1:]]
                    except ValueError as exc:
                        raise ValueError(
                            f"YOLO staging label {location} fields must be numeric"
                        ) from exc
                    if not all(math.isfinite(value) for value in coordinates):
                        raise ValueError(
                            f"YOLO staging label {location} fields must be finite"
                        )
                    if not 0 <= class_id < len(categories):
                        raise ValueError(
                            f"YOLO staging label {location} class ID is out of range"
                        )
                    center_x, center_y, width, height = coordinates
                    if not (
                        0 <= center_x <= 1
                        and 0 <= center_y <= 1
                        and 0 < width <= 1
                        and 0 < height <= 1
                    ):
                        if width <= 0 or height <= 0:
                            raise ValueError(
                                f"YOLO staging label {location} width and height must be positive"
                            )
                        raise ValueError(
                            f"YOLO staging label {location} normalized values are out of range"
                        )
                expected_label_content = "".join(
                    f"{line}\n" for line in manifest_entry["label_lines"]
                )
                if label_content != expected_label_content:
                    raise ValueError(
                        f"YOLO staging label {label_path.name} does not match "
                        "the expected content from the validated source"
                    )

            actual_split_counts[split] = len(image_names)
            actual_source_filenames.extend(image_names)

        actual_source_filenames.sort()
        if len(actual_source_filenames) != expected_source_count:
            raise ValueError(
                f"YOLO staging source total mismatch: expected {expected_source_count}, "
                f"found {len(actual_source_filenames)}"
            )
        if actual_source_filenames != expected_source_filenames:
            raise ValueError(
                "YOLO staging filenames do not exactly match exported source filenames"
            )
        if actual_split_counts != expected_split_counts:
            raise ValueError(
                f"YOLO staging split counts mismatch: expected {expected_split_counts}, "
                f"found {actual_split_counts}"
            )
        if sum(actual_split_counts.values()) != expected_source_count:
            raise ValueError("YOLO staging split counts do not add up to source total")

        yaml_path = staging_path / "data.yaml"
        if yaml_path.is_symlink():
            raise ValueError("YOLO staging data.yaml cannot be a symlink")
        try:
            with yaml_path.open("r", encoding="utf-8") as file:
                dataset_config = yaml.safe_load(file)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"Invalid staged data.yaml: {exc}") from exc
        if not isinstance(dataset_config, dict):
            raise ValueError("Invalid staged data.yaml: expected an object")
        if dataset_config.get("path") != str(active_path):
            raise ValueError(
                f"Staged data.yaml path must name future active path {active_path}"
            )
        for split, expected_relative_path in (
            ("train", "images/train"),
            ("val", "images/val"),
            ("test", "images/test"),
        ):
            if dataset_config.get(split) != expected_relative_path:
                raise ValueError(
                    f"Staged data.yaml {split} must equal {expected_relative_path}"
                )
        expected_names = {
            index: category for index, category in enumerate(categories)
        }
        if dataset_config.get("names") != expected_names:
            raise ValueError(
                f"Staged data.yaml names mismatch: expected {expected_names}"
            )
        if dataset_config.get("nc") != len(categories):
            raise ValueError(
                f"Staged data.yaml nc mismatch: expected {len(categories)}"
            )

        domain_counts = export_stats.get("domain_counts", {})
        if not isinstance(domain_counts, dict):
            raise ValueError("YOLO export domain counts are invalid")
        for split in ("train", "val", "test"):
            split_domains = domain_counts.get(split)
            if (
                not isinstance(split_domains, dict)
                or any(
                    not isinstance(domain, str)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                    for domain, count in split_domains.items()
                )
                or sum(split_domains.values()) != actual_split_counts[split]
            ):
                raise ValueError(
                    f"YOLO export domain counts do not match staged {split} count"
                )

        return {
            "source_count": expected_source_count,
            "source_filenames": actual_source_filenames,
            "split_counts": actual_split_counts,
            "domain_counts": {
                split: dict(domain_counts[split])
                for split in ("train", "val", "test")
            },
            "categories": list(categories),
        }

    @staticmethod
    def _sha256_stream(file_object) -> str:
        """Hash the current stream to EOF without retaining its contents."""
        digest = hashlib.sha256()
        while True:
            chunk = file_object.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)

    @staticmethod
    def _unique_backup_path(parent_path: Path) -> Path:
        """Reserve a unique same-filesystem backup name without leaving a target."""
        placeholder = Path(
            tempfile.mkdtemp(dir=parent_path, prefix=".yolo_data_backup_")
        )
        placeholder.rmdir()
        return placeholder

    @staticmethod
    def _annotate_cancellation(cancellation, message, **recovery_paths):
        """Attach recovery state without changing cancellation identity."""
        for attribute, value in recovery_paths.items():
            setattr(cancellation, attribute, str(value))
        if hasattr(cancellation, "add_note"):
            cancellation.add_note(message)

    def _activate_staged_dataset(self, staging_path, active_path):
        """Atomically activate staging, restoring or preserving recovery data."""
        staging_path = Path(staging_path)
        active_path = Path(active_path)
        if not staging_path.is_dir():
            raise ValueError(f"YOLO staging directory does not exist: {staging_path}")
        active_path.parent.mkdir(parents=True, exist_ok=True)

        if not active_path.exists():
            try:
                os.replace(staging_path, active_path)
            except Exception as exc:
                raise _DatasetActivationError(
                    f"Failed to activate YOLO dataset; staging preserved at "
                    f"{staging_path}: {type(exc).__name__}: {exc}",
                    preserve_staging=True,
                ) from exc
            return {}

        backup_path = self._unique_backup_path(active_path.parent)
        try:
            os.replace(active_path, backup_path)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                if backup_path.exists() and not active_path.exists():
                    try:
                        os.replace(backup_path, active_path)
                    except BaseException as restore_error:
                        self._annotate_cancellation(
                            exc,
                            f"Cancellation occurred while moving active dataset to backup; "
                            f"restoration failed ({type(restore_error).__name__}: "
                            f"{restore_error}). Backup preserved at {backup_path}; staging "
                            f"preserved at {staging_path}",
                            recovery_backup_path=backup_path,
                            recovery_staging_path=staging_path,
                            recovery_active_path=active_path,
                        )
                        raise exc from restore_error
                elif not active_path.exists():
                    self._annotate_cancellation(
                        exc,
                        f"Cancellation left active dataset state ambiguous. Expected active "
                        f"path {active_path}; backup path {backup_path}; staging preserved at "
                        f"{staging_path}",
                        recovery_backup_path=backup_path,
                        recovery_staging_path=staging_path,
                        recovery_active_path=active_path,
                    )
                    raise
                try:
                    shutil.rmtree(staging_path)
                except BaseException as cleanup_error:
                    self._annotate_cancellation(
                        exc,
                        f"Active dataset is available at {active_path}, but cancellation "
                        f"cleanup failed ({type(cleanup_error).__name__}: {cleanup_error}); "
                        f"staging preserved at {staging_path}",
                        recovery_staging_path=staging_path,
                        recovery_active_path=active_path,
                    )
                    raise exc from cleanup_error
                raise
            try:
                shutil.rmtree(staging_path)
            except Exception as cleanup_error:
                raise _DatasetActivationError(
                    f"Failed to move active YOLO dataset to backup; old active dataset "
                    f"remains at {active_path}. Staging cleanup also failed "
                    f"({type(cleanup_error).__name__}: {cleanup_error}); staging "
                    f"preserved at {staging_path}",
                    preserve_staging=True,
                ) from cleanup_error
            raise _DatasetActivationError(
                f"Failed to move active YOLO dataset to backup; old active dataset "
                f"remains at {active_path}: {type(exc).__name__}: {exc}",
                preserve_staging=False,
            ) from exc

        try:
            os.replace(staging_path, active_path)
        except BaseException as activation_error:
            cancellation = not isinstance(activation_error, Exception)
            try:
                os.replace(backup_path, active_path)
            except BaseException as rollback_error:
                if cancellation:
                    self._annotate_cancellation(
                        activation_error,
                        f"Cancellation occurred during staged activation; rollback failed "
                        f"({type(rollback_error).__name__}: {rollback_error}). Previous "
                        f"dataset backup preserved at {backup_path}; staging preserved at "
                        f"{staging_path}",
                        recovery_backup_path=backup_path,
                        recovery_staging_path=staging_path,
                        recovery_active_path=active_path,
                    )
                    raise activation_error from rollback_error
                raise _DatasetActivationError(
                    f"Failed to activate staged YOLO dataset "
                    f"({type(activation_error).__name__}: {activation_error}); rollback "
                    f"also failed ({type(rollback_error).__name__}: {rollback_error}). "
                    f"Previous dataset backup preserved at {backup_path}; staging "
                    f"preserved at {staging_path}",
                    preserve_staging=True,
                ) from rollback_error
            try:
                shutil.rmtree(staging_path)
            except BaseException as cleanup_error:
                if cancellation:
                    self._annotate_cancellation(
                        activation_error,
                        f"Cancellation occurred during staged activation; previous active "
                        f"dataset was restored at {active_path}, but staging cleanup failed "
                        f"({type(cleanup_error).__name__}: {cleanup_error}). Staging "
                        f"preserved at {staging_path}",
                        recovery_staging_path=staging_path,
                        recovery_active_path=active_path,
                    )
                    raise activation_error from cleanup_error
                raise _DatasetActivationError(
                    f"Failed to activate staged YOLO dataset "
                    f"({type(activation_error).__name__}: {activation_error}); previous "
                    f"active dataset was restored at {active_path}, but staging cleanup "
                    f"failed ({type(cleanup_error).__name__}: {cleanup_error}). Staging "
                    f"preserved at {staging_path}",
                    preserve_staging=True,
                ) from cleanup_error
            if cancellation:
                raise
            raise _DatasetActivationError(
                f"Failed to activate staged YOLO dataset; previous active dataset was "
                f"restored at {active_path}: {type(activation_error).__name__}: "
                f"{activation_error}",
                preserve_staging=False,
            ) from activation_error

        try:
            shutil.rmtree(backup_path)
        except Exception as cleanup_error:
            return {
                "activation_committed": True,
                "activation_warning": (
                    f"New active YOLO dataset is committed at {active_path}, but backup "
                    f"cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"
                ),
                "recovery_backup_path": str(backup_path),
            }
        return {}

    def _prepare_dataset(
        self,
        project_id: str,
        split_ratios: tuple = (0.7, 0.2, 0.1),
    ) -> tuple[bool, str, dict]:
        """Serialize one project's build, validation, and atomic activation."""
        from backend.export_manager import ExportManager

        try:
            ExportManager._validate_project_id(project_id)
        except Exception as exc:
            return False, str(exc), {}
        with self._get_project_lock(project_id):
            return self._prepare_dataset_locked(project_id, split_ratios)

    def _prepare_dataset_locked(self, project_id, split_ratios):
        """Prepare a dataset while the caller holds the project's Lock."""
        staging_path = None
        export_path = None
        activation_started = False
        try:
            from backend.export_manager import ExportManager

            ExportManager._validate_project_id(project_id)
            data_dir = Path(self.models_dir).parent
            projects_dir = data_dir / "projects"
            exports_dir = data_dir / "exports"
            project_path = projects_dir / project_id
            if not project_path.is_dir():
                return False, f"项目不存在: {project_id}", {}

            annotations_dir = project_path / "annotations"
            if not annotations_dir.is_dir():
                return False, "项目没有标注数据", {}

            annotation_files = [
                path for path in annotations_dir.iterdir() if path.suffix == ".json"
            ]
            if not annotation_files:
                return False, "项目没有标注文件", {}

            print(f"[YOLO数据准备] 找到 {len(annotation_files)} 个标注文件")

            export_mgr = ExportManager(str(projects_dir), str(exports_dir))
            project_model_dir = Path(self.models_dir) / project_id
            project_model_dir.mkdir(parents=True, exist_ok=True)
            active_path = project_model_dir / "yolo_data"
            staging_path = Path(
                tempfile.mkdtemp(
                    dir=project_model_dir, prefix=".yolo_data_staging_"
                )
            )
            export_path = Path(
                tempfile.mkdtemp(dir=project_model_dir, prefix=".yolo_export_")
            )
            print(f"[YOLO数据准备] 暂存目录: {staging_path}")

            print(f"[YOLO数据准备] 开始导出 YOLO 格式，划分比例: {split_ratios}")
            export_stats = export_mgr._export_yolo(
                project_id=project_id,
                export_path=str(export_path),
                split_ratios=split_ratios,
                augmentation=False,
                training_data_path=str(staging_path),
                training_yaml_root=str(active_path),
            )
            print(f"[YOLO数据准备] 导出完成")

            verified_stats = self._validate_staged_dataset(
                staging_path, active_path, export_stats
            )
            activation_started = True
            activation_state = self._activate_staged_dataset(
                staging_path, active_path
            )
            if activation_state:
                verified_stats.update(activation_state)
            export_cleanup_error = self._cleanup_throwaway_export(export_path)
            if export_cleanup_error is not None:
                cleanup_warning = (
                    f"Throwaway YOLO export cleanup failed "
                    f"({type(export_cleanup_error).__name__}: {export_cleanup_error}); "
                    f"export remains at {export_path}"
                )
                existing_warning = verified_stats.get("activation_warning")
                verified_stats.update(
                    {
                        "activation_committed": True,
                        "cleanup_warning": cleanup_warning,
                        "activation_warning": (
                            f"{existing_warning}; {cleanup_warning}"
                            if existing_warning
                            else cleanup_warning
                        ),
                        "leftover_export_path": str(export_path),
                    }
                )
            return True, "", verified_stats
        except _DatasetActivationError as exc:
            error_msg = str(exc)
            export_cleanup_error = self._cleanup_throwaway_export(export_path)
            if export_cleanup_error is not None:
                error_msg += self._format_export_cleanup_failure(
                    export_path, export_cleanup_error
                )
            print(f"[YOLO数据准备] 激活失败: {error_msg}")
            return False, error_msg, {}
        except Exception as e:
            import traceback

            cleanup_error = None
            if staging_path is not None:
                try:
                    shutil.rmtree(staging_path)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    cleanup_error = exc
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            if cleanup_error is not None:
                error_msg += (
                    f"\nStaging cleanup failed ({type(cleanup_error).__name__}: "
                    f"{cleanup_error}); staging may remain at {staging_path}"
                )
            export_cleanup_error = self._cleanup_throwaway_export(export_path)
            if export_cleanup_error is not None:
                error_msg += self._format_export_cleanup_failure(
                    export_path, export_cleanup_error
                )
            print(f"[YOLO数据准备] 失败: {error_msg}")
            return False, error_msg, {}
        except BaseException as cancellation:
            if not activation_started and staging_path is not None:
                try:
                    shutil.rmtree(staging_path)
                except FileNotFoundError:
                    pass
                except BaseException as cleanup_error:
                    if hasattr(cancellation, "add_note"):
                        cancellation.add_note(
                            f"Staging cleanup failed ({type(cleanup_error).__name__}: "
                            f"{cleanup_error}); staging remains at {staging_path}"
                        )
            export_cleanup_error = self._cleanup_throwaway_export(export_path)
            if (
                export_cleanup_error is not None
                and hasattr(cancellation, "add_note")
            ):
                cancellation.add_note(
                    self._format_export_cleanup_failure(
                        export_path, export_cleanup_error
                    ).lstrip()
                )
            raise

    @staticmethod
    def _cleanup_throwaway_export(export_path):
        if export_path is None:
            return None
        try:
            shutil.rmtree(export_path)
        except FileNotFoundError:
            return None
        except Exception as cleanup_error:
            return cleanup_error
        return None

    @staticmethod
    def _format_export_cleanup_failure(export_path, cleanup_error):
        return (
            f"\nThrowaway YOLO export cleanup failed "
            f"({type(cleanup_error).__name__}: {cleanup_error}); "
            f"export remains at {export_path}"
        )
    
    @staticmethod
    def _build_train_info(
        *,
        project_id: str,
        train_config: Dict,
        final_metrics: Dict,
        final_model_dir: str,
        verified_stats: Dict,
        trained_at: Optional[str] = None,
    ) -> Dict:
        """Build backward-compatible metadata with complete dataset counts."""
        split_counts = verified_stats["split_counts"]
        domain_counts = verified_stats["domain_counts"]
        return {
            "model_type": "yolo",
            "project_id": project_id,
            "trained_at": trained_at or datetime.now().isoformat(),
            "config": train_config,
            "source_samples": verified_stats["source_count"],
            "train_samples": split_counts["train"],
            "val_samples": split_counts["val"],
            "test_samples": split_counts["test"],
            "domain_counts": {
                split: dict(counts) for split, counts in domain_counts.items()
            },
            "final_metrics": final_metrics,
            "model_path": final_model_dir,
            "best_model": os.path.join(final_model_dir, "best.pt"),
        }

    def start_training(
        self, project_id: str, train_config: Dict
    ) -> Generator[Dict, None, None]:
        """Stream training while preventing same-project dataset replacement."""
        with self._get_project_lock(project_id):
            yield from self._start_training_locked(project_id, train_config)

    def _start_training_locked(
        self, project_id: str, train_config: Dict
    ) -> Generator[Dict, None, None]:
        """Run training while ``start_training`` holds the project's Lock."""
        try:
            dataset_path = os.path.join(self.models_dir, project_id, "yolo_data")
            data_yaml = os.path.join(dataset_path, "data.yaml")

            yield {
                'type': 'log',
                'message': '🔄 正在从当前项目标注重建YOLO数据集...\n',
                'progress': 0
            }

            split_ratios = (
                train_config.get('train_split', 0.7),
                train_config.get('val_split', 0.2),
                train_config.get('test_split', 0.1)
            )

            yield {
                'type': 'log',
                'message': f'📊 数据划分: 训练集{split_ratios[0]*100}% | 验证集{split_ratios[1]*100}% | 测试集{split_ratios[2]*100}%\n',
                'progress': 2
            }

            yield {
                'type': 'log',
                'message': '⚙️ 正在处理标注数据和生成YOLO格式...\n',
                'progress': 5
            }

            success, error_msg, verified_stats = self._prepare_dataset_locked(
                project_id, split_ratios
            )
            if not success:
                yield {
                    'type': 'error',
                    'message': f'❌ 错误：重新准备YOLO数据集失败\n\n详细信息：\n{error_msg}\n',
                    'progress': 0
                }
                return

            yield {
                'type': 'log',
                'message': '✅ YOLO数据集已从当前标注重新生成！\n',
                'progress': 10
            }

            activation_warning = verified_stats.get("activation_warning")
            if activation_warning:
                recovery_backup_path = verified_stats.get("recovery_backup_path")
                leftover_export_path = verified_stats.get("leftover_export_path")
                warning_message = f"⚠️ 数据集已激活，但清理未完成: {activation_warning}\n"
                if recovery_backup_path:
                    warning_message += f"  - 可恢复备份: {recovery_backup_path}\n"
                if leftover_export_path:
                    warning_message += f"  - 残留导出目录: {leftover_export_path}\n"
                yield {
                    'type': 'log',
                    'message': warning_message,
                    'progress': 10
                }

            with open(data_yaml, 'r', encoding='utf-8') as f:
                dataset_config = yaml.safe_load(f)

            yield {
                'type': 'log',
                'message': f"✅ 数据集配置已加载\n",
                'progress': 12
            }

            split_counts = verified_stats["split_counts"]
            source_count = verified_stats["source_count"]
            total_count = sum(split_counts.values())
            domain_counts = verified_stats["domain_counts"]
            domains = sorted(
                {
                    domain
                    for split_domains in domain_counts.values()
                    for domain in split_domains
                }
            )
            domain_lines = "".join(
                f"  - {domain}: "
                f"train={domain_counts['train'].get(domain, 0)}, "
                f"val={domain_counts['val'].get(domain, 0)}, "
                f"test={domain_counts['test'].get(domain, 0)}\n"
                for domain in domains
            )

            yield {
                'type': 'log',
                'message': (
                    "📊 数据集统计:\n"
                    f"  - 源标注: {source_count}\n"
                    f"  - 训练集: {split_counts['train']}\n"
                    f"  - 验证集: {split_counts['val']}\n"
                    f"  - 测试集: {split_counts['test']}\n"
                    f"  - 总计: {total_count}\n"
                    f"{domain_lines}"
                ),
                'progress': 15
            }

            # Avoid loading the training stack until data is committed and reported.
            from ultralytics import YOLO

            # 加载基础模型
            base_model = train_config.get('base_model', 'yolov8n.pt')
            yield {
                'type': 'log',
                'message': f"🤖 正在加载基础模型: {base_model}\n",
                'progress': 18
            }
            
            # 检查是否有已有的微调模型
            custom_model_path = train_config.get('custom_model_path')
            if custom_model_path and os.path.exists(custom_model_path):
                model = YOLO(custom_model_path)
                yield {
                    'type': 'log',
                    'message': f"✅ 加载自定义模型: {custom_model_path}\n",
                    'progress': 20
                }
            else:
                model = YOLO(base_model)
                yield {
                    'type': 'log',
                    'message': f"✅ 加载预训练模型: {base_model}\n",
                    'progress': 20
                }
            
            # 设置设备
            device = self._get_device(train_config.get('device', 'auto'))
            yield {
                'type': 'log',
                'message': f"🖥️ 使用设备: {device}\n",
                'progress': 25
            }
            
            # 准备训练参数
            epochs = train_config.get('epochs', 50)
            batch_size = train_config.get('batch_size', 16)
            img_size = train_config.get('img_size', 640)
            patience = train_config.get('patience', 20)
            
            yield {
                'type': 'log',
                'message': f"⚙️ 训练参数:\n  - Epochs: {epochs}\n  - Batch Size: {batch_size}\n  - Image Size: {img_size}\n  - Patience: {patience}\n",
                'progress': 30
            }
            
            # 创建输出目录
            output_dir = os.path.join(self.models_dir, project_id, "yolo_checkpoints")
            os.makedirs(output_dir, exist_ok=True)
            
            yield {
                'type': 'log',
                'message': "🚀 开始训练...\n",
                'progress': 35
            }
            
            # 自定义回调来报告进度
            class ProgressCallback:
                def __init__(self, generator, total_epochs):
                    self.generator = generator
                    self.total_epochs = total_epochs
                    self.current_epoch = 0
                
                def on_train_epoch_end(self, trainer):
                    """每个epoch结束时调用"""
                    self.current_epoch += 1
                    progress = 35 + int((self.current_epoch / self.total_epochs) * 55)  # 35-90%
                    
                    metrics = trainer.metrics
                    loss = metrics.get('train/box_loss', 0) + metrics.get('train/cls_loss', 0) + metrics.get('train/dfl_loss', 0)
                    
                    self.generator({
                        'type': 'log',
                        'message': f"📊 Epoch {self.current_epoch}/{self.total_epochs} - Loss: {loss:.4f}\n",
                        'progress': progress
                    })
            
            # 训练模型
            try:
                # 注意：ultralytics的train方法会自动处理callbacks，但为了进度报告
                # 我们需要使用更细粒度的控制
                results = model.train(
                    data=data_yaml,
                    epochs=epochs,
                    batch=batch_size,
                    imgsz=img_size,
                    device=device,
                    patience=patience,
                    project=output_dir,
                    name='train',
                    exist_ok=True,
                    pretrained=True,
                    optimizer=train_config.get('optimizer', 'SGD'),
                    lr0=train_config.get('learning_rate', 0.01),
                    lrf=train_config.get('lr_final', 0.01),
                    momentum=train_config.get('momentum', 0.937),
                    weight_decay=train_config.get('weight_decay', 0.0005),
                    warmup_epochs=train_config.get('warmup_epochs', 3),
                    warmup_momentum=train_config.get('warmup_momentum', 0.8),
                    box=train_config.get('box_loss_gain', 7.5),
                    cls=train_config.get('cls_loss_gain', 0.5),
                    dfl=train_config.get('dfl_loss_gain', 1.5),
                    plots=True,
                    save=True,
                    save_period=train_config.get('save_period', -1),
                    cache=train_config.get('cache', False),
                    verbose=True
                )
                
                yield {
                    'type': 'log',
                    'message': "\n✅ 训练完成！\n",
                    'progress': 90
                }
                
                # 获取最佳模型路径
                best_model_path = os.path.join(output_dir, "train", "weights", "best.pt")
                last_model_path = os.path.join(output_dir, "train", "weights", "last.pt")
                
                # 复制到最终模型目录
                final_model_dir = os.path.join(self.models_dir, project_id, "yolo_final_model")
                os.makedirs(final_model_dir, exist_ok=True)
                
                if os.path.exists(best_model_path):
                    shutil.copy(best_model_path, os.path.join(final_model_dir, "best.pt"))
                    shutil.copy(last_model_path, os.path.join(final_model_dir, "last.pt"))
                
                yield {
                    'type': 'log',
                    'message': f"💾 模型已保存到: {final_model_dir}\n",
                    'progress': 95
                }
                
                # 提取训练指标
                results_csv = os.path.join(output_dir, "train", "results.csv")
                final_metrics = {}
                if os.path.exists(results_csv):
                    import pandas as pd
                    df = pd.read_csv(results_csv)
                    final_metrics = {
                        'mAP50': float(df['metrics/mAP50(B)'].iloc[-1]) if 'metrics/mAP50(B)' in df else 0,
                        'mAP50-95': float(df['metrics/mAP50-95(B)'].iloc[-1]) if 'metrics/mAP50-95(B)' in df else 0,
                        'precision': float(df['metrics/precision(B)'].iloc[-1]) if 'metrics/precision(B)' in df else 0,
                        'recall': float(df['metrics/recall(B)'].iloc[-1]) if 'metrics/recall(B)' in df else 0
                    }
                
                # 保存训练信息
                train_info = self._build_train_info(
                    project_id=project_id,
                    train_config=train_config,
                    final_metrics=final_metrics,
                    final_model_dir=final_model_dir,
                    verified_stats=verified_stats,
                )
                
                info_path = os.path.join(self.models_dir, project_id, "yolo_train_info.json")
                with open(info_path, 'w', encoding='utf-8') as f:
                    json.dump(train_info, f, indent=2, ensure_ascii=False)
                
                yield {
                    'type': 'log',
                    'message': f"✅ 训练信息已保存\n📊 最终指标:\n  - mAP50: {final_metrics.get('mAP50', 0):.4f}\n  - mAP50-95: {final_metrics.get('mAP50-95', 0):.4f}\n  - Precision: {final_metrics.get('precision', 0):.4f}\n  - Recall: {final_metrics.get('recall', 0):.4f}\n",
                    'progress': 100
                }
                
                yield {
                    'type': 'complete',
                    'message': "🎉 YOLO训练全部完成！\n",
                    'progress': 100
                }
                
            except Exception as e:
                yield {
                    'type': 'error',
                    'message': f"\n❌ 训练过程中出错: {str(e)}\n",
                    'progress': -1
                }
                import traceback
                yield {
                    'type': 'error',
                    'message': f"{traceback.format_exc()}\n",
                    'progress': -1
                }
        
        except Exception as e:
            yield {
                'type': 'error',
                'message': f"❌ 启动训练失败: {str(e)}\n",
                'progress': -1
            }
            import traceback
            yield {
                'type': 'error',
                'message': f"{traceback.format_exc()}\n",
                'progress': -1
            }
    
    def _get_device(self, device_config: str) -> str:
        """获取训练设备"""
        import torch
        
        if device_config == 'auto':
            if torch.cuda.is_available():
                return 'cuda'
            elif torch.backends.mps.is_available():
                return 'mps'
            else:
                return 'cpu'
        return device_config
    
    def list_trained_models(self) -> list:
        """列出所有训练好的YOLO模型"""
        models = []
        
        if not os.path.exists(self.models_dir):
            return models
        
        for project_id in os.listdir(self.models_dir):
            info_path = os.path.join(self.models_dir, project_id, "yolo_train_info.json")
            if os.path.exists(info_path):
                try:
                    with open(info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                    models.append(info)
                except Exception as e:
                    print(f"读取YOLO模型信息失败: {project_id}, 错误: {e}")
        
        return sorted(models, key=lambda x: x['trained_at'], reverse=True)
    
    def get_model_info(self, project_id: str) -> Optional[Dict]:
        """获取YOLO模型信息"""
        info_path = os.path.join(self.models_dir, project_id, "yolo_train_info.json")
        
        if not os.path.exists(info_path):
            return None
        
        with open(info_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def delete_model(self, project_id: str) -> bool:
        """删除训练好的YOLO模型"""
        model_dir = os.path.join(self.models_dir, project_id, "yolo_checkpoints")
        final_model_dir = os.path.join(self.models_dir, project_id, "yolo_final_model")
        info_path = os.path.join(self.models_dir, project_id, "yolo_train_info.json")
        
        try:
            import shutil
            if os.path.exists(model_dir):
                shutil.rmtree(model_dir)
            if os.path.exists(final_model_dir):
                shutil.rmtree(final_model_dir)
            if os.path.exists(info_path):
                os.remove(info_path)
            return True
        except Exception as e:
            print(f"删除YOLO模型失败: {e}")
            return False
