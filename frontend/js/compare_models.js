// 模型对比验证脚本

let selectedImage = null;
let selectedProject = null;

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
    await loadProjects();
    setupEventListeners();
});

// 加载项目列表
async function loadProjects() {
    try {
        const response = await fetch('/api/projects');
        const data = await response.json();
        
        if (data.success) {
            const select = document.getElementById('projectSelect');
            select.innerHTML = '<option value="">选择微调模型的项目...</option>';
            
            data.projects.forEach(project => {
                const option = document.createElement('option');
                option.value = project.id;
                option.textContent = `${project.name} (${project.annotated_count}张标注)`;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('加载项目失败:', error);
    }
}

// 设置事件监听
function setupEventListeners() {
    const uploadArea = document.getElementById('uploadArea');
    const imageInput = document.getElementById('imageInput');
    const compareBtn = document.getElementById('compareBtn');
    const projectSelect = document.getElementById('projectSelect');

    // 点击上传区域
    uploadArea.addEventListener('click', () => {
        imageInput.click();
    });

    // 文件选择
    imageInput.addEventListener('change', handleFileSelect);

    // 拖拽上传
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });

    // 项目选择
    projectSelect.addEventListener('change', (e) => {
        selectedProject = e.target.value;
        updateCompareButton();
        
        if (selectedProject) {
            document.getElementById('fineTunedModelName').textContent = 
                e.target.options[e.target.selectedIndex].text;
        } else {
            document.getElementById('fineTunedModelName').textContent = '选择项目...';
        }
    });

    // 开始对比
    compareBtn.addEventListener('click', startComparison);
}

// 处理文件选择
function handleFileSelect(e) {
    const files = e.target.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
}

// 处理文件
function handleFile(file) {
    if (!file.type.startsWith('image/')) {
        alert('请上传图片文件');
        return;
    }

    selectedImage = file;
    
    // 显示预览
    const reader = new FileReader();
    reader.onload = (e) => {
        const preview = document.getElementById('previewImage');
        preview.src = e.target.result;
        preview.style.display = 'block';
    };
    reader.readAsDataURL(file);

    updateCompareButton();
}

// 更新对比按钮状态
function updateCompareButton() {
    const btn = document.getElementById('compareBtn');
    btn.disabled = !(selectedImage && selectedProject);
}

// 开始对比
async function startComparison() {
    if (!selectedImage || !selectedProject) {
        return;
    }

    // 显示加载状态
    document.getElementById('loadingSpinner').style.display = 'block';
    document.getElementById('resultsSection').style.display = 'none';

    try {
        // 准备表单数据
        const formData = new FormData();
        formData.append('image', selectedImage);
        formData.append('model_a_path', '../weights/icon_caption_florence');
        formData.append('model_b_path', `data/models/${selectedProject}/final_model`);
        formData.append('model_type', 'florence2');

        // 发送请求
        const response = await fetch('/api/models/compare', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (result.success) {
            displayResults(result);
        } else {
            alert(`对比失败: ${result.error || '未知错误'}`);
        }
    } catch (error) {
        console.error('对比失败:', error);
        alert(`对比失败: ${error.message}`);
    } finally {
        document.getElementById('loadingSpinner').style.display = 'none';
    }
}

// 显示结果
function displayResults(result) {
    const resultsSection = document.getElementById('resultsSection');
    resultsSection.style.display = 'block';

    // 滚动到结果区域
    resultsSection.scrollIntoView({ behavior: 'smooth' });

    // 显示基础模型结果
    displayModelResult('base', result.model_a);

    // 显示微调模型结果
    displayModelResult('tuned', result.model_b);

    // 显示对比总结
    displaySummary(result);
}

// 显示单个模型的结果
function displayModelResult(type, data) {
    const prefix = type === 'base' ? 'base' : 'tuned';
    const imageContainer = document.getElementById(`${prefix}ResultImage`);
    const detectionsContainer = document.getElementById(`${prefix}Detections`);

    if (!data.success) {
        detectionsContainer.innerHTML = `
            <div style="color: #ef4444; padding: 1rem;">
                <strong>❌ 识别失败</strong>
                <p>${data.error || '未知错误'}</p>
            </div>
        `;
        return;
    }

    // 显示结果图片
    if (data.result_image) {
        imageContainer.src = `data:image/jpeg;base64,${data.result_image}`;
    } else {
        // 如果没有结果图，显示原图
        const reader = new FileReader();
        reader.onload = (e) => {
            imageContainer.src = e.target.result;
        };
        reader.readAsDataURL(selectedImage);
    }

    // 显示检测结果
    const detections = data.detections || [];
    
    let html = '<h4 style="margin: 0 0 0.75rem 0; color: #6b7280;">检测结果：</h4>';
    
    if (detections.length === 0) {
        html += '<p style="color: #6b7280;">未检测到任何对象</p>';
    } else {
        html += `<p style="margin-bottom: 0.75rem; color: #3b82f6; font-weight: 600;">共检测到 ${detections.length} 个对象</p>`;
        
        // 显示前5个检测结果
        const showCount = Math.min(5, detections.length);
        for (let i = 0; i < showCount; i++) {
            const det = detections[i];
            html += `
                <div class="detection-item">
                    <div class="detection-label">${i + 1}. ${det.label}</div>
                    <div class="detection-bbox">位置: [${det.bbox.map(v => Math.round(v)).join(', ')}]</div>
                </div>
            `;
        }

        if (detections.length > 5) {
            html += `<p style="color: #6b7280; margin-top: 0.5rem;">... 还有 ${detections.length - 5} 个检测结果</p>`;
        }
    }

    detectionsContainer.innerHTML = html;
}

// 显示对比总结
function displaySummary(result) {
    const summaryContainer = document.getElementById('summaryContent');
    
    const modelA = result.model_a;
    const modelB = result.model_b;

    if (!modelA.success || !modelB.success) {
        summaryContainer.innerHTML = '<p style="color: #ef4444;">无法生成对比总结，请检查识别结果</p>';
        return;
    }

    const detectionsA = modelA.detections || [];
    const detectionsB = modelB.detections || [];

    const labelsA = detectionsA.map(d => d.label);
    const labelsB = detectionsB.map(d => d.label);

    // 统计差异
    const countDiff = detectionsB.length - detectionsA.length;
    const uniqueLabelsB = [...new Set(labelsB)];

    let html = `
        <div class="summary-item">
            <span>基础模型检测数量</span>
            <span class="badge badge-info">${detectionsA.length} 个</span>
        </div>
        <div class="summary-item">
            <span>微调模型检测数量</span>
            <span class="badge badge-info">${detectionsB.length} 个</span>
        </div>
        <div class="summary-item">
            <span>检测数量差异</span>
            <span class="badge ${countDiff === 0 ? 'badge-success' : 'badge-warning'}">${countDiff > 0 ? '+' : ''}${countDiff}</span>
        </div>
    `;

    // 检查是否有训练的类别被识别
    const projectName = document.getElementById('projectSelect').options[document.getElementById('projectSelect').selectedIndex].text;
    
    // 尝试从项目名称或标签中提取关键词
    const hasImprovement = labelsB.some(label => 
        !labelsA.includes(label) || 
        labelsB.filter(l => l === label).length > labelsA.filter(l => l === label).length
    );

    html += `
        <div class="summary-item">
            <span>识别效果</span>
            <span class="badge ${hasImprovement ? 'badge-success' : 'badge-warning'}">
                ${hasImprovement ? '✓ 有差异' : '相似'}
            </span>
        </div>
    `;

    // 显示微调模型的独特识别
    const uniqueToB = uniqueLabelsB.filter(label => !labelsA.includes(label));
    if (uniqueToB.length > 0) {
        html += `
            <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;">
                <strong style="color: #10b981;">✨ 微调模型的新识别：</strong>
                <div style="margin-top: 0.5rem;">
                    ${uniqueToB.slice(0, 5).map(label => 
                        `<span class="badge badge-success" style="margin-right: 0.5rem; margin-top: 0.25rem; display: inline-block;">${label}</span>`
                    ).join('')}
                </div>
            </div>
        `;
    }

    summaryContainer.innerHTML = html;
}

