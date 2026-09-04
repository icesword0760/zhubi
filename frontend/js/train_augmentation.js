// 数据增强和智能配置功能

// 切换数据增强选项
function toggleAugmentationOptions() {
    const checkbox = document.getElementById('useAugmentation');
    const options = document.getElementById('augmentationOptions');
    options.style.display = checkbox.checked ? 'block' : 'none';
    
    if (checkbox.checked) {
        updateAugmentationPreview();
    }
}

// 更新数据增强预览
function updateAugmentationPreview() {
    const strategy = document.getElementById('augmentationStrategy').value;
    const preview = document.getElementById('augPreview');
    
    // 显示/隐藏自定义选项
    const customDiv = document.getElementById('customAugmentation');
    customDiv.style.display = strategy === 'custom' ? 'block' : 'none';
    
    // 计算增强后的样本数
    const projectSelect = document.getElementById('projectSelect');
    if (!projectSelect.value) {
        preview.innerHTML = '<span style="color: #6b7280;">请先选择项目</span>';
        return;
    }
    
    // 获取当前项目的标注数量（使用标注框总数而不是图片数）
    fetch(`/api/projects/${projectSelect.value}`)
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // 对于Florence-2训练，使用标注框总数（每个框是独立样本）
                const modelType = document.querySelector('.model-type-btn.active')?.dataset?.type || 'florence2';
                const baseSamples = modelType === 'florence2' 
                    ? (data.project.total_boxes || 0)  // Florence-2: 标注框数量
                    : (data.project.annotated_count || 0);  // YOLO: 图片数量
                    
                const multiplier = getAugmentationMultiplier(strategy);
                const totalSamples = baseSamples * multiplier;
                
                const sampleType = modelType === 'florence2' ? '标注框' : '图片';
                
                preview.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-weight: 600; color: #0c4a6e; margin-bottom: 0.25rem;">
                                预计生成样本数
                            </div>
                            <div style="color: #64748b; font-size: 0.8rem;">
                                原始: ${baseSamples} 个${sampleType} → 增强后: ${totalSamples} 个样本
                            </div>
                        </div>
                        <div style="background: #06b6d4; color: white; padding: 0.5rem 1rem; border-radius: 0.375rem; font-weight: 600; font-size: 1.1rem;">
                            ${totalSamples} 个
                        </div>
                    </div>
                `;
                
                // 自动调整训练参数
                suggestTrainingParams(totalSamples);
            }
        })
        .catch(err => console.error('获取项目信息失败:', err));
}

// 获取增强倍数
function getAugmentationMultiplier(strategy) {
    const multipliers = {
        'light': 4,              // 原始 + 3个变体
        'moderate': 7,           // 原始 + 6个变体
        'aggressive': 11,        // 原始 + 10个变体
        'super': 36,             // 原始 + 35个变体（Super增强）
        'mobile': 8,             // 移动端优化：7个变体
        'desktop': 8,            // 桌面端优化：7个变体
        'web': 8,                // Web端优化：7个变体
        'cross_platform': 11,    // 跨平台：10个变体
        'custom': calculateCustomMultiplier()  // 动态计算
    };
    return multipliers[strategy] || 7;
}

// 计算自定义增强的倍数
function calculateCustomMultiplier() {
    let totalMethods = 1;  // 1 = 原始样本
    
    // 检查每个勾选的具体方法（不是类别复选框）
    const checkboxes = document.querySelectorAll('#customAugmentation input[type="checkbox"][data-method]');
    checkboxes.forEach(checkbox => {
        if (checkbox.checked) {
            totalMethods += 1;
        }
    });
    
    return totalMethods;
}

// 展开/折叠增强类别
function toggleAugCategory(category) {
    const methodsDiv = document.getElementById(`${category}-methods`);
    const arrow = document.getElementById(`${category}-arrow`);
    
    if (methodsDiv.style.display === 'none' || methodsDiv.style.display === '') {
        methodsDiv.style.display = 'grid';
        arrow.textContent = '▼';
    } else {
        methodsDiv.style.display = 'none';
        arrow.textContent = '▶';
    }
}

// 全选/取消全选某个类别
function toggleAllInCategory(category) {
    const categoryCheckbox = document.querySelector(`input[data-aug-category="${category}"]`);
    const methodCheckboxes = document.querySelectorAll(`input[data-aug="${category}"][data-method]`);
    
    methodCheckboxes.forEach(checkbox => {
        checkbox.checked = categoryCheckbox.checked;
    });
    
    updateCustomAugmentationPreview();
}

// 更新自定义增强预览
function updateCustomAugmentationPreview() {
    const strategy = document.getElementById('augmentationStrategy').value;
    if (strategy === 'custom') {
        updateAugmentationPreview();
    }
}

// 根据样本数量推荐训练参数
function suggestTrainingParams(sampleCount) {
    if (sampleCount < 5) {
        // 样本太少，给出警告
        showTrainingTip('⚠️ 样本数量较少，建议至少10个样本以获得更好效果');
    } else if (sampleCount < 20) {
        // 中等样本量
        showTrainingTip('💡 样本数量适中，建议使用"高精度"配置');
    } else {
        // 充足的样本
        showTrainingTip('✅ 样本数量充足，可以使用"生产环境"配置');
    }
}

// 显示训练提示
function showTrainingTip(message) {
    // 可以在界面上显示提示信息
    console.log('Training Tip:', message);
}

// 应用场景化配置
function applyScenarioConfig(scenario) {
    console.log(`应用场景配置: ${scenario}`);
    
    const configs = {
        'test': {
            name: '🧪 极速验证',
            description: '2-5个样本，快速测试流程（10-15分钟）',
            epochs: 300,
            learningRate: '0.00005',
            batchSize: 2,
            augmentation: true,
            augStrategy: 'aggressive',
            trainSplit: 100,
            valSplit: 0,
            testSplit: 0,
            sampleRange: '2-5个',
            timeEstimate: '10-15分钟',
            useLora: true,
            loraR: 8,
            loraAlpha: 8
        },
        'production': {
            name: '🚀 标准训练',
            description: '10-30个样本，平衡效果与时间（30-60分钟）',
            epochs: 200,
            learningRate: '0.00001',
            batchSize: 4,
            augmentation: true,
            augStrategy: 'moderate',
            trainSplit: 80,
            valSplit: 20,
            testSplit: 0,
            sampleRange: '10-30个',
            timeEstimate: '30-60分钟',
            useLora: true,
            loraR: 16,
            loraAlpha: 16
        },
        'precision': {
            name: '🎯 生产部署',
            description: '30+个样本，追求最佳效果（1-2小时）',
            epochs: 100,
            learningRate: '0.000001',
            batchSize: 4,
            augmentation: false,
            augStrategy: 'moderate',
            trainSplit: 70,
            valSplit: 20,
            testSplit: 10,
            sampleRange: '30+个',
            timeEstimate: '1-2小时',
            useLora: true,
            loraR: 16,
            loraAlpha: 16
        }
    };
    
    const config = configs[scenario];
    if (!config) return;
    
    // 应用配置到Florence-2参数
    if (currentModelType === 'florence2') {
        document.getElementById('florenceEpochs').value = config.epochs;
        document.getElementById('florenceLearningRate').value = config.learningRate;
        document.getElementById('florenceBatchSize').value = config.batchSize;
        document.getElementById('trainSplit').value = config.trainSplit;
        document.getElementById('valSplit').value = config.valSplit;
        document.getElementById('testSplit').value = config.testSplit;
        
        // 设置LoRA
        document.getElementById('useLora').checked = config.useLora;
        document.getElementById('loraOptions').style.display = config.useLora ? 'block' : 'none';
        if (config.useLora) {
            document.getElementById('loraR').value = config.loraR;
            document.getElementById('loraAlpha').value = config.loraAlpha;
        }
        
        // 设置数据增强
        document.getElementById('useAugmentation').checked = config.augmentation;
        toggleAugmentationOptions();
        
        if (config.augmentation) {
            document.getElementById('augmentationStrategy').value = config.augStrategy;
            updateAugmentationPreview();
        }
    }
    
    // 显示应用成功的提示
    showConfigAppliedNotification(config);
}

// 显示配置应用成功的通知
function showConfigAppliedNotification(config) {
    // 创建通知元素
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: linear-gradient(135deg, #10b981, #059669);
        color: white;
        padding: 1.25rem 1.75rem;
        border-radius: 0.75rem;
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
        z-index: 1000;
        animation: slideIn 0.3s ease-out;
        max-width: 400px;
    `;
    
    notification.innerHTML = `
        <div style="display: flex; align-items: start; gap: 1rem;">
            <span style="font-size: 2rem;">✓</span>
            <div style="flex: 1;">
                <div style="font-weight: 700; font-size: 1.1rem; margin-bottom: 0.5rem;">${config.name} 配置已应用</div>
                <div style="font-size: 0.875rem; opacity: 0.95; margin-bottom: 0.75rem;">${config.description}</div>
                <div style="background: rgba(255,255,255,0.15); padding: 0.5rem; border-radius: 0.375rem; font-size: 0.8rem;">
                    <div style="margin-bottom: 0.25rem;">📊 样本范围: ${config.sampleRange}</div>
                    <div style="margin-bottom: 0.25rem;">⏱️ 预计耗时: ${config.timeEstimate}</div>
                    <div>🎯 Epochs: ${config.epochs} | LR: ${config.learningRate}</div>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    // 5秒后自动移除
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-in';
        setTimeout(() => notification.remove(), 300);
    }, 5000);
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

// 在项目选择变化时更新预览
document.addEventListener('DOMContentLoaded', () => {
    const projectSelect = document.getElementById('projectSelect');
    if (projectSelect) {
        projectSelect.addEventListener('change', () => {
            const useAug = document.getElementById('useAugmentation');
            if (useAug && useAug.checked) {
                updateAugmentationPreview();
            }
        });
    }
});

// ==================== 智能配置助手 ====================

// 应用智能配置
function applySmartConfig(configType) {
    const configs = {
        'quick': {
            name: '⚡ 极速验证',
            description: '快速测试模型效果',
            // YOLO配置
            yolo: {
                epochs: 20,
                learningRate: '0.01',
                batchSize: 16,
                trainSplit: 80,
                valSplit: 20,
                testSplit: 0
            },
            // Florence-2配置
            florence: {
                epochs: 10,
                learningRate: '0.000001',
                batchSize: 4,
                trainSplit: 100,
                valSplit: 0,
                testSplit: 0,
                useLora: true,
                loraR: 8,
                loraAlpha: 8
            },
            augmentation: true,
            augStrategy: 'light'
        },
        'standard': {
            name: '🎯 标准训练',
            description: '平衡效果与时间',
            yolo: {
                epochs: 50,
                learningRate: '0.01',
                batchSize: 16,
                trainSplit: 70,
                valSplit: 20,
                testSplit: 10
            },
            florence: {
                epochs: 50,
                learningRate: '0.00001',
                batchSize: 4,
                trainSplit: 80,
                valSplit: 20,
                testSplit: 0,
                useLora: true,
                loraR: 16,
                loraAlpha: 16
            },
            augmentation: true,
            augStrategy: 'moderate'
        },
        'production': {
            name: '🏭 生产部署',
            description: '追求最佳模型性能',
            yolo: {
                epochs: 100,
                learningRate: '0.01',
                batchSize: 16,
                trainSplit: 70,
                valSplit: 20,
                testSplit: 10
            },
            florence: {
                epochs: 100,
                learningRate: '0.000001',
                batchSize: 4,
                trainSplit: 70,
                valSplit: 20,
                testSplit: 10,
                useLora: true,
                loraR: 16,
                loraAlpha: 16
            },
            augmentation: true,
            augStrategy: 'aggressive'
        }
    };
    
    const config = configs[configType];
    if (!config) return;
    
    // 应用配置到对应模型
    if (currentModelType === 'yolo') {
        document.getElementById('yoloEpochs').value = config.yolo.epochs;
        document.getElementById('yoloLearningRate').value = config.yolo.learningRate;
        document.getElementById('yoloBatchSize').value = config.yolo.batchSize;
        document.getElementById('yoloTrainSplit').value = config.yolo.trainSplit;
        document.getElementById('yoloValSplit').value = config.yolo.valSplit;
        document.getElementById('yoloTestSplit').value = config.yolo.testSplit;
    } else if (currentModelType === 'florence2') {
        document.getElementById('florenceEpochs').value = config.florence.epochs;
        document.getElementById('florenceLearningRate').value = config.florence.learningRate;
        document.getElementById('florenceBatchSize').value = config.florence.batchSize;
        document.getElementById('trainSplit').value = config.florence.trainSplit;
        document.getElementById('valSplit').value = config.florence.valSplit;
        document.getElementById('testSplit').value = config.florence.testSplit;
        
        // 设置LoRA
        document.getElementById('useLora').checked = config.florence.useLora;
        const loraOptions = document.getElementById('loraOptions');
        if (loraOptions) {
            loraOptions.style.display = config.florence.useLora ? 'block' : 'none';
        }
        if (config.florence.useLora) {
            document.getElementById('loraR').value = config.florence.loraR;
            document.getElementById('loraAlpha').value = config.florence.loraAlpha;
        }
        
        // 设置数据增强
        document.getElementById('useAugmentation').checked = config.augmentation;
        toggleAugmentationOptions();
        
        if (config.augmentation) {
            document.getElementById('augmentationStrategy').value = config.augStrategy;
            updateAugmentationPreview();
        }
    }
    
    // 显示配置摘要
    updateConfigSummary(config.name, config.description);
    
    // 显示成功通知
    showNotification('success', `${config.name} 配置已应用`, config.description);
}

// 更新配置摘要
function updateConfigSummary(name, description) {
    const summary = document.getElementById('configSummary');
    const summaryText = document.getElementById('configSummaryText');
    
    if (summary && summaryText) {
        summaryText.textContent = `${name} - ${description}`;
        summary.style.display = 'block';
        
        // 5秒后淡出
        setTimeout(() => {
            summary.style.opacity = '0.5';
        }, 5000);
    }
}

// ==================== 设备端配置 ====================

let currentDeviceConfig = null;

// 选择设备端配置
function selectDeviceConfig(deviceType) {
    currentDeviceConfig = deviceType;
    
    // 更新UI选中状态
    ['mobile', 'desktop', 'web', 'cross_platform'].forEach(type => {
        const element = document.getElementById(`device-${type}`);
        if (element) {
            if (type === deviceType) {
                element.style.borderColor = '#3b82f6';
                element.style.background = '#eff6ff';
                element.style.fontWeight = '700';
            } else {
                element.style.borderColor = '#cbd5e1';
                element.style.background = 'white';
                element.style.fontWeight = '600';
            }
        }
    });
    
    // 配置说明
    const descriptions = {
        'mobile': {
            icon: '📱',
            title: '移动端优化',
            desc: '模拟不同DPI缩放(1x/2x/3x)、屏幕方向(横屏/竖屏)、暗色模式、运动模糊等移动设备特性',
            strategy: 'mobile'
        },
        'desktop': {
            icon: '🖥️',
            title: '桌面端优化',
            desc: '模拟不同分辨率(1080p/2K/4K)、DPI缩放(125%/150%)、锐化/轻微模糊等桌面显示特性',
            strategy: 'desktop'
        },
        'web': {
            icon: '🌐',
            title: 'Web端优化',
            desc: '模拟浏览器缩放(75%/90%/110%/125%)、图片压缩、暗色模式、饱和度变化等Web场景',
            strategy: 'web'
        },
        'cross_platform': {
            icon: '🔄',
            title: '跨平台通用',
            desc: '综合移动端、桌面端、Web端的关键增强策略，适用于多平台部署场景',
            strategy: 'cross_platform'
        }
    };
    
    const config = descriptions[deviceType];
    if (!config) return;
    
    // 显示配置说明
    const descElement = document.getElementById('deviceConfigDesc');
    if (descElement) {
        descElement.innerHTML = `
            <div style="display: flex; align-items: start; gap: 0.75rem;">
                <span style="font-size: 1.5rem;">${config.icon}</span>
                <div>
                    <div style="font-weight: 600; color: #1e40af; margin-bottom: 0.25rem;">${config.title}</div>
                    <div style="color: #3b82f6; font-size: 0.8rem;">${config.desc}</div>
                </div>
            </div>
        `;
        descElement.style.display = 'block';
    }
    
    // 自动应用对应的增强策略
    const augStrategy = document.getElementById('augmentationStrategy');
    if (augStrategy) {
        augStrategy.value = config.strategy;
        updateAugmentationPreview();
    }
    
    // 显示通知
    showNotification('info', `${config.icon} ${config.title}`, `已切换到${config.title}配置`);
}

// 显示通知
function showNotification(type, title, message) {
    const colors = {
        'success': 'linear-gradient(135deg, #10b981, #059669)',
        'info': 'linear-gradient(135deg, #3b82f6, #2563eb)',
        'warning': 'linear-gradient(135deg, #f59e0b, #d97706)',
        'error': 'linear-gradient(135deg, #ef4444, #dc2626)'
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
        z-index: 1000;
        animation: slideIn 0.3s ease-out;
        max-width: 400px;
        font-size: 0.875rem;
    `;
    
    notification.innerHTML = `
        <div style="display: flex; align-items: start; gap: 0.75rem;">
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

