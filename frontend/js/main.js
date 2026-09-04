// 朱笔 Zhubi 主页面逻辑

const API_BASE = '';

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
});

// 加载项目列表
async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/api/projects`);
        const data = await response.json();
        
        if (data.success && data.projects.length > 0) {
            document.getElementById('welcomeSection').style.display = 'none';
            document.getElementById('projectsSection').style.display = 'block';
            renderProjects(data.projects);
        } else {
            document.getElementById('welcomeSection').style.display = 'block';
            document.getElementById('projectsSection').style.display = 'none';
        }
    } catch (error) {
        console.error('加载项目失败:', error);
        showNotification('加载项目失败', 'error');
    }
}

// 渲染项目列表
function renderProjects(projects) {
    const grid = document.getElementById('projectsGrid');
    grid.innerHTML = projects.map(project => `
        <div class="project-card" onclick="openProject('${project.id}')">
            <h3>${project.name}</h3>
            <p>${project.description || '暂无描述'}</p>
            <div class="project-stats">
                <div class="project-stat">
                    <span>📷 ${project.image_count}</span>
                </div>
                <div class="project-stat">
                    <span>✅ ${project.annotated_count}</span>
                </div>
                <div class="project-stat">
                    <span>🏷️ ${project.categories.length} 类</span>
                </div>
            </div>
            <div class="project-actions" onclick="event.stopPropagation()">
                <button class="btn btn-sm btn-primary" 
                        onclick="goToAnnotate('${project.id}')">标注</button>
                <button class="btn btn-sm btn-secondary" 
                        onclick="showProjectDetail('${project.id}')">详情</button>
                <button class="btn btn-sm btn-danger" 
                        onclick="deleteProject('${project.id}')">删除</button>
            </div>
        </div>
    `).join('');
}

// 显示创建项目对话框
function showCreateProject() {
    document.getElementById('createProjectModal').classList.add('active');
}

// 隐藏创建项目对话框
function hideCreateProject() {
    document.getElementById('createProjectModal').classList.remove('active');
    document.getElementById('createProjectForm').reset();
}

// 处理创建项目表单提交
async function handleCreateProject(event) {
    event.preventDefault();
    
    const name = document.getElementById('projectName').value;
    const description = document.getElementById('projectDescription').value;
    const categoriesText = document.getElementById('projectCategories').value;
    const categories = categoriesText.split('\n').filter(c => c.trim()).map(c => c.trim());
    
    if (categories.length === 0) {
        showNotification('请至少添加一个类别', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/projects`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, description, categories })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('项目创建成功！', 'success');
            hideCreateProject();
            loadProjects();
        } else {
            showNotification(data.error || '创建失败', 'error');
        }
    } catch (error) {
        console.error('创建项目失败:', error);
        showNotification('创建项目失败', 'error');
    }
}

// 删除项目
async function deleteProject(projectId) {
    if (!confirm('确定要删除这个项目吗？此操作不可恢复！')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/projects/${projectId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('项目已删除', 'success');
            loadProjects();
        } else {
            showNotification(data.error || '删除失败', 'error');
        }
    } catch (error) {
        console.error('删除项目失败:', error);
        showNotification('删除项目失败', 'error');
    }
}

// 打开项目
function openProject(projectId) {
    showProjectDetail(projectId);
}

// 显示项目详情
async function showProjectDetail(projectId) {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${projectId}`);
        const data = await response.json();
        
        if (data.success) {
            const project = data.project;
            const content = document.getElementById('projectDetailContent');
            content.innerHTML = `
                <div style="padding: 1.5rem;">
                    <h3>${project.name}</h3>
                    <p style="color: var(--text-secondary); margin: 1rem 0;">
                        ${project.description || '暂无描述'}
                    </p>
                    <div style="margin: 1.5rem 0;">
                        <h4>📊 统计信息</h4>
                        <div class="stats" style="margin-top: 0.5rem;">
                            <div class="stat-item">
                                <label>总图片:</label>
                                <span>${project.image_count}</span>
                            </div>
                            <div class="stat-item">
                                <label>已标注:</label>
                                <span>${project.annotated_count}</span>
                            </div>
                            <div class="stat-item">
                                <label>未标注:</label>
                                <span>${project.image_count - project.annotated_count}</span>
                            </div>
                            <div class="stat-item">
                                <label>创建时间:</label>
                                <span>${new Date(project.created_at).toLocaleDateString()}</span>
                            </div>
                        </div>
                    </div>
                    <div style="margin: 1.5rem 0;">
                        <h4>🏷️ 标注类别</h4>
                        <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">
                            ${project.categories.map(cat => `
                                <span style="padding: 0.25rem 0.75rem; background: var(--hover-bg); 
                                       border-radius: 1rem; font-size: 0.875rem;">${cat}</span>
                            `).join('')}
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.5rem; margin-top: 1.5rem;">
                        <button class="btn btn-primary" onclick="goToAnnotate('${project.id}')">
                            开始标注
                        </button>
                        <button class="btn btn-secondary" onclick="hideProjectDetail()">
                            关闭
                        </button>
                    </div>
                </div>
            `;
            document.getElementById('projectDetailModal').classList.add('active');
        }
    } catch (error) {
        console.error('加载项目详情失败:', error);
        showNotification('加载项目详情失败', 'error');
    }
}

// 隐藏项目详情
function hideProjectDetail() {
    document.getElementById('projectDetailModal').classList.remove('active');
}

// 跳转到标注页面
function goToAnnotate(projectId) {
    localStorage.setItem('currentProject', projectId);
    window.location.href = 'annotate_enhanced.html';
}

// 显示通知
function showNotification(message, type = 'info') {
    // 简单的通知实现
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? 'var(--success-color)' : 
                     type === 'error' ? 'var(--danger-color)' : 
                     'var(--primary-color)'};
        color: white;
        border-radius: 0.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        z-index: 9999;
        animation: slideIn 0.3s ease-out;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// 添加动画样式
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

