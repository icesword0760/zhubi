// OmniParser 模型对比页面逻辑

const API_BASE = '';
let uploadedImageFile = null;
let logCount = 0;
let comparisonModelCounter = 0;  // 对比模型计数器
let availableYoloModels = [];    // 可用的YOLO模型列表
let availableFlorenceModels = []; // 可用的Florence-2模型列表

// 页面加载
document.addEventListener('DOMContentLoaded', () => {
    console.log('=== OmniParser 对比页面加载完成 ===');
    addComparisonLog('✅ 页面加载完成，正在初始化...', 'success');
    loadAvailableModels();
    setupDragAndDrop();
});

// ==================== 对比日志功能 ====================

function addComparisonLog(message, type = 'info') {
    const comparisonLog = document.getElementById('comparisonLog');
    const timestamp = new Date().toLocaleTimeString('zh-CN');
    
    const colors = {
        'info': '#3b82f6',
        'success': '#10b981',
        'warning': '#f59e0b',
        'error': '#ef4444'
    };
    
    const icons = {
        'info': 'ℹ️',
        'success': '✅',
        'warning': '⚠️',
        'error': '❌'
    };
    
    logCount++;
    document.getElementById('logCount').textContent = logCount;
    
    const entry = document.createElement('div');
    entry.style.cssText = `
        margin-bottom: 0.5rem;
        padding: 0.5rem;
        background: rgba(55, 65, 81, 0.5);
        border-radius: 0.25rem;
        border-left: 3px solid ${colors[type] || colors['info']};
    `;
    entry.innerHTML = `
        <span style="color: #9ca3af;">[${timestamp}]</span>
        <span style="margin: 0 0.25rem;">${icons[type] || '📝'}</span>
        <span style="color: ${colors[type] || colors['info']};">${message}</span>
    `;
    
    // 如果是第一条日志，清空"等待开始对比..."提示
    if (logCount === 1) {
        comparisonLog.innerHTML = '';
    }
    
    comparisonLog.appendChild(entry);
    comparisonLog.scrollTop = comparisonLog.scrollHeight;
    
    // 同时输出到console
    console.log(`[${timestamp}] ${message}`);
}

function clearComparisonLog() {
    document.getElementById('comparisonLog').innerHTML = '<div style="color: #9ca3af;">等待开始对比...</div>';
    logCount = 0;
    document.getElementById('logCount').textContent = '0';
}

// 设置拖拽上传
function setupDragAndDrop() {
    const uploadZone = document.getElementById('uploadZone');
    
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.style.borderColor = '#3b82f6';
        uploadZone.style.background = '#eff6ff';
    });
    
    uploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        if (!uploadZone.classList.contains('has-image')) {
            uploadZone.style.borderColor = '#d1d5db';
            uploadZone.style.background = '#f9fafb';
        }
    });
    
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type.startsWith('image/')) {
            handleImageFile(files[0]);
        }
    });
}

// 处理图片上传
function handleImageUpload(event) {
    const file = event.target.files[0];
    if (file) {
        handleImageFile(file);
    }
}

// 处理图片文件
function handleImageFile(file) {
    uploadedImageFile = file;
    
    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('previewImg').src = e.target.result;
        document.getElementById('uploadPrompt').style.display = 'none';
        document.getElementById('imagePreview').style.display = 'block';
        document.getElementById('uploadZone').classList.add('has-image');
        
        // 显示模型选择区域
        document.getElementById('modelsSection').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

// 更新参数显示值
function updateParamValue(type, value) {
    const displays = {
        'box': 'boxValue',
        'iou': 'iouValue',
        'imgsz': 'imgszValue',
        'temperature': 'temperatureValue',
        'repetitionPenalty': 'repetitionPenaltyValue'
    };
    
    if (displays[type]) {
        document.getElementById(displays[type]).textContent = value;
    }
}

// 加载可用模型
async function loadAvailableModels() {
    try {
        addComparisonLog('📡 正在加载可用模型列表...', 'info');
        
        // 加载YOLO模型
        const yoloModelsResponse = await fetch(`${API_BASE}/api/yolo/models`);
        const yoloData = await yoloModelsResponse.json();
        
        // 加载Florence-2模型
        const florenceModelsResponse = await fetch(`${API_BASE}/api/models`);
        const florenceData = await florenceModelsResponse.json();
        
        addComparisonLog(`📥 YOLO模型: ${yoloData.models?.length || 0} 个`, 'info');
        addComparisonLog(`📥 Florence-2模型: ${florenceData.models?.length || 0} 个`, 'info');
        
        // 保存模型数据供动态添加使用
        availableYoloModels = yoloData.models || [];
        availableFlorenceModels = florenceData.models || [];
        
        const baseYoloSelect = document.getElementById('baseYoloSelect');
        const baseFlorence2Select = document.getElementById('baseFlorence2Select');
        
        // ===== 基础模型 - YOLO =====
        baseYoloSelect.innerHTML = '<option value="">-- 选择YOLO模型 --</option>';
        baseYoloSelect.innerHTML += '<option value="weights/icon_detect/model.pt" selected>icon_detect (默认)</option>';
        
        // 添加训练的YOLO模型到基础选项
        if (availableYoloModels.length > 0) {
            availableYoloModels.forEach(model => {
                baseYoloSelect.innerHTML += `<option value="${model.path}">${model.name || model.project_id}</option>`;
            });
        }
        
        // ===== 基础模型 - Florence-2 =====
        baseFlorence2Select.innerHTML = '<option value="">-- 选择Florence-2模型 --</option>';
        baseFlorence2Select.innerHTML += '<option value="weights/icon_caption_florence" selected>icon_caption_florence (默认)</option>';
        
        // 添加训练的Florence-2模型到基础选项
        if (availableFlorenceModels.length > 0) {
            availableFlorenceModels.forEach(model => {
                const modelPath = model.model_path || model.path;
                const modelName = model.project_id || 'Unknown';
                const trainDate = model.trained_at ? new Date(model.trained_at).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
                const lossText = model.final_loss ? ` [Loss: ${model.final_loss.toFixed(4)}]` : '';
                baseFlorence2Select.innerHTML += `<option value="${modelPath}">${modelName} ${trainDate ? '(' + trainDate + ')' : ''}${lossText}</option>`;
            });
        }
        
        // 自动添加第一个对比模型槽位
        addComparisonModel();
        
        addComparisonLog(`✅ 成功加载所有模型`, 'success');
        console.log('模型加载完成:', {
            yoloCount: availableYoloModels.length,
            florenceCount: availableFlorenceModels.length
        });
    } catch (error) {
        addComparisonLog(`💥 加载模型异常: ${error.message}`, 'error');
        console.error('加载模型列表失败:', error);
        showNotification('error', '加载失败', '无法加载模型列表');
    }
}

// ==================== 动态添加/删除对比模型 ====================

function addComparisonModel() {
    const container = document.getElementById('comparisonModelsContainer');
    const modelId = ++comparisonModelCounter;
    
    const modelDiv = document.createElement('div');
    modelDiv.id = `comparisonModel_${modelId}`;
    modelDiv.className = 'comparison-model-slot';
    modelDiv.style.cssText = `
        margin-bottom: 1.5rem;
        padding: 1rem;
        background: #f9fafb;
        border-radius: 0.5rem;
        border: 2px solid #e5e7eb;
        position: relative;
    `;
    
    // 构建YOLO选项
    let yoloOptions = '<option value="">-- 不选则使用基础模型 --</option>';
    availableYoloModels.forEach(model => {
        yoloOptions += `<option value="${model.path}">${model.name || model.project_id} (训练)</option>`;
    });
    
    // 构建Florence-2选项
    let florenceOptions = '<option value="">-- 不选则使用基础模型 --</option>';
    availableFlorenceModels.forEach(model => {
        const modelPath = model.model_path || model.path;
        const modelName = model.project_id || 'Unknown';
        const trainDate = model.trained_at ? new Date(model.trained_at).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
        const lossText = model.final_loss ? ` [Loss: ${model.final_loss.toFixed(4)}]` : '';
        florenceOptions += `<option value="${modelPath}">${modelName} ${trainDate ? '(' + trainDate + ')' : ''}${lossText}</option>`;
    });
    
    modelDiv.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
            <h5 style="margin: 0; font-weight: 600; color: #374151;">
                <span style="background: #3b82f6; color: white; padding: 0.25rem 0.5rem; border-radius: 0.25rem; margin-right: 0.5rem;">对比 ${modelId}</span>
            </h5>
            ${modelId > 1 ? `<button onclick="removeComparisonModel(${modelId})" class="btn btn-sm" style="background: #ef4444; color: white; padding: 0.375rem 0.75rem; border-radius: 0.25rem; border: none; cursor: pointer; font-size: 0.875rem;">
                ❌ 移除
            </button>` : ''}
        </div>
        
        <div style="margin-bottom: 1rem;">
            <label style="display: block; font-weight: 600; margin-bottom: 0.5rem; color: #374151;">
                🎯 YOLO 检测模型（可选）
            </label>
            <select id="trainedYoloSelect_${modelId}" class="form-control trained-yolo-select" style="width: 100%; padding: 0.75rem; border-radius: 0.375rem; border: 1px solid #d1d5db;">
                ${yoloOptions}
            </select>
            <small style="color: #6b7280; margin-top: 0.25rem; display: block;">可选，不选则使用基础YOLO</small>
        </div>
        
        <div>
            <label style="display: block; font-weight: 600; margin-bottom: 0.5rem; color: #374151;">
                🖼️ Florence-2 识别模型（可选）
            </label>
            <select id="trainedFlorence2Select_${modelId}" class="form-control trained-florence-select" style="width: 100%; padding: 0.75rem; border-radius: 0.375rem; border: 1px solid #d1d5db;">
                ${florenceOptions}
            </select>
            <small style="color: #6b7280; margin-top: 0.25rem; display: block;">可选，不选则使用基础Florence-2</small>
        </div>
    `;
    
    container.appendChild(modelDiv);
    addComparisonLog(`➕ 添加了对比模型槽位 #${modelId}`, 'info');
}

function removeComparisonModel(modelId) {
    const modelDiv = document.getElementById(`comparisonModel_${modelId}`);
    if (modelDiv) {
        modelDiv.remove();
        addComparisonLog(`➖ 移除了对比模型槽位 #${modelId}`, 'warning');
    }
}

// 开始对比（多模型版本）
async function startComparison() {
    addComparisonLog('🚀 开始多模型对比流程', 'info');
    
    // 验证输入
    if (!uploadedImageFile) {
        addComparisonLog('❌ 未上传图片', 'error');
        showNotification('warning', '请上传图片', '请先上传要测试的屏幕截图');
        return;
    }
    
    // 获取基础模型（必选）
    const baseYolo = document.getElementById('baseYoloSelect').value;
    const baseFlorence2 = document.getElementById('baseFlorence2Select').value;
    
    if (!baseYolo || !baseFlorence2) {
        addComparisonLog('❌ 未选择基础模型', 'error');
        showNotification('warning', '请选择基础模型', '请选择完整的基础模型组（YOLO + Florence-2）');
        return;
    }
    
    // 收集所有对比模型配置
    const comparisonModels = [];
    const allSlots = document.querySelectorAll('.comparison-model-slot');
    
    allSlots.forEach((slot, index) => {
        const slotId = slot.id.replace('comparisonModel_', '');
        const yoloSelect = document.getElementById(`trainedYoloSelect_${slotId}`);
        const florenceSelect = document.getElementById(`trainedFlorence2Select_${slotId}`);
        
        if (yoloSelect && florenceSelect) {
            const trainedYolo = yoloSelect.value || baseYolo;
            const trainedFlorence2 = florenceSelect.value || baseFlorence2;
            
            comparisonModels.push({
                id: slotId,
                yolo: trainedYolo,
                florence2: trainedFlorence2,
                name: `对比模型 ${slotId}`
            });
        }
    });
    
    if (comparisonModels.length === 0) {
        addComparisonLog('❌ 未配置对比模型', 'error');
        showNotification('warning', '请添加对比模型', '请至少添加一个对比模型配置');
        return;
    }
    
    addComparisonLog(`📦 基础YOLO: ${baseYolo}`, 'info');
    addComparisonLog(`📦 基础Florence-2: ${baseFlorence2}`, 'info');
    addComparisonLog(`✨ 共配置了 ${comparisonModels.length} 个对比模型`, 'info');
    
    // 获取参数
    const params = {
        box_threshold: parseFloat(document.getElementById('boxThreshold').value),
        iou_threshold: parseFloat(document.getElementById('iouThreshold').value),
        imgsz: parseInt(document.getElementById('imgsz').value),
        use_paddleocr: document.getElementById('usePaddleOCR').checked,
        temperature: parseFloat(document.getElementById('temperature').value),
        repetition_penalty: parseFloat(document.getElementById('repetitionPenalty').value)
    };
    
    // 显示加载中
    showLoading();
    updateProgress(0, '准备处理...');
    
    try {
        // 1. 处理基础模型组
        const progressBase = 10;
        updateProgress(progressBase, '📦 处理基础模型组（YOLO + Florence-2）...');
        const baseResult = await processWithOmniParser(
            uploadedImageFile, 
            baseYolo,
            baseFlorence2,
            params,
            '基础模型'
        );
        
        if (!baseResult.success) {
            throw new Error('基础模型处理失败');
        }
        
        const baseContents = extractContents(baseResult.parsed_content_list || []);
        addComparisonLog(`✅ 基础模型完成（检测到 ${baseContents.length} 个图标）`, 'success');
        
        // 2. 逐个处理对比模型
        const comparisonResults = [];
        const progressStep = 80 / comparisonModels.length;
        
        for (let i = 0; i < comparisonModels.length; i++) {
            const model = comparisonModels[i];
            const currentProgress = progressBase + (i + 1) * progressStep;
            
            updateProgress(currentProgress, `✨ 处理 ${model.name}...`);
            addComparisonLog(`📡 正在处理 ${model.name}`, 'info');
            
            const result = await processWithOmniParser(
                uploadedImageFile,
                model.yolo,
                model.florence2,
                params,
                model.name
            );
            
            if (result.success) {
                const contents = extractContents(result.parsed_content_list || []);
                comparisonResults.push({
                    model: model,
                    result: result,
                    contents: contents
                });
                addComparisonLog(`✅ ${model.name} 完成（检测到 ${contents.length} 个图标）`, 'success');
            } else {
                addComparisonLog(`❌ ${model.name} 处理失败`, 'error');
            }
        }
        
        updateProgress(95, '📊 分析对比结果...');
        
        // 3. 显示所有结果
        displayMultipleResults(baseResult, comparisonResults);
        
        // 4. 生成对比统计
        addComparisonLog('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'info');
        addComparisonLog('📊 多模型对比统计汇总', 'success');
        addComparisonLog(`📦 基础模型: ${baseContents.length} 个图标`, 'info');
        
        comparisonResults.forEach((item, index) => {
            const contentDiff = compareContents(baseContents, item.contents);
            const numDiff = item.contents.length - baseContents.length;
            
            let diffMsg = `✨ ${item.model.name}: ${item.contents.length} 个图标 (`;
            if (numDiff > 0) {
                diffMsg += `+${numDiff}`;
            } else if (numDiff < 0) {
                diffMsg += `${numDiff}`;
            } else {
                diffMsg += `±0`;
            }
            diffMsg += `)`;
            
            addComparisonLog(diffMsg, 'info');
            
            // 详细差异
            if (contentDiff.onlyB > 0) {
                addComparisonLog(`  ➕ 新增: ${contentDiff.onlyB}个`, 'info');
            }
            if (contentDiff.onlyA > 0) {
                addComparisonLog(`  ➖ 缺失: ${contentDiff.onlyA}个`, 'warning');
            }
            if (contentDiff.same > 0) {
                addComparisonLog(`  ✓ 相同: ${contentDiff.same}个`, 'success');
            }
        });
        
        addComparisonLog('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'info');
        
        updateProgress(100, '完成！');
        hideLoading();
        
        showNotification('success', '对比完成', `已完成 ${comparisonResults.length} 个模型的对比分析`);
    } catch (error) {
        hideLoading();
        addComparisonLog(`💥 异常错误: ${error.message}`, 'error');
        console.error('对比失败:', error);
        showNotification('error', '对比失败', error.message);
    }
}

// 提取内容列表（处理嵌套结构）
function extractContents(parsedList) {
    const contents = [];
    
    function extract(item) {
        if (Array.isArray(item)) {
            item.forEach(extract);
        } else if (typeof item === 'object' && item !== null) {
            if (item.content) {
                contents.push(item.content.trim());
            }
        } else if (typeof item === 'string') {
            contents.push(item.trim());
        }
    }
    
    extract(parsedList);
    return contents;
}

// 比较两个内容列表
function compareContents(contentsA, contentsB) {
    const setA = new Set(contentsA);
    const setB = new Set(contentsB);
    
    let same = 0;
    let onlyA = 0;
    let onlyB = 0;
    
    // 统计相同的
    for (const content of contentsA) {
        if (setB.has(content)) {
            same++;
        } else {
            onlyA++;
        }
    }
    
    // 统计仅在B中的
    for (const content of contentsB) {
        if (!setA.has(content)) {
            onlyB++;
        }
    }
    
    return { same, onlyA, onlyB };
}

// 使用OmniParser处理图片
async function processWithOmniParser(imageFile, yoloPath, florence2Path, params, modelLabel) {
    addComparisonLog(`📡 处理 ${modelLabel}...`, 'info');
    console.log(`处理 ${modelLabel}:`, { yoloPath, florence2Path });
    
    const formData = new FormData();
    formData.append('image', imageFile);
    formData.append('yolo_model_path', yoloPath);
    formData.append('florence2_model_path', florence2Path);
    formData.append('box_threshold', params.box_threshold);
    formData.append('iou_threshold', params.iou_threshold);
    formData.append('imgsz', params.imgsz);
    formData.append('use_paddleocr', params.use_paddleocr);
    formData.append('temperature', params.temperature);
    formData.append('repetition_penalty', params.repetition_penalty);
    
    const response = await fetch(`${API_BASE}/api/omniparser/process`, {
        method: 'POST',
        body: formData
    });
    
    if (!response.ok) {
        const errorText = await response.text();
        addComparisonLog(`❌ ${modelLabel}处理失败: ${errorText.substring(0, 100)}`, 'error');
        throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 200)}`);
    }
    
    const data = await response.json();
    
    if (!data.success) {
        addComparisonLog(`❌ ${modelLabel}返回错误: ${data.error}`, 'error');
        throw new Error(data.error || '处理失败');
    }
    
    addComparisonLog(`✅ ${modelLabel}处理完成（检测到 ${data.total_icons || 0} 个图标）`, 'success');
    
    return data;
}

// 显示结果
// 显示多模型对比结果
function displayMultipleResults(baseResult, comparisonResults) {
    const resultsSection = document.getElementById('resultsSection');
    
    // 清空并重新构建结果区域
    resultsSection.innerHTML = `
        <h3 style="margin: 0 0 1.5rem 0; font-size: 1.5rem; font-weight: 700;">📊 对比结果</h3>
        <div id="multiResultsGrid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 1.5rem;"></div>
    `;
    
    const grid = document.getElementById('multiResultsGrid');
    
    // 添加基础模型结果
    const baseCard = createResultCard('📦 基础模型', baseResult, 'base');
    grid.appendChild(baseCard);
    
    // 添加对比模型结果
    comparisonResults.forEach((item, index) => {
        const card = createResultCard(`✨ ${item.model.name}`, item.result, `comparison_${index}`);
        grid.appendChild(card);
    });
    
    // 显示结果区域
    resultsSection.style.display = 'block';
    
    // 滚动到结果
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 创建结果卡片
function createResultCard(title, result, id) {
    const card = document.createElement('div');
    card.style.cssText = `
        background: white;
        border-radius: 0.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        overflow: hidden;
        border: 2px solid ${id === 'base' ? '#3b82f6' : '#10b981'};
    `;
    
    const contents = extractContents(result.parsed_content_list || []);
    const iconCount = contents.length;
    
    card.innerHTML = `
        <div style="background: ${id === 'base' ? '#eff6ff' : '#f0fdf4'}; padding: 1rem; border-bottom: 2px solid ${id === 'base' ? '#3b82f6' : '#10b981'};">
            <h4 style="margin: 0; font-weight: 600; color: ${id === 'base' ? '#1e40af' : '#065f46'};">${title}</h4>
            <div style="margin-top: 0.5rem; font-size: 0.875rem; color: ${id === 'base' ? '#1e40af' : '#065f46'};">
                检测到 ${iconCount} 个图标
            </div>
        </div>
        <div style="padding: 1rem;">
            <img src="data:image/png;base64,${result.image}" style="width: 100%; border-radius: 0.375rem; margin-bottom: 1rem;">
            <details ${id === 'base' ? 'open' : ''}>
                <summary style="cursor: pointer; font-weight: 600; color: #374151; padding: 0.5rem; background: #f9fafb; border-radius: 0.25rem;">
                    📋 查看解析元素 (${iconCount})
                </summary>
                <pre style="margin-top: 0.5rem; padding: 0.75rem; background: #1f2937; color: #f3f4f6; border-radius: 0.25rem; overflow-x: auto; font-size: 0.75rem; line-height: 1.5;">${result.parsed_content || '无解析结果'}</pre>
            </details>
        </div>
    `;
    
    return card;
}

function displayResults(resultA, resultB) {
    // 显示图片
    if (resultA.image) {
        document.getElementById('resultImageA').src = `data:image/png;base64,${resultA.image}`;
    }
    if (resultB.image) {
        document.getElementById('resultImageB').src = `data:image/png;base64,${resultB.image}`;
    }
    
    // 显示解析元素
    document.getElementById('parsedElementsA').textContent = resultA.parsed_content || '无解析结果';
    document.getElementById('parsedElementsB').textContent = resultB.parsed_content || '无解析结果';
    
    // 显示结果区域
    document.getElementById('resultsSection').style.display = 'block';
    
    // 滚动到结果
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 显示加载中
function showLoading() {
    const btn = document.getElementById('startComparisonBtn');
    if (btn) {
        btn.disabled = true;
        btn.style.opacity = '0.6';
        btn.style.cursor = 'not-allowed';
        btn.innerHTML = '<span style="font-size: 1.25rem;">⏳</span> 处理中...';
    }
    
    // 显示进度条
    const progressSection = document.getElementById('progressSection');
    if (progressSection) {
        progressSection.style.display = 'block';
    }
}

// 隐藏加载中
function hideLoading() {
    const btn = document.getElementById('startComparisonBtn');
    if (btn) {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
        btn.innerHTML = '<span style="font-size: 1.25rem;">🚀</span> 开始 OmniParser 对比';
    }
    
    // 保持进度条显示（显示完成状态）
}

// 更新进度
function updateProgress(percent, text) {
    const progressSection = document.getElementById('progressSection');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const progressPercent = document.getElementById('progressPercent');
    
    // 显示进度条区域
    if (progressSection) {
        progressSection.style.display = 'block';
    }
    
    if (progressBar) {
        progressBar.style.width = `${percent}%`;
    }
    
    if (progressPercent) {
        progressPercent.textContent = `${percent}%`;
    }
    
    if (progressText && text) {
        progressText.textContent = text;
    }
    
    addComparisonLog(`📊 进度: ${percent}% - ${text}`, 'info');
}

// 显示通知
function showNotification(type, title, message) {
    const colors = {
        'success': 'linear-gradient(135deg, #10b981, #059669)',
        'info': 'linear-gradient(135deg, #3b82f6, #2563eb)',
        'warning': 'linear-gradient(135deg, #f59e0b, #d97706)',
        'error': 'linear-gradient(135deg, #ef4444, #dc2626)'
    };
    
    const icons = {
        'success': '✅',
        'info': 'ℹ️',
        'warning': '⚠️',
        'error': '❌'
    };
    
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${colors[type] || colors['info']};
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 0.75rem;
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
        max-width: 400px;
        font-size: 0.875rem;
    `;
    
    notification.innerHTML = `
        <div style="display: flex; align-items: start; gap: 0.75rem;">
            <span style="font-size: 1.25rem;">${icons[type]}</span>
            <div style="flex: 1;">
                <div style="font-weight: 700; margin-bottom: 0.25rem;">${title}</div>
                <div style="opacity: 0.95;">${message}</div>
            </div>
            <button onclick="this.parentElement.parentElement.remove()" 
                    style="background: rgba(255,255,255,0.2); border: none; color: white; 
                           padding: 0.25rem 0.5rem; border-radius: 0.25rem; cursor: pointer;">✕</button>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        if (notification.parentElement) {
            notification.style.animation = 'slideOut 0.3s ease-in';
            setTimeout(() => notification.remove(), 300);
        }
    }, 3000);
}

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

