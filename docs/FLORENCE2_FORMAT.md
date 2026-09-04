# Florence-2 数据格式说明

## 问题分析

您导出的数据格式**存在问题**，已修复。

## ❌ 错误格式（修复前）

```json
{"image": "images/xxx.jpg", "prefix": "<OD>", "suffix": "<loc_220><loc_423><loc_400><loc_498>抖音<loc_619><loc_415><loc_795><loc_499>icon"}
```

**问题**：类别名称没有用尖括号包裹。

## ✅ 正确格式（修复后）

```json
{"image": "images/xxx.jpg", "prefix": "<OD>", "suffix": "<loc_220><loc_423><loc_400><loc_498><抖音><loc_619><loc_415><loc_795><loc_499><icon>"}
```

**修复内容**：类别名称现在被尖括号包裹：`<抖音>` 和 `<icon>`

## 📋 Florence-2 格式详解

### 格式1：对象检测（原图 + 标注框）

**用途**：从大图中检测多个对象及其位置

**格式**：
```json
{
  "image": "images/screenshot.jpg",
  "prefix": "<OD>",
  "suffix": "<loc_x1><loc_y1><loc_x2><loc_y2><类别1><loc_x3><loc_y3><loc_x4><loc_y4><类别2>..."
}
```

**说明**：
- `prefix`: `<OD>` 表示 Object Detection 任务
- `suffix`: 包含多个检测结果
  - `<loc_x1><loc_y1><loc_x2><loc_y2>`: 归一化坐标（0-999）
  - `<类别名>`: 用尖括号包裹的类别名称
- 坐标计算：`loc = int((pixel / image_dimension) * 999)`

**示例**：
```json
{
  "image": "images/screen.jpg",
  "prefix": "<OD>",
  "suffix": "<loc_220><loc_423><loc_400><loc_498><抖音><loc_619><loc_415><loc_795><loc_499><icon>"
}
```

### 格式2：图像描述（裁切图标）

**用途**：识别单个图标/图像的类别

**格式**：
```json
{
  "image": "images/icon_douyin.png",
  "prefix": "<CAPTION>",
  "suffix": "抖音"
}
```

**说明**：
- `prefix`: `<CAPTION>` 表示图像描述任务
- `suffix`: 直接是类别名称（不需要尖括号，因为没有坐标）
- 适用于已经裁切好的单个图标

## 🔧 修复内容

### 修改的文件

**backend/export_manager.py**

修复前（第316行）：
```python
suffix_parts.append(
    f"<loc_{x1}><loc_{y1}><loc_{x2}><loc_{y2}>{category}"
)
```

修复后：
```python
# Florence-2格式：类别名称需要用尖括号包裹
suffix_parts.append(
    f"<loc_{x1}><loc_{y1}><loc_{x2}><loc_{y2}><{category}>"
)
```

## 📊 两种格式的对比

| 特性 | 对象检测格式 (<OD>) | 图像描述格式 (<CAPTION>) |
|------|-------------------|------------------------|
| **prefix** | `<OD>` | `<CAPTION>` |
| **suffix** | `<loc_x><loc_y><loc_x><loc_y><类别>...` | `类别名称` |
| **坐标信息** | 需要（归一化到0-999） | 不需要 |
| **类别括号** | 需要 `<类别>` | 不需要 |
| **适用场景** | 从大图检测多个对象 | 识别单个图标 |
| **图像类型** | 完整UI截图 | 裁切的图标 |

## 🎯 使用建议

### 场景1：UI元素检测（推荐用 <OD>）
- 保留完整的UI截图
- 标注所有感兴趣的元素位置
- 导出为对象检测格式
- **优势**：可以检测位置和类别

### 场景2：图标分类（推荐用 <CAPTION>）
- 先裁切出单个图标
- 每个图标一张图
- 导出为图像描述格式
- **优势**：训练更快，识别更准确

### 场景3：混合方案（最佳）
1. 同时导出两种格式
2. <OD> 格式用于位置检测
3. <CAPTION> 格式用于细粒度识别
4. 结合使用，效果最佳

## ✅ 验证您的数据

### 正确的test.jsonl示例

**修复前**（错误）：
```json
{"image": "images/Screenshot_2025-06-19-14-49-40-592_com.huawei.app.jpg", "prefix": "<OD>", "suffix": "<loc_220><loc_423><loc_400><loc_498>抖音<loc_619><loc_415><loc_795><loc_499>icon"}
```

**修复后**（正确）：
```json
{"image": "images/Screenshot_2025-06-19-14-49-40-592_com.huawei.app.jpg", "prefix": "<OD>", "suffix": "<loc_220><loc_423><loc_400><loc_498><抖音><loc_619><loc_415><loc_795><loc_499><icon>"}
```

### 检查清单

- ✅ 每个类别名称都用尖括号包裹：`<类别>`
- ✅ 坐标标签格式正确：`<loc_数字>`
- ✅ 坐标值在0-999范围内
- ✅ prefix是 `<OD>`（对象检测）或 `<CAPTION>`（图像描述）
- ✅ 图像路径正确：`images/xxx.jpg`

## 🚀 重新导出

现在代码已修复，请：

1. **删除旧的导出数据**
2. **重新导出项目**
3. **验证新数据格式**

### 导出步骤

1. 访问 http://localhost:8000/export.html
2. 选择项目
3. 选择格式：Florence-2
4. 点击导出
5. 检查生成的 train.jsonl 和 test.jsonl

### 验证命令

```bash
# 查看导出的数据
cat exports/xxx/train.jsonl

# 应该看到类似这样的格式（注意尖括号）：
# {"image": "...", "prefix": "<OD>", "suffix": "<loc_220>...<抖音><loc_619>...<icon>"}
```

## 📝 训练注意事项

使用修复后的数据训练时：

1. ✅ 确保所有类别名称都有尖括号
2. ✅ 坐标归一化正确（0-999）
3. ✅ 图像路径可访问
4. ✅ JSONL文件UTF-8编码
5. ✅ 每行一个有效的JSON对象

## 🎓 参考资源

- [Florence-2 官方论文](https://arxiv.org/abs/2311.06242)
- [Florence-2 GitHub](https://github.com/microsoft/Florence)
- [Hugging Face 模型](https://huggingface.co/microsoft/Florence-2-large)

---

**修复时间**: 2026-01-19  
**影响范围**: 所有使用 `<OD>` 任务的Florence-2导出  
**兼容性**: 修复后的格式与Florence-2官方要求一致

