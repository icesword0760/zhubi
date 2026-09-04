// 模型验证页面逻辑

const API_BASE = '';
let uploadedImageFile = null;
let debugPanelVisible = false;
let logCount = 0;

// 页面加载
document.addEventListener('DOMContentLoaded', () => {
    console.log('=== 模型验证页面加载完成 ===');
    addValidationLog('✅ 页面加载完成，正在初始化...', 'success');
    addDebugLog('✅ 页面加载完成');
    loadAvailableModels();
    setupDragAndDrop();
});

// ==================== 验证日志功能 ====================

function addValidationLog(message, type = 'info') {
    const validationLog = document.getElementById('validationLog');
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
    
    // 如果是第一条日志，清空"等待开始验证..."提示
    if (logCount === 1) {
        validationLog.innerHTML = '';
    }
    
    validationLog.appendChild(entry);
    validationLog.scrollTop = validationLog.scrollHeight;
    
    // 同时输出到console
    console.log(`[${timestamp}] ${message}`);
}

function clearValidationLog() {
    document.getElementById('validationLog').innerHTML = '<div style="color: #9ca3af;">等待开始验证...</div>';
    logCount = 0;
    document.getElementById('logCount').textContent = '0';
}

// ==================== 调试日志功能（底部面板） ====================

function addDebugLog(message, type = 'info') {
    const debugLog = document.getElementById('debugLog');
    if (!debugLog) return;
    
    const timestamp = new Date().toLocaleTimeString('zh-CN');
    
    const colors = {
        'info': '#3b82f6',
        'success': '#10b981',
        'warning': '#f59e0b',
        'error': '#ef4444'
    };
    
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
        <span style="color: ${colors[type] || colors['info']};">${message}</span>
    `;
    
    debugLog.appendChild(entry);
    debugLog.scrollTop = debugLog.scrollHeight;
    
    // 同时输出到console
    console.log(`[${timestamp}] ${message}`);
}

function clearDebugLog() {
    document.getElementById('debugLog').innerHTML = '';
    addDebugLog('日志已清空', 'info');
}

function toggleDebugPanel() {
    const panel = document.getElementById('debugPanel');
    debugPanelVisible = !debugPanelVisible;
    panel.style.display = debugPanelVisible ? 'block' : 'none';
}

// ==================== 进度更新功能 ====================

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
    
    addValidationLog(`📊 进度: ${percent}% - ${text}`, 'info');
    addDebugLog(`📊 进度: ${percent}% - ${text}`, 'info');
}

function showLoading() {
    const btn = document.getElementById('startValidationBtn');
    if (btn) {
        btn.disabled = true;
        btn.style.opacity = '0.6';
        btn.style.cursor = 'not-allowed';
        btn.innerHTML = '<span style="font-size: 1.25rem;">⏳</span> 验证中...';
    }
    
    // 显示进度条
    const progressSection = document.getElementById('progressSection');
    if (progressSection) {
        progressSection.style.display = 'block';
    }
}

function hideLoading() {
    const btn = document.getElementById('startValidationBtn');
    if (btn) {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
        btn.innerHTML = '<span style="font-size: 1.25rem;">🚀</span> 开始对比验证';
    }
    
    // 保持进度条显示（显示完成状态）
}

// 设置拖拽上传
function setupDragAndDrop() {
    const uploadArea = document.getElementById('uploadArea');
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#3b82f6';
        uploadArea.style.background = '#eff6ff';
    });
    
    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        if (!uploadArea.classList.contains('has-image')) {
            uploadArea.style.borderColor = '#d1d5db';
            uploadArea.style.background = '#f9fafb';
        }
    });
    
    uploadArea.addEventListener('drop', (e) => {
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
    
    // 显示预览
    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('previewImage').src = e.target.result;
        document.getElementById('uploadPrompt').style.display = 'none';
        document.getElementById('imagePreview').style.display = 'block';
        document.getElementById('uploadArea').classList.add('has-image');
        
        // 显示模型选择区域
        document.getElementById('modelSelection').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

// 加载可用模型
async function loadAvailableModels() {
    try {
        addValidationLog('📡 正在加载可用模型列表...', 'info');
        addDebugLog('📡 正在加载可用模型列表...', 'info');
        
        // 加载YOLO模型
        const yoloResponse = await fetch(`${API_BASE}/api/yolo/models`);
        const yoloData = await yoloResponse.json();
        
        // 加载Florence-2模型
        const florenceResponse = await fetch(`${API_BASE}/api/models`);
        const florenceData = await florenceResponse.json();
        
        addValidationLog(`📥 YOLO模型: ${yoloData.models?.length || 0} 个`, 'info');
        addValidationLog(`📥 Florence-2模型: ${florenceData.models?.length || 0} 个`, 'info');
        
        // ===== 基础模型 - YOLO =====
        const baseYoloSelect = document.getElementById('baseYoloSelect');
        baseYoloSelect.innerHTML = '<option value="">-- 选择YOLO模型 --</option>';
        baseYoloSelect.innerHTML += '<option value="weights/icon_detect/model.pt" selected>icon_detect (默认)</option>';
        
        if (yoloData.success && yoloData.models && yoloData.models.length > 0) {
            yoloData.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.path;
                option.textContent = model.name || model.project_id || 'YOLO模型';
                baseYoloSelect.appendChild(option);
            });
        }
        
        // ===== 基础模型 - Florence-2 =====
        const baseFlorence2Select = document.getElementById('baseFlorence2Select');
        baseFlorence2Select.innerHTML = '<option value="">-- 选择Florence-2模型 --</option>';
        baseFlorence2Select.innerHTML += '<option value="weights/icon_caption_florence" selected>icon_caption_florence (默认)</option>';
        
        if (florenceData.success && florenceData.models && florenceData.models.length > 0) {
            florenceData.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.model_path || model.path;
                const modelName = model.project_id || 'Florence-2模型';
                const trainDate = model.trained_at ? new Date(model.trained_at).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
                option.textContent = `${modelName} ${trainDate ? '(' + trainDate + ')' : ''}`;
                baseFlorence2Select.appendChild(option);
            });
        }
        
        // ===== 微调模型 - YOLO（可选） =====
        const trainedYoloSelect = document.getElementById('trainedYoloSelect');
        trainedYoloSelect.innerHTML = '<option value="" selected>-- 不选则使用基础模型 --</option>';
        
        if (yoloData.success && yoloData.models && yoloData.models.length > 0) {
            yoloData.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.path;
                option.textContent = `${model.name || model.project_id || 'YOLO模型'} (训练)`;
                trainedYoloSelect.appendChild(option);
            });
        }
        
        // ===== 微调模型 - Florence-2（可选） =====
        const trainedFlorence2Select = document.getElementById('trainedFlorence2Select');
        trainedFlorence2Select.innerHTML = '<option value="" selected>-- 不选则使用基础模型 --</option>';
        
        if (florenceData.success && florenceData.models && florenceData.models.length > 0) {
            florenceData.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.model_path || model.path;
                const modelName = model.project_id || 'Florence-2模型';
                const trainDate = model.trained_at ? new Date(model.trained_at).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
                option.textContent = `${modelName} ${trainDate ? '(' + trainDate + ')' : ''}`;
                trainedFlorence2Select.appendChild(option);
            });
        }
        
        addValidationLog(`✅ 成功加载所有模型`, 'success');
        addDebugLog(`✅ 成功加载所有模型`, 'success');
    } catch (error) {
        addValidationLog(`💥 加载模型异常: ${error.message}`, 'error');
        addDebugLog(`💥 加载模型异常详情: ${error.message}`, 'error');
        console.error('加载模型列表失败:', error);
        showNotification('error', '加载失败', '无法加载模型列表');
    }
}

// 开始验证
async function startValidation() {
    addValidationLog('🚀 开始验证流程', 'info');
    addDebugLog('🚀 开始验证流程', 'info');
    
    // 获取基础模型（必选）
    const baseYolo = document.getElementById('baseYoloSelect').value;
    const baseFlorence2 = document.getElementById('baseFlorence2Select').value;
    
    // 获取微调模型（可选，不选则使用基础模型）
    const trainedYolo = document.getElementById('trainedYoloSelect').value || baseYolo;
    const trainedFlorence2 = document.getElementById('trainedFlorence2Select').value || baseFlorence2;
    
    addValidationLog(`📦 基础YOLO: ${baseYolo}`, 'info');
    addValidationLog(`📦 基础Florence-2: ${baseFlorence2}`, 'info');
    addValidationLog(`✨ 微调YOLO: ${trainedYolo}`, 'info');
    addValidationLog(`✨ 微调Florence-2: ${trainedFlorence2}`, 'info');
    
    // 验证输入
    if (!uploadedImageFile) {
        addValidationLog('❌ 未上传图片', 'error');
        showNotification('warning', '请上传图片', '请先上传要验证的测试图片');
        return;
    }
    
    if (!baseYolo || !baseFlorence2) {
        addValidationLog('❌ 未选择基础模型', 'error');
        showNotification('warning', '请选择基础模型', '请选择完整的基础模型组（YOLO + Florence-2）');
        return;
    }
    
    // 显示加载中
    showLoading();
    updateProgress(10, '准备验证数据...');
    
    // 准备表单数据 - 基础模型组
    const formDataA = new FormData();
    formDataA.append('image', uploadedImageFile);
    formDataA.append('yolo_model_path', baseYolo);
    formDataA.append('florence2_model_path', baseFlorence2);
    
    // 准备表单数据 - 微调模型组
    const formDataB = new FormData();
    formDataB.append('image', uploadedImageFile);
    formDataB.append('yolo_model_path', trainedYolo);
    formDataB.append('florence2_model_path', trainedFlorence2);
    
    updateProgress(20, '上传验证数据...');
    
    try {
        // 处理基础模型组
        addValidationLog(`📡 处理基础模型组（YOLO + Florence-2）...`, 'info');
        updateProgress(30, '处理基础模型组...');
        
        const responseA = await fetch(`${API_BASE}/api/omniparser/process`, {
            method: 'POST',
            body: formDataA
        });
        
        if (!responseA.ok) {
            const errorText = await responseA.text();
            addValidationLog(`❌ 基础模型错误: ${errorText.substring(0, 200)}`, 'error');
            addDebugLog(`❌ 基础模型错误详情: ${errorText}`, 'error');
            throw new Error(`基础模型处理失败: ${errorText.substring(0, 100)}`);
        }
        
        const resultA = await responseA.json();
        addValidationLog(`✅ 基础模型处理完成（检测到 ${resultA.total_icons || 0} 个图标）`, 'success');
        
        // 处理微调模型组
        addValidationLog(`📡 处理微调模型组（YOLO + Florence-2）...`, 'info');
        updateProgress(60, '处理微调模型组...');
        
        const responseB = await fetch(`${API_BASE}/api/omniparser/process`, {
            method: 'POST',
            body: formDataB
        });
        
        if (!responseB.ok) {
            const errorText = await responseB.text();
            addValidationLog(`❌ 微调模型错误: ${errorText.substring(0, 200)}`, 'error');
            addDebugLog(`❌ 微调模型错误详情: ${errorText}`, 'error');
            throw new Error(`微调模型处理失败: ${errorText.substring(0, 100)}`);
        }
        
        const resultB = await responseB.json();
        addValidationLog(`✅ 微调模型处理完成（检测到 ${resultB.total_icons || 0} 个图标）`, 'success');
        
        updateProgress(90, '处理结果数据...');
        
        hideLoading();
        
        if (resultA.success && resultB.success) {
            const diff = (resultB.total_icons || 0) - (resultA.total_icons || 0);
            addValidationLog(`✅ 验证成功完成！差异: ${diff > 0 ? '+' : ''}${diff} 个图标`, 'success');
            displayResults({
                model_a: resultA,
                model_b: resultB
            });
            showNotification('success', '验证完成', '模型对比验证已完成');
            updateProgress(100, '验证完成！');
        } else {
            const error = (!resultA.success ? resultA.error : resultB.error) || '处理失败';
            addValidationLog(`❌ 验证失败: ${error}`, 'error');
            showNotification('error', '验证失败', error);
        }
    } catch (error) {
        hideLoading();
        addValidationLog(`💥 异常错误: ${error.message}`, 'error');
        addDebugLog(`💥 异常错误详情: ${error.message}`, 'error');
        addDebugLog(`错误堆栈: ${error.stack}`, 'error');
        console.error('验证失败:', error);
        showNotification('error', '验证失败', error.message);
        
        // 自动显示调试面板
        if (!debugPanelVisible) {
            toggleDebugPanel();
        }
    }
}

// 显示验证结果
function displayResults(data) {
    addDebugLog('📊 开始处理验证结果', 'info');
    
    const resultsSection = document.getElementById('comparisonResults');
    const comparisonGrid = document.getElementById('comparisonGrid');
    
    // 适配OmniParser API返回的数据格式
    const modelA = data.model_a || {};
    const modelB = data.model_b || {};
    
    addDebugLog(`模型A数据: total_icons=${modelA.total_icons}`, 'info');
    addDebugLog(`模型B数据: total_icons=${modelB.total_icons}`, 'info');
    
    // 计算差异
    const countDiff = (modelB.total_icons || 0) - (modelA.total_icons || 0);
    
    // 格式化解析内容
    const formatParsedContent = (parsedContent) => {
        if (!parsedContent) {
            return '<span style="color: #9ca3af;">未检测到图标</span>';
        }
        return parsedContent.split('\n').map(line => 
            `<div style="margin-bottom: 0.5rem; color: #4b5563; font-size: 0.75rem;">${line}</div>`
        ).join('');
    };
    
    // 构建结果HTML
    comparisonGrid.innerHTML = `
        <div class="result-card">
            <div class="result-header">
                <span style="font-size: 1.25rem;">📦</span>
                <span>基础模型（训练前）</span>
            </div>
            <div class="result-content">
                ${modelA.image ? `<img src="data:image/png;base64,${modelA.image}" class="result-image" alt="基础模型结果">` : '<p style="color: #9ca3af;">无可视化结果</p>'}
                <div class="result-info">
                    <div class="result-info-item">
                        <span style="font-weight: 600;">检测数量</span>
                        <span style="color: #3b82f6; font-weight: 600;">
                            ${modelA.total_icons || 0} 个图标
                        </span>
                    </div>
                    ${modelA.parsed_content ? `
                        <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;">
                            <div style="font-size: 0.875rem; font-weight: 600; margin-bottom: 0.5rem; color: #1f2937;">识别结果：</div>
                            <div style="max-height: 200px; overflow-y: auto;">
                                ${formatParsedContent(modelA.parsed_content)}
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        </div>
        
        <div class="result-card">
            <div class="result-header" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
                <span style="font-size: 1.25rem;">✨</span>
                <span>微调模型（训练后）</span>
            </div>
            <div class="result-content">
                ${modelB.image ? `<img src="data:image/png;base64,${modelB.image}" class="result-image" alt="微调模型结果">` : '<p style="color: #9ca3af;">无可视化结果</p>'}
                <div class="result-info">
                    <div class="result-info-item">
                        <span style="font-weight: 600;">检测数量</span>
                        <span style="color: #10b981; font-weight: 600;">
                            ${modelB.total_icons || 0} 个图标
                        </span>
                    </div>
                    <div class="result-info-item">
                        <span style="font-weight: 600;">对比差异</span>
                        <span style="color: ${countDiff > 0 ? '#10b981' : countDiff < 0 ? '#ef4444' : '#6b7280'}; font-weight: 600;">
                            ${countDiff > 0 ? '+' : ''}${countDiff} 个图标
                        </span>
                    </div>
                    ${modelB.parsed_content ? `
                        <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;">
                            <div style="font-size: 0.875rem; font-weight: 600; margin-bottom: 0.5rem; color: #1f2937;">识别结果：</div>
                            <div style="max-height: 200px; overflow-y: auto;">
                                ${formatParsedContent(modelB.parsed_content)}
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
    
    addDebugLog('✅ 结果显示成功', 'success');
    
    // 显示结果区域
    resultsSection.style.display = 'block';
    
    // 滚动到结果区域
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 格式化检测详情
function formatDetectionDetails(details) {
    if (typeof details === 'string') {
        return details;
    }
    if (Array.isArray(details)) {
        return details.map(d => `• ${d}`).join('<br>');
    }
    return JSON.stringify(details);
}

// 显示加载中
function showLoading() {
    document.getElementById('loadingOverlay').style.display = 'flex';
}

// 隐藏加载中
function hideLoading() {
    document.getElementById('loadingOverlay').style.display = 'none';
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
                           padding: 0.25rem 0.5rem; border-radius: 0.25rem; cursor: pointer; 
                           font-size: 0.875rem;">✕</button>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    // 3秒后自动移除
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

