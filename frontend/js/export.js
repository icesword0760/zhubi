// 朱笔 Zhubi 导出页面逻辑

const API_BASE = '';

// 页面加载
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    setupEventListeners();
});

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

// 更新项目统计
async function updateProjectStats() {
    const projectId = document.getElementById('projectSelect').value;
    if (!projectId) {
        document.getElementById('projectStats').style.display = 'none';
        return;
    }
    
    try {
        const [projectRes, statsRes] = await Promise.all([
            fetch(`${API_BASE}/api/projects/${projectId}`),
            fetch(`${API_BASE}/api/projects/${projectId}/stats`)
        ]);
        
        const projectData = await projectRes.json();
        const statsData = await statsRes.json();
        
        if (projectData.success) {
            const project = projectData.project;
            const stats = statsData.success ? statsData.stats : {
                total_images: project.annotated_count,
                total_boxes: 0,
                category_counts: {}
            };
            
            const statsDiv = document.getElementById('projectStats');
            statsDiv.innerHTML = `
                <h4>📊 项目统计</h4>
                <div class="stats">
                    <div class="stat-item">
                        <label>总图片:</label>
                        <span>${project.image_count}</span>
                    </div>
                    <div class="stat-item">
                        <label>已标注:</label>
                        <span>${project.annotated_count}</span>
                    </div>
                    <div class="stat-item">
                        <label>标注框数:</label>
                        <span>${stats.total_boxes}</span>
                    </div>
                </div>
                ${Object.keys(stats.category_counts).length > 0 ? `
                    <div style="margin-top: 1rem;">
                        <strong>类别分布:</strong>
                        <div style="margin-top: 0.5rem;">
                            ${Object.entries(stats.category_counts).map(([cat, count]) => `
                                <div style="display: flex; justify-content: space-between; 
                                     padding: 0.25rem 0; font-size: 0.875rem;">
                                    <span>${cat}</span>
                                    <span>${count}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
            `;
            statsDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('加载统计失败:', error);
    }
}

// 设置事件监听
function setupEventListeners() {
    // 数据增强切换
    document.getElementById('augmentation').addEventListener('change', (e) => {
        const options = document.getElementById('augmentationOptions');
        options.style.display = e.target.checked ? 'block' : 'none';
    });
}

// 更新划分总和
function updateSplitTotal() {
    const train = parseInt(document.getElementById('trainSplit').value) || 0;
    const val = parseInt(document.getElementById('valSplit').value) || 0;
    const test = parseInt(document.getElementById('testSplit').value) || 0;
    
    const total = train + val + test;
    const warning = document.getElementById('splitWarning');
    
    if (total !== 100) {
        warning.style.display = 'block';
        warning.textContent = `⚠️ 当前总和为 ${total}%，必须等于100%`;
    } else {
        warning.style.display = 'none';
    }
}

// 处理导出
async function handleExport(event) {
    event.preventDefault();
    
    const projectId = document.getElementById('projectSelect').value;
    if (!projectId) {
        alert('请选择项目');
        return;
    }
    
    // 验证划分比例
    const train = parseInt(document.getElementById('trainSplit').value);
    const val = parseInt(document.getElementById('valSplit').value);
    const test = parseInt(document.getElementById('testSplit').value);
    
    if (train + val + test !== 100) {
        alert('数据集划分比例之和必须为100%');
        return;
    }
    
    // 获取导出格式
    const format = document.querySelector('input[name="format"]:checked').value;
    const augmentation = document.getElementById('augmentation').checked;
    
    // 显示进度
    const form = document.querySelector('.export-form-container');
    const progress = document.getElementById('exportProgress');
    const exportBtn = document.getElementById('exportBtn');
    
    form.style.display = 'none';
    progress.style.display = 'block';
    exportBtn.disabled = true;
    
    document.getElementById('progressText').textContent = '正在导出数据...';
    
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${projectId}/export`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    format: format,
                    split: [train / 100, val / 100, test / 100],
                    augmentation: augmentation
                })
            }
        );
        
        if (response.ok) {
            // 下载文件
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${projectId}_${format}_${Date.now()}.zip`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            document.getElementById('progressText').textContent = '✅ 导出成功！';
            
            setTimeout(() => {
                form.style.display = 'block';
                progress.style.display = 'none';
                exportBtn.disabled = false;
            }, 2000);
        } else {
            const data = await response.json();
            alert('导出失败: ' + (data.error || '未知错误'));
            form.style.display = 'block';
            progress.style.display = 'none';
            exportBtn.disabled = false;
        }
    } catch (error) {
        console.error('导出失败:', error);
        alert('导出失败: ' + error.message);
        form.style.display = 'block';
        progress.style.display = 'none';
        exportBtn.disabled = false;
    }
}

// ============ 新增功能：负样本自动标注 ============

// 切换负样本选项显示
function toggleNegativeSamplesOptions() {
    const checkbox = document.getElementById('autoNegativeSamples');
    const options = document.getElementById('negativeSamplesOptions');
    options.style.display = checkbox.checked ? 'block' : 'none';
}