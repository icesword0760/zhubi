"""
标注管理模块
管理图像标注的保存、读取、更新等操作
"""

import os
import json
import math
from datetime import datetime
from numbers import Real
from typing import Dict, List, Optional
from PIL import Image
from backend.project_manager import shared_project_lock


class AnnotationManager:
    """标注管理器"""
    
    def __init__(self, projects_dir: str):
        self.projects_dir = projects_dir
    
    def save_annotation(self, project_id: str, image_id: str, 
                       annotations: List[Dict]) -> Dict:
        """保存标注数据"""
        project_path = os.path.join(self.projects_dir, project_id)
        with shared_project_lock(project_path):
            return self._save_annotation_locked(project_path, image_id, annotations)

    def _save_annotation_locked(self, project_path: str, image_id: str,
                                annotations: List[Dict]) -> Dict:
        annotations_path = os.path.join(project_path, "annotations")
        images_path = os.path.join(project_path, "images")
        
        os.makedirs(annotations_path, exist_ok=True)
        
        # 获取图片信息
        image_files = [f for f in os.listdir(images_path) 
                      if os.path.splitext(f)[0] == image_id
                      and f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp'))]
        
        if not image_files:
            raise ValueError(f"图片不存在: {image_id}")
        
        image_file = image_files[0]
        image_path = os.path.join(images_path, image_file)
        
        # 获取图片尺寸
        with Image.open(image_path) as img:
            width, height = img.size

        self._validate_annotation_bounds(annotations, width, height)
        
        # 构建标注数据
        annotation_data = {
            "image_id": image_id,
            "image_filename": image_file,
            "image_width": width,
            "image_height": height,
            "annotations": annotations,
            "annotated_at": datetime.now().isoformat(),
            "version": 1
        }
        
        # 保存标注文件
        annotation_file = os.path.join(annotations_path, f"{image_id}.json")
        with open(annotation_file, 'w', encoding='utf-8') as f:
            json.dump(annotation_data, f, indent=2, ensure_ascii=False)
        
        return annotation_data

    @staticmethod
    def _validate_annotation_bounds(annotations, image_width: int,
                                    image_height: int) -> None:
        """Reject malformed boxes before they can corrupt persisted annotations."""
        if not isinstance(annotations, list):
            raise ValueError("annotations must be a list")

        for index, annotation in enumerate(annotations):
            location = f"annotation {index}"
            if not isinstance(annotation, dict):
                raise ValueError(f"{location}: annotation must be an object")
            bbox = annotation.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ValueError(f"{location}: bbox must contain exactly 4 values")
            if any(
                not isinstance(value, Real)
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in bbox
            ):
                raise ValueError(f"{location}: bbox values must be finite numbers")

            x, y, width, height = bbox
            if width <= 0 or height <= 0:
                raise ValueError(f"{location}: bbox width and height must be positive")
            if (
                x < 0
                or y < 0
                or x + width > image_width
                or y + height > image_height
            ):
                raise ValueError(
                    f"{location}: bbox {bbox!r} is outside "
                    f"{image_width}x{image_height} image bounds"
                )
    
    def get_annotation(self, project_id: str, image_id: str) -> Optional[Dict]:
        """获取标注数据"""
        project_path = os.path.join(self.projects_dir, project_id)
        with shared_project_lock(project_path):
            return self._get_annotation_locked(project_path, image_id)

    def _get_annotation_locked(self, project_path: str, image_id: str) -> Optional[Dict]:
        annotation_file = os.path.join(project_path, "annotations", f"{image_id}.json")
        
        if not os.path.exists(annotation_file):
            return None
        
        with open(annotation_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def delete_annotation(self, project_id: str, image_id: str) -> bool:
        """删除标注数据"""
        project_path = os.path.join(self.projects_dir, project_id)
        with shared_project_lock(project_path):
            return self._delete_annotation_locked(project_path, image_id)

    def _delete_annotation_locked(self, project_path: str, image_id: str) -> bool:
        annotation_file = os.path.join(project_path, "annotations", f"{image_id}.json")
        
        if not os.path.exists(annotation_file):
            return False
        
        try:
            os.remove(annotation_file)
            return True
        except Exception as e:
            print(f"删除标注失败: {e}")
            return False
    
    def get_all_annotations(self, project_id: str) -> List[Dict]:
        """获取项目所有标注数据"""
        project_path = os.path.join(self.projects_dir, project_id)
        with shared_project_lock(project_path):
            return self._get_all_annotations_locked(project_path)

    def _get_all_annotations_locked(self, project_path: str) -> List[Dict]:
        annotations_path = os.path.join(project_path, "annotations")
        
        if not os.path.exists(annotations_path):
            return []
        
        all_annotations = []
        for filename in os.listdir(annotations_path):
            if filename.endswith('.json'):
                annotation_file = os.path.join(annotations_path, filename)
                try:
                    with open(annotation_file, 'r', encoding='utf-8') as f:
                        annotation_data = json.load(f)
                    all_annotations.append(annotation_data)
                except Exception as e:
                    print(f"读取标注文件失败: {filename}, 错误: {e}")
        
        return all_annotations
    
    def get_annotation_stats(self, project_id: str) -> Dict:
        """获取标注统计信息"""
        annotations = self.get_all_annotations(project_id)
        
        # 统计每个类别的数量
        category_counts = {}
        total_boxes = 0
        
        for annotation in annotations:
            for ann in annotation.get('annotations', []):
                category = ann.get('category', 'unknown')
                category_counts[category] = category_counts.get(category, 0) + 1
                total_boxes += 1
        
        return {
            "total_images": len(annotations),
            "total_boxes": total_boxes,
            "category_counts": category_counts,
            "avg_boxes_per_image": total_boxes / len(annotations) if annotations else 0
        }
    
    def validate_annotations(self, project_id: str) -> Dict:
        """验证标注数据质量"""
        annotations = self.get_all_annotations(project_id)
        
        issues = {
            "missing_category": [],
            "invalid_bbox": [],
            "small_bbox": [],
            "large_bbox": []
        }
        
        for annotation in annotations:
            image_id = annotation['image_id']
            width = annotation['image_width']
            height = annotation['image_height']
            
            for idx, ann in enumerate(annotation.get('annotations', [])):
                # 检查类别
                if not ann.get('category'):
                    issues['missing_category'].append({
                        "image_id": image_id,
                        "bbox_index": idx
                    })
                
                # 检查bbox有效性
                bbox = ann.get('bbox', [])
                if len(bbox) != 4:
                    issues['invalid_bbox'].append({
                        "image_id": image_id,
                        "bbox_index": idx,
                        "reason": "bbox length != 4"
                    })
                    continue
                
                x, y, w, h = bbox
                
                # 检查边界
                if x < 0 or y < 0 or x + w > width or y + h > height:
                    issues['invalid_bbox'].append({
                        "image_id": image_id,
                        "bbox_index": idx,
                        "reason": "bbox out of bounds"
                    })
                
                # 检查尺寸
                if w < 10 or h < 10:
                    issues['small_bbox'].append({
                        "image_id": image_id,
                        "bbox_index": idx,
                        "size": f"{w}x{h}"
                    })
                
                if w > width * 0.9 or h > height * 0.9:
                    issues['large_bbox'].append({
                        "image_id": image_id,
                        "bbox_index": idx,
                        "size": f"{w}x{h}"
                    })
        
        return {
            "total_issues": sum(len(v) for v in issues.values()),
            "issues": issues
        }
