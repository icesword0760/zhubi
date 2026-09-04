# 模型训练完整指南

## 📋 概述

本系统现已支持**YOLO**和**Florence-2**两种模型的增量训练，并提供完整的训练进度监控和模型验证对比功能。

## ✨ 核心功能

### 1. 双模型训练支持

#### 🎯 YOLO训练
- **用途**: 目标检测（边界框识别）
- **数据格式**: YOLO格式（原图 + 标注文件）
- **特点**:
  - 快速训练
  - 高精度检测
  - 支持多种backbone（YOLOv8n/s/m/l/x）
  - 实时进度报告

#### 🖼️ Florence-2训练
- **用途**: 视觉语言模型（图标理解和描述）
- **数据格式**: Florence-2格式（裁切图标 + JSONL标注）
- **特点**:
  - LoRA低秩适配
  - 参数高效微调
  - 多模态理解
  - 实时进度报告

### 2. 训练进度监控

#### 可视化进度条
- 实时显示训练进度（0-100%）
- 不同阶段颜色变化：
  - 蓝色：训练中
  - 绿色：训练完成
  - 红色：训练出错

#### 详细日志输出
- 数据加载状态
- 模型加载信息
- 每个epoch的损失
- 最终指标（mAP、Loss等）
- 错误追踪

### 3. 模型验证对比

#### 功能特性
- 上传测试图片
- 选择基础模型和微调模型
- 并行推理对比
- 可视化结果展示
- 检测数量统计
- 性能对比分析

#### 对比指标
- 检测框可视化
- 检测数量对比
- 置信度对比
- 标签准确性

## 🚀 使用流程

### 步骤1: 准备数据

#### 对于YOLO训练
1. 在标注页面完成标注
2. 导出YOLO格式数据
3. 系统自动生成：
   ```
   yolo_data/
   ├── images/
   │   ├── train/
   │   └── val/
   ├── labels/
   │   ├── train/
   │   └── val/
   └── data.yaml
   ```

#### 对于Florence-2训练
1. 在标注页面完成标注
2. 导出Florence-2格式数据
3. 系统自动生成：
   ```
   florence2_data/
   ├── cropped_icons/
   ├── train.jsonl
   └── val.jsonl
   ```

### 步骤2: 配置训练

#### YOLO配置建议
```yaml
训练轮数: 50-100
批次大小: 16 (根据显存调整)
学习率: 0.01
设备: auto (自动选择GPU/MPS/CPU)
```

#### Florence-2配置建议
```yaml
训练轮数: 10-20
批次大小: 4 (根据显存调整)
学习率: 1e-6 ~ 5e-6
LoRA配置:
  - Rank (r): 8
  - Alpha: 8
设备: auto
```

### 步骤3: 启动训练

1. 选择模型类型（YOLO / Florence-2）
2. 选择项目
3. 配置训练参数
4. 点击"🚀 开始训练"
5. 观察进度条和日志输出

### 步骤4: 验证效果

1. 在右侧"模型验证"区域上传测试图片
2. 选择基础模型（预训练）
3. 选择微调模型（训练后）
4. 点击"🔍 开始对比验证"
5. 查看可视化对比结果

## 📊 训练参数详解

### YOLO参数

| 参数 | 说明 | 推荐值 | 范围 |
|------|------|--------|------|
| epochs | 训练轮数 | 50-100 | 1-500 |
| batch_size | 批次大小 | 16 | 1-64 |
| img_size | 图片尺寸 | 640 | 320-1280 |
| learning_rate | 学习率 | 0.01 | 0.001-0.1 |
| patience | 早停轮数 | 20 | 5-50 |

### Florence-2参数

| 参数 | 说明 | 推荐值 | 范围 |
|------|------|--------|------|
| epochs | 训练轮数 | 10-20 | 1-100 |
| batch_size | 批次大小 | 4 | 1-32 |
| learning_rate | 学习率 | 1e-6 | 1e-7 ~ 1e-5 |
| lora_r | LoRA秩 | 8 | 1-64 |
| lora_alpha | LoRA alpha | 8 | 1-64 |

## 🎯 最佳实践

### 数据准备
- ✅ 确保标注质量（边界框准确、类别正确）
- ✅ 训练集:验证集 = 7:3 或 8:2
- ✅ 数据均衡（每个类别至少20-50张）
- ✅ 图片分辨率一致性

### 训练策略
- ✅ 从小模型开始（YOLOv8n, Florence-2-base）
- ✅ 使用LoRA进行Florence-2微调（节省显存）
- ✅ 观察验证集损失，防止过拟合
- ✅ 保存多个checkpoint以备选择

### 验证测试
- ✅ 使用未见过的测试图片
- ✅ 多样化测试场景
- ✅ 对比训练前后效果
- ✅ 记录关键指标

## 💡 常见问题

### Q1: 显存不足怎么办？
**A**: 
- 减小batch_size（YOLO: 8-4, Florence: 2-1）
- 使用LoRA（Florence-2）
- 降低图片分辨率（YOLO）
- 使用CPU训练（较慢）

### Q2: 训练效果不理想？
**A**: 
- 检查标注质量
- 增加训练数据
- 调整学习率
- 延长训练轮数
- 尝试数据增强

### Q3: 如何选择合适的学习率？
**A**: 
- YOLO: 从0.01开始，观察损失曲线
- Florence-2: 从1e-6开始，逐步调整
- 如果损失震荡，降低学习率
- 如果损失下降慢，提高学习率

### Q4: 训练中断后能否继续？
**A**: 
- YOLO: 会自动保存checkpoint
- Florence-2: 每N步保存一次
- 可从断点继续训练

### Q5: 如何部署训练好的模型？
**A**: 
```bash
# YOLO模型
cp data/models/{project_id}/yolo_final_model/best.pt \
   ../weights/icon_detect/model.pt

# Florence-2模型
cp -r data/models/{project_id}/final_model \
   ../weights/icon_caption_florence_custom
```

## 📈 性能优化建议

### 硬件配置
- **推荐**: NVIDIA GPU（8GB+ 显存）
- **可选**: Apple Silicon M1/M2/M3（MPS加速）
- **最低**: CPU（训练较慢）

### 训练加速技巧
1. 使用混合精度训练（fp16）
2. 启用梯度累积
3. 使用预训练模型权重
4. 优化数据加载（多进程）
5. 缓存数据到内存

## 🔧 技术架构

### 后端模块
- `backend/yolo_train_manager.py`: YOLO训练管理
- `backend/train_manager.py`: Florence-2训练管理
- `backend/model_validator.py`: 模型验证对比

### 前端界面
- `frontend/train.html`: 训练和验证UI
- `frontend/js/train.js`: 交互逻辑

### API端点
- `POST /api/projects/{id}/train`: 启动训练
- `POST /api/models/validate`: 单模型验证
- `POST /api/models/compare`: 双模型对比

## 📝 示例输出

### YOLO训练日志
```
📦 正在准备YOLO训练...
✅ 数据集配置已加载
✅ 训练集: 150 张图片
✅ 验证集: 50 张图片
🤖 正在加载基础模型: yolov8n.pt
✅ 加载预训练模型: yolov8n.pt
🖥️ 使用设备: mps
⚙️ 训练参数:
  - Epochs: 50
  - Batch Size: 16
  - Image Size: 640
  - Patience: 20
🚀 开始训练...
📊 Epoch 1/50 - Loss: 0.8523
📊 Epoch 2/50 - Loss: 0.6234
...
✅ 训练完成！
📊 最终指标:
  - mAP50: 0.8765
  - mAP50-95: 0.6543
  - Precision: 0.8432
  - Recall: 0.8210
💾 模型已保存到: data/models/{project_id}/yolo_final_model
🎉 YOLO训练全部完成！
```

### Florence-2训练日志
```
📦 正在加载数据集...
✅ 加载训练样本: 120张
✅ 加载验证样本: 30张
🤖 正在加载Florence-2模型...
🖥️ 使用设备: mps
✅ 模型加载完成
🔧 配置LoRA低秩适配...
✅ 可训练参数: 8,388,608 / 232,000,000 (3.62%)
📊 准备训练数据集...
✅ 数据集准备完成
⚙️ 配置训练参数...
✅ Epochs: 10
✅ Batch Size: 4
✅ Learning Rate: 1e-06
🚀 开始训练...
✅ 训练完成！
📊 最终训练损失: 0.1234
💾 模型已保存到: data/models/{project_id}/final_model
✅ 训练信息已保存
🎉 全部完成！
```

## 🎓 进阶技巧

### 超参数调优
- 使用网格搜索找最优参数
- 记录每次实验结果
- 关注验证集指标

### 数据增强
- 随机翻转、旋转
- 颜色抖动
- 随机裁剪
- Mosaic拼接（YOLO）

### 集成学习
- 训练多个模型
- 结果投票或平均
- 提高鲁棒性

## 📚 参考资源

- [YOLO官方文档](https://docs.ultralytics.com/)
- [Florence-2论文](https://arxiv.org/abs/2311.06242)
- [LoRA原理](https://arxiv.org/abs/2106.09685)
- [Hugging Face PEFT](https://huggingface.co/docs/peft)

---

**提示**: 训练过程中请保持耐心，观察日志和进度，及时调整策略。祝训练顺利！🚀

