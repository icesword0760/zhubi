"""
模型验证模块
用于验证和对比训练前后的模型效果
"""

import os
import json
import base64
from io import BytesIO
from typing import Dict, List, Tuple
from PIL import Image, ImageDraw, ImageFont


class ModelValidator:
    """模型验证器"""
    
    def __init__(self, models_dir: str, config: Dict):
        self.models_dir = models_dir
        self.config = config
    
    def validate_yolo(self, model_path: str, image_path: str, conf_threshold: float = 0.25) -> Dict:
        """验证YOLO模型"""
        try:
            from ultralytics import YOLO
            from PIL import Image
            
            # 加载模型
            model = YOLO(model_path)
            
            # 运行推理
            results = model(image_path, conf=conf_threshold)
            
            # 解析结果
            detections = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    class_name = model.names[cls]
                    
                    detections.append({
                        'bbox': [float(x1), float(y1), float(x2), float(y2)],
                        'confidence': conf,
                        'class_id': cls,
                        'class_name': class_name
                    })
            
            # 生成可视化图片
            result_image = results[0].plot()  # 返回numpy数组
            result_pil = Image.fromarray(result_image)
            
            # 转换为base64
            buffered = BytesIO()
            result_pil.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            return {
                'success': True,
                'detections': detections,
                'visualization': f"data:image/png;base64,{img_str}",
                'count': len(detections)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def validate_florence2(self, model_path: str, image_path: str) -> Dict:
        """验证Florence-2模型"""
        try:
            from transformers import AutoModelForCausalLM, AutoProcessor
            from PIL import Image
            import torch
            
            # 加载模型和processor
            device = self._get_device()
            
            # 使用配置的processor路径（统一使用本地路径）
            processor_path = self.config.get('training', {}).get('processor_path',
                                                                  os.path.join(os.environ.get('OMNIPARSER_ROOT', '../OmniParser'), 'weights', 'icon_caption_florence'))
            print(f"[处理器加载] 从本地路径加载: {processor_path}")
            processor = AutoProcessor.from_pretrained(
                processor_path,
                trust_remote_code=True
            )
            print(f"✅ Processor 加载成功")
            
            # 检查是否是LoRA微调模型
            is_lora_model = os.path.exists(os.path.join(model_path, 'adapter_config.json'))
            print(f"是否为LoRA模型: {is_lora_model}")
            print(f"模型路径: {model_path}")
            
            if is_lora_model:
                # 加载LoRA微调模型
                from peft import PeftModel
                
                # 获取基础模型路径
                base_model_path = self.config.get('training', {}).get('base_model_path', 
                                                                      '../weights/icon_caption_florence')
                print(f"加载基础模型: {base_model_path}")
                
                # 加载基础模型
                if device == 'cpu' or device == 'mps':
                    base_model = AutoModelForCausalLM.from_pretrained(
                        base_model_path,
                        torch_dtype=torch.float32,
                        trust_remote_code=True,
                        attn_implementation="eager"  # 避免 SDPA 兼容性问题
                    )
                    if device == 'mps':
                        base_model = base_model.to(device)
                else:
                    base_model = AutoModelForCausalLM.from_pretrained(
                        base_model_path,
                        torch_dtype=torch.float16,
                        trust_remote_code=True,
                        attn_implementation="eager"  # 避免 SDPA 兼容性问题
                    ).to(device)
                
                # 加载LoRA适配器
                print(f"加载LoRA适配器: {model_path}")
                model = PeftModel.from_pretrained(base_model, model_path)
                print("✅ LoRA适配器加载成功")
            else:
                # 普通模型
                print(f"加载普通模型: {model_path}")
                if device == 'cpu' or device == 'mps':
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        torch_dtype=torch.float32,
                        trust_remote_code=True,
                        attn_implementation="eager"  # 避免 SDPA 兼容性问题
                    )
                    if device == 'mps':
                        model = model.to(device)
                else:
                    # CUDA使用float16
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        torch_dtype=torch.float16,
                        trust_remote_code=True,
                        attn_implementation="eager"  # 避免 SDPA 兼容性问题
                    ).to(device)
            
            # 加载图片
            image = Image.open(image_path).convert("RGB")
            
            # 先使用YOLO检测图标位置
            print("步骤1: 使用YOLO检测图标位置...")
            yolo_model_path = self.config.get('training', {}).get('yolo_model_path',
                                                                   os.path.join(os.environ.get('OMNIPARSER_ROOT', '../OmniParser'), 'weights', 'icon_detect', 'model.pt'))

            # 检查YOLO模型是否存在
            if not os.path.exists(yolo_model_path):
                yolo_model_path = os.path.join(
                    os.environ.get('OMNIPARSER_ROOT', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'OmniParser')),
                    'weights', 'icon_detect', 'model.pt'
                )
            
            results = []
            detected_boxes = []
            
            try:
                from ultralytics import YOLO
                yolo_model = YOLO(yolo_model_path)
                yolo_results = yolo_model(image, conf=0.1)
                
                if yolo_results and len(yolo_results) > 0:
                    boxes = yolo_results[0].boxes
                    if boxes is not None and len(boxes) > 0:
                        # 获取检测框的xyxy格式
                        for box in boxes:
                            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                            detected_boxes.append([int(x1), int(y1), int(x2), int(y2)])
                        
                        print(f"✅ 检测到 {len(detected_boxes)} 个图标")
                    else:
                        print("⚠️ YOLO未检测到任何图标")
                else:
                    print("⚠️ YOLO推理失败")
            except Exception as e:
                print(f"⚠️ YOLO检测失败: {e}")
                print("将对整张图片进行Florence-2推理")
                detected_boxes = [[0, 0, image.width, image.height]]
            
            # 如果没有检测到，使用整张图
            if not detected_boxes:
                detected_boxes = [[0, 0, image.width, image.height]]
            
            # 步骤2: 对每个检测到的图标进行Florence-2 captioning
            print(f"步骤2: 对 {len(detected_boxes)} 个图标进行语义识别...")
            
            import numpy as np
            image_np = np.array(image)
            
            for idx, bbox in enumerate(detected_boxes):
                x1, y1, x2, y2 = bbox
                
                # 裁剪图标区域
                try:
                    cropped_icon = image.crop((x1, y1, x2, y2))
                    print(f"  图标 {idx+1}: 位置=[{x1}, {y1}, {x2}, {y2}], 大小={cropped_icon.size}")
                except Exception as e:
                    print(f"  ⚠️ 裁剪失败: {e}")
                    continue
                
                # 使用Florence-2 CAPTION任务（与OmniParser一致）
                task_prompt = "<CAPTION>"
                inputs = processor(
                    text=task_prompt,
                    images=cropped_icon,
                    return_tensors="pt"
                    # 让processor自动resize为模型期望的尺寸
                ).to(device)
                
                # 生成
                with torch.no_grad():
                    generated_ids = model.generate(
                        input_ids=inputs["input_ids"],
                        pixel_values=inputs["pixel_values"],
                        max_new_tokens=20,  # 与OmniParser一致
                        num_beams=1,        # 与OmniParser一致
                        do_sample=False
                    )
                
                # 解码
                generated_text = processor.batch_decode(
                    generated_ids,
                    skip_special_tokens=True
                )[0].strip()
                
                print(f"  ✅ 识别结果: {generated_text}")
                
                # 保存结果
                results.append({
                    'bbox': bbox,
                    'label': generated_text,
                    'confidence': 1.0  # Florence-2没有置信度分数
                })
            
            # 构建兼容的返回格式
            parsed_result = {
                '<OD>': {
                    'bboxes': [r['bbox'] for r in results],
                    'labels': [r['label'] for r in results]
                }
            }
            
            # 为了日志显示，构建generated_text
            generated_text = f"检测到 {len(results)} 个图标\n"
            for i, r in enumerate(results, 1):
                generated_text += f"图标{i}: {r['label']} (位置: {r['bbox']})\n"
            
            # 调试输出
            print(f"\n=== Florence-2 模型验证调试信息 ===")
            print(f"模型路径: {model_path}")
            print(f"生成文本: {generated_text}")
            print(f"解析结果: {parsed_result}")
            
            # 提取检测结果
            detections = []
            if '<OD>' in parsed_result:
                od_result = parsed_result['<OD>']
                bboxes = od_result.get('bboxes', [])
                labels = od_result.get('labels', [])
                
                print(f"检测到 {len(bboxes)} 个对象")
                for i, (bbox, label) in enumerate(zip(bboxes, labels)):
                    print(f"  对象 {i+1}: {label} at {bbox}")
                    detections.append({
                        'bbox': bbox,
                        'label': label
                    })
            else:
                print("警告: 解析结果中没有<OD>键")
            
            # 生成可视化
            visualization = self._draw_florence2_results(image, detections)
            
            return {
                'success': True,
                'detections': detections,
                'visualization': visualization,
                'count': len(detections),
                'raw_output': generated_text,
                'parsed_result': str(parsed_result)
            }
            
        except Exception as e:
            import traceback
            return {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
    
    def compare_models(self, model_a_path: str, model_b_path: str, 
                      image_path: str, model_type: str) -> Dict:
        """对比两个模型的效果"""
        if model_type == 'yolo':
            result_a = self.validate_yolo(model_a_path, image_path)
            result_b = self.validate_yolo(model_b_path, image_path)
        else:  # florence2
            result_a = self.validate_florence2(model_a_path, image_path)
            result_b = self.validate_florence2(model_b_path, image_path)
        
        return {
            'model_a': result_a,
            'model_b': result_b,
            'comparison': {
                'count_diff': result_b.get('count', 0) - result_a.get('count', 0),
                'model_a_count': result_a.get('count', 0),
                'model_b_count': result_b.get('count', 0)
            }
        }
    
    def _draw_florence2_results(self, image: Image.Image, detections: List[Dict]) -> str:
        """绘制Florence-2检测结果"""
        from PIL import ImageDraw, ImageFont
        
        # 创建副本
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        
        # 尝试加载字体（加大字号以便查看）
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        except:
            try:
                # 尝试其他常见字体
                font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 20)
            except:
                font = ImageFont.load_default()
        
        # 绘制检测框
        colors = ['red', 'blue', 'green', 'yellow', 'purple', 'orange', 'pink', 'cyan']
        for i, det in enumerate(detections):
            bbox = det['bbox']
            label = det.get('label', 'unknown')
            color = colors[i % len(colors)]
            
            # 绘制边界框（加粗）
            draw.rectangle(bbox, outline=color, width=3)
            
            # 绘制标签背景（扩大一些以便阅读）
            text_bbox = draw.textbbox((bbox[0], bbox[1] - 25), label, font=font)
            # 添加padding
            text_bbox = (text_bbox[0] - 5, text_bbox[1] - 2, text_bbox[2] + 5, text_bbox[3] + 2)
            draw.rectangle(text_bbox, fill=color)
            
            # 绘制标签文字（加大字号）
            draw.text((bbox[0], bbox[1] - 25), label, fill='white', font=font)
            
            print(f"绘制标签: '{label}' at position {bbox}")
        
        # 转换为base64
        buffered = BytesIO()
        img_copy.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    
    def _get_device(self) -> str:
        """获取推理设备"""
        import torch
        
        if torch.cuda.is_available():
            return 'cuda'
        elif torch.backends.mps.is_available():
            return 'mps'
        else:
            return 'cpu'
    
    def batch_validate(self, model_path: str, image_paths: List[str], 
                      model_type: str) -> List[Dict]:
        """批量验证"""
        results = []
        
        for image_path in image_paths:
            if model_type == 'yolo':
                result = self.validate_yolo(model_path, image_path)
            else:
                result = self.validate_florence2(model_path, image_path)
            
            result['image_path'] = image_path
            results.append(result)
        
        return results
    
    def calculate_metrics(self, predictions: List[Dict], ground_truth: List[Dict]) -> Dict:
        """计算评估指标（IoU, mAP等）"""
        # TODO: 实现详细的评估指标计算
        # 这里简化实现，只计算基本统计
        
        total_pred = sum(len(p.get('detections', [])) for p in predictions)
        total_gt = sum(len(g.get('detections', [])) for g in ground_truth)
        
        return {
            'total_predictions': total_pred,
            'total_ground_truth': total_gt,
            'avg_pred_per_image': total_pred / len(predictions) if predictions else 0,
            'avg_gt_per_image': total_gt / len(ground_truth) if ground_truth else 0
        }

