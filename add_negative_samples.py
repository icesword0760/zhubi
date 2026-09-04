#!/usr/bin/env python3
"""
添加负样本到标注数据
策略：在现有3张图片中，标注2-3个其他常见图标（微信、QQ、支付宝等）作为负样本
"""

import os
import json
import shutil
from datetime import datetime

PROJECT_ID = "测试"
DATA_DIR = f"data/projects/{PROJECT_ID}"
ANNOTATIONS_DIR = os.path.join(DATA_DIR, "annotations")
BACKUP_DIR = os.path.join(DATA_DIR, f"annotations_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

# 定义负样本（根据YOLO检测结果，这些图标在验证图片中可见）
# 坐标格式: [x_min, y_min, x_max, y_max] (归一化坐标 0-1)
NEGATIVE_SAMPLES = {
    "1.jpg": [
        # 微信图标 (根据验证图片位置估算)
        {
            "bbox": [0.534, 0.682, 0.700, 0.781],
            "category": "微信"
        },
        # QQ图标
        {
            "bbox": [0.297, 0.682, 0.464, 0.783],
            "category": "QQ"
        }
    ],
    "1_.jpg": [
        # 支付宝图标 (如果在这张图中)
        {
            "bbox": [0.061, 0.453, 0.239, 0.552],
            "category": "支付宝"
        }
    ]
}

def add_negative_samples():
    """添加负样本到标注文件"""
    
    print("\n" + "="*70)
    print("添加负样本到训练数据".center(68))
    print("="*70 + "\n")
    
    # 备份原始标注
    if os.path.exists(ANNOTATIONS_DIR):
        print(f"📦 备份原始标注到: {BACKUP_DIR}")
        shutil.copytree(ANNOTATIONS_DIR, BACKUP_DIR)
    else:
        print(f"❌ 标注目录不存在: {ANNOTATIONS_DIR}")
        return False
    
    # 统计信息
    added_count = 0
    updated_files = []
    
    # 处理每个图片的负样本
    for image_name, negative_samples in NEGATIVE_SAMPLES.items():
        json_file = os.path.join(ANNOTATIONS_DIR, image_name.replace('.jpg', '.json'))
        
        if not os.path.exists(json_file):
            print(f"⚠️  标注文件不存在: {json_file}")
            continue
        
        # 读取现有标注
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        original_count = len(data.get('annotations', []))
        
        # 添加负样本
        if 'annotations' not in data:
            data['annotations'] = []
        
        for neg_sample in negative_samples:
            data['annotations'].append({
                'bbox': neg_sample['bbox'],
                'category': neg_sample['category']
            })
            added_count += 1
        
        # 保存更新后的标注
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        new_count = len(data['annotations'])
        updated_files.append(image_name)
        
        print(f"✅ {image_name}: {original_count} → {new_count} 个标注")
    
    print(f"\n📊 总结:")
    print(f"  - 更新文件数: {len(updated_files)}")
    print(f"  - 新增负样本: {added_count} 个")
    print(f"  - 备份位置: {BACKUP_DIR}")
    
    print(f"\n💡 下一步:")
    print(f"  1. 检查标注是否正确")
    print(f"  2. 使用新的训练数据重新训练")
    print(f"  3. 如果需要恢复，从备份目录复制回来")
    
    return True

def estimate_negative_sample_coordinates():
    """
    根据YOLO检测结果估算负样本的坐标
    这个函数可以帮助自动生成NEGATIVE_SAMPLES配置
    """
    import sys
    omniparser_root = os.environ.get('OMNIPARSER_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'OmniParser'))
    if omniparser_root not in sys.path:
        sys.path.append(omniparser_root)
    from util.utils import get_yolo_model
    from PIL import Image

    YOLO_MODEL = os.path.join(omniparser_root, "weights", "icon_detect", "model.pt")
    som_model = get_yolo_model(model_path=YOLO_MODEL)
    
    print("\n" + "="*70)
    print("自动检测负样本候选位置".center(68))
    print("="*70 + "\n")
    
    images_to_check = ["1.jpg", "1_.jpg", "20260119170925_67_441.jpg"]
    
    for img_name in images_to_check:
        img_path = os.path.join(DATA_DIR, "images", img_name)
        if not os.path.exists(img_path):
            continue
        
        image = Image.open(img_path)
        results = som_model(image, imgsz=640, conf=0.05, iou=0.1)
        
        boxes = results[0].boxes
        print(f"\n📷 {img_name}: 检测到 {len(boxes)} 个图标")
        
        # 读取现有标注（如果有）
        json_file = os.path.join(ANNOTATIONS_DIR, img_name.replace('.jpg', '.json'))
        existing_bboxes = []
        if os.path.exists(json_file):
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                existing_bboxes = [ann['bbox'] for ann in data.get('annotations', [])]
        
        print(f"   现有标注: {len(existing_bboxes)} 个")
        
        # 显示前5个未标注的框
        print(f"   推荐作为负样本的框（前5个）:")
        count = 0
        for i in range(len(boxes)):
            box = boxes.xyxyn[i]
            bbox = [float(box[0].item()), float(box[1].item()), float(box[2].item()), float(box[3].item())]
            
            # 检查是否已标注
            is_annotated = False
            for existing_bbox in existing_bboxes:
                # 简单的重叠检查
                if abs(bbox[0] - existing_bbox[0]) < 0.05 and abs(bbox[1] - existing_bbox[1]) < 0.05:
                    is_annotated = True
                    break
            
            if not is_annotated:
                print(f"     {count+1}. bbox: {bbox}")
                count += 1
                if count >= 5:
                    break

def auto_add_negative_samples(project_id, category_name="通用图标", confidence_threshold=0.3):
    """
    自动检测并添加负样本
    
    Args:
        project_id: 项目ID
        category_name: 负样本的类别名称
        confidence_threshold: 检测置信度阈值
        
    Returns:
        tuple: (success, message, stats)
    """
    import sys
    import os
    
    # OmniParser 仓库目录（提供 util/ 与 weights/）
    project_root = os.environ.get('OMNIPARSER_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'OmniParser'))
    if project_root not in sys.path:
        sys.path.append(project_root)
    
    try:
        from PIL import Image
        from ultralytics import YOLO
        from transformers import AutoModelForCausalLM, AutoProcessor
        import torch
        
        # 路径设置
        data_dir = f"data/projects/{project_id}"
        images_dir = os.path.join(data_dir, "images")
        annotations_dir = os.path.join(data_dir, "annotations")
        
        if not os.path.exists(images_dir) or not os.path.exists(annotations_dir):
            return False, "项目路径不存在", {}
        
        # 备份原始标注
        backup_dir = os.path.join(data_dir, f"annotations_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copytree(annotations_dir, backup_dir)
        
        # 加载YOLO模型
        yolo_model_path = "weights/icon_detect/model.pt"
        if not os.path.exists(yolo_model_path):
            return False, "YOLO模型不存在", {}
        yolo_model = YOLO(yolo_model_path)
        
        # 加载Florence-2基础模型
        florence_model_path = "weights/icon_caption_florence"
        if not os.path.exists(florence_model_path):
            return False, "Florence-2模型不存在", {}
        
        device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
        florence_model = AutoModelForCausalLM.from_pretrained(
            florence_model_path, trust_remote_code=True
        ).to(device)
        florence_processor = AutoProcessor.from_pretrained(
            florence_model_path, trust_remote_code=True
        )
        
        # 统计信息
        total_added = 0
        total_images = 0
        
        # 遍历所有图片
        for image_file in os.listdir(images_dir):
            if not image_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
                
            total_images += 1
            image_path = os.path.join(images_dir, image_file)
            annotation_file = os.path.join(annotations_dir, os.path.splitext(image_file)[0] + '.json')
            
            # 加载图片
            image = Image.open(image_path).convert('RGB')
            img_width, img_height = image.size
            
            # 加载现有标注
            if os.path.exists(annotation_file):
                with open(annotation_file, 'r', encoding='utf-8') as f:
                    annotation_data = json.load(f)
            else:
                annotation_data = {
                    'image_path': image_file,
                    'image_width': img_width,
                    'image_height': img_height,
                    'annotations': []
                }
            
            # 获取已标注的边界框
            existing_categories = set([ann['category'] for ann in annotation_data.get('annotations', [])])
            existing_bboxes = [ann['bbox'] for ann in annotation_data.get('annotations', [])]
            
            # 使用YOLO检测所有图标
            results = yolo_model(image, conf=confidence_threshold)
            
            if len(results) == 0 or len(results[0].boxes) == 0:
                continue
            
            # 处理检测结果
            boxes = results[0].boxes
            added_count = 0
            
            for i in range(len(boxes)):
                conf = float(boxes.conf[i].item())
                if conf < confidence_threshold:
                    continue
                
                # 获取边界框（YOLO返回的是tensor）
                box_xyxy = boxes.xyxy[i].tolist()
                
                # 检查是否与已标注的框重叠
                is_overlap = False
                for existing_bbox in existing_bboxes:
                    # 将现有bbox转换为xyxy格式进行比较
                    ex_x, ex_y, ex_w, ex_h = existing_bbox
                    ex_x2 = ex_x + ex_w
                    ex_y2 = ex_y + ex_h
                    
                    # 计算IoU
                    x_overlap = max(0, min(box_xyxy[2], ex_x2) - max(box_xyxy[0], ex_x))
                    y_overlap = max(0, min(box_xyxy[3], ex_y2) - max(box_xyxy[1], ex_y))
                    overlap_area = x_overlap * y_overlap
                    
                    if overlap_area > 0:
                        is_overlap = True
                        break
                
                if not is_overlap:
                    # 转换为xywh格式（像素坐标）
                    x = box_xyxy[0]
                    y = box_xyxy[1]
                    w = box_xyxy[2] - box_xyxy[0]
                    h = box_xyxy[3] - box_xyxy[1]
                    
                    # 添加负样本标注
                    new_annotation = {
                        'bbox': [x, y, w, h],
                        'category': category_name
                    }
                    annotation_data['annotations'].append(new_annotation)
                    added_count += 1
            
            # 保存更新后的标注
            if added_count > 0:
                with open(annotation_file, 'w', encoding='utf-8') as f:
                    json.dump(annotation_data, f, indent=2, ensure_ascii=False)
                total_added += added_count
        
        stats = {
            'total_images': total_images,
            'total_added': total_added,
            'backup_dir': backup_dir
        }
        
        message = f"成功添加 {total_added} 个负样本到 {total_images} 张图片。备份位置: {backup_dir}"
        return True, message, stats
        
    except Exception as e:
        import traceback
        error_msg = f"自动添加负样本失败: {str(e)}\n{traceback.format_exc()}"
        return False, error_msg, {}


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--estimate":
        estimate_negative_sample_coordinates()
    else:
        add_negative_samples()

