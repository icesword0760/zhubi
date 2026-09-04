"""
训练管理模块
管理Florence-2模型的增量训练
"""

import os
import json
import torch
import time
from datetime import datetime
from typing import Dict, Optional, Generator
from pathlib import Path
from transformers import TrainerCallback, Trainer


class WeightedTrainer(Trainer):
    """支持类别权重的自定义Trainer"""
    
    def __init__(self, *args, class_weights=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights or {}
        print(f"✅ WeightedTrainer 初始化，类别权重: {self.class_weights}")
    
    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        """重写损失计算，应用类别权重"""
        sample_weights = inputs.pop("sample_weights", None)
        labels = inputs.pop("labels", None)
        
        outputs = model(**inputs, labels=labels)
        
        if labels is None or sample_weights is None:
            loss = outputs.loss if hasattr(outputs, 'loss') else outputs[0]
            if return_outputs:
                return (loss, outputs)
            return loss
        
        # 计算加权loss
        logits = outputs.logits if hasattr(outputs, 'logits') else outputs[1]
        
        # 使用 CrossEntropyLoss，设置 reduction='none' 以获得每个token的loss
        import torch.nn as nn
        loss_fct = nn.CrossEntropyLoss(reduction='none')
        
        # 计算每个token的loss
        loss = loss_fct(logits.view(-1, logits.size(-1)), labels.view(-1))
        loss = loss.view(labels.size(0), -1)  # reshape to [batch_size, seq_len]
        
        # 应用样本权重到每个样本
        if sample_weights.dim() == 1:
            sample_weights = sample_weights.unsqueeze(1).expand_as(loss)
        
        weighted_loss = loss * sample_weights
        final_loss = weighted_loss.mean()
        
        if return_outputs:
            return (final_loss, outputs)
        return final_loss


class TrainManager:
    """训练管理器"""
    
    def __init__(self, models_dir: str, config: Dict):
        self.models_dir = models_dir
        self.config = config
        os.makedirs(models_dir, exist_ok=True)
    
    def _prepare_dataset(self, project_id: str, split_ratios: tuple = (0.7, 0.2, 0.1), 
                         augmentation_config: dict = None) -> tuple[bool, str]:
        """自动准备训练数据集
        
        Args:
            project_id: 项目ID
            split_ratios: 数据划分比例
            augmentation_config: 数据增强配置 {'enabled': bool, 'strategy': str, 'params': dict}
        
        Returns:
            tuple: (成功标志, 错误信息)
        """
        try:
            from backend.export_manager import ExportManager
            import shutil
            import traceback
            
            # 获取项目目录和导出目录
            data_dir = os.path.dirname(self.models_dir)
            projects_dir = os.path.join(data_dir, 'projects')
            exports_dir = os.path.join(data_dir, 'exports')
            
            # 检查项目是否存在
            project_path = os.path.join(projects_dir, project_id)
            if not os.path.exists(project_path):
                return False, f"项目不存在: {project_id}"
            
            # 检查是否有标注数据
            annotations_dir = os.path.join(project_path, 'annotations')
            if not os.path.exists(annotations_dir):
                return False, "项目没有标注数据"
            
            annotation_files = [f for f in os.listdir(annotations_dir) if f.endswith('.json')]
            if not annotation_files:
                return False, "项目没有标注文件"
            
            print(f"[数据准备] 找到 {len(annotation_files)} 个标注文件")
            
            export_mgr = ExportManager(projects_dir, exports_dir)
            
            # 创建临时导出路径（仅用于生成数据，不用于下载）
            temp_export_path = os.path.join(self.models_dir, project_id, 'temp_export')
            os.makedirs(temp_export_path, exist_ok=True)
            print(f"[数据准备] 临时目录: {temp_export_path}")
            
            # 处理数据增强配置
            use_augmentation = False
            augmentation_strategy = None
            if augmentation_config:
                use_augmentation = augmentation_config.get('enabled', False)
                augmentation_strategy = augmentation_config.get('strategy', 'moderate')
                print(f"[数据准备] 数据增强: {'启用' if use_augmentation else '禁用'}")
                if use_augmentation:
                    print(f"[数据准备] 增强策略: {augmentation_strategy}")
            
            # 导出Florence-2格式（会自动保存到models目录）
            # 先导出基础数据（不增强），然后再应用数据增强
            print(f"[数据准备] 开始导出 Florence-2 格式，划分比例: {split_ratios}")
            export_mgr._export_florence2(
                project_id=project_id,
                export_path=temp_export_path,
                split_ratios=split_ratios,
                augmentation=False  # 先导出基础数据
            )
            print(f"[数据准备] 基础数据导出完成")
            
            # 如果启用了数据增强，应用增强策略
            if use_augmentation:
                print(f"[数据准备] 开始应用数据增强...")
                from backend.data_augmentor import DataAugmentor
                augmentor = DataAugmentor(self.models_dir)
                
                # 获取自定义配置（支持类别或具体方法）
                custom_categories = None
                custom_methods = None
                if augmentation_strategy == 'custom' and augmentation_config:
                    categories = augmentation_config.get('categories', None)
                    # 判断是类别列表还是方法列表
                    # 如果列表中的元素包含下划线，说明是方法名（如'bright_1_2'）
                    # 否则是类别名（如'brightness'）
                    if categories and len(categories) > 0:
                        first_item = categories[0]
                        if '_' in first_item or any(first_item.startswith(prefix) for prefix in ['bright', 'dark', 'contrast', 'dpi', 'ultra', 'sharp', 'slight', 'blur', 'motion', 'edge', 'find', 'noise', 'compressed', 'saturated', 'desaturated', 'rotate', 'zoom', 'shrink']):
                            # 细粒度方法列表
                            custom_methods = categories
                            print(f"[数据准备] 自定义方法（细粒度）: {custom_methods}")
                        else:
                            # 类别列表（向后兼容）
                            custom_categories = categories
                            print(f"[数据准备] 自定义类别: {custom_categories}")
                
                success, msg, aug_count = augmentor.augment_dataset(
                    project_id, 
                    augmentation_strategy,
                    custom_categories,
                    custom_methods
                )
                if success:
                    print(f"[数据准备] 数据增强完成，总样本数: {aug_count}")
                else:
                    print(f"[数据准备] 数据增强失败: {msg}")
                    return False, f"数据增强失败: {msg}"
            
            print(f"[数据准备] 所有数据准备完成")
            
            # 清理临时目录
            shutil.rmtree(temp_export_path, ignore_errors=True)
            print(f"[数据准备] 清理临时目录完成")
            
            return True, ""
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"[数据准备] 失败: {error_msg}")
            return False, error_msg
    
    def start_training(self, project_id: str, train_config: Dict) -> Generator[Dict, None, None]:
        """开始训练（生成器，流式返回日志和进度）"""
        try:
            # 🔧 生成唯一的训练会话ID（避免多个训练混淆）
            import uuid
            session_id = str(uuid.uuid4())[:8]
            print(f"[训练会话] 开始新训练会话: {session_id}")
            
            # 导入必要的库
            from transformers import AutoModelForCausalLM, AutoProcessor, Trainer, TrainingArguments
            from peft import LoraConfig, get_peft_model, TaskType
            from datasets import Dataset
            from PIL import Image
            
            # 检查数据集是否存在
            dataset_path = os.path.join(self.models_dir, project_id, "florence2_data")
            train_jsonl = os.path.join(dataset_path, "train.jsonl")
            val_jsonl = os.path.join(dataset_path, "val.jsonl")
            
            # 总是使用最新的标注数据准备训练集
            # 原因：
            # 1. 确保使用最新的标注（用户可能添加了新标注）
            # 2. 应用最新的数据增强配置（如果启用）
            # 3. 应用最新的数据划分配置
            use_augmentation = train_config.get('augmentation_enabled', False)
            
            # 显示提示信息
            if os.path.exists(train_jsonl):
                if use_augmentation:
                    yield {
                        'type': 'log',
                        'message': '🔄 检测到数据增强配置，正在重新生成训练数据...\n',
                        'progress': 0
                    }
                else:
                    yield {
                        'type': 'log',
                        'message': '🔄 使用最新标注数据，正在重新生成训练集...\n',
                        'progress': 0
                    }
            else:
                yield {
                    'type': 'log',
                    'message': '🔍 未找到训练数据集，正在自动准备...\n',
                    'progress': 0
                }
            
            # 无论数据是否存在，都重新准备（确保使用最新标注和配置）
            # 获取数据划分比例
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
                'message': '⚙️ 正在处理标注数据...\n',
                'progress': 5
            }
            
            # 提取数据增强配置
            augmentation_config = {
                'enabled': train_config.get('augmentation_enabled', False),
                'strategy': train_config.get('augmentation_strategy', 'moderate'),
                'params': train_config.get('augmentation_params', {}),
                'categories': train_config.get('augmentation_categories', None)
            }
            
            # 自动准备数据集
            success, error_msg = self._prepare_dataset(project_id, split_ratios, augmentation_config)
            if not success:
                yield {
                    'type': 'error',
                    'message': f'❌ 错误：自动准备数据集失败\n\n详细信息：\n{error_msg}\n',
                    'progress': 0
                }
                return
            
            yield {
                'type': 'log',
                'message': '✅ 数据集准备完成！\n',
                'progress': 10
            }
            
            yield {
                'type': 'log',
                'message': '📦 正在加载数据集...\n',
                'progress': 12
            }
            
            # 读取JSONL数据
            train_data = []
            with open(train_jsonl, 'r', encoding='utf-8') as f:
                for line in f:
                    train_data.append(json.loads(line))
            
            val_data = []
            if os.path.exists(val_jsonl):
                with open(val_jsonl, 'r', encoding='utf-8') as f:
                    for line in f:
                        val_data.append(json.loads(line))
            
            yield {
                'type': 'log',
                'message': f"✅ 加载训练样本: {len(train_data)}张\n✅ 加载验证样本: {len(val_data)}张\n",
                'progress': 15
            }
            
            # 加载模型和processor
            yield {
                'type': 'log',
                'message': '🤖 正在加载Florence-2模型...\n',
                'progress': 18
            }
            
            # 🔧 检查是否为继续训练模式
            resume_from = train_config.get('resume_from')
            is_resume = resume_from is not None
            
            base_model_path = train_config.get('base_model_path', 
                                              self.config['training']['base_model_path'])
            processor_path = self.config['training']['processor_path']
            
            device = self._get_device(train_config.get('device', 'auto'))
            yield {
                'type': 'log',
                'message': f"🖥️ 使用设备: {device}\n",
                'progress': 15
            }
            
            if is_resume:
                # 🔄 继续训练模式：从保存的模型加载
                yield {
                    'type': 'log',
                    'message': f'🔄 继续训练模式\n📁 加载模型: {resume_from}\n',
                    'progress': 18
                }
                
                # 加载processor
                processor = AutoProcessor.from_pretrained(
                    resume_from,  # 从保存的模型加载processor
                    trust_remote_code=True
                )
                print(f"✅ Processor 从保存的模型加载成功")
                
                # 加载已训练的模型
                if device == 'cpu' or device == 'mps':
                    model = AutoModelForCausalLM.from_pretrained(
                        resume_from,  # 从保存的模型加载
                        torch_dtype=torch.float32,
                        trust_remote_code=True,
                        attn_implementation="eager"
                    )
                    if device == 'mps':
                        model = model.to(device)
                else:
                    model = AutoModelForCausalLM.from_pretrained(
                        resume_from,
                        torch_dtype=torch.float16,
                        trust_remote_code=True,
                        attn_implementation="eager"
                    ).to(device)
                
                yield {
                    'type': 'log',
                    'message': '✅ 已训练模型加载完成，继续训练...\n',
                    'progress': 20
                }
                
                # 模型已经有LoRA配置，无需重新应用
                print(f"[继续训练] 模型已包含LoRA配置，跳过LoRA初始化")
                
            else:
                # 🆕 正常训练模式：从基础模型开始
                yield {
                    'type': 'log',
                    'message': f'🚀 从基础模型开始训练\n',
                    'progress': 18
                }
                
                # 加载processor - 本地文件已完整，直接加载
                print(f"[处理器加载] 从本地路径加载: {processor_path}")
                processor = AutoProcessor.from_pretrained(
                    processor_path,
                    trust_remote_code=True
                )
                print(f"✅ Processor 加载成功")
                
                # 加载模型 - MPS只支持float32
                # 使用 eager attention 避免 SDPA 兼容性问题
                if device == 'cpu' or device == 'mps':
                    # CPU和MPS使用float32
                    model = AutoModelForCausalLM.from_pretrained(
                        base_model_path,
                        torch_dtype=torch.float32,
                        trust_remote_code=True,
                        attn_implementation="eager"  # 避免 SDPA 兼容性问题
                    )
                    if device == 'mps':
                        model = model.to(device)
                else:
                    # CUDA使用float16
                    model = AutoModelForCausalLM.from_pretrained(
                        base_model_path,
                        torch_dtype=torch.float16,
                        trust_remote_code=True,
                        attn_implementation="eager"  # 避免 SDPA 兼容性问题
                    ).to(device)
                
                yield {
                    'type': 'log',
                    'message': '✅ 模型加载完成\n',
                    'progress': 20
                }
            
            # 配置LoRA（仅在非resume模式）
            if not is_resume and train_config.get('use_lora', self.config['training']['use_lora']):
                yield {
                    'type': 'log',
                    'message': '🔧 配置LoRA低秩适配...\n',
                    'progress': 25
                }
                
                lora_config = LoraConfig(
                    r=train_config.get('lora_r', self.config['training']['lora_r']),
                    lora_alpha=train_config.get('lora_alpha', self.config['training']['lora_alpha']),
                    target_modules=self.config['training']['lora_target_modules'],
                    lora_dropout=self.config['training']['lora_dropout'],
                    bias="none",
                    task_type=TaskType.SEQ_2_SEQ_LM
                )
                
                model = get_peft_model(model, lora_config)
                model.print_trainable_parameters()
                
                # 计算可训练参数
                trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
                total_params = sum(p.numel() for p in model.parameters())
                yield {
                    'type': 'log',
                    'message': f"✅ 可训练参数: {trainable_params:,} / {total_params:,} ({100 * trainable_params / total_params:.2f}%)\n",
                    'progress': 30
                }
            
            # 准备数据集
            yield {
                'type': 'log',
                'message': '📊 准备训练数据集...\n',
                'progress': 35
            }
            
            # 不预处理，保留原始数据
            # 在collate_fn中实时处理
            train_dataset = Dataset.from_list(train_data)
            val_dataset = Dataset.from_list(val_data) if val_data else None
            
            yield {
                'type': 'log',
                'message': '✅ 数据集准备完成\n',
                'progress': 40
            }
            
            # 配置训练参数
            yield {
                'type': 'log',
                'message': '⚙️ 配置训练参数...\n',
                'progress': 45
            }
            
            output_dir = os.path.join(self.models_dir, project_id, "checkpoints")
            
            # 配置混合精度训练（MPS不支持fp16）
            use_fp16 = False
            use_bf16 = False
            if device == 'cuda':
                use_fp16 = True  # CUDA支持fp16
            elif device == 'mps':
                # MPS不支持fp16，使用float32
                pass
            
            training_args = TrainingArguments(
                output_dir=output_dir,
                num_train_epochs=train_config.get('epochs', self.config['training']['default_epochs']),
                per_device_train_batch_size=train_config.get('batch_size', 
                                                            self.config['training']['default_batch_size']),
                learning_rate=train_config.get('learning_rate', self.config['training']['default_lr']),
                warmup_steps=train_config.get('warmup_steps', self.config['training']['default_warmup_steps']),
                logging_steps=self.config['training']['logging_steps'],
                save_steps=self.config['training']['save_steps'],
                eval_steps=self.config['training']['eval_steps'],
                save_total_limit=self.config['training']['save_total_limit'],
                eval_strategy="steps" if val_dataset else "no",  # 新版本使用 eval_strategy 而非 evaluation_strategy
                save_strategy="steps",
                load_best_model_at_end=True if val_dataset else False,
                metric_for_best_model="loss" if val_dataset else None,
                greater_is_better=False,
                fp16=use_fp16,
                bf16=use_bf16,
                gradient_accumulation_steps=train_config.get('gradient_accumulation_steps', self.config['training']['gradient_accumulation_steps']),
                max_grad_norm=train_config.get('max_grad_norm', self.config['training']['max_grad_norm']),
                # 关键正则化参数（防止遗忘预训练知识）
                weight_decay=train_config.get('weight_decay', 0.01),  # 添加L2正则化
                # label_smoothing_factor=train_config.get('label_smoothing', 0.0),  # 暂时禁用，可能与Florence-2不兼容
                report_to="none",  # 不使用wandb等
                remove_unused_columns=False,
            )
            
            # 打印完整训练参数
            params_info = f"""
📋 完整训练参数:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔢 基础参数:
   • Epochs: {training_args.num_train_epochs}
   • Batch Size: {training_args.per_device_train_batch_size}
   • Learning Rate: {training_args.learning_rate}
   • Warmup Steps: {training_args.warmup_steps}
   
📊 训练数据:
   • 训练样本: {len(train_data)}
   • 验证样本: {len(val_data)}
   • 训练/验证/测试比例: {train_config['train_split']:.0%}/{train_config['val_split']:.0%}/{train_config['test_split']:.0%}
   
⚙️ 优化参数:
   • Weight Decay: {training_args.weight_decay}
   • Max Grad Norm: {training_args.max_grad_norm}
   • Gradient Accumulation Steps: {training_args.gradient_accumulation_steps}
   
💾 保存策略:
   • Save Strategy: {training_args.save_strategy}
   • Save Steps: {training_args.save_steps if training_args.save_strategy == 'steps' else 'N/A'}
   
🖥️ 硬件加速:
   • Device: {device}
   • FP16: {use_fp16}
   • BF16: {use_bf16}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            yield {
                'type': 'log',
                'message': params_info,
                'progress': 50
            }
            
            # 创建Trainer
            yield {
                'type': 'log',
                'message': '🚀 开始训练...\n',
                'progress': 55
            }
            
            # 创建实时进度回调（写入文件，供前端轮询）
            progress_file = os.path.join(self.models_dir, f"{project_id}_training_progress.json")
            
            # 创建日志文件用于实时输出
            log_file = os.path.join(self.models_dir, f"{project_id}_training_log.txt")
            
            # 🔧 强化：在开始训练前，强制清空旧的日志和进度文件（多次尝试）
            for attempt in range(3):  # 尝试3次删除
                try:
                    if os.path.exists(log_file):
                        os.remove(log_file)
                        print(f"[日志清理-{attempt+1}] 已删除旧日志文件: {log_file}")
                    if os.path.exists(progress_file):
                        os.remove(progress_file)
                        print(f"[日志清理-{attempt+1}] 已删除旧进度文件: {progress_file}")
                    
                    # 等待一小段时间，确保文件系统同步
                    if attempt < 2:
                        import time
                        time.sleep(0.1)
                    break
                except Exception as e:
                    print(f"[日志清理-{attempt+1}] 清理失败: {e}")
                    if attempt == 2:
                        print(f"[日志清理] ⚠️ 警告：无法删除旧文件，可能导致日志混淆")
            
            class ProgressCallback(TrainerCallback):
                """实时报告训练进度的回调（通过文件）"""
                def __init__(self, progress_file_path, log_file_path, total_epochs, target_loss=None, 
                           early_stop_patience=3, reduce_lr_config=None, trainer=None, session_id=None):
                    super().__init__()
                    self.progress_file = progress_file_path
                    self.log_file = log_file_path
                    self.total_epochs = total_epochs
                    self.session_id = session_id or "unknown"  # 训练会话ID
                    self.start_time = None
                    self.epoch_start_time = None
                    self.epoch_times = []  # 记录每轮的实际耗时
                    
                    # 早停相关参数
                    self.target_loss = target_loss
                    self.early_stop_patience = early_stop_patience
                    self.target_met_count = 0  # 连续达到目标的次数
                    self.best_loss = float('inf')  # 记录最佳Loss
                    
                    # ReduceLROnPlateau相关参数
                    self.reduce_lr_config = reduce_lr_config or {}
                    self.use_reduce_lr = self.reduce_lr_config.get('enabled', False)
                    self.reduce_lr_patience = self.reduce_lr_config.get('patience', 5)
                    self.reduce_lr_factor = self.reduce_lr_config.get('factor', 0.5)
                    self.reduce_lr_min_lr = self.reduce_lr_config.get('min_lr', 1e-8)
                    self.reduce_lr_counter = 0  # 停滞计数器
                    self.last_best_loss = float('inf')  # 上次最佳Loss
                    self.current_lr = None  # 当前学习率
                    self.trainer_ref = trainer  # Trainer引用
                    self.lr_changes = []  # 学习率变化历史
                    
                    # 智能分析相关参数
                    self.loss_history = []  # Loss历史记录
                    self.last_reminder_epoch = 0  # 上次提醒的轮次
                    self.reminder_interval = 3  # 提醒间隔（轮次）
                    
                    # 用户主动完成训练标志
                    self.user_finished = False
                    
                    # 🔧 注意：日志文件已在外层删除，这里只需要创建新文件
                    # 第一次写入会自动创建文件
                    
                    print(f"[DEBUG] ProgressCallback initialized, file: {progress_file_path}")
                    print(f"[DEBUG] 自适应学习率状态: use_reduce_lr={self.use_reduce_lr}, current_lr={self.current_lr}")
                    if target_loss:
                        print(f"[早停] 目标Loss: {target_loss}, 容忍轮数: {early_stop_patience}")
                    if self.use_reduce_lr:
                        print(f"[ReduceLR] 启用自适应学习率, 停滞轮数: {self.reduce_lr_patience}, 衰减因子: {self.reduce_lr_factor}")
                    else:
                        print(f"[ReduceLR] 未启用自适应学习率")
                    
                def _write_progress(self, data):
                    """写入进度到文件"""
                    try:
                        print(f"[DEBUG] Writing progress to: {self.progress_file}")
                        print(f"[DEBUG] Data: {data}")
                        with open(self.progress_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False)
                        print(f"[DEBUG] Progress file written successfully")
                    except Exception as e:
                        import traceback
                        print(f"❌ 写入进度文件失败: {e}")
                        print(f"❌ 文件路径: {self.progress_file}")
                        print(f"❌ 错误详情:\n{traceback.format_exc()}")
                
                def _write_log(self, message):
                    """写入日志到文件"""
                    try:
                        # 添加时间戳
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        timestamped_message = f"[{timestamp}] {message}"
                        
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(timestamped_message + '\n')
                            f.flush()  # 立即刷新到磁盘
                    except Exception as e:
                        print(f"❌ 写入日志失败: {e}")
                
                def _smart_analysis(self, current_epoch, current_loss, elapsed_time, estimated_remaining):
                    """智能分析训练趋势并提供建议"""
                    try:
                        # 至少需要3个数据点才能进行分析
                        if len(self.loss_history) < 3:
                            return
                        
                        # 1. 计算Loss下降速率（最近3轮的平均下降）
                        recent_losses = [h['loss'] for h in self.loss_history[-3:]]
                        loss_decline_rate = (recent_losses[0] - recent_losses[-1]) / 3
                        
                        # 2. 如果设置了目标Loss，预测需要的轮数
                        if self.target_loss and current_loss > self.target_loss:
                            if loss_decline_rate > 0.001:  # Loss正在下降
                                remaining_loss = current_loss - self.target_loss
                                estimated_epochs_needed = int(remaining_loss / loss_decline_rate)
                                remaining_epochs = self.total_epochs - current_epoch
                                
                                if estimated_epochs_needed > remaining_epochs:
                                    # 轮数可能不够
                                    shortage = estimated_epochs_needed - remaining_epochs
                                    self._write_log(f"💡 智能分析: 当前下降速率 {loss_decline_rate:.4f}/轮，预计还需 {estimated_epochs_needed} 轮达到目标 {self.target_loss:.4f}")
                                    self._write_log(f"⚠️ 建议: 剩余轮数可能不足（缺 {shortage} 轮），考虑：")
                                    self._write_log(f"   1️⃣ 训练完成后继续训练（Resume Training）")
                                    if not self.use_reduce_lr:
                                        self._write_log(f"   2️⃣ 启用自适应学习率（ReduceLR）加速收敛")
                                    if self.current_lr and self.current_lr > 1e-7:
                                        self._write_log(f"   3️⃣ 降低学习率至 {self.current_lr * 0.5:.2e} 进行微调")
                                else:
                                    # 轮数充足
                                    self._write_log(f"💡 智能分析: 按当前速率，预计 {estimated_epochs_needed} 轮后达到目标（剩余 {remaining_epochs} 轮，充足✅）")
                            else:
                                # Loss下降停滞
                                self._write_log(f"⚠️ 智能分析: Loss下降停滞（最近3轮变化<0.001），建议：")
                                if not self.use_reduce_lr:
                                    self._write_log(f"   1️⃣ 启用自适应学习率（ReduceLR）")
                                if self.current_lr and self.current_lr > self.reduce_lr_min_lr:
                                    self._write_log(f"   2️⃣ 手动降低学习率")
                                self._write_log(f"   3️⃣ 检查数据质量或增加数据增强")
                        
                        # 3. 分析Loss趋势（不依赖目标Loss）
                        if len(self.loss_history) >= 6:
                            # 比较最近3轮和之前3轮
                            earlier_losses = [h['loss'] for h in self.loss_history[-6:-3]]
                            recent_losses = [h['loss'] for h in self.loss_history[-3:]]
                            earlier_avg = sum(earlier_losses) / len(earlier_losses)
                            recent_avg = sum(recent_losses) / len(recent_losses)
                            improvement = earlier_avg - recent_avg
                            
                            if improvement < 0.01:  # 改善不明显
                                if not self.use_reduce_lr:
                                    self._write_log(f"💡 提示: Loss改善趋缓（最近6轮仅下降 {improvement:.4f}），建议启用自适应学习率")
                        
                        # 4. ReduceLR状态分析
                        if self.use_reduce_lr and self.lr_changes:
                            lr_change_count = len(self.lr_changes)
                            if lr_change_count >= 2:
                                self._write_log(f"💡 提示: 学习率已降低 {lr_change_count} 次，模型正在精细调整中")
                                if self.current_lr <= self.reduce_lr_min_lr * 2:
                                    self._write_log(f"⚠️ 学习率接近最小值，如Loss仍未达标，建议增加训练数据或调整模型架构")
                        
                        print(f"[智能分析] Epoch {current_epoch}: Loss={current_loss:.4f}, 下降速率={loss_decline_rate:.4f}/轮")
                    
                    except Exception as e:
                        print(f"⚠️ 智能分析失败: {e}")
                        import traceback
                        traceback.print_exc()
                    
                def on_train_begin(self, args, state, control, **kwargs):
                    print(f"[DEBUG] on_train_begin called")
                    self.start_time = time.time()
                    
                    # 🔧 记录训练会话信息
                    initial_lr = args.learning_rate
                    self._write_log(f"🚀 训练开始 [会话: {self.session_id}]")
                    self._write_log(f"📋 配置: 总轮数={self.total_epochs}, 初始学习率={initial_lr:.2e}")
                    if self.target_loss:
                        self._write_log(f"🎯 目标Loss: {self.target_loss:.4f}, 容忍轮数: {self.early_stop_patience}")
                    if self.use_reduce_lr:
                        self._write_log(f"⚙️ 自适应学习率: 启用（停滞{self.reduce_lr_patience}轮降低，因子={self.reduce_lr_factor}）")
                    else:
                        self._write_log(f"⚙️ 自适应学习率: 未启用")
                    self._write_log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    
                    self._write_progress({
                        'status': 'training',
                        'current_epoch': 0,
                        'total_epochs': self.total_epochs,
                        'elapsed_time': 0,
                        'estimated_remaining': None,
                        'current_loss': None,
                        'avg_loss': None,
                        'updated_at': time.time()
                    })
                    print(f"[DEBUG] Progress file written at train begin")
                    
                def on_epoch_begin(self, args, state, control, **kwargs):
                    self.epoch_start_time = time.time()
                
                def on_step_end(self, args, state, control, **kwargs):
                    """每个batch后调用，用于快速响应用户的完成训练请求"""
                    # 🔧 检查是否用户请求完成训练（立即响应）
                    finish_flag_file = self.progress_file.replace('_training_progress.json', '_finish_flag.txt')
                    if os.path.exists(finish_flag_file):
                        print(f"[完成训练] 检测到完成标志，立即停止训练")
                        self._write_log(f"👤 用户请求完成训练，立即停止并保存当前模型...")
                        try:
                            os.remove(finish_flag_file)
                            print(f"[完成训练] 已删除完成标志文件")
                        except:
                            pass
                        control.should_training_stop = True
                        # 标记为用户主动完成，而非早停
                        self.user_finished = True
                    return control
                    
                def on_epoch_end(self, args, state, control, **kwargs):
                    print(f"[DEBUG] on_epoch_end called, epoch: {state.epoch}")
                    
                    # 计算本轮耗时
                    epoch_time = time.time() - self.epoch_start_time
                    self.epoch_times.append(epoch_time)
                    
                    # 计算平均每轮耗时（使用最近的轮次更准确）
                    recent_epochs = self.epoch_times[-5:]  # 使用最近5轮的平均值
                    avg_epoch_time = sum(recent_epochs) / len(recent_epochs)
                    
                    # 计算剩余时间
                    current_epoch = int(state.epoch)
                    remaining_epochs = self.total_epochs - current_epoch
                    estimated_remaining = remaining_epochs * avg_epoch_time
                    print(f"[DEBUG] Epoch {current_epoch}/{self.total_epochs}, remaining: {estimated_remaining:.0f}s")
                    
                    # 计算已用时间
                    elapsed_time = time.time() - self.start_time
                    
                    # 获取当前损失（优化：也检查eval_loss）
                    current_loss = None
                    avg_loss = None
                    if state.log_history:
                        # 获取最后一条包含loss的日志（优先使用loss，其次使用eval_loss）
                        for log in reversed(state.log_history):
                            if 'loss' in log:
                                current_loss = log['loss']
                                break
                            elif 'eval_loss' in log:
                                current_loss = log['eval_loss']
                                break
                        # 计算平均损失
                        losses = [log.get('loss', log.get('eval_loss')) for log in state.log_history if 'loss' in log or 'eval_loss' in log]
                        losses = [l for l in losses if l is not None]
                        if losses:
                            avg_loss = sum(losses) / len(losses)
                    
                    # 🔧 修复：如果仍然没有loss，尝试从训练日志获取
                    if current_loss is None and hasattr(state, 'log_history'):
                        print(f"[DEBUG] 轮次{current_epoch}无法获取loss，log_history条目数: {len(state.log_history)}")
                    
                    # 🔧 早停检查
                    early_stop_triggered = False
                    if self.target_loss and current_loss is not None:
                        # 更新最佳Loss
                        if current_loss < self.best_loss:
                            self.best_loss = current_loss
                        
                        # 检查是否达到目标
                        if current_loss <= self.target_loss:
                            self.target_met_count += 1
                            print(f"[早停] Loss {current_loss:.4f} <= 目标 {self.target_loss:.4f}, 计数: {self.target_met_count}/{self.early_stop_patience}")
                            
                            if self.target_met_count >= self.early_stop_patience:
                                print(f"[早停] 连续{self.early_stop_patience}轮达到目标，触发早停！")
                                self._write_log(f"🎯 早停触发！连续{self.early_stop_patience}轮达到目标Loss {self.target_loss:.4f}")
                                control.should_training_stop = True
                                early_stop_triggered = True
                        else:
                            # 未达到目标，重置计数
                            if self.target_met_count > 0:
                                print(f"[早停] Loss {current_loss:.4f} > 目标 {self.target_loss:.4f}, 计数归零")
                            self.target_met_count = 0
                    
                    # 🔧 ReduceLROnPlateau检查
                    lr_reduced = False
                    if self.use_reduce_lr and current_loss is not None and not early_stop_triggered:
                        # 检查Loss是否有显著改善
                        improvement_threshold = 0.01  # 改善阈值：1%
                        if self.last_best_loss - current_loss > improvement_threshold:
                            # Loss有显著改善，重置计数器
                            self.last_best_loss = min(self.last_best_loss, current_loss)
                            self.reduce_lr_counter = 0
                            print(f"[ReduceLR] Loss改善 ({self.last_best_loss:.4f} -> {current_loss:.4f}), 计数器归零")
                        else:
                            # Loss停滞，计数器+1
                            self.reduce_lr_counter += 1
                            print(f"[ReduceLR] Loss停滞 (改善<{improvement_threshold}), 计数器: {self.reduce_lr_counter}/{self.reduce_lr_patience}")
                            
                            # 达到停滞轮数，降低学习率
                            if self.reduce_lr_counter >= self.reduce_lr_patience:
                                # 获取当前学习率
                                if self.current_lr is None:
                                    self.current_lr = args.learning_rate
                                
                                # 计算新学习率
                                new_lr = max(self.current_lr * self.reduce_lr_factor, self.reduce_lr_min_lr)
                                
                                if new_lr > self.reduce_lr_min_lr:
                                    old_lr = self.current_lr
                                    self.current_lr = new_lr
                                    
                                    # 更新Trainer的学习率
                                    for param_group in self.trainer_ref.optimizer.param_groups:
                                        param_group['lr'] = new_lr
                                    
                                    # 记录学习率变化
                                    lr_change_info = {
                                        'epoch': current_epoch,
                                        'old_lr': old_lr,
                                        'new_lr': new_lr,
                                        'reason': f'Loss停滞{self.reduce_lr_patience}轮'
                                    }
                                    self.lr_changes.append(lr_change_info)
                                    
                                    # 写入日志
                                    self._write_log(f"📉 学习率降低: {old_lr:.2e} → {new_lr:.2e} (因Loss停滞{self.reduce_lr_patience}轮)")
                                    print(f"[ReduceLR] 学习率降低: {old_lr:.2e} → {new_lr:.2e}")
                                    
                                    # 重置计数器
                                    self.reduce_lr_counter = 0
                                    self.last_best_loss = current_loss  # 更新基准
                                    lr_reduced = True
                                else:
                                    print(f"[ReduceLR] 学习率已达最小值 {self.reduce_lr_min_lr:.2e}，不再降低")
                                    self._write_log(f"⚠️ 学习率已达最小值 {self.reduce_lr_min_lr:.2e}")
                    
                    # 🔧 智能分析与提醒
                    if current_loss is not None and not early_stop_triggered:
                        # 记录Loss历史
                        self.loss_history.append({
                            'epoch': current_epoch,
                            'loss': current_loss
                        })
                        
                        # 每隔N轮进行一次智能分析（避免过度提醒）
                        if current_epoch - self.last_reminder_epoch >= self.reminder_interval and current_epoch >= 3:
                            self._smart_analysis(current_epoch, current_loss, elapsed_time, estimated_remaining)
                            self.last_reminder_epoch = current_epoch
                    
                    # 格式化时间
                    def format_time(seconds):
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                    
                    # 输出训练日志
                    log_msg = f"📊 轮次 {current_epoch}/{self.total_epochs} | "
                    if current_loss is not None:
                        log_msg += f"损失: {current_loss:.4f} | "
                        if self.target_loss:
                            log_msg += f"目标: {self.target_loss:.4f} | "
                    if self.use_reduce_lr and self.current_lr is not None:
                        log_msg += f"LR: {self.current_lr:.2e} | "
                    log_msg += f"耗时: {format_time(epoch_time)} | "
                    log_msg += f"已用: {format_time(elapsed_time)} | "
                    if not early_stop_triggered:
                        log_msg += f"预计剩余: {format_time(estimated_remaining)}"
                    else:
                        log_msg += f"🎯 早停触发"
                    
                    self._write_log(log_msg)
                    print(log_msg)
                    
                    # 写入进度文件
                    progress_data = {
                        'status': 'training',
                        'current_epoch': current_epoch,
                        'total_epochs': self.total_epochs,
                        'elapsed_time': elapsed_time,
                        'estimated_remaining': estimated_remaining,
                        'current_loss': current_loss,
                        'avg_loss': avg_loss,
                        'epoch_time': epoch_time,
                        'avg_epoch_time': avg_epoch_time,
                        'best_loss': self.best_loss if self.target_loss else None,
                        'target_loss': self.target_loss,
                        'early_stopped': early_stop_triggered,
                        'updated_at': time.time()
                    }
                    
                    # 添加学习率信息
                    if self.use_reduce_lr:
                        progress_data['current_lr'] = self.current_lr
                        progress_data['lr_changes'] = self.lr_changes
                    
                    self._write_progress(progress_data)
                    
                def on_train_end(self, args, state, control, **kwargs):
                    # 训练完成，写入最终状态
                    elapsed_time = time.time() - self.start_time
                    
                    # 获取最终损失
                    final_loss = None
                    if state.log_history:
                        for log in reversed(state.log_history):
                            if 'loss' in log:
                                final_loss = log['loss']
                                break
                    
                    self._write_progress({
                        'status': 'completed',
                        'current_epoch': self.total_epochs,
                        'total_epochs': self.total_epochs,
                        'elapsed_time': elapsed_time,
                        'estimated_remaining': 0,
                        'current_loss': final_loss,
                        'updated_at': time.time()
                    })
                    
                    # 输出完成日志
                    def format_time(seconds):
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                    
                    completion_msg = f"✅ 训练完成！总耗时: {format_time(elapsed_time)}"
                    if final_loss is not None:
                        completion_msg += f" | 最终损失: {final_loss:.4f}"
                    
                    self._write_log(completion_msg)
            
            # 自定义data collator - 实时处理原始数据
            def collate_fn(features):
                """实时处理数据并collate - 修复版：避免processor自动转换task prompt"""
                # 提取数据
                images = []
                prefixes = []
                suffixes = []
                
                for feature in features:
                    # 加载图片
                    img_path = os.path.join(dataset_path, feature['image'])
                    img = Image.open(img_path).convert("RGB")
                    # 🔧 修复：resize到64x64（与原始OmniParser一致，减少计算量）
                    img = img.resize((64, 64), Image.Resampling.LANCZOS)
                    images.append(img)
                    prefixes.append(feature['prefix'])
                    suffixes.append(feature['suffix'])
                
                # 🔧 修复：禁用processor的resize（因为已手动resize到64x64）
                inputs = processor(
                    images=images,
                    return_tensors="pt",
                    padding=True,
                    do_resize=False  # 与原始OmniParser一致
                )
                
                # 🔧 修复：手动tokenize prefix（保持原始<CAPTION>格式）
                prefix_encoding = processor.tokenizer(
                    prefixes,
                    return_tensors="pt",
                    padding=True,
                    add_special_tokens=True
                )
                
                # 覆盖input_ids和attention_mask
                inputs["input_ids"] = prefix_encoding["input_ids"]
                inputs["attention_mask"] = prefix_encoding["attention_mask"]
                
                # 🔧 修复：处理标签（与原始OmniParser完全一致）
                labels = processor.tokenizer(
                    text_target=suffixes,
                    return_tensors="pt",
                    padding="max_length",  # 修复：强制padding到max_length（关键！）
                    truncation=True,
                    max_length=20  # 修改：使用合理的max_length（原始OmniParser使用20）
                )
                
                # 🔧 关键修复：将padding token的label设为-100（忽略）
                # 这是原始OmniParser的做法，确保loss计算时忽略padding
                label_ids = labels["input_ids"].clone()
                label_ids[label_ids == processor.tokenizer.pad_token_id] = -100
                
                inputs["labels"] = label_ids
                
                # 确保所有tensor使用正确的dtype
                if "pixel_values" in inputs:
                    inputs["pixel_values"] = inputs["pixel_values"].to(torch.float32)
                
                return inputs
            
            # 创建进度回调实例
            progress_callback = ProgressCallback(
                progress_file_path=progress_file,
                log_file_path=log_file,
                total_epochs=train_config['epochs'],
                target_loss=train_config.get('target_loss', None),
                early_stop_patience=train_config.get('early_stop_patience', 3),
                reduce_lr_config=train_config.get('reduce_lr_config', {}),
                trainer=None,  # 稍后设置
                session_id=session_id  # 传递会话ID
            )
            
            # 🔧 立即写入初始进度（确保前端能获取到）
            try:
                initial_progress = {
                    'status': 'starting',
                    'current_epoch': 0,
                    'total_epochs': train_config['epochs'],
                    'elapsed_time': 0,
                    'estimated_remaining': None,
                    'current_loss': None,
                    'avg_loss': None,
                    'epoch_time': None,
                    'avg_epoch_time': None,
                    'updated_at': time.time()
                }
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(initial_progress, f, ensure_ascii=False)
                print(f"✅ 初始进度文件已写入: {progress_file}")
                
                yield {
                    'type': 'log',
                    'message': f'📊 初始化训练进度跟踪...\n',
                    'progress': 0
                }
            except Exception as e:
                print(f"⚠️  写入初始进度文件失败: {e}")
                import traceback
                traceback.print_exc()
            
            # 检查是否使用类别权重
            class_weights = train_config.get('class_weights', None)
            if class_weights:
                yield {
                    'type': 'log',
                    'message': f'⚖️ 使用类别权重训练: {class_weights}\n',
                    'progress': 0
                }
                
                trainer = WeightedTrainer(
                    model=model,
                    args=training_args,
                    train_dataset=train_dataset,
                    eval_dataset=val_dataset,
                    data_collator=collate_fn,
                    callbacks=[progress_callback],
                    class_weights=class_weights
                )
                # 将trainer引用传递给progress_callback（用于ReduceLROnPlateau）
                progress_callback.trainer_ref = trainer
            else:
                trainer = Trainer(
                    model=model,
                    args=training_args,
                    train_dataset=train_dataset,
                    eval_dataset=val_dataset,
                    data_collator=collate_fn,
                    callbacks=[progress_callback],
                )
                # 将trainer引用传递给progress_callback（用于ReduceLROnPlateau）
                progress_callback.trainer_ref = trainer
            
            # 训练
            try:
                # 注意：日志文件已在前面删除并重新创建，无需再次清空
                train_result = trainer.train()
                
                # 🔧 获取最后一轮的实际Loss（而不是平均Loss）
                final_epoch_loss = None
                if hasattr(trainer.state, 'log_history') and trainer.state.log_history:
                    # 从后往前找最后一个包含loss的记录
                    for log in reversed(trainer.state.log_history):
                        if 'loss' in log:
                            final_epoch_loss = log['loss']
                            break
                
                # 如果没找到，使用training_loss作为备选
                if final_epoch_loss is None:
                    final_epoch_loss = train_result.training_loss
                
                # 读取并输出训练日志
                if os.path.exists(log_file):
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            log_content = f.read()
                        if log_content.strip():
                            yield {
                                'type': 'log',
                                'message': f"\n{'='*60}\n📊 训练过程详情\n{'='*60}\n{log_content}\n{'='*60}\n",
                                'progress': 85
                            }
                    except Exception as e:
                        print(f"⚠️ 读取训练日志失败: {e}")
                
                # 检查是否早停
                early_stopped = progress_callback.target_met_count >= progress_callback.early_stop_patience if progress_callback.target_loss else False
                
                # 检查是否用户主动完成
                user_finished = progress_callback.user_finished
                
                # 生成学习率变化总结
                lr_summary = ""
                if progress_callback.use_reduce_lr and progress_callback.lr_changes:
                    lr_summary = f"\n📉 学习率调整记录:\n"
                    for change in progress_callback.lr_changes:
                        lr_summary += f"   • 第{change['epoch']}轮: {change['old_lr']:.2e} → {change['new_lr']:.2e} ({change['reason']})\n"
                
                # 根据结束原因生成不同的消息
                if user_finished:
                    completion_msg = "（用户主动完成）"
                elif early_stopped:
                    completion_msg = "（早停触发）"
                else:
                    completion_msg = ""
                
                yield {
                    'type': 'log',
                    'message': f"\n✅ 训练完成{completion_msg}！\n📊 最终轮次损失: {final_epoch_loss:.4f}\n📊 全程平均损失: {train_result.training_loss:.4f}{lr_summary}\n",
                    'progress': 90
                }
                
                # 保存模型（使用时间戳避免覆盖）
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_dir = os.path.join(self.models_dir, project_id, timestamp)
                os.makedirs(model_dir, exist_ok=True)
                
                final_model_path = os.path.join(model_dir, "final_model")
                trainer.save_model(final_model_path)
                processor.save_pretrained(final_model_path)
                
                yield {
                    'type': 'log',
                    'message': f"💾 模型已保存到: {final_model_path}\n",
                    'progress': 95
                }
                
                # 统计每个类别的样本数量
                category_counts = {}
                for sample in train_data:
                    category = sample.get('suffix', 'unknown')
                    category_counts[category] = category_counts.get(category, 0) + 1
                
                # 保存训练信息
                train_info = {
                    "project_id": project_id,
                    "timestamp": timestamp,
                    "trained_at": datetime.now().isoformat(),
                    "config": train_config,
                    "train_samples": len(train_data),
                    "val_samples": len(val_data),
                    "category_counts": category_counts,
                    "final_loss": float(final_epoch_loss),  # 🔧 使用最后一轮的Loss
                    "avg_loss": float(train_result.training_loss),  # 全程平均Loss
                    "best_loss": float(progress_callback.best_loss) if progress_callback.target_loss else None,
                    "early_stopped": early_stopped,
                    "user_finished": user_finished,
                    "target_loss": train_config.get('target_loss', None),
                    "model_path": final_model_path,
                    "lr_changes": progress_callback.lr_changes if progress_callback.use_reduce_lr else [],
                    "is_resumed": is_resume,  # 是否为继续训练
                    "resumed_from": train_config.get('resume_from') if is_resume else None  # 从哪个模型继续
                }
                
                info_path = os.path.join(model_dir, "train_info.json")
                with open(info_path, 'w', encoding='utf-8') as f:
                    json.dump(train_info, f, indent=2, ensure_ascii=False)
                
                yield {
                    'type': 'log',
                    'message': '✅ 训练信息已保存\n',
                    'progress': 98
                }
                
                # 🔧 不立即删除进度文件，让前端有时间读取最终状态
                # 在前端停止轮询后，文件会被后续训练覆盖或手动清理
                yield {
                    'type': 'log',
                    'message': '💾 保留进度文件供查看...\n',
                    'progress': 99
                }
                
                # 延迟清理日志文件（进度文件保留）
                import threading
                def delayed_cleanup():
                    time.sleep(30)  # 30秒后清理
                    try:
                        if os.path.exists(log_file):
                            os.remove(log_file)
                            print(f"🧹 已清理训练日志: {log_file}")
                        if os.path.exists(progress_file):
                            os.remove(progress_file)
                            print(f"🧹 已清理进度文件: {progress_file}")
                    except Exception as e:
                        print(f"⚠️ 清理文件失败: {e}")
                
                cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
                cleanup_thread.start()
                
                # 🔧 释放内存资源（重要！防止内存泄漏）
                print("🧹 开始释放训练资源...")
                
                # 释放模型和训练器
                del model
                del trainer
                del processor
                
                # 释放数据集
                del train_dataset
                del val_dataset
                del train_data
                del val_data
                
                # 清理PyTorch缓存
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    print("  ✅ CUDA缓存已清理")
                if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                    print("  ✅ MPS缓存已清理")
                
                # 强制垃圾回收
                import gc
                collected = gc.collect()
                print(f"  ✅ 垃圾回收完成，回收了 {collected} 个对象")
                
                print("✅ 训练资源已完全释放")
                
                yield {
                    'type': 'complete',
                    'message': '🎉 全部完成！\n',
                    'progress': 100,
                    'model_path': final_model_path,
                    'final_loss': float(final_epoch_loss),
                    'avg_loss': float(train_result.training_loss),
                    'early_stopped': early_stopped
                }
                
            except Exception as e:
                # 清理进度文件和日志文件
                if os.path.exists(progress_file):
                    os.remove(progress_file)
                if os.path.exists(log_file):
                    os.remove(log_file)
                    
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
            # 清理进度文件和日志文件
            progress_file = os.path.join(self.models_dir, f"{project_id}_training_progress.json")
            log_file = os.path.join(self.models_dir, f"{project_id}_training_log.txt")
            if os.path.exists(progress_file):
                try:
                    os.remove(progress_file)
                    print(f"🧹 已清理进度文件: {progress_file}")
                except:
                    pass
            if os.path.exists(log_file):
                try:
                    os.remove(log_file)
                    print(f"🧹 已清理日志文件: {log_file}")
                except:
                    pass
                    
            # 清理资源（即使失败也要清理）
            try:
                print("🧹 训练失败，清理资源...")
                import gc
                
                # 尝试释放可能已创建的对象
                if 'model' in locals():
                    del model
                if 'trainer' in locals():
                    del trainer
                if 'processor' in locals():
                    del processor
                if 'train_dataset' in locals():
                    del train_dataset
                if 'val_dataset' in locals():
                    del val_dataset
                
                # 清理PyTorch缓存
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                
                gc.collect()
                print("✅ 资源清理完成")
            except Exception as cleanup_error:
                print(f"⚠️ 资源清理失败: {cleanup_error}")
            
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
        if device_config == 'auto':
            if torch.cuda.is_available():
                return 'cuda'
            elif torch.backends.mps.is_available():
                return 'mps'
            else:
                return 'cpu'
        return device_config
    
    def list_trained_models(self) -> list:
        """列出所有训练好的模型（支持多个训练历史）"""
        models = []
        
        if not os.path.exists(self.models_dir):
            return models
        
        for project_id in os.listdir(self.models_dir):
            project_path = os.path.join(self.models_dir, project_id)
            if not os.path.isdir(project_path):
                continue
            
            # 先检查旧格式（根目录下的train_info.json）
            old_info_path = os.path.join(project_path, "train_info.json")
            if os.path.exists(old_info_path):
                try:
                    with open(old_info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                    info['display_name'] = f"{project_id} (旧版本)"
                    models.append(info)
                except Exception as e:
                    print(f"读取旧模型信息失败: {project_id}, 错误: {e}")
                
            # 遍历项目下的所有时间戳目录（新格式）
            for item in os.listdir(project_path):
                item_path = os.path.join(project_path, item)
                if not os.path.isdir(item_path):
                    continue
                    
                info_path = os.path.join(item_path, "train_info.json")
                if os.path.exists(info_path):
                    try:
                        with open(info_path, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                        # 添加显示名称，包含项目ID和时间戳
                        timestamp = info.get('timestamp', item)
                        info['display_name'] = f"{project_id} ({timestamp})"
                        models.append(info)
                    except Exception as e:
                        print(f"读取模型信息失败: {project_id}/{item}, 错误: {e}")
        
        return sorted(models, key=lambda x: x.get('trained_at', ''), reverse=True)
    
    def get_model_info(self, project_id: str) -> Optional[Dict]:
        """获取模型信息"""
        info_path = os.path.join(self.models_dir, project_id, "train_info.json")
        
        if not os.path.exists(info_path):
            return None
        
        with open(info_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def delete_model(self, project_id: str) -> bool:
        """删除训练好的模型"""
        model_dir = os.path.join(self.models_dir, project_id)
        
        if not os.path.exists(model_dir):
            return False
        
        try:
            import shutil
            shutil.rmtree(model_dir)
            return True
        except Exception as e:
            print(f"删除模型失败: {e}")
            return False

