"""
裁切管理模块
从大图中裁切标注区域，同时准备Florence-2和YOLO格式数据
"""

import os
import json
import shutil
from datetime import datetime
from PIL import Image
from typing import Dict, List


class CropManager:
    """裁切管理器"""
    
    def __init__(self, projects_dir: str):
        self.projects_dir = projects_dir
    
    def crop_and_save(self, project_id: str, image_id: str, image_filename: str,
                     image_width: int, image_height: int, bboxes: List[Dict]) -> Dict:
        """
        裁切单张图片的所有标注区域
        
        同时准备：
        1. 裁切的小图（用于Florence-2训练）
        2. 原图+YOLO格式标注（用于YOLO训练）
        """
        project_path = os.path.join(self.projects_dir, project_id)
        images_path = os.path.join(project_path, "images")
        
        # 创建输出目录
        crops_dir = os.path.join(project_path, "cropped_icons")
        florence_dir = os.path.join(crops_dir, "florence2_crops")
        yolo_dir = os.path.join(crops_dir, "yolo_format")
        
        os.makedirs(florence_dir, exist_ok=True)
        os.makedirs(os.path.join(yolo_dir, "images"), exist_ok=True)
        os.makedirs(os.path.join(yolo_dir, "labels"), exist_ok=True)
        
        # 加载原图
        image_path = os.path.join(images_path, image_filename)
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_filename}")
        
        original_image = Image.open(image_path).convert('RGB')
        
        # 1. 裁切小图（Florence-2格式）
        cropped_count = 0
        crop_metadata = []
        
        for idx, bbox_data in enumerate(bboxes):
            bbox = bbox_data['bbox']
            category = bbox_data['category']
            bbox_id = bbox_data.get('id', f'bbox_{idx}')
            
            x, y, w, h = map(int, bbox)
            
            # 确保bbox在图像范围内
            x = max(0, min(x, image_width))
            y = max(0, min(y, image_height))
            w = min(w, image_width - x)
            h = min(h, image_height - y)
            
            if w <= 0 or h <= 0:
                continue
            
            # 裁切图像
            cropped = original_image.crop((x, y, x + w, y + h))
            
            # 保存裁切图像
            crop_filename = f"{image_id}_{bbox_id}_{category}.png"
            crop_path = os.path.join(florence_dir, crop_filename)
            cropped.save(crop_path)
            
            # 记录元数据
            crop_metadata.append({
                "crop_filename": crop_filename,
                "original_image": image_filename,
                "category": category,
                "bbox": bbox,
                "bbox_id": bbox_id,
                "size": f"{w}x{h}"
            })
            
            cropped_count += 1
        
        # 保存裁切元数据
        metadata_file = os.path.join(florence_dir, f"{image_id}_metadata.json")
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump({
                "original_image": image_filename,
                "image_size": [image_width, image_height],
                "cropped_at": datetime.now().isoformat(),
                "crops": crop_metadata
            }, f, indent=2, ensure_ascii=False)
        
        # 2. 保存YOLO格式
        # 复制原图
        yolo_image_path = os.path.join(yolo_dir, "images", image_filename)
        shutil.copy(image_path, yolo_image_path)
        
        # 创建YOLO标注文件
        label_filename = os.path.splitext(image_filename)[0] + '.txt'
        label_path = os.path.join(yolo_dir, "labels", label_filename)
        
        # 收集所有类别
        categories = list(set(bbox_data['category'] for bbox_data in bboxes))
        
        with open(label_path, 'w') as f:
            for bbox_data in bboxes:
                bbox = bbox_data['bbox']
                category = bbox_data['category']
                
                # 获取类别ID
                cat_id = categories.index(category)
                
                x, y, w, h = bbox
                
                # 转换为YOLO格式 (center_x, center_y, width, height) 归一化
                x_center = (x + w / 2) / image_width
                y_center = (y + h / 2) / image_height
                w_norm = w / image_width
                h_norm = h / image_height
                
                f.write(f"{cat_id} {x_center} {y_center} {w_norm} {h_norm}\n")
        
        # 保存YOLO类别配置
        yaml_path = os.path.join(yolo_dir, "data.yaml")
        if not os.path.exists(yaml_path):
            import yaml
            data_yaml = {
                'path': yolo_dir,
                'train': 'images',
                'val': 'images',
                'names': {idx: cat for idx, cat in enumerate(categories)},
                'nc': len(categories)
            }
            with open(yaml_path, 'w', encoding='utf-8') as f:
                yaml.dump(data_yaml, f, allow_unicode=True)
        
        return {
            "cropped_count": cropped_count,
            "save_path": crops_dir,
            "florence2_path": florence_dir,
            "yolo_path": yolo_dir,
            "metadata_file": metadata_file
        }
    
    def batch_crop_project(self, project_id: str) -> Dict:
        """批量裁切项目中所有已标注图片"""
        from backend.annotation_manager import AnnotationManager
        
        ann_mgr = AnnotationManager(self.projects_dir)
        
        # 获取所有标注
        all_annotations = ann_mgr.get_all_annotations(project_id)
        
        if not all_annotations:
            return {
                "processed_images": 0,
                "total_crops": 0,
                "message": "没有已标注的图片"
            }
        
        processed_images = 0
        total_crops = 0
        errors = []
        
        for annotation_data in all_annotations:
            try:
                result = self.crop_and_save(
                    project_id=project_id,
                    image_id=annotation_data['image_id'],
                    image_filename=annotation_data['image_filename'],
                    image_width=annotation_data['image_width'],
                    image_height=annotation_data['image_height'],
                    bboxes=annotation_data['annotations']
                )
                
                processed_images += 1
                total_crops += result['cropped_count']
                
            except Exception as e:
                errors.append({
                    "image": annotation_data['image_filename'],
                    "error": str(e)
                })
        
        return {
            "processed_images": processed_images,
            "total_crops": total_crops,
            "errors": errors
        }
    
    def prepare_florence2_dataset(self, project_id: str, output_path: str = None) -> str:
        """
        准备Florence-2训练数据集
        
        将裁切的图标整理为Florence-2训练格式
        """
        project_path = os.path.join(self.projects_dir, project_id)
        crops_dir = os.path.join(project_path, "cropped_icons", "florence2_crops")
        
        if not os.path.exists(crops_dir):
            raise FileNotFoundError("没有裁切数据，请先执行裁切操作")
        
        # 输出目录
        if output_path is None:
            output_path = os.path.join(project_path, "cropped_icons", "florence2_dataset")
        
        os.makedirs(output_path, exist_ok=True)
        images_dir = os.path.join(output_path, "images")
        os.makedirs(images_dir, exist_ok=True)
        
        # 收集所有裁切图像和元数据
        jsonl_data = []
        
        # 读取所有元数据文件
        for filename in os.listdir(crops_dir):
            if filename.endswith('_metadata.json'):
                metadata_path = os.path.join(crops_dir, filename)
                
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                for crop_info in metadata['crops']:
                    crop_filename = crop_info['crop_filename']
                    category = crop_info['category']
                    
                    # 复制图像到数据集目录
                    src = os.path.join(crops_dir, crop_filename)
                    dst = os.path.join(images_dir, crop_filename)
                    
                    if os.path.exists(src):
                        shutil.copy(src, dst)
                        
                        # 构建Florence-2格式（图像分类任务）
                        jsonl_data.append({
                            "image": f"images/{crop_filename}",
                            "prefix": "<CAPTION>",
                            "suffix": category
                        })
        
        # 保存为JSONL
        jsonl_path = os.path.join(output_path, "train.jsonl")
        with open(jsonl_path, 'w', encoding='utf-8') as f:
            for item in jsonl_data:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        
        # 创建README
        readme_content = f"""# Florence-2 图标识别训练数据集

## 数据说明
- 总图像数: {len(jsonl_data)}
- 数据来源: 从大图中裁切的图标区域
- 任务类型: 图像分类/Caption

## 文件结构
```
florence2_dataset/
├── images/          # 裁切的图标图像
├── train.jsonl      # 训练数据（Florence-2格式）
└── README.md        # 本文件
```

## 数据格式
每行为一个JSON对象：
```json
{{
  "image": "images/xxx.png",
  "prefix": "<CAPTION>",
  "suffix": "category_name"
}}
```

## 使用方法
1. 使用此数据集微调Florence-2模型
2. 训练后可识别图标类别
3. 结合OmniParser进行UI元素识别

生成时间: {datetime.now().isoformat()}
"""
        
        with open(os.path.join(output_path, 'README.md'), 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        return output_path

