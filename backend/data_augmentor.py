"""
数据增强模块
对训练数据进行增强处理
"""

import os
import json
from PIL import Image, ImageEnhance, ImageFilter
from typing import List, Dict


class DataAugmentor:
    """数据增强器"""
    
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
    
    def augment_dataset(self, project_id: str, strategy: str = 'moderate', custom_categories: list = None, custom_methods: list = None) -> tuple[bool, str, int]:
        """增强数据集
        
        Args:
            project_id: 项目ID
            strategy: 增强策略 (light/moderate/aggressive/super/custom)
            custom_categories: 自定义策略的类别列表（仅当strategy='custom'时使用，向后兼容）
            custom_methods: 自定义策略的具体方法列表（细粒度控制，如['bright_1_2', 'contrast_high']）
            
        Returns:
            tuple: (成功标志, 消息, 增强后的样本数)
        """
        try:
            florence_data_dir = os.path.join(self.data_dir, project_id, 'florence2_data')
            images_dir = os.path.join(florence_data_dir, 'images')
            train_jsonl = os.path.join(florence_data_dir, 'train.jsonl')
            
            if not os.path.exists(train_jsonl):
                return False, "训练数据不存在，请先准备数据集", 0
            
            # 读取原始数据
            original_data = []
            with open(train_jsonl, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        original_data.append(json.loads(line))
            
            original_count = len(original_data)
            
            # 根据策略确定增强方法
            augmentations = self._get_augmentation_methods(strategy, custom_categories, custom_methods)
            
            # 执行增强
            augmented_data = list(original_data)  # 保留原始数据
            
            for item in original_data:
                img_path = os.path.join(florence_data_dir, item['image'])
                
                if not os.path.exists(img_path):
                    continue
                
                try:
                    image = Image.open(img_path)
                    base_name = os.path.splitext(os.path.basename(img_path))[0]
                    category = item['suffix']
                    
                    for aug_name, aug_func in augmentations:
                        aug_img = aug_func(image)
                        aug_filename = f"{base_name}_{aug_name}.jpg"
                        aug_path = os.path.join(images_dir, aug_filename)
                        
                        # 保存增强图片
                        aug_img.save(aug_path, 'JPEG', quality=95)
                        
                        # 添加到数据列表
                        augmented_data.append({
                            "image": f"images/{aug_filename}",
                            "prefix": item['prefix'],
                            "suffix": category
                        })
                    
                except Exception as e:
                    print(f"增强图片失败 {img_path}: {e}")
                    continue
            
            # 写入增强后的数据
            with open(train_jsonl, 'w', encoding='utf-8') as f:
                for item in augmented_data:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
            augmented_count = len(augmented_data)
            
            return True, f"数据增强完成：{original_count} → {augmented_count} 个样本", augmented_count
            
        except Exception as e:
            import traceback
            return False, f"数据增强失败: {str(e)}\n{traceback.format_exc()}", 0
    
    def _get_augmentation_methods(self, strategy: str, custom_categories: list = None, custom_methods: list = None) -> List[tuple]:
        """根据策略获取增强方法
        
        Args:
            strategy: 增强策略名称
            custom_categories: 自定义策略的类别列表（仅当strategy='custom'时使用，向后兼容）
            custom_methods: 自定义策略的具体方法列表（细粒度控制，优先级更高）
        
        Returns:
            List of (name, function) tuples
        """
        # Super增强的完整分类定义
        super_categories = {
            'brightness': [
                ("bright_1_2", lambda img: ImageEnhance.Brightness(img).enhance(1.2)),
                ("bright_1_4", lambda img: ImageEnhance.Brightness(img).enhance(1.4)),
                ("dark_0_6", lambda img: ImageEnhance.Brightness(img).enhance(0.6)),
                ("dark_0_8", lambda img: ImageEnhance.Brightness(img).enhance(0.8)),
                ("dark_mode", lambda img: ImageEnhance.Brightness(img).enhance(0.5)),
            ],
            'contrast': [
                ("contrast_high", lambda img: ImageEnhance.Contrast(img).enhance(1.5)),
                ("contrast_low", lambda img: ImageEnhance.Contrast(img).enhance(0.7)),
                ("contrast_very_high", lambda img: ImageEnhance.Contrast(img).enhance(1.8)),
                ("contrast_very_low", lambda img: ImageEnhance.Contrast(img).enhance(0.5)),
            ],
            'dpi': [
                ("dpi_0_5x", lambda img: self._scale_image(img, 0.5)),
                ("dpi_0_75x", lambda img: self._scale_image(img, 0.75)),
                ("dpi_1_25x", lambda img: self._scale_image(img, 1.25)),
                ("dpi_1_5x", lambda img: self._scale_image(img, 1.5)),
                ("dpi_2x", lambda img: self._scale_image(img, 2.0)),
                ("dpi_3x", lambda img: self._scale_image(img, 3.0)),
            ],
            'sharpness': [
                ("ultra_sharp", lambda img: ImageEnhance.Sharpness(img).enhance(2.5)),
                ("sharp", lambda img: ImageEnhance.Sharpness(img).enhance(1.8)),
                ("slight_blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=0.5))),
                ("blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=1.5))),
                ("motion_blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=2.0))),
            ],
            'edge': [
                ("edge_enhance", lambda img: img.filter(ImageFilter.EDGE_ENHANCE)),
                ("edge_enhance_more", lambda img: img.filter(ImageFilter.EDGE_ENHANCE_MORE)),
                ("find_edges", lambda img: self._apply_edge_detection(img)),
            ],
            'noise': [
                ("noise_light", lambda img: self._add_noise(img, 0.02)),
                ("noise_medium", lambda img: self._add_noise(img, 0.05)),
                ("compressed_60", lambda img: self._compress_image(img, 60)),
                ("compressed_40", lambda img: self._compress_image(img, 40)),
            ],
            'saturation': [
                ("saturated_high", lambda img: ImageEnhance.Color(img).enhance(1.4)),
                ("saturated_low", lambda img: ImageEnhance.Color(img).enhance(0.6)),
                ("saturated_very_high", lambda img: ImageEnhance.Color(img).enhance(1.6)),
                ("desaturated", lambda img: ImageEnhance.Color(img).enhance(0.4)),
            ],
            'rotation': [
                ("rotate_5", lambda img: self._rotate_small(img, 5)),
                ("rotate_minus5", lambda img: self._rotate_small(img, -5)),
                ("slight_zoom", lambda img: self._scale_image(img, 1.1)),
                ("slight_shrink", lambda img: self._scale_image(img, 0.9)),
            ]
        }
        
        # 创建所有方法的字典，方便查找
        all_methods_dict = {}
        for category, methods in super_categories.items():
            for method_name, method_func in methods:
                all_methods_dict[method_name] = method_func
        
        # 处理自定义策略 - 优先使用细粒度方法列表
        if strategy == 'custom':
            if custom_methods:
                # 细粒度控制：根据具体方法名筛选
                print(f"[数据增强] 使用细粒度自定义方法: {custom_methods}")
                selected_methods = []
                for method_name in custom_methods:
                    if method_name in all_methods_dict:
                        selected_methods.append((method_name, all_methods_dict[method_name]))
                    else:
                        print(f"[数据增强] 警告：未知方法 '{method_name}'")
                return selected_methods if selected_methods else super_categories['brightness'][:1]  # 至少返回一个方法
            elif custom_categories:
                # 类别级别控制（向后兼容）
                print(f"[数据增强] 使用类别级别自定义: {custom_categories}")
                category_methods = []
                for category in custom_categories:
                    if category in super_categories:
                        category_methods.extend(super_categories[category])
                return category_methods if category_methods else super_categories['brightness']  # 至少返回一个类别
        
        # 基础增强方法
        methods = {
            'light': [
                ("bright", lambda img: ImageEnhance.Brightness(img).enhance(1.3)),
                ("dark", lambda img: ImageEnhance.Brightness(img).enhance(0.7)),
                ("contrast", lambda img: ImageEnhance.Contrast(img).enhance(1.3)),
            ],
            'moderate': [
                ("bright", lambda img: ImageEnhance.Brightness(img).enhance(1.3)),
                ("dark", lambda img: ImageEnhance.Brightness(img).enhance(0.7)),
                ("contrast", lambda img: ImageEnhance.Contrast(img).enhance(1.4)),
                ("sharp", lambda img: ImageEnhance.Sharpness(img).enhance(2.0)),
                ("blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=1))),
                ("dpi_1_5x", lambda img: self._scale_image(img, 1.5)),
            ],
            'aggressive': [
                ("bright", lambda img: ImageEnhance.Brightness(img).enhance(1.3)),
                ("dark", lambda img: ImageEnhance.Brightness(img).enhance(0.7)),
                ("contrast_high", lambda img: ImageEnhance.Contrast(img).enhance(1.4)),
                ("contrast_low", lambda img: ImageEnhance.Contrast(img).enhance(0.7)),
                ("sharp", lambda img: ImageEnhance.Sharpness(img).enhance(2.0)),
                ("blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=1))),
                ("saturated", lambda img: ImageEnhance.Color(img).enhance(1.3)),
                ("desaturated", lambda img: ImageEnhance.Color(img).enhance(0.7)),
                ("dpi_2x", lambda img: self._scale_image(img, 2.0)),
                ("dpi_0_75x", lambda img: self._scale_image(img, 0.75)),
            ],
            # 移动端：DPI缩放(1x, 2x, 3x) + 屏幕方向 + 暗色模式 + 运动模糊
            'mobile': [
                ("dpi_2x", lambda img: self._scale_image(img, 2.0)),
                ("dpi_3x", lambda img: self._scale_image(img, 3.0)),
                ("landscape", lambda img: self._adjust_aspect_ratio(img, 1.5)),
                ("portrait", lambda img: self._adjust_aspect_ratio(img, 0.67)),
                ("dark_mode", lambda img: ImageEnhance.Brightness(img).enhance(0.6)),
                ("motion_blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=2))),
                ("high_contrast", lambda img: ImageEnhance.Contrast(img).enhance(1.5)),
            ],
            # 桌面端：分辨率变化(1080p, 2K, 4K) + DPI缩放(125%, 150%) + 锐化
            'desktop': [
                ("1080p", lambda img: self._resize_to_resolution(img, 1920, 1080)),
                ("2k", lambda img: self._resize_to_resolution(img, 2560, 1440)),
                ("4k", lambda img: self._resize_to_resolution(img, 3840, 2160)),
                ("dpi_125", lambda img: self._scale_image(img, 1.25)),
                ("dpi_150", lambda img: self._scale_image(img, 1.5)),
                ("ultra_sharp", lambda img: ImageEnhance.Sharpness(img).enhance(2.5)),
                ("slight_blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=0.5))),
            ],
            # Web端：浏览器缩放(75%, 90%, 110%, 125%) + 压缩 + 暗色模式
            'web': [
                ("zoom_75", lambda img: self._scale_image(img, 0.75)),
                ("zoom_90", lambda img: self._scale_image(img, 0.9)),
                ("zoom_110", lambda img: self._scale_image(img, 1.1)),
                ("zoom_125", lambda img: self._scale_image(img, 1.25)),
                ("compressed", lambda img: self._compress_image(img)),
                ("dark_mode", lambda img: ImageEnhance.Brightness(img).enhance(0.65)),
                ("saturated", lambda img: ImageEnhance.Color(img).enhance(1.3)),
            ],
            # 跨平台：综合关键增强
            'cross_platform': [
                ("bright", lambda img: ImageEnhance.Brightness(img).enhance(1.3)),
                ("dark", lambda img: ImageEnhance.Brightness(img).enhance(0.7)),
                ("dpi_2x", lambda img: self._scale_image(img, 2.0)),
                ("dpi_0_75x", lambda img: self._scale_image(img, 0.75)),
                ("sharp", lambda img: ImageEnhance.Sharpness(img).enhance(2.0)),
                ("blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=1))),
                ("high_contrast", lambda img: ImageEnhance.Contrast(img).enhance(1.4)),
                ("compressed", lambda img: self._compress_image(img)),
                ("landscape", lambda img: self._adjust_aspect_ratio(img, 1.5)),
                ("portrait", lambda img: self._adjust_aspect_ratio(img, 0.67)),
            ],
            # 超级增强：根据成功案例（120样本→10000+）的策略
            'super': [
                # 亮度变化（5种）
                ("bright_1_2", lambda img: ImageEnhance.Brightness(img).enhance(1.2)),
                ("bright_1_4", lambda img: ImageEnhance.Brightness(img).enhance(1.4)),
                ("dark_0_6", lambda img: ImageEnhance.Brightness(img).enhance(0.6)),
                ("dark_0_8", lambda img: ImageEnhance.Brightness(img).enhance(0.8)),
                ("dark_mode", lambda img: ImageEnhance.Brightness(img).enhance(0.5)),
                # 对比度变化（4种）
                ("contrast_high", lambda img: ImageEnhance.Contrast(img).enhance(1.5)),
                ("contrast_low", lambda img: ImageEnhance.Contrast(img).enhance(0.7)),
                ("contrast_very_high", lambda img: ImageEnhance.Contrast(img).enhance(1.8)),
                ("contrast_very_low", lambda img: ImageEnhance.Contrast(img).enhance(0.5)),
                # DPI/分辨率（6种）
                ("dpi_0_5x", lambda img: self._scale_image(img, 0.5)),
                ("dpi_0_75x", lambda img: self._scale_image(img, 0.75)),
                ("dpi_1_25x", lambda img: self._scale_image(img, 1.25)),
                ("dpi_1_5x", lambda img: self._scale_image(img, 1.5)),
                ("dpi_2x", lambda img: self._scale_image(img, 2.0)),
                ("dpi_3x", lambda img: self._scale_image(img, 3.0)),
                # 锐化/模糊（5种）
                ("ultra_sharp", lambda img: ImageEnhance.Sharpness(img).enhance(2.5)),
                ("sharp", lambda img: ImageEnhance.Sharpness(img).enhance(1.8)),
                ("slight_blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=0.5))),
                ("blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=1.5))),
                ("motion_blur", lambda img: img.filter(ImageFilter.GaussianBlur(radius=2.0))),
                # 边缘检测（3种 - 关键！成功案例使用）
                ("edge_enhance", lambda img: img.filter(ImageFilter.EDGE_ENHANCE)),
                ("edge_enhance_more", lambda img: img.filter(ImageFilter.EDGE_ENHANCE_MORE)),
                ("find_edges", lambda img: self._apply_edge_detection(img)),
                # 噪声（4种）
                ("noise_light", lambda img: self._add_noise(img, 0.02)),
                ("noise_medium", lambda img: self._add_noise(img, 0.05)),
                ("compressed_60", lambda img: self._compress_image(img, 60)),
                ("compressed_40", lambda img: self._compress_image(img, 40)),
                # 颜色饱和度（4种）
                ("saturated_high", lambda img: ImageEnhance.Color(img).enhance(1.4)),
                ("saturated_low", lambda img: ImageEnhance.Color(img).enhance(0.6)),
                ("saturated_very_high", lambda img: ImageEnhance.Color(img).enhance(1.6)),
                ("desaturated", lambda img: ImageEnhance.Color(img).enhance(0.4)),
                # 旋转/翻转（4种）
                ("rotate_5", lambda img: self._rotate_small(img, 5)),
                ("rotate_minus5", lambda img: self._rotate_small(img, -5)),
                ("slight_zoom", lambda img: self._scale_image(img, 1.1)),
                ("slight_shrink", lambda img: self._scale_image(img, 0.9)),
            ]
        }
        
        return methods.get(strategy, methods['moderate'])
    
    def _scale_image(self, img: Image.Image, scale: float) -> Image.Image:
        """缩放图片（模拟DPI变化）"""
        w, h = img.size
        new_size = (int(w * scale), int(h * scale))
        scaled = img.resize(new_size, Image.Resampling.LANCZOS)
        # 缩放回原始尺寸以保持一致性
        return scaled.resize((w, h), Image.Resampling.LANCZOS)
    
    def _adjust_aspect_ratio(self, img: Image.Image, ratio: float) -> Image.Image:
        """调整宽高比（裁剪或填充）"""
        w, h = img.size
        target_w = int(h * ratio)
        
        if target_w > w:
            # 需要填充
            new_img = Image.new('RGB', (target_w, h), (255, 255, 255))
            offset = (target_w - w) // 2
            new_img.paste(img, (offset, 0))
            return new_img.resize((w, h), Image.Resampling.LANCZOS)
        else:
            # 需要裁剪
            offset = (w - target_w) // 2
            cropped = img.crop((offset, 0, offset + target_w, h))
            return cropped.resize((w, h), Image.Resampling.LANCZOS)
    
    def _resize_to_resolution(self, img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """调整到指定分辨率后再缩放回原尺寸"""
        original_size = img.size
        resized = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        return resized.resize(original_size, Image.Resampling.LANCZOS)
    
    def _compress_image(self, img: Image.Image, quality: int = 60) -> Image.Image:
        """模拟JPEG压缩"""
        import io
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality)
        buffer.seek(0)
        return Image.open(buffer).convert('RGB')
    
    def _apply_edge_detection(self, img: Image.Image) -> Image.Image:
        """应用边缘检测（成功案例关键策略）"""
        # 先找边缘
        edges = img.filter(ImageFilter.FIND_EDGES)
        # 与原图混合，保留部分原始信息
        from PIL import ImageChops
        return ImageChops.add(img, edges, scale=1.5, offset=0)
    
    def _add_noise(self, img: Image.Image, noise_level: float = 0.05) -> Image.Image:
        """添加随机噪声"""
        import numpy as np
        img_array = np.array(img).astype(np.float32)
        noise = np.random.normal(0, noise_level * 255, img_array.shape)
        noisy_img = np.clip(img_array + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(noisy_img)
    
    def _rotate_small(self, img: Image.Image, angle: float) -> Image.Image:
        """小角度旋转（保持尺寸）"""
        return img.rotate(angle, expand=False, fillcolor=(255, 255, 255))

