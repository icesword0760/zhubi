// 朱笔 Zhubi 训练页面逻辑

const API_BASE = '';
let currentModelType = 'yolo';
let validationImageFile = null;
let progressPollingInterval = null;  // 进度轮询定时器
let logsPollingInterval = null;      // 日志轮询定时器
let lastLogContent = '';             // 上次的日志内容
let currentTrainingProject = null;   // 当前训练的项目ID

// 格式化时间（秒 -> HH:MM:SS）
function formatTime(seconds) {
    if (!seconds || seconds < 0) return '--:--:--';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// 开始轮询训练进度
function startProgressPolling(projectId) {
    // 清除之前的轮询
    if (progressPollingInterval) {
        clearInterval(progressPollingInterval);
    }
    
    // 显示详细进度区域
    const detailsDiv = document.getElementById('trainingDetails');
    if (detailsDiv) {
        detailsDiv.style.display = 'block';
    }
    
    // 每2秒轮询一次
    progressPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/api/projects/${projectId}/train/progress`);
            const result = await response.json();
            
            console.log('[进度轮询] 收到响应:', result);
            
            if (result.success && result.data) {
                console.log('[进度轮询] 更新进度数据:', result.data);
                updateTrainingDetails(result.data);
                
                // 如果训练完成，延迟5秒后停止轮询
                if (result.data.status === 'completed') {
                    console.log('训练已完成，5秒后停止进度轮询');
                    setTimeout(() => {
                        stopProgressPolling();
                    }, 5000);
                }
            } else if (result.status === 'not_found') {
                console.log('[进度轮询] 训练未找到，停止轮询');
                // 训练已完成或未开始，停止轮询
                stopProgressPolling();
            }
        } catch (error) {
            console.error('轮询进度失败:', error);
        }
    }, 2000);
}

// 开始轮询训练日志
function startLogsPolling(projectId) {
    // 清除之前的轮询
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
    }
    
    lastLogContent = '';  // 重置日志内容
    
    // 每2秒轮询一次
    logsPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/api/projects/${projectId}/train/logs`);
            const result = await response.json();
            
            if (result.success && result.logs) {
                // 只有当日志内容变化时才更新
                if (result.logs !== lastLogContent) {
                    updateTrainingLogs(result.logs);
                    lastLogContent = result.logs;
                }
            }
        } catch (error) {
            console.error('轮询日志失败:', error);
        }
    }, 2000);
}

// 停止轮询训练进度
function stopProgressPolling() {
    if (progressPollingInterval) {
        clearInterval(progressPollingInterval);
        progressPollingInterval = null;
    }
}

// 停止轮询训练日志
function stopLogsPolling() {
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }
}

// 更新训练日志显示
function updateTrainingLogs(logs) {
    const logContent = document.getElementById('logContent');
    if (!logContent) {
        console.error('logContent element not found');
        return;
    }
    
    if (!logs || logs.trim() === '') {
        return;  // 日志为空，不更新
    }
    
    console.log('[日志更新] 收到日志，长度:', logs.length);
    
    // 如果日志中包含分隔线，说明是完整的训练过程详情（训练结束）
    if (logs.includes('============')) {
        console.log('[日志更新] 完整日志模式');
        // 完整日志，直接替换
        logContent.innerHTML = logs.replace(/\n/g, '<br>');
    } else {
        console.log('[日志更新] 实时日志模式');
        // 实时日志 - 创建或更新实时日志区域
        let realtimeSection = logContent.querySelector('.realtime-logs-section');
        if (!realtimeSection) {
            // 创建实时日志区域（追加到现有内容后）
            const separator = '<div style="border-top: 2px solid #3b82f6; margin: 1rem 0;"></div>';
            logContent.innerHTML += separator;
            
            const header = '<div class="realtime-logs-section"><div style="color: #3b82f6; font-weight: bold; margin: 0.5rem 0; font-size: 1.1em;">📊 实时训练进度</div>';
            logContent.innerHTML += header;
            
            realtimeSection = logContent.querySelector('.realtime-logs-section');
        }
        
        // 更新实时日志内容
        const lines = logs.split('\n').filter(line => line.trim());
        const logsHtml = lines.map(line => {
            // 根据内容类型添加样式
            if (line.startsWith('📊')) {
                return `<div style="color: #10b981; margin: 0.25rem 0;">${line}</div>`;
            } else if (line.startsWith('✅')) {
                return `<div style="color: #059669; font-weight: bold; margin: 0.5rem 0;">${line}</div>`;
            } else {
                return `<div style="margin: 0.25rem 0;">${line}</div>`;
            }
        }).join('');
        
        // 更新内容（保留header）
        realtimeSection.innerHTML = '<div style="color: #3b82f6; font-weight: bold; margin: 0.5rem 0; font-size: 1.1em;">📊 实时训练进度</div>' + logsHtml + '</div>';
    }
    
    // 自动滚动到底部
    logContent.scrollTop = logContent.scrollHeight;
}

// 更新训练详细信息
function updateTrainingDetails(data) {
    console.log('[更新进度显示] 收到数据:', data);
    
    // 更新当前轮次
    const currentEpochEl = document.getElementById('currentEpoch');
    const totalEpochsEl = document.getElementById('totalEpochs');
    if (currentEpochEl && totalEpochsEl) {
        currentEpochEl.textContent = data.current_epoch || 0;
        totalEpochsEl.textContent = data.total_epochs || 0;
        console.log('[更新进度显示] 轮次更新为:', data.current_epoch, '/', data.total_epochs);
    } else {
        console.warn('[更新进度显示] 未找到轮次元素');
    }
    
    // 更新当前损失
    const currentLossEl = document.getElementById('currentLoss');
    if (currentLossEl && data.current_loss !== null && data.current_loss !== undefined) {
        currentLossEl.textContent = data.current_loss.toFixed(4);
        console.log('[更新进度显示] 损失更新为:', data.current_loss.toFixed(4));
    } else {
        console.warn('[更新进度显示] 未找到损失元素或损失为空');
    }
    
    // 更新已用时间
    const elapsedTimeEl = document.getElementById('elapsedTime');
    if (elapsedTimeEl && data.elapsed_time) {
        elapsedTimeEl.textContent = formatTime(data.elapsed_time);
        console.log('[更新进度显示] 已用时间更新为:', formatTime(data.elapsed_time));
    } else {
        console.warn('[更新进度显示] 未找到已用时间元素或时间为空');
    }
    
    // 更新预计剩余时间
    const remainingTimeEl = document.getElementById('remainingTime');
    if (remainingTimeEl) {
        if (data.estimated_remaining && data.estimated_remaining > 0) {
            remainingTimeEl.textContent = formatTime(data.estimated_remaining);
            remainingTimeEl.style.color = '#F59E0B';
            console.log('[更新进度显示] 预计剩余更新为:', formatTime(data.estimated_remaining));
        } else if (data.current_epoch === 0) {
            remainingTimeEl.textContent = '计算中...';
            remainingTimeEl.style.color = '#9CA3AF';
        } else {
            remainingTimeEl.textContent = '即将完成';
            remainingTimeEl.style.color = '#10B981';
        }
    } else {
        console.warn('[更新进度显示] 未找到剩余时间元素');
    }
    
    // 更新本轮耗时
    const epochTimeEl = document.getElementById('epochTime');
    if (epochTimeEl && data.epoch_time) {
        epochTimeEl.textContent = formatTime(data.epoch_time);
        console.log('[更新进度显示] 本轮耗时更新为:', formatTime(data.epoch_time));
    } else {
        console.warn('[更新进度显示] 未找到本轮耗时元素或时间为空');
    }
    
    // 更新平均每轮耗时
    const avgEpochTimeEl = document.getElementById('avgEpochTime');
    if (avgEpochTimeEl && data.avg_epoch_time) {
        avgEpochTimeEl.textContent = formatTime(data.avg_epoch_time);
        console.log('[更新进度显示] 平均每轮更新为:', formatTime(data.avg_epoch_time));
    } else {
        console.warn('[更新进度显示] 未找到平均每轮元素或时间为空');
    }
}

// 停止训练
async function stopTraining() {
    if (!currentTrainingProject) {
        alert('没有正在进行的训练');
        return;
    }
    
    if (!confirm('确定要停止当前训练吗？训练进度将会丢失。')) {
        return;
    }
    
    try {
        console.log('停止训练:', currentTrainingProject);
        
        // 显示停止中状态
        const logContent = document.getElementById('logContent');
        logContent.innerHTML += '<br><div style="color: #f59e0b; font-weight: bold;">⏳ 正在停止训练并清理内存...</div>';
        
        const response = await fetch(`${API_BASE}/api/projects/${currentTrainingProject}/train/stop`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 停止所有轮询
            stopProgressPolling();
            stopLogsPolling();
            
            // 更新UI
            logContent.innerHTML += '<br><div style="color: #10b981; font-weight: bold;">✅ 训练已停止，内存已清理</div>';
            if (result.killed_pids && result.killed_pids.length > 0) {
                logContent.innerHTML += `<div style="color: #6b7280; font-size: 0.9em;">终止进程: ${result.killed_pids.join(', ')}</div>`;
            }
            
            const trainBtn = document.getElementById('trainBtn');
            trainBtn.disabled = false;
            trainBtn.textContent = '🚀 开始训练';
            
            const stopBtn = document.getElementById('stopBtn');
            if (stopBtn) {
                stopBtn.style.display = 'none';
            }
            
            const finishBtn = document.getElementById('finishBtn');
            if (finishBtn) {
                finishBtn.style.display = 'none';
            }
            
            // 清除状态
            currentTrainingProject = null;
            localStorage.removeItem('trainingProject');
            localStorage.removeItem('trainingStartTime');
            
            alert('训练已停止');
        } else {
            alert('停止训练失败: ' + (result.error || '未知错误'));
        }
    } catch (error) {
        console.error('停止训练失败:', error);
        alert('停止训练失败: ' + error.message);
    }
}

// 完成训练（保存当前模型并正常结束）
async function finishTraining() {
    if (!currentTrainingProject) {
        alert('没有正在进行的训练');
        return;
    }
    
    if (!confirm('确定要完成训练吗？\n\n将立即停止训练并保存当前模型，舍弃当前批次和后续所有轮次。\n\n提示：如果当前Loss已经满意，可以使用此功能立即结束训练，避免过拟合。')) {
        return;
    }
    
    try {
        console.log('完成训练:', currentTrainingProject);
        
        // 显示完成中状态
        const logContent = document.getElementById('logContent');
        logContent.innerHTML += '<br><div style="color: #10b981; font-weight: bold;">✅ 完成请求已发送，训练将立即停止并保存模型...</div>';
        
        // 禁用完成按钮，避免重复点击
        const finishBtn = document.getElementById('finishBtn');
        if (finishBtn) {
            finishBtn.disabled = true;
            finishBtn.textContent = '⏳ 正在完成...';
        }
        
        const response = await fetch(`${API_BASE}/api/projects/${currentTrainingProject}/train/finish`, {
            method: 'POST'
        });
        
        const result = await response.json();
        console.log('完成训练响应:', result);
        
        if (result.success) {
            logContent.innerHTML += '<br><div style="color: #10b981; font-weight: bold;">✅ ' + result.message + '</div>';
            
            // 注意：不立即重置按钮状态，等待训练自然结束
            // 按钮状态会在训练完成时由轮询逻辑处理
        } else {
            alert('完成训练失败: ' + (result.error || '未知错误'));
            // 失败时恢复按钮状态
            if (finishBtn) {
                finishBtn.disabled = false;
                finishBtn.textContent = '✅ 完成训练';
            }
        }
    } catch (error) {
        console.error('完成训练失败:', error);
        alert('完成训练失败: ' + error.message);
        // 失败时恢复按钮状态
        const finishBtn = document.getElementById('finishBtn');
        if (finishBtn) {
            finishBtn.disabled = false;
            finishBtn.textContent = '✅ 完成训练';
        }
    }
}

// 页面加载
document.addEventListener('DOMContentLoaded', () => {
    console.log('=== 训练页面加载完成 ===');
    console.log('API_BASE:', API_BASE);
    loadProjects();
    loadModels();
    setupEventListeners();
    
    // 检查是否有正在进行的训练
    checkOngoingTraining();
    
    console.log('=== 事件监听器设置完成 ===');
});

// 检查是否有正在进行的训练
async function checkOngoingTraining() {
    // 从 localStorage 获取训练状态
    const trainingProject = localStorage.getItem('trainingProject');
    const trainingStartTime = localStorage.getItem('trainingStartTime');
    
    if (trainingProject && trainingStartTime) {
        const startTime = parseInt(trainingStartTime);
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        
        // 如果距离开始时间不超过2小时，尝试恢复训练状态
        if (elapsed < 7200) {
            console.log('检测到正在进行的训练，尝试恢复状态...');
            
            // 恢复训练项目ID（重要！）
            currentTrainingProject = trainingProject;
            
            // 显示训练UI
            const trainLog = document.getElementById('trainLog');
            const progressContainer = document.getElementById('progressContainer');
            const trainBtn = document.getElementById('trainBtn');
            const stopBtn = document.getElementById('stopBtn');
            
            if (trainLog) trainLog.style.display = 'block';
            if (progressContainer) progressContainer.style.display = 'block';
            if (trainBtn) {
                trainBtn.disabled = true;
                trainBtn.textContent = '⏳ 训练中...';
            }
            if (stopBtn) {
                stopBtn.style.display = 'inline-block';  // 显示停止按钮
            }
            const finishBtn = document.getElementById('finishBtn');
            if (finishBtn) {
                finishBtn.style.display = 'inline-block';  // 显示完成训练按钮
            }
            
            // 开始轮询进度
            startProgressPolling(trainingProject);
            
            // 延迟启动日志轮询，避免与恢复的日志冲突
            setTimeout(() => {
                startLogsPolling(trainingProject);
            }, 2000);
            
            // 添加提示日志
            const logContent = document.getElementById('logContent');
            if (logContent) {
                logContent.innerHTML = '<div style="color: #3b82f6; padding: 0.5rem; background: #eff6ff; border-radius: 0.375rem; margin-bottom: 0.5rem;">ℹ️ 检测到正在进行的训练，已恢复进度显示...</div>';
            }
        } else {
            // 训练时间太久，清除状态
            localStorage.removeItem('trainingProject');
            localStorage.removeItem('trainingStartTime');
        }
    }
}

// 设置事件监听
function setupEventListeners() {
    // LoRA切换
    const useLora = document.getElementById('useLora');
    if (useLora) {
        useLora.addEventListener('change', (e) => {
            const options = document.getElementById('loraOptions');
            options.style.display = e.target.checked ? 'block' : 'none';
        });
    }
}

// 选择模型类型
function selectModelType(type) {
    currentModelType = type;
    
    // 更新按钮状态
    document.querySelectorAll('.model-type-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`[data-type="${type}"]`).classList.add('active');
    
    // 切换参数表单
    if (type === 'yolo') {
        document.getElementById('yoloParams').style.display = 'block';
        document.getElementById('florence2Params').style.display = 'none';
    } else {
        document.getElementById('yoloParams').style.display = 'none';
        document.getElementById('florence2Params').style.display = 'block';
    }
    
    // 重新检查数据集
    checkDataset();
}

// 加载项目列表
async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/api/projects`);
        const data = await response.json();
        
        if (data.success) {
            const select = document.getElementById('projectSelect');
            select.innerHTML = '<option value="">-- 请选择项目 --</option>' + 
                data.projects.map(p => `
                    <option value="${p.id}">${p.name}</option>
                `).join('');
        }
    } catch (error) {
        console.error('加载项目失败:', error);
    }
}

// 检查数据集
async function checkDataset() {
    const projectId = document.getElementById('projectSelect').value;
    if (!projectId) {
        document.getElementById('datasetStatus').style.display = 'none';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/projects/${projectId}`);
        const data = await response.json();
        
        if (data.success) {
            const project = data.project;
            const statusDiv = document.getElementById('datasetStatus');
            
            const formatNeeded = currentModelType === 'yolo' ? 'YOLO' : 'Florence-2';
            
            if (project.annotated_count === 0) {
                statusDiv.innerHTML = `
                    <div class="warning-message">
                        ⚠️ 该项目还没有标注数据，请先完成标注和导出
                    </div>
                `;
            } else {
                // 显示图片数量和标注框数量
                const totalBoxes = project.total_boxes || 0;
                const boxesInfo = currentModelType === 'florence2' && totalBoxes > 0 
                    ? `，共 <strong>${totalBoxes}</strong> 个标注样本` 
                    : '';
                
                statusDiv.innerHTML = `
                    <div style="padding: 1rem; background: #F0FDF4; border-radius: 0.375rem; 
                         border: 1px solid #86EFAC;">
                        ✅ 已有 ${project.annotated_count} 张标注图片${boxesInfo}
                        <div style="margin-top: 0.5rem; font-size: 0.875rem;">
                            <strong>提示:</strong> 请先在"数据导出"页面导出 ${formatNeeded} 格式的数据集，
                            然后才能开始训练
                        </div>
                    </div>
                `;
            }
            statusDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('检查数据集失败:', error);
    }
}

// 处理训练
async function handleTrain(event) {
    console.log('=== 开始训练函数被调用 ===');
    event.preventDefault();
    
    const projectId = document.getElementById('projectSelect').value;
    console.log('选择的项目ID:', projectId);
    
    if (!projectId) {
        alert('请选择项目');
        return;
    }
    
    // 收集训练参数
    let trainConfig = {
        model_type: currentModelType
    };
    
    if (currentModelType === 'yolo') {
        // 收集YOLO参数
        const trainSplit = parseInt(document.getElementById('yoloTrainSplit').value);
        const valSplit = parseInt(document.getElementById('yoloValSplit').value);
        const testSplit = parseInt(document.getElementById('yoloTestSplit').value);
        
        trainConfig = {
            ...trainConfig,
            epochs: parseInt(document.getElementById('yoloEpochs').value),
            batch_size: parseInt(document.getElementById('yoloBatchSize').value),
            learning_rate: parseFloat(document.getElementById('yoloLearningRate').value),
            device: document.getElementById('yoloDevice').value,
            train_split: trainSplit / 100,
            val_split: valSplit / 100,
            test_split: testSplit / 100
        };
    } else {
        // 收集Florence-2参数
        const trainSplit = parseInt(document.getElementById('trainSplit').value);
        const valSplit = parseInt(document.getElementById('valSplit').value);
        const testSplit = parseInt(document.getElementById('testSplit').value);
        
        trainConfig = {
            ...trainConfig,
            epochs: parseInt(document.getElementById('florenceEpochs').value),
            learning_rate: parseFloat(document.getElementById('florenceLearningRate').value),
            batch_size: parseInt(document.getElementById('florenceBatchSize').value),
            device: document.getElementById('florenceDevice').value,
            use_lora: document.getElementById('useLora').checked,
            lora_r: parseInt(document.getElementById('loraR').value),
            lora_alpha: parseInt(document.getElementById('loraAlpha').value),
            train_split: trainSplit / 100,
            val_split: valSplit / 100,
            test_split: testSplit / 100,
            // 数据增强配置
            augmentation_enabled: document.getElementById('useAugmentation')?.checked || false,
            augmentation_strategy: document.getElementById('augmentationStrategy')?.value || 'moderate',
            augmentation_categories: getCustomAugmentationCategories(),
            // 早停配置
            target_loss: getEarlyStoppingConfig().target_loss,
            early_stop_patience: getEarlyStoppingConfig().patience,
            // ReduceLROnPlateau配置
            reduce_lr_config: getReduceLRConfig(),
            // 类别权重配置
            class_weights: getClassWeights(),
            // 高级训练参数
            ...getAdvancedParams()
        };
    }
    
    // 显示日志和进度
    const trainLog = document.getElementById('trainLog');
    const logContent = document.getElementById('logContent');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const trainBtn = document.getElementById('trainBtn');
    
    trainLog.style.display = 'block';
    progressContainer.style.display = 'block';
    logContent.innerHTML = '';
    progressBar.style.width = '0%';
    progressBar.textContent = '0%';
    trainBtn.disabled = true;
    trainBtn.textContent = '⏳ 训练中...';
    
    // 显示停止按钮和完成训练按钮
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
        stopBtn.style.display = 'inline-block';
    }
    const finishBtn = document.getElementById('finishBtn');
    if (finishBtn) {
        finishBtn.style.display = 'inline-block';
    }
    
    // 保存训练状态
    currentTrainingProject = projectId;
    localStorage.setItem('trainingProject', projectId);
    localStorage.setItem('trainingStartTime', Date.now().toString());
    
    // 开始轮询进度
    startProgressPolling(projectId);
    
    // 延迟启动日志轮询，避免与SSE冲突
    setTimeout(() => {
        startLogsPolling(projectId);
    }, 3000);  // 3秒后开始日志轮询
    
    try {
        console.log('===== 准备发送训练请求 =====');
        console.log('项目ID:', projectId);
        console.log('训练配置:', trainConfig);
        console.log('API URL:', `${API_BASE}/api/projects/${projectId}/train`);
        
        const response = await fetch(
            `${API_BASE}/api/projects/${projectId}/train`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(trainConfig)
            }
        );
        
        console.log('收到响应:', response.status, response.statusText);
        
        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
        }
        
        if (!response.body) {
            throw new Error('响应没有body');
        }
        
        // 使用 Server-Sent Events 接收流式日志
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const jsonStr = line.substring(6);
                    try {
                        const progressData = JSON.parse(jsonStr);
                        
                        // 添加日志
                        if (progressData.message) {
                            logContent.innerHTML += progressData.message;
                            logContent.scrollTop = logContent.scrollHeight;
                        }
                        
                        // 更新进度条
                        if (progressData.progress >= 0) {
                            const progress = Math.min(100, Math.max(0, progressData.progress));
                            progressBar.style.width = progress + '%';
                            progressBar.textContent = progress + '%';
                        }
                        
                        // 处理不同类型的消息
                        if (progressData.type === 'complete') {
                            progressBar.style.width = '100%';
                            progressBar.textContent = '100% 完成';
                            progressBar.style.background = 'linear-gradient(90deg, #10b981, #059669)';
                            
                            // 重置按钮状态
                            const trainBtn = document.getElementById('trainBtn');
                            if (trainBtn) {
                                trainBtn.disabled = false;
                                trainBtn.textContent = '🚀 开始训练';
                            }
                            const stopBtn = document.getElementById('stopBtn');
                            if (stopBtn) {
                                stopBtn.style.display = 'none';
                            }
                            const finishBtn = document.getElementById('finishBtn');
                            if (finishBtn) {
                                finishBtn.style.display = 'none';
                                finishBtn.disabled = false;
                                finishBtn.textContent = '✅ 完成训练';
                            }
                            
                            // 延迟清除训练状态，让前端有时间显示最终进度
                            setTimeout(() => {
                                localStorage.removeItem('trainingProject');
                                localStorage.removeItem('trainingStartTime');
                                stopProgressPolling();
                                stopLogsPolling();
                            }, 5000);  // 5秒后清除
                        } else if (progressData.type === 'error') {
                            progressBar.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
                            
                            // 重置按钮状态
                            const trainBtn = document.getElementById('trainBtn');
                            if (trainBtn) {
                                trainBtn.disabled = false;
                                trainBtn.textContent = '🚀 开始训练';
                            }
                            const stopBtn = document.getElementById('stopBtn');
                            if (stopBtn) {
                                stopBtn.style.display = 'none';
                            }
                            const finishBtn = document.getElementById('finishBtn');
                            if (finishBtn) {
                                finishBtn.style.display = 'none';
                                finishBtn.disabled = false;
                                finishBtn.textContent = '✅ 完成训练';
                            }
                            
                            // 清除训练状态
                            localStorage.removeItem('trainingProject');
                            localStorage.removeItem('trainingStartTime');
                            stopProgressPolling();
                            stopLogsPolling();
                        }
                    } catch (e) {
                        console.error('解析进度数据失败:', e, jsonStr);
                    }
                }
            }
        }
        
        // 停止进度轮询
        stopProgressPolling();
        
        trainBtn.disabled = false;
        trainBtn.textContent = '🚀 开始训练';
        
        // 重新加载模型列表
        setTimeout(() => loadModels(), 1000);
        
    } catch (error) {
        console.error('训练失败:', error);
        
        // 停止进度轮询
        stopProgressPolling();
        
        // 确保日志区域可见
        trainLog.style.display = 'block';
        progressContainer.style.display = 'block';
        
        // 显示详细错误信息
        let errorMessage = `\n❌ 训练失败: ${error.message}\n`;
        
        if (error.message.includes('找不到训练数据')) {
            errorMessage += `\n💡 解决方法：\n`;
            errorMessage += `1. 点击顶部导航的"数据导出"\n`;
            errorMessage += `2. 选择当前项目\n`;
            errorMessage += `3. 选择"Florence-2"格式\n`;
            errorMessage += `4. 点击"导出数据集"\n`;
            errorMessage += `5. 导出完成后再回来训练\n`;
        }
        
        logContent.innerHTML += errorMessage;
        progressBar.style.width = '0%';
        progressBar.textContent = '训练失败';
        progressBar.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
        
        // 也弹出提示
        alert(`训练失败：${error.message}\n\n${error.message.includes('找不到训练数据') ? '请先在"数据导出"页面导出Florence-2格式的数据集！' : '请查看训练日志了解详情。'}`);
        
        trainBtn.disabled = false;
        trainBtn.textContent = '🚀 开始训练';
    }
}

// 加载已训练模型
async function loadModels() {
    try {
        const response = await fetch(`${API_BASE}/api/models`);
        const data = await response.json();
        
        if (data.success) {
            renderModels(data.models);
            updateModelSelectors(data.models);
        }
    } catch (error) {
        console.error('加载模型失败:', error);
    }
}

// 渲染模型列表
function renderModels(models) {
    const list = document.getElementById('modelsList');
    
    if (models.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无训练好的模型</div>';
        return;
    }
    
    list.innerHTML = models.map(model => {
        const modelType = model.model_type || 'florence2';
        const modelIcon = modelType === 'yolo' ? '🎯' : '🖼️';
        const modelName = modelType === 'yolo' ? 'YOLO' : 'Florence-2';
        
        // 提取训练参数
        const config = model.config || {};
        const hasLora = config.lora_r || config.use_lora;
        
        return `
            <div class="model-card">
                <h4>${modelIcon} ${model.project_id} (${modelName})</h4>
                <div class="stats" style="margin: 0.5rem 0; display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem;">
                    <div class="stat-item">
                        <label>训练时间:</label>
                        <span style="font-size: 0.875rem;">${new Date(model.trained_at).toLocaleString()}</span>
                    </div>
                    <div class="stat-item">
                        <label>训练样本:</label>
                        <span>${model.train_samples || 'N/A'}${model.category_counts ? ` (${Object.keys(model.category_counts).length}类)` : ''}</span>
                    </div>
                    ${model.final_loss ? `
                    <div class="stat-item">
                        <label>Loss:</label>
                        <span style="color: ${model.final_loss < 1 ? '#10b981' : model.final_loss < 3 ? '#f59e0b' : '#ef4444'}; font-weight: 600;">${model.final_loss.toFixed(4)}</span>
                    </div>
                    ` : ''}
                    ${config.epochs ? `
                    <div class="stat-item">
                        <label>Epochs:</label>
                        <span>${config.epochs}</span>
                    </div>
                    ` : ''}
                    ${config.learning_rate ? `
                    <div class="stat-item">
                        <label>学习率:</label>
                        <span>${config.learning_rate.toExponential(1)}</span>
                    </div>
                    ` : ''}
                    ${config.batch_size ? `
                    <div class="stat-item">
                        <label>批次:</label>
                        <span>${config.batch_size}</span>
                    </div>
                    ` : ''}
                    ${hasLora ? `
                    <div class="stat-item">
                        <label>LoRA:</label>
                        <span>r=${config.lora_r || 'N/A'}, α=${config.lora_alpha || 'N/A'}</span>
                    </div>
                    ` : ''}
                    ${config.augmentation_enabled ? `
                    <div class="stat-item">
                        <label>增强:</label>
                        <span>${config.augmentation_strategy || 'basic'} (×${config.augmentation_factor || 10})</span>
                    </div>
                    ` : ''}
                    ${config.train_split || config.val_split || config.test_split ? `
                    <div class="stat-item">
                        <label>数据集划分:</label>
                        <span>${Math.round((config.train_split || 0.9) * 100)}/${Math.round((config.val_split || 0.1) * 100)}/${Math.round((config.test_split || 0) * 100)}</span>
                    </div>
                    ` : ''}
                    ${config.weight_decay ? `
                    <div class="stat-item">
                        <label>Weight Decay:</label>
                        <span>${config.weight_decay}</span>
                    </div>
                    ` : ''}
                    ${config.warmup_steps ? `
                    <div class="stat-item">
                        <label>Warmup Steps:</label>
                        <span>${config.warmup_steps}</span>
                    </div>
                    ` : ''}
                    ${config.gradient_accumulation_steps && config.gradient_accumulation_steps > 1 ? `
                    <div class="stat-item">
                        <label>梯度累积:</label>
                        <span>${config.gradient_accumulation_steps}</span>
                    </div>
                    ` : ''}
                    ${config.max_grad_norm ? `
                    <div class="stat-item">
                        <label>梯度裁剪:</label>
                        <span>${config.max_grad_norm}</span>
                    </div>
                    ` : ''}
                    ${config.class_weights ? `
                    <div class="stat-item">
                        <label>类别权重:</label>
                        <span style="font-size: 0.75rem;">${Object.keys(config.class_weights).length}类</span>
                    </div>
                    ` : ''}
                    ${model.final_metrics ? `
                    <div class="stat-item">
                        <label>mAP50:</label>
                        <span>${model.final_metrics.mAP50?.toFixed(4) || 'N/A'}</span>
                    </div>
                    ` : ''}
                </div>
                ${(model.category_counts || config.class_weights || config.weight_decay || config.warmup_steps || config.gradient_accumulation_steps || config.max_grad_norm) ? `
                <details style="margin-top: 0.5rem; font-size: 0.875rem;">
                    <summary style="cursor: pointer; color: #3b82f6; font-weight: 600;">📋 详细参数</summary>
                    <div style="margin-top: 0.5rem; padding: 0.75rem; background: #f9fafb; border-radius: 0.375rem; font-size: 0.8125rem;">
                        ${model.category_counts ? `
                        <div style="margin-bottom: 0.75rem;">
                            <strong>📊 训练样本分布:</strong>
                            <div style="margin-left: 1rem; margin-top: 0.25rem; font-family: monospace; font-size: 0.75rem;">
                                ${Object.entries(model.category_counts)
                                    .sort((a, b) => b[1] - a[1])  // 按数量降序排列
                                    .map(([category, count]) => {
                                        const percentage = ((count / model.train_samples) * 100).toFixed(1);
                                        const barWidth = Math.min(percentage, 100);
                                        return `
                                            <div style="margin-bottom: 0.5rem;">
                                                <div style="display: flex; justify-content: space-between; margin-bottom: 0.125rem;">
                                                    <span style="color: #374151; font-weight: 600;">${category}</span>
                                                    <span style="color: #6b7280;">${count} (${percentage}%)</span>
                                                </div>
                                                <div style="background: #e5e7eb; border-radius: 0.25rem; height: 0.375rem; overflow: hidden;">
                                                    <div style="background: linear-gradient(90deg, #3b82f6, #06b6d4); height: 100%; width: ${barWidth}%;"></div>
                                                </div>
                                            </div>
                                        `;
                                    }).join('')}
                            </div>
                        </div>
                        ` : ''}
                        ${config.weight_decay ? `<div><strong>Weight Decay:</strong> ${config.weight_decay}</div>` : ''}
                        ${config.warmup_steps ? `<div><strong>Warmup Steps:</strong> ${config.warmup_steps}</div>` : ''}
                        ${config.gradient_accumulation_steps ? `<div><strong>Gradient Accumulation:</strong> ${config.gradient_accumulation_steps}</div>` : ''}
                        ${config.max_grad_norm ? `<div><strong>Max Grad Norm:</strong> ${config.max_grad_norm}</div>` : ''}
                        ${config.class_weights ? `
                        <div style="margin-top: 0.5rem;">
                            <strong>类别权重:</strong>
                            <div style="margin-left: 1rem; font-family: monospace; font-size: 0.75rem;">
                                ${Object.entries(config.class_weights).map(([k, v]) => `${k}: ${v}`).join('<br>')}
                            </div>
                        </div>
                        ` : ''}
                    </div>
                </details>
                ` : ''}
                <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                    <button class="btn btn-sm btn-success" 
                            onclick="showResumeDialog('${model.project_id}', '${model.timestamp}', ${model.final_loss || 0}, ${model.config?.epochs || 0})"
                            title="继续训练更多轮次">
                        🔄 继续训练
                    </button>
                    <button class="btn btn-sm btn-primary" 
                            onclick="deployModel('${model.project_id}', '${modelType}')">
                        部署到OmniParser
                    </button>
                    <button class="btn btn-sm btn-danger" 
                            onclick="deleteModel('${model.project_id}')">
                        删除
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

// 更新验证区的模型选择器
function updateModelSelectors(models) {
    const baseSelect = document.getElementById('baseModelSelect');
    const trainedSelect = document.getElementById('trainedModelSelect');
    
    // 基础模型（预训练模型）
    baseSelect.innerHTML = `
        <option value="">-- 选择基础模型 --</option>
        <option value="yolov8n.pt">YOLOv8n (预训练)</option>
        <option value="yolov8s.pt">YOLOv8s (预训练)</option>
        <option value="../weights/icon_caption_florence">Florence-2 (预训练)</option>
    `;
    
    // 已训练模型
    trainedSelect.innerHTML = '<option value="">-- 选择微调模型 --</option>' +
        models.map(m => {
            const path = m.model_type === 'yolo' ? m.best_model : m.model_path;
            return `<option value="${path}">${m.project_id} (${m.model_type || 'florence2'})</option>`;
        }).join('');
}

// 处理验证图片上传
function handleValidationUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    validationImageFile = file;
    
    // 显示预览
    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('uploadPrompt').style.display = 'none';
        document.getElementById('uploadedPreview').style.display = 'block';
        document.getElementById('previewImage').src = e.target.result;
        document.getElementById('modelSelection').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

// 运行对比验证
async function runComparison() {
    if (!validationImageFile) {
        alert('请先上传验证图片');
        return;
    }
    
    const baseModel = document.getElementById('baseModelSelect').value;
    const trainedModel = document.getElementById('trainedModelSelect').value;
    
    if (!baseModel || !trainedModel) {
        alert('请选择要对比的模型');
        return;
    }
    
    // 根据模型路径自动判断类型
    let modelType = 'florence2';  // 默认Florence-2
    if (baseModel.endsWith('.pt') || trainedModel.endsWith('.pt')) {
        modelType = 'yolo';
    } else if (baseModel.includes('florence') || trainedModel.includes('florence')) {
        modelType = 'florence2';
    }
    
    console.log('检测到的模型类型:', modelType);
    console.log('基础模型路径:', baseModel);
    console.log('微调模型路径:', trainedModel);
    
    const resultsDiv = document.getElementById('validationResults');
    const gridDiv = document.getElementById('comparisonGrid');
    
    resultsDiv.style.display = 'block';
    gridDiv.innerHTML = '<p>正在验证中...</p>';
    
    try {
        // 创建FormData
        const formData = new FormData();
        formData.append('image', validationImageFile);
        formData.append('model_a_path', baseModel);
        formData.append('model_b_path', trainedModel);
        formData.append('model_type', modelType);
        
        const response = await fetch(`${API_BASE}/api/models/compare`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.model_a && data.model_b) {
            // 辅助函数：格式化检测结果
            const formatDetections = (detections) => {
                if (!detections || detections.length === 0) {
                    return '<li>未检测到对象</li>';
                }
                return detections.map((det, i) => 
                    `<li>对象${i+1}: <strong>${det.label || 'unknown'}</strong> (位置: ${JSON.stringify(det.bbox)})</li>`
                ).join('');
            };
            
            gridDiv.innerHTML = `
                <div class="validation-result-card">
                    <h4>🔷 基础模型</h4>
                    ${data.model_a.success ? `
                        <img src="${data.model_a.visualization}" class="validation-image">
                        <p><strong>检测数量:</strong> ${data.model_a.count}</p>
                        
                        <details style="margin-top: 1rem;">
                            <summary style="cursor: pointer; color: #3b82f6; font-weight: 600;">📋 检测详情</summary>
                            <div style="margin-top: 0.5rem; padding: 0.5rem; background: #f3f4f6; border-radius: 0.25rem; font-size: 0.875rem;">
                                <p><strong>检测到的对象:</strong></p>
                                <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
                                    ${formatDetections(data.model_a.detections)}
                                </ul>
                                ${data.model_a.raw_output ? `
                                    <p style="margin-top: 0.5rem;"><strong>模型原始输出:</strong></p>
                                    <pre style="background: white; padding: 0.5rem; border-radius: 0.25rem; overflow-x: auto; font-size: 0.75rem;">${data.model_a.raw_output}</pre>
                                ` : ''}
                                ${data.model_a.parsed_result ? `
                                    <p style="margin-top: 0.5rem;"><strong>解析后的结果:</strong></p>
                                    <pre style="background: white; padding: 0.5rem; border-radius: 0.25rem; overflow-x: auto; font-size: 0.75rem;">${data.model_a.parsed_result}</pre>
                                ` : ''}
                            </div>
                        </details>
                    ` : `<p style="color: red;">验证失败: ${data.model_a.error}</p>`}
                </div>
                
                <div class="validation-result-card">
                    <h4>✨ 微调模型</h4>
                    ${data.model_b.success ? `
                        <img src="${data.model_b.visualization}" class="validation-image">
                        <p><strong>检测数量:</strong> ${data.model_b.count}</p>
                        
                        <details style="margin-top: 1rem;">
                            <summary style="cursor: pointer; color: #3b82f6; font-weight: 600;">📋 检测详情</summary>
                            <div style="margin-top: 0.5rem; padding: 0.5rem; background: #f3f4f6; border-radius: 0.25rem; font-size: 0.875rem;">
                                <p><strong>检测到的对象:</strong></p>
                                <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
                                    ${formatDetections(data.model_b.detections)}
                                </ul>
                                ${data.model_b.raw_output ? `
                                    <p style="margin-top: 0.5rem;"><strong>模型原始输出:</strong></p>
                                    <pre style="background: white; padding: 0.5rem; border-radius: 0.25rem; overflow-x: auto; font-size: 0.75rem;">${data.model_b.raw_output}</pre>
                                ` : ''}
                                ${data.model_b.parsed_result ? `
                                    <p style="margin-top: 0.5rem;"><strong>解析后的结果:</strong></p>
                                    <pre style="background: white; padding: 0.5rem; border-radius: 0.25rem; overflow-x: auto; font-size: 0.75rem;">${data.model_b.parsed_result}</pre>
                                ` : ''}
                            </div>
                        </details>
                    ` : `<p style="color: red;">验证失败: ${data.model_b.error}</p>`}
                </div>
                
                ${data.comparison ? `
                <div style="grid-column: 1 / -1; padding: 1rem; background: #f9fafb; border-radius: 0.5rem;">
                    <h4>📊 对比分析</h4>
                    <p>检测数量差异: ${data.comparison.count_diff > 0 ? '+' : ''}${data.comparison.count_diff}</p>
                    <p>基础模型: ${data.comparison.model_a_count} | 微调模型: ${data.comparison.model_b_count}</p>
                </div>
                ` : ''}
            `;
        } else {
            gridDiv.innerHTML = '<p style="color: red;">验证失败</p>';
        }
    } catch (error) {
        console.error('验证失败:', error);
        gridDiv.innerHTML = `<p style="color: red;">验证失败: ${error.message}</p>`;
    }
}

// 部署模型
function deployModel(projectId, modelType) {
    const modelTypeName = modelType === 'yolo' ? 'YOLO' : 'Florence-2';
    alert(`模型部署功能:\n\n将训练好的 ${modelTypeName} 模型部署到 OmniParser:\n1. 复制模型文件到相应目录\n2. 修改 OmniParser 配置使用新模型\n\n模型路径: data/models/${projectId}/`);
}

// 删除模型
async function deleteModel(projectId) {
    if (!confirm('确定要删除这个模型吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/models/${projectId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('模型已删除');
            loadModels();
        } else {
            alert('删除失败');
        }
    } catch (error) {
        console.error('删除模型失败:', error);
        alert('删除失败');
    }
}

// 清空日志
function clearLog() {
    document.getElementById('logContent').innerHTML = '';
}

// ============ 新增功能：类别权重配置 ============

// 切换类别权重选项显示
function toggleClassWeightsOptions() {
    const checkbox = document.getElementById('useClassWeights');
    const options = document.getElementById('classWeightsOptions');
    options.style.display = checkbox.checked ? 'block' : 'none';
    
    // 如果启用，自动加载项目的类别列表
    if (checkbox.checked) {
        loadProjectCategories();
    }
}

// 加载项目类别
async function loadProjectCategories() {
    const projectSelect = document.getElementById('projectSelect');
    const projectId = projectSelect.value;
    
    if (!projectId) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/projects/${projectId}/categories`);
        const data = await response.json();
        
        if (data.success && data.categories) {
            const listDiv = document.getElementById('classWeightsList');
            // 保留标题行
            let html = `
                <div style="display: grid; grid-template-columns: 2fr 1fr auto; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem; font-weight: 600; font-size: 0.875rem; color: #6b7280;">
                    <span>类别名称</span>
                    <span>权重</span>
                    <span></span>
                </div>
            `;
            
            // 添加每个类别
            data.categories.forEach(category => {
                html += createClassWeightRow(category, 1.0);
            });
            
            listDiv.innerHTML = html;
        }
    } catch (error) {
        console.error('加载类别失败:', error);
    }
}

// 创建类别权重行
function createClassWeightRow(categoryName = '', weight = 1.0) {
    const id = 'cw_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    return `
        <div id="${id}" style="display: grid; grid-template-columns: 2fr 1fr auto; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem; padding: 0.5rem; background: white; border-radius: 0.375rem;">
            <input type="text" value="${categoryName}" placeholder="类别名称" style="padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem; font-size: 0.875rem;" class="class-weight-name">
            <input type="number" value="${weight}" min="0.1" max="10" step="0.1" style="padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem; font-size: 0.875rem;" class="class-weight-value">
            <button type="button" onclick="removeClassWeightRow('${id}')" style="padding: 0.5rem; background: #ef4444; color: white; border: none; border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem;">
                ❌
            </button>
        </div>
    `;
}

// 添加类别权重行
function addClassWeightRow() {
    const listDiv = document.getElementById('classWeightsList');
    listDiv.insertAdjacentHTML('beforeend', createClassWeightRow());
}

// 删除类别权重行
function removeClassWeightRow(id) {
    const row = document.getElementById(id);
    if (row) {
        row.remove();
    }
}

// 获取类别权重配置
function getClassWeights() {
    const checkbox = document.getElementById('useClassWeights');
    if (!checkbox || !checkbox.checked) {
        return null;
    }
    
    const weights = {};
    const names = document.querySelectorAll('.class-weight-name');
    const values = document.querySelectorAll('.class-weight-value');
    
    for (let i = 0; i < names.length; i++) {
        const name = names[i].value.trim();
        const value = parseFloat(values[i].value);
        if (name && !isNaN(value) && value > 0) {
            weights[name] = value;
        }
    }
    
    return Object.keys(weights).length > 0 ? weights : null;
}

// 获取自定义增强配置（细粒度方法列表）
function getCustomAugmentationCategories() {
    const strategy = document.getElementById('augmentationStrategy')?.value;
    if (strategy !== 'custom') {
        return null;
    }
    
    // 收集所有勾选的具体方法（不是类别复选框）
    const methods = [];
    const checkboxes = document.querySelectorAll('#customAugmentation input[type="checkbox"][data-method]');
    checkboxes.forEach(checkbox => {
        if (checkbox.checked) {
            const method = checkbox.getAttribute('data-method');
            if (method) {
                methods.push(method);
            }
        }
    });
    
    console.log('[数据增强] 自定义方法:', methods);
    return methods.length > 0 ? methods : null;
}

// 获取早停配置
function getEarlyStoppingConfig() {
    const checkbox = document.getElementById('useEarlyStopping');
    if (!checkbox || !checkbox.checked) {
        return { target_loss: null, patience: null };
    }
    
    return {
        target_loss: parseFloat(document.getElementById('targetLoss')?.value) || null,
        patience: parseInt(document.getElementById('earlyStopPatience')?.value) || 3
    };
}

// 获取ReduceLROnPlateau配置
function getReduceLRConfig() {
    const checkbox = document.getElementById('useReduceLR');
    if (!checkbox || !checkbox.checked) {
        return { enabled: false };
    }
    
    return {
        enabled: true,
        patience: parseInt(document.getElementById('reduceLRPatience')?.value) || 5,
        factor: parseFloat(document.getElementById('reduceLRFactor')?.value) || 0.5,
        min_lr: parseFloat(document.getElementById('reduceLRMinLR')?.value) || 1e-8
    };
}

// ============ 新增功能：早停配置 ============

// 切换早停选项显示
function toggleEarlyStoppingOptions() {
    const checkbox = document.getElementById('useEarlyStopping');
    const options = document.getElementById('earlyStoppingOptions');
    options.style.display = checkbox.checked ? 'block' : 'none';
}

// 切换自适应学习率选项显示
function toggleReduceLROptions() {
    const checkbox = document.getElementById('useReduceLR');
    const options = document.getElementById('reduceLROptions');
    options.style.display = checkbox.checked ? 'block' : 'none';
}

// ============ 新增功能：高级训练参数 ============

// 切换高级参数选项显示
function toggleAdvancedParamsOptions() {
    const checkbox = document.getElementById('useAdvancedParams');
    const options = document.getElementById('advancedParamsOptions');
    options.style.display = checkbox.checked ? 'block' : 'none';
}

// 获取高级训练参数
function getAdvancedParams() {
    const checkbox = document.getElementById('useAdvancedParams');
    if (!checkbox || !checkbox.checked) {
        return {};
    }
    
    return {
        warmup_steps: parseInt(document.getElementById('warmupSteps').value) || 100,
        weight_decay: parseFloat(document.getElementById('weightDecay').value) || 0.01,
        gradient_accumulation_steps: parseInt(document.getElementById('gradientAccumulationSteps').value) || 1,
        max_grad_norm: parseFloat(document.getElementById('maxGradNorm').value) || 1.0
    };
}

// ============ 新增功能：增强策略预览 ============

// 更新增强预览
function updateAugmentationPreview() {
    const strategy = document.getElementById('augmentationStrategy').value;
    const previewDiv = document.getElementById('augPreview');
    
    if (!previewDiv) return;
    
    const strategyInfo = {
        'light': {
            name: '轻度增强',
            methods: ['亮度调整', '对比度调整', '锐化'],
            count: '3-5',
            desc: '适合数据充足、追求稳定的场景'
        },
        'moderate': {
            name: '中度增强',
            methods: ['亮度', '对比度', '锐化', '模糊', 'DPI缩放', '分辨率'],
            count: '6-8',
            desc: '推荐的默认策略，平衡效果与多样性'
        },
        'aggressive': {
            name: '激进增强',
            methods: ['亮度', '对比度', '锐化', '模糊', '饱和度', 'DPI', '分辨率', '纵横比', '旋转'],
            count: '10-15',
            desc: '适合数据稀缺场景，最大化样本多样性'
        },
        'super': {
            name: 'Super增强',
            methods: ['亮度(5种)', '对比度(4种)', 'DPI(6种)', '锐化/模糊(5种)', '边缘检测(3种)', '噪声(4种)', '饱和度(4种)', '透视变换', '颜色抖动', '旋转'],
            count: '35',
            desc: '🔥 最强增强策略！包含边缘检测、透视变换等高级技术，适合单图标精准识别'
        },
        'mobile': {
            name: '移动端优化',
            methods: ['DPI缩放(1x/2x/3x)', '屏幕方向', '暗色模式', '运动模糊'],
            count: '8-12',
            desc: '针对移动应用场景优化'
        },
        'desktop': {
            name: '桌面端优化',
            methods: ['分辨率变化', 'DPI缩放', '锐化', '高对比度', '压缩', '显示比例'],
            count: '8-12',
            desc: '针对桌面应用场景优化'
        },
        'web': {
            name: 'Web端优化',
            methods: ['浏览器缩放', '压缩', '暗色模式', '响应式缩放', '亮度对比度'],
            count: '8-12',
            desc: '针对网页应用场景优化'
        },
        'cross_platform': {
            name: '跨平台',
            methods: ['所有平台的综合增强策略'],
            count: '15-20',
            desc: '覆盖所有平台的使用场景'
        }
    };
    
    const info = strategyInfo[strategy] || strategyInfo['moderate'];
    
    previewDiv.innerHTML = `
        <div style="margin-bottom: 0.5rem;">
            <strong style="color: #1f2937;">${info.name}</strong>
            ${strategy === 'super' ? '<span style="background: linear-gradient(90deg, #ef4444, #f59e0b); color: white; padding: 0.125rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; margin-left: 0.5rem;">HOT</span>' : ''}
        </div>
        <div style="color: #6b7280; font-size: 0.875rem; margin-bottom: 0.5rem;">
            ${info.desc}
        </div>
        <div style="display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 0.5rem;">
            <div>
                <span style="color: #6b7280;">增强方法:</span>
                <span style="font-weight: 600; color: #3b82f6;">${info.count}种</span>
            </div>
        </div>
        <div style="margin-top: 0.5rem; padding: 0.5rem; background: #f9fafb; border-radius: 0.25rem; font-size: 0.75rem; color: #6b7280;">
            <strong>包含:</strong> ${info.methods.join(' · ')}
        </div>
    `;
}

// 页面加载时初始化预览
document.addEventListener('DOMContentLoaded', function() {
    updateAugmentationPreview();
});

// ============ 继续训练功能 ============

// 显示继续训练对话框
function showResumeDialog(projectId, timestamp, currentLoss, completedEpochs) {
    const targetLoss = document.getElementById('targetLoss')?.value || 0.20;
    const lossDifference = Math.max(0, currentLoss - targetLoss);
    
    // 根据Loss差距建议额外轮数
    let suggestedEpochs = 10;
    if (lossDifference < 0.05) {
        suggestedEpochs = 5;
    } else if (lossDifference < 0.10) {
        suggestedEpochs = 10;
    } else if (lossDifference < 0.20) {
        suggestedEpochs = 15;
    } else {
        suggestedEpochs = 20;
    }
    
    const additionalEpochs = prompt(
        `🔄 继续训练\n\n` +
        `当前状态:\n` +
        `• 已训练: ${completedEpochs}轮\n` +
        `• 当前Loss: ${currentLoss.toFixed(4)}\n` +
        `• 目标Loss: ${targetLoss}\n` +
        `• Loss差距: ${lossDifference.toFixed(4)}\n\n` +
        `建议额外训练 ${suggestedEpochs} 轮\n\n` +
        `请输入要继续训练的轮数:`,
        suggestedEpochs
    );
    
    if (!additionalEpochs || parseInt(additionalEpochs) <= 0) {
        return;
    }
    
    // 询问学习率
    const currentLR = document.getElementById('florenceLearningRate')?.value || '1e-6';
    const suggestedLR = currentLR === '1e-6' ? '5e-7' : '1e-7';
    
    const newLR = prompt(
        `🔄 继续训练 - 学习率设置\n\n` +
        `初始训练使用的学习率: ${currentLR}\n\n` +
        `建议使用更小的学习率进行精细调整:\n` +
        `• 5e-7 - 推荐（适中）\n` +
        `• 1e-7 - 更精细\n` +
        `• 1e-6 - 保持不变\n\n` +
        `请输入学习率（如: 5e-7）:`,
        suggestedLR
    );
    
    if (!newLR) {
        return;
    }
    
    // 确认继续训练
    if (!confirm(
        `确认继续训练？\n\n` +
        `项目: ${projectId}\n` +
        `额外轮数: ${additionalEpochs}轮 (${completedEpochs} + ${additionalEpochs} = ${parseInt(completedEpochs) + parseInt(additionalEpochs)}轮)\n` +
        `学习率: ${newLR}\n` +
        `预计时间: ~${parseInt(additionalEpochs) * 2}分钟\n\n` +
        `提示: 将加载已训练的模型继续训练，保留已学习的知识。`
    )) {
        return;
    }
    
    // 调用继续训练
    resumeTraining(projectId, timestamp, parseInt(additionalEpochs), parseFloat(newLR));
}

// 继续训练
async function resumeTraining(projectId, timestamp, additionalEpochs, learningRate) {
    try {
        console.log('开始继续训练:', projectId, timestamp, additionalEpochs, learningRate);
        
        // 构建配置
        const resumeConfig = {
            model_timestamp: timestamp,
            additional_epochs: additionalEpochs,
            learning_rate: learningRate,
            batch_size: parseInt(document.getElementById('florenceBatchSize')?.value) || 12,
            
            // 继承早停配置
            ...getEarlyStoppingConfig(),
            
            // 继承ReduceLR配置
            reduce_lr_config: getReduceLRConfig(),
            
            // 其他参数
            warmup_steps: 0,
            weight_decay: 0.01,
            max_grad_norm: 1.0,
            gradient_accumulation_steps: 1
        };
        
        console.log('继续训练配置:', resumeConfig);
        
        // 显示进度容器
        document.getElementById('progressContainer').style.display = 'block';
        const logContent = document.getElementById('logContent');
        const progressBar = document.getElementById('progressBar');
        
        // 清空之前的日志
        logContent.innerHTML = '<div style="color: #10b981; font-weight: bold;">🔄 准备继续训练...</div>';
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
        
        // 禁用训练按钮
        const trainBtn = document.getElementById('trainBtn');
        if (trainBtn) {
            trainBtn.disabled = true;
            trainBtn.textContent = '⏳ 继续训练中...';
        }
        
        // 显示停止按钮和完成训练按钮
        const stopBtn = document.getElementById('stopBtn');
        if (stopBtn) {
            stopBtn.style.display = 'inline-block';
        }
        const finishBtn = document.getElementById('finishBtn');
        if (finishBtn) {
            finishBtn.style.display = 'inline-block';
        }
        
        // 保存训练状态
        currentTrainingProject = projectId;
        localStorage.setItem('trainingProject', projectId);
        localStorage.setItem('trainingStartTime', Date.now().toString());
        
        // 发送继续训练请求
        const response = await fetch(`${API_BASE}/api/projects/${projectId}/train/resume`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(resumeConfig)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // 处理流式响应
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (!line.trim()) continue;
                
                try {
                    const data = JSON.parse(line);
                    console.log('继续训练更新:', data);
                    
                    if (data.type === 'log') {
                        logContent.innerHTML += `<div>${data.message}</div>`;
                        logContent.scrollTop = logContent.scrollHeight;
                    }
                    
                    if (data.type === 'progress' && data.progress !== undefined) {
                        progressBar.style.width = data.progress + '%';
                        progressBar.textContent = data.progress + '%';
                    }
                    
                    if (data.type === 'complete') {
                        progressBar.style.width = '100%';
                        progressBar.textContent = '100% 完成';
                        progressBar.style.background = 'linear-gradient(90deg, #10b981, #059669)';
                        
                        // 重置按钮状态
                        if (trainBtn) {
                            trainBtn.disabled = false;
                            trainBtn.textContent = '🚀 开始训练';
                        }
                        if (stopBtn) {
                            stopBtn.style.display = 'none';
                        }
                        if (finishBtn) {
                            finishBtn.style.display = 'none';
                        }
                        
                        // 刷新模型列表
                        setTimeout(() => {
                            loadModels();
                        }, 2000);
                        
                        // 清除训练状态
                        currentTrainingProject = null;
                        localStorage.removeItem('trainingProject');
                        localStorage.removeItem('trainingStartTime');
                    }
                    
                    if (data.type === 'error') {
                        progressBar.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
                        alert('继续训练失败: ' + data.message);
                        
                        // 重置按钮
                        if (trainBtn) {
                            trainBtn.disabled = false;
                            trainBtn.textContent = '🚀 开始训练';
                        }
                        if (stopBtn) {
                            stopBtn.style.display = 'none';
                        }
                        if (finishBtn) {
                            finishBtn.style.display = 'none';
                        }
                    }
                } catch (e) {
                    console.error('解析响应失败:', e, line);
                }
            }
        }
        
        console.log('继续训练完成');
        
    } catch (error) {
        console.error('继续训练失败:', error);
        alert('继续训练失败: ' + error.message);
        
        // 重置UI状态
        const trainBtn = document.getElementById('trainBtn');
        if (trainBtn) {
            trainBtn.disabled = false;
            trainBtn.textContent = '🚀 开始训练';
        }
        const stopBtn = document.getElementById('stopBtn');
        if (stopBtn) {
            stopBtn.style.display = 'none';
        }
        const finishBtn = document.getElementById('finishBtn');
        if (finishBtn) {
            finishBtn.style.display = 'none';
        }
        
        currentTrainingProject = null;
        localStorage.removeItem('trainingProject');
    }
}
