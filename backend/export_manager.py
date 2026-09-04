"""
导出管理模块
支持多种格式导出：COCO、YOLO、Florence-2、VOC、CSV
"""

import os
import json
import hashlib
import math
import shutil
import unicodedata
import zipfile
from datetime import datetime
from numbers import Real
from pathlib import Path, PureWindowsPath
from typing import Dict, List, Tuple
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
import random


class ExportManager:
    """导出管理器"""
    
    def __init__(self, projects_dir: str, exports_dir: str):
        self.projects_dir = projects_dir
        self.exports_dir = exports_dir
        os.makedirs(exports_dir, exist_ok=True)

    @staticmethod
    def _validate_project_id(project_id: str) -> str:
        """Require one portable, relative basename before constructing paths."""
        windows_path = PureWindowsPath(project_id) if isinstance(project_id, str) else None
        if (
            not isinstance(project_id, str)
            or not project_id
            or project_id in {".", ".."}
            or "/" in project_id
            or "\\" in project_id
            or os.path.isabs(project_id)
            or (windows_path is not None and bool(windows_path.drive))
            or os.path.basename(project_id) != project_id
        ):
            raise ValueError(
                f"Invalid project id: {project_id!r}; expected one relative basename"
            )
        return project_id
    
    def export_project(self, project_id: str, export_format: str,
                      split_ratios: Tuple[float, float, float] = (0.7, 0.2, 0.1),
                      augmentation: bool = False,
                      use_cropped: bool = False) -> str:
        """导出项目数据
        
        Args:
            use_cropped: 是否使用裁切后的图标（仅对florence2格式有效）
        """
        self._validate_project_id(project_id)
        
        exporters = {
            'coco': self._export_coco,
            'yolo': self._export_yolo,
            'florence2': self._export_florence2,
            'florence2_cropped': self._export_florence2_cropped,  # 新增：使用裁切图标
            'voc': self._export_voc,
            'csv': self._export_csv
        }
        
        # 如果使用裁切且是florence2格式
        if use_cropped and export_format == 'florence2':
            export_format = 'florence2_cropped'
        
        if export_format not in exporters:
            raise ValueError(f"不支持的导出格式: {export_format}")
        
        # 创建导出目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"{project_id}_{export_format}_{timestamp}"
        exports_root = Path(self.exports_dir).resolve()
        export_path = (exports_root / export_name).resolve()
        zip_path = export_path.with_name(f"{export_path.name}.zip")
        if export_path.parent != exports_root or zip_path.parent != exports_root:
            raise ValueError(f"Export path escapes configured directory: {export_name!r}")

        exporter = exporters[export_format]
        temp_created = False
        archive_started = False
        archive_success = False
        try:
            export_path.mkdir(parents=False, exist_ok=False)
            temp_created = True
            exporter(
                project_id,
                str(export_path),
                split_ratios,
                augmentation,
            )
            archive_started = True
            self._create_zip(str(export_path), str(zip_path))
            archive_success = True
        except BaseException as primary_error:
            cleanup_reports = []
            if archive_started and not archive_success and zip_path.exists():
                try:
                    zip_path.unlink()
                except Exception as cleanup_error:
                    cleanup_reports.append(
                        f"Partial ZIP cleanup failed ({type(cleanup_error).__name__}: "
                        f"{cleanup_error}); ZIP remains at {zip_path}"
                    )
            if temp_created and export_path.exists():
                try:
                    shutil.rmtree(export_path)
                except Exception as cleanup_error:
                    cleanup_reports.append(
                        f"Temporary export cleanup failed "
                        f"({type(cleanup_error).__name__}: {cleanup_error}); "
                        f"temporary export remains at {export_path}"
                    )
            if cleanup_reports and hasattr(primary_error, "add_note"):
                primary_error.add_note("\n".join(cleanup_reports))
            raise

        if temp_created and export_path.exists():
            try:
                shutil.rmtree(export_path)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"Export archive was created at {zip_path}, but temporary export "
                    f"cleanup failed ({type(cleanup_error).__name__}: {cleanup_error}); "
                    f"temporary export remains at {export_path}"
                ) from cleanup_error
        return str(zip_path)
    
    def _split_dataset(self, annotations: List[Dict], 
                      split_ratios: Tuple[float, float, float]) -> Dict[str, List[Dict]]:
        """划分数据集"""
        random.shuffle(annotations)
        
        total = len(annotations)
        train_end = int(total * split_ratios[0])
        val_end = train_end + int(total * split_ratios[1])
        
        return {
            'train': annotations[:train_end],
            'val': annotations[train_end:val_end],
            'test': annotations[val_end:]
        }
    
    def _export_coco(self, project_id: str, export_path: str,
                    split_ratios: Tuple[float, float, float],
                    augmentation: bool):
        """导出COCO格式"""
        from backend.annotation_manager import AnnotationManager
        from backend.project_manager import ProjectManager
        
        ann_mgr = AnnotationManager(self.projects_dir)
        proj_mgr = ProjectManager(self.projects_dir)
        
        # 获取项目信息
        project = proj_mgr.get_project(project_id)
        categories = project['categories']
        
        # 获取所有标注
        all_annotations = ann_mgr.get_all_annotations(project_id)
        
        # 划分数据集
        splits = self._split_dataset(all_annotations, split_ratios)
        
        # 为每个split生成COCO格式
        for split_name, split_annotations in splits.items():
            if not split_annotations:
                continue
            
            split_dir = os.path.join(export_path, split_name)
            images_dir = os.path.join(split_dir, 'images')
            os.makedirs(images_dir, exist_ok=True)
            
            # 构建COCO数据结构
            coco_data = {
                "info": {
                    "description": project['description'],
                    "version": str(project['version']),
                    "year": datetime.now().year,
                    "date_created": datetime.now().isoformat()
                },
                "licenses": [],
                "images": [],
                "annotations": [],
                "categories": []
            }
            
            # 添加类别
            for idx, cat_name in enumerate(categories):
                coco_data['categories'].append({
                    "id": idx + 1,
                    "name": cat_name,
                    "supercategory": "object"
                })
            
            # 构建类别名称到ID的映射
            cat_name_to_id = {cat['name']: cat['id'] 
                            for cat in coco_data['categories']}
            
            annotation_id = 1
            
            # 处理每张图片
            for img_idx, annotation_data in enumerate(split_annotations):
                image_id = img_idx + 1
                
                # 复制图片
                src_image_path = os.path.join(
                    self.projects_dir, project_id, "images",
                    annotation_data['image_filename']
                )
                dst_image_path = os.path.join(
                    images_dir, annotation_data['image_filename']
                )
                shutil.copy(src_image_path, dst_image_path)
                
                # 添加图片信息
                coco_data['images'].append({
                    "id": image_id,
                    "file_name": annotation_data['image_filename'],
                    "width": annotation_data['image_width'],
                    "height": annotation_data['image_height']
                })
                
                # 添加标注
                for ann in annotation_data['annotations']:
                    bbox = ann['bbox']  # [x, y, width, height]
                    area = bbox[2] * bbox[3]
                    
                    coco_data['annotations'].append({
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": cat_name_to_id[ann['category']],
                        "bbox": bbox,
                        "area": area,
                        "iscrowd": 0
                    })
                    annotation_id += 1
            
            # 保存COCO JSON文件
            coco_json_path = os.path.join(split_dir, f"_annotations.coco.json")
            with open(coco_json_path, 'w', encoding='utf-8') as f:
                json.dump(coco_data, f, indent=2, ensure_ascii=False)
    
    def _load_validated_yolo_source(self, project_id: str):
        """Load every YOLO source record, rejecting the project as a unit."""
        from PIL import Image

        self._validate_project_id(project_id)
        projects_root = Path(self.projects_dir).resolve()
        project_path = (projects_root / project_id).resolve()
        if project_path.parent != projects_root:
            raise ValueError(f"Invalid project id: {project_id!r}")
        if not project_path.is_dir():
            raise ValueError(f"Project does not exist: {project_id}")

        project_config_path = project_path / "project.json"
        try:
            with project_config_path.open("r", encoding="utf-8") as file:
                project = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Invalid project configuration {project_config_path.name}: {exc}"
            ) from exc

        categories = project.get("categories") if isinstance(project, dict) else None
        if (
            not isinstance(categories, list)
            or any(not isinstance(category, str) or not category for category in categories)
            or len(set(categories)) != len(categories)
        ):
            raise ValueError("Project categories must be a list of unique non-empty strings")

        annotations_path = project_path / "annotations"
        images_path = project_path / "images"
        if not annotations_path.is_dir():
            raise ValueError(f"Annotations directory does not exist: {annotations_path}")
        if not images_path.is_dir():
            raise ValueError(f"Images directory does not exist: {images_path}")
        resolved_images_path = images_path.resolve()

        annotation_filenames = sorted(
            filename
            for filename in os.listdir(annotations_path)
            if filename.endswith(".json")
        )
        records = []
        seen_image_ids = set()
        seen_image_filenames = set()
        seen_label_stems = set()
        category_ids = {
            category: index for index, category in enumerate(categories)
        }

        for annotation_filename in annotation_filenames:
            annotation_path = annotations_path / annotation_filename
            try:
                with annotation_path.open("r", encoding="utf-8") as file:
                    record = json.load(file)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: expected one JSON object"
                )

            image_id = record.get("image_id")
            if not isinstance(image_id, str) or not image_id:
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: image_id must be a non-empty string"
                )

            image_filename = record.get("image_filename")
            if (
                not isinstance(image_filename, str)
                or not image_filename
                or image_filename in {".", ".."}
                or "/" in image_filename
                or "\\" in image_filename
                or os.path.basename(image_filename) != image_filename
            ):
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: image_filename must be a basename"
                )

            image_width = record.get("image_width")
            image_height = record.get("image_height")
            for field_name, value in (
                ("image_width", image_width),
                ("image_height", image_height),
            ):
                if (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value <= 0
                ):
                    raise ValueError(
                        f"Invalid annotation {annotation_filename}: {field_name} must be a positive integer"
                    )

            annotations = record.get("annotations")
            if not isinstance(annotations, list):
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: annotations must be a list"
                )

            image_path = images_path / image_filename
            try:
                resolved_image_path = image_path.resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: source image does not exist: {image_filename}"
                ) from exc
            if resolved_image_path.parent != resolved_images_path or not image_path.is_file():
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: source image escapes images directory: {image_filename}"
                )

            try:
                with image_path.open("rb") as source_image:
                    source_digest = self._sha256_stream(source_image)
                    source_image.seek(0)
                    with Image.open(source_image) as image:
                        actual_width, actual_height = image.size
                        image.verify()
                    source_image.seek(0)
                    confirmed_digest = self._sha256_stream(source_image)
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: unreadable source image {image_filename}: {exc}"
                ) from exc
            if source_digest != confirmed_digest:
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: source image "
                    f"{image_filename} changed during validation"
                )
            if (actual_width, actual_height) != (image_width, image_height):
                raise ValueError(
                    f"Invalid annotation {annotation_filename}: stored dimensions "
                    f"{image_width}x{image_height} do not match source image "
                    f"{actual_width}x{actual_height}"
                )

            label_stem = os.path.splitext(image_filename)[0]
            for value, seen, description in (
                (image_id, seen_image_ids, "image_id"),
                (image_filename, seen_image_filenames, "image_filename"),
                (label_stem, seen_label_stems, "label stem"),
            ):
                normalized_value = unicodedata.normalize("NFC", value)
                collision_key = os.path.normcase(normalized_value).casefold()
                if collision_key in seen:
                    raise ValueError(
                        f"Invalid annotation {annotation_filename}: duplicate {description}: {value}"
                    )
                seen.add(collision_key)

            for annotation_index, annotation in enumerate(annotations):
                location = f"{annotation_filename} annotation {annotation_index}"
                if not isinstance(annotation, dict):
                    raise ValueError(f"Invalid {location}: expected an object")
                category = annotation.get("category")
                if category not in categories:
                    raise ValueError(
                        f"Invalid {location}: unknown category {category!r}"
                    )
                bbox = annotation.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise ValueError(
                        f"Invalid {location}: bbox must be a four-element list"
                    )
                if any(
                    not isinstance(value, Real)
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    for value in bbox
                ):
                    raise ValueError(
                        f"Invalid {location}: bbox values must be finite numbers"
                    )
                x, y, width, height = bbox
                if width <= 0 or height <= 0:
                    raise ValueError(
                        f"Invalid {location}: bbox width and height must be positive"
                    )
                if (
                    x < 0
                    or y < 0
                    or x + width > image_width
                    or y + height > image_height
                ):
                    raise ValueError(
                        f"Invalid {location}: bbox {bbox!r} is outside "
                        f"{image_width}x{image_height} image bounds"
                    )

            validated_record = dict(record)
            validated_record["_source_image_path"] = str(image_path)
            validated_record["_source_sha256"] = source_digest
            validated_record["_source_dimensions"] = [
                actual_width,
                actual_height,
            ]
            validated_record["_yolo_label_lines"] = [
                (
                    f"{category_ids[annotation['category']]} "
                    f"{(annotation['bbox'][0] + annotation['bbox'][2] / 2) / image_width} "
                    f"{(annotation['bbox'][1] + annotation['bbox'][3] / 2) / image_height} "
                    f"{annotation['bbox'][2] / image_width} "
                    f"{annotation['bbox'][3] / image_height}"
                )
                for annotation in annotations
            ]
            records.append(validated_record)

        return records, list(categories)

    @staticmethod
    def _sha256_stream(file_object) -> str:
        """Hash the current stream to EOF without retaining its contents."""
        digest = hashlib.sha256()
        while True:
            chunk = file_object.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)

    @classmethod
    def _sha256_path(cls, path) -> str:
        with Path(path).open("rb") as file:
            return cls._sha256_stream(file)

    @staticmethod
    def _yolo_domain(annotation: Dict) -> str:
        """Classify a validated record by its image aspect ratio."""
        ratio = annotation["image_width"] / annotation["image_height"]
        if ratio < 0.8:
            return "portrait"
        if ratio > 1.25:
            return "landscape"
        return "square"

    def _split_yolo_dataset(
        self,
        records: List[Dict],
        ratios: Tuple[float, float, float],
        seed: int = 0,
    ):
        """Deterministically split records after aspect-domain stratification."""
        try:
            ratio_values = tuple(ratios)
        except TypeError as exc:
            raise ValueError("YOLO split ratios must contain exactly three numbers") from exc
        if len(ratio_values) != 3:
            raise ValueError("YOLO split ratios must contain exactly three numbers")
        if any(
            not isinstance(value, Real)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
            for value in ratio_values
        ):
            raise ValueError("YOLO split ratios must be finite non-negative numbers")
        if not math.isclose(sum(ratio_values), 1.0):
            raise ValueError("YOLO split ratios must sum to 1")

        canonical_records = sorted(records, key=lambda record: record["image_filename"])
        grouped = {}
        for record in canonical_records:
            grouped.setdefault(self._yolo_domain(record), []).append(record)

        domain_keys = sorted(grouped)
        splits = {"train": [], "val": [], "test": []}
        domain_counts = {
            split: {domain: 0 for domain in domain_keys}
            for split in ("train", "val", "test")
        }
        rng = random.Random(seed)

        for domain in domain_keys:
            domain_records = list(grouped[domain])
            rng.shuffle(domain_records)
            train_count = math.floor(len(domain_records) * ratio_values[0])
            val_count = math.floor(len(domain_records) * ratio_values[1])
            boundaries = (train_count, train_count + val_count)
            domain_splits = {
                "train": domain_records[:boundaries[0]],
                "val": domain_records[boundaries[0]:boundaries[1]],
                "test": domain_records[boundaries[1]:],
            }
            for split, split_records in domain_splits.items():
                splits[split].extend(split_records)
                domain_counts[split][domain] = len(split_records)

        for split_records in splits.values():
            split_records.sort(key=lambda record: record["image_filename"])

        return splits, domain_counts

    @staticmethod
    def _ensure_empty_yolo_target(root, *, must_exist=False):
        root = Path(root)
        if root.exists():
            if not root.is_dir():
                raise ValueError(f"YOLO target is not a directory: {root}")
            if any(root.iterdir()):
                raise ValueError(f"YOLO target must be empty: {root}")
        elif must_exist:
            raise ValueError(f"YOLO staging directory does not exist: {root}")

    def _write_yolo_tree(self, root, yaml_root, splits, categories):
        """Write one exact YOLO image/label tree into an empty target."""
        root = Path(root)
        self._ensure_empty_yolo_target(root)
        root.mkdir(parents=True, exist_ok=True)
        if set(splits) != {"train", "val", "test"}:
            raise ValueError("YOLO splits must contain train, val, and test")

        for split in ("train", "val", "test"):
            images_path = root / "images" / split
            labels_path = root / "labels" / split
            images_path.mkdir(parents=True)
            labels_path.mkdir(parents=True)
            for record in splits[split]:
                image_filename = record["image_filename"]
                destination = images_path / image_filename
                shutil.copy2(record["_source_image_path"], destination)
                destination_digest = self._sha256_path(destination)
                if destination_digest != record["_source_sha256"]:
                    raise ValueError(
                        f"Source image {image_filename} changed after validation; "
                        "copied SHA-256 does not match the validated source"
                    )
                label_path = labels_path / f"{os.path.splitext(image_filename)[0]}.txt"
                label_lines = record["_yolo_label_lines"]
                label_content = "".join(f"{line}\n" for line in label_lines)
                label_path.write_text(label_content, encoding="utf-8")

        data_yaml = {
            "path": os.fspath(yaml_root),
            "train": "images/train",
            "val": "images/val",
            "test": "images/test",
            "names": {index: category for index, category in enumerate(categories)},
            "nc": len(categories),
        }
        import yaml

        with (root / "data.yaml").open("w", encoding="utf-8") as file:
            yaml.safe_dump(data_yaml, file, allow_unicode=True, sort_keys=False)

    def _export_yolo(
        self,
        project_id: str,
        export_path: str,
        split_ratios: Tuple[float, float, float],
        augmentation: bool,
        *,
        training_data_path=None,
        training_yaml_root=None,
        seed=0,
    ):
        """Export YOLO data and optionally mirror it into an empty staging tree."""
        del augmentation  # Augmentation is intentionally out of scope for YOLO export.

        self._ensure_empty_yolo_target(export_path)
        if training_data_path is None:
            if training_yaml_root is not None:
                raise ValueError("training_yaml_root requires training_data_path")
        else:
            try:
                yaml_root_value = os.fspath(training_yaml_root)
            except TypeError as exc:
                raise ValueError(
                    "training_yaml_root must be a non-empty path string"
                ) from exc
            if not isinstance(yaml_root_value, str) or not yaml_root_value.strip():
                raise ValueError("training_yaml_root is required for YOLO training export")
            self._ensure_empty_yolo_target(training_data_path, must_exist=True)
            if Path(training_data_path).resolve() == Path(export_path).resolve():
                raise ValueError("Download and training YOLO targets must be different")

        records, categories = self._load_validated_yolo_source(project_id)
        splits, domain_counts = self._split_yolo_dataset(
            records, split_ratios, seed=seed
        )

        self._write_yolo_tree(export_path, export_path, splits, categories)
        if training_data_path is not None:
            self._write_yolo_tree(
                training_data_path,
                training_yaml_root,
                splits,
                categories,
            )

        return {
            "source_count": len(records),
            "source_filenames": sorted(
                record["image_filename"] for record in records
            ),
            "split_counts": {
                split: len(split_records)
                for split, split_records in splits.items()
            },
            "domain_counts": domain_counts,
            "categories": list(categories),
            "_source_manifest": [
                {
                    "filename": record["image_filename"],
                    "sha256": record["_source_sha256"],
                    "dimensions": list(record["_source_dimensions"]),
                    "label_lines": list(record["_yolo_label_lines"]),
                }
                for record in sorted(
                    records, key=lambda item: item["image_filename"]
                )
            ],
        }
    
    def _export_florence2(self, project_id: str, export_path: str,
                         split_ratios: Tuple[float, float, float],
                         augmentation: bool):
        """导出Florence-2格式（CAPTION任务：裁剪图标用于captioning训练）"""
        from backend.annotation_manager import AnnotationManager
        from backend.project_manager import ProjectManager
        from PIL import Image
        
        ann_mgr = AnnotationManager(self.projects_dir)
        proj_mgr = ProjectManager(self.projects_dir)
        
        # 同时在models目录下创建训练数据（供训练使用）
        models_dir = os.path.join(os.path.dirname(self.projects_dir), 'models')
        training_data_path = os.path.join(models_dir, project_id, 'florence2_data')
        os.makedirs(training_data_path, exist_ok=True)
        os.makedirs(os.path.join(training_data_path, 'images'), exist_ok=True)
        
        # 获取所有标注
        all_annotations = ann_mgr.get_all_annotations(project_id)
        
        # Florence-2 CAPTION任务：每个标注框是独立样本
        # 先展开所有标注框，然后按框级别划分（而不是按图片级别）
        all_boxes = []
        for ann_data in all_annotations:
            for ann in ann_data['annotations']:
                all_boxes.append({
                    'image_filename': ann_data['image_filename'],
                    'bbox': ann['bbox'],
                    'category': ann['category']
                })
        
        print(f"[导出] 总标注框数: {len(all_boxes)}")
        
        # 按标注框级别划分数据集
        import random
        random.shuffle(all_boxes)
        total = len(all_boxes)
        train_end = int(total * split_ratios[0])
        val_end = train_end + int(total * split_ratios[1])
        
        splits = {
            'train': all_boxes[:train_end],
            'val': all_boxes[train_end:val_end],
            'test': all_boxes[val_end:]
        }
        
        print(f"[导出] 数据划分: train={len(splits['train'])}, val={len(splits['val'])}, test={len(splits['test'])}")
        
        # 创建images目录
        images_dir = os.path.join(export_path, 'images')
        os.makedirs(images_dir, exist_ok=True)
        
        # 处理每个split（现在是标注框级别的split）
        icon_index = 0  # 用于生成唯一的裁剪图标文件名
        
        for split_name, split_boxes in splits.items():
            if not split_boxes:
                continue
            
            # 导出路径（用于下载）
            jsonl_path = os.path.join(export_path, f"{split_name}.jsonl")
            # 训练路径（用于训练）
            training_jsonl_path = os.path.join(training_data_path, f"{split_name}.jsonl")
            
            with open(jsonl_path, 'w', encoding='utf-8') as f_export, \
                 open(training_jsonl_path, 'w', encoding='utf-8') as f_train:
                
                # 遍历每个标注框
                for box_data in split_boxes:
                    # 加载原始图片
                    src_image_path = os.path.join(
                        self.projects_dir, project_id, "images",
                        box_data['image_filename']
                    )
                    
                    try:
                        original_image = Image.open(src_image_path)
                    except Exception as e:
                        print(f"错误：无法加载图片 {src_image_path}: {e}")
                        continue
                    
                    # 裁剪图标区域
                    bbox = box_data['bbox']  # [x, y, w, h]
                    category = box_data['category']
                    
                    x, y, w, h = bbox
                    try:
                        cropped_icon = original_image.crop((x, y, x + w, y + h))
                    except Exception as e:
                        print(f"错误：无法裁剪图标 {bbox}: {e}")
                        continue
                    
                    # 生成裁剪图标的文件名
                    base_name = os.path.splitext(box_data['image_filename'])[0]
                    icon_filename = f"{base_name}_icon_{icon_index}.jpg"
                    icon_index += 1
                    
                    # 保存裁剪图标到导出目录
                    icon_export_path = os.path.join(images_dir, icon_filename)
                    cropped_icon.save(icon_export_path, 'JPEG', quality=95)
                    
                    # 保存裁剪图标到训练目录
                    icon_training_path = os.path.join(
                        training_data_path, 'images', icon_filename
                    )
                    cropped_icon.save(icon_training_path, 'JPEG', quality=95)
                    
                    # 构建Florence-2 CAPTION格式的数据
                    # 使用<CAPTION>任务，suffix只包含类别名称（描述）
                    florence_item = {
                        "image": f"images/{icon_filename}",
                        "prefix": "<CAPTION>",
                        "suffix": category
                    }
                    
                    # 同时写入导出文件和训练文件
                    line = json.dumps(florence_item, ensure_ascii=False) + '\n'
                    f_export.write(line)
                    f_train.write(line)
        
        # 创建README
        readme_content = """# Florence-2 训练数据集（CAPTION任务）

## 文件说明
- train.jsonl: 训练集
- val.jsonl: 验证集  
- test.jsonl: 测试集
- images/: 裁剪后的图标图片目录

## 数据格式说明

本数据集用于Florence-2的图像描述（CAPTION）任务，与OmniParser的使用方式一致。

### 数据流程
1. 从原始截图中裁剪出标注的图标区域
2. 每个图标作为独立的训练样本
3. 训练Florence-2学习图标的语义含义

### JSONL格式
每行为一个JSON对象：
```json
{
  "image": "images/icon_001.jpg",  // 裁剪后的图标图片
  "prefix": "<CAPTION>",            // 使用CAPTION任务
  "suffix": "vla浏览器"             // 图标的描述/类别名称
}
```

### 与OmniParser的对应关系
```
OmniParser工作流程：
1. YOLO检测图标位置 → bounding box
2. 裁剪图标区域 → 小图标图片
3. Florence-2 CAPTION → 图标语义描述

训练数据：
- 输入：裁剪后的图标图片（对应步骤2的输出）
- 输出：图标的语义描述（对应步骤3的输出）
```

## 使用方法
在训练页面选择Florence-2模型，系统会自动使用此数据集进行微调训练。
"""
        with open(os.path.join(export_path, 'README.md'), 'w', encoding='utf-8') as f:
            f.write(readme_content)
    
    def _export_voc(self, project_id: str, export_path: str,
                   split_ratios: Tuple[float, float, float],
                   augmentation: bool):
        """导出Pascal VOC格式"""
        from backend.annotation_manager import AnnotationManager
        
        ann_mgr = AnnotationManager(self.projects_dir)
        all_annotations = ann_mgr.get_all_annotations(project_id)
        splits = self._split_dataset(all_annotations, split_ratios)
        
        # 创建VOC目录结构
        annotations_dir = os.path.join(export_path, 'Annotations')
        images_dir = os.path.join(export_path, 'JPEGImages')
        imagesets_dir = os.path.join(export_path, 'ImageSets', 'Main')
        
        os.makedirs(annotations_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(imagesets_dir, exist_ok=True)
        
        # 处理每个split
        for split_name, split_annotations in splits.items():
            split_files = []
            
            for annotation_data in split_annotations:
                image_id = annotation_data['image_id']
                split_files.append(image_id)
                
                # 复制图片
                src_image_path = os.path.join(
                    self.projects_dir, project_id, "images",
                    annotation_data['image_filename']
                )
                dst_image_path = os.path.join(images_dir, annotation_data['image_filename'])
                shutil.copy(src_image_path, dst_image_path)
                
                # 创建XML标注
                xml_content = self._create_voc_xml(annotation_data)
                xml_path = os.path.join(annotations_dir, f"{image_id}.xml")
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
            
            # 保存split文件列表
            split_file_path = os.path.join(imagesets_dir, f"{split_name}.txt")
            with open(split_file_path, 'w') as f:
                f.write('\n'.join(split_files))
    
    def _create_voc_xml(self, annotation_data: Dict) -> str:
        """创建VOC XML格式"""
        root = Element('annotation')
        
        SubElement(root, 'folder').text = 'JPEGImages'
        SubElement(root, 'filename').text = annotation_data['image_filename']
        
        size = SubElement(root, 'size')
        SubElement(size, 'width').text = str(annotation_data['image_width'])
        SubElement(size, 'height').text = str(annotation_data['image_height'])
        SubElement(size, 'depth').text = '3'
        
        for ann in annotation_data['annotations']:
            obj = SubElement(root, 'object')
            SubElement(obj, 'name').text = ann['category']
            SubElement(obj, 'pose').text = 'Unspecified'
            SubElement(obj, 'truncated').text = '0'
            SubElement(obj, 'difficult').text = '0'
            
            bbox = ann['bbox']
            bndbox = SubElement(obj, 'bndbox')
            SubElement(bndbox, 'xmin').text = str(int(bbox[0]))
            SubElement(bndbox, 'ymin').text = str(int(bbox[1]))
            SubElement(bndbox, 'xmax').text = str(int(bbox[0] + bbox[2]))
            SubElement(bndbox, 'ymax').text = str(int(bbox[1] + bbox[3]))
        
        # 格式化XML
        rough_string = tostring(root, encoding='utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    
    def _export_csv(self, project_id: str, export_path: str,
                   split_ratios: Tuple[float, float, float],
                   augmentation: bool):
        """导出CSV格式"""
        from backend.annotation_manager import AnnotationManager
        
        ann_mgr = AnnotationManager(self.projects_dir)
        all_annotations = ann_mgr.get_all_annotations(project_id)
        
        import csv
        csv_path = os.path.join(export_path, 'annotations.csv')
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'image_filename', 'width', 'height',
                'category', 'x', 'y', 'width', 'height'
            ])
            
            for annotation_data in all_annotations:
                for ann in annotation_data['annotations']:
                    bbox = ann['bbox']
                    writer.writerow([
                        annotation_data['image_filename'],
                        annotation_data['image_width'],
                        annotation_data['image_height'],
                        ann['category'],
                        bbox[0], bbox[1], bbox[2], bbox[3]
                    ])
    
    def _export_florence2_cropped(self, project_id: str, export_path: str,
                                 split_ratios: Tuple[float, float, float],
                                 augmentation: bool):
        """导出Florence-2格式（使用裁切的图标）"""
        from backend.crop_manager import CropManager
        
        crop_mgr = CropManager(self.projects_dir)
        
        # 准备Florence-2数据集
        try:
            dataset_path = crop_mgr.prepare_florence2_dataset(project_id)
            
            # 复制到导出目录
            import shutil
            for item in os.listdir(dataset_path):
                src = os.path.join(dataset_path, item)
                dst = os.path.join(export_path, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy(src, dst)
            
            # 创建说明文件
            readme = """# Florence-2 图标训练数据集（裁切版）

本数据集使用从大图中裁切的图标区域。

## 优势
- 每个图标独立成图
- 适合图标识别任务
- 可直接用于Florence-2微调

## 与原图版本的区别
- 原图版本：保留完整UI截图，标注位置
- 裁切版本：仅包含图标本身

## 使用场景
裁切版本更适合：
- 纯图标识别
- 图标分类
- 小样本学习

原图版本更适合：
- UI元素检测
- 布局理解
- 上下文相关任务
"""
            with open(os.path.join(export_path, 'README_CROPPED.md'), 'w', encoding='utf-8') as f:
                f.write(readme)
                
        except FileNotFoundError as e:
            # 如果没有裁切数据，提示用户
            with open(os.path.join(export_path, 'ERROR.txt'), 'w', encoding='utf-8') as f:
                f.write(f"""错误: 没有找到裁切数据

请先在标注页面执行以下操作之一：
1. 点击"裁切当前图片"按钮
2. 点击"批量裁切所有已标注图片"按钮

然后再进行导出。

详细错误: {str(e)}
""")
    
    def _create_zip(self, source_dir: str, zip_path: str):
        """创建ZIP压缩包"""
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                dirs.sort()
                files.sort()
                for directory in dirs:
                    directory_path = os.path.join(root, directory)
                    arcname = os.path.relpath(directory_path, source_dir)
                    zipf.writestr(f"{arcname.rstrip('/')}/", b"")
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, source_dir)
                    zipf.write(file_path, arcname)
