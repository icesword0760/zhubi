// 朱笔 Zhubi 标注页面逻辑

const API_BASE = '';
let currentProject = null;
let images = [];
let currentImageIndex = -1;
let currentImage = null;
let bboxes = [];
let selectedBboxIndex = -1;
let selectedCategory = null;
let isDrawing = false;
let startX, startY;
let canvas, ctx;

// 页面加载
document.addEventListener('DOMContentLoaded', () => {
    const projectId = localStorage.getItem('currentProject');
    if (!projectId) {
        alert('请先选择一个项目');
        window.location.href = 'index.html';
        return;
    }
    
    initCanvas();
    loadProject(projectId);
    setupKeyboardShortcuts();
});

// 初始化画布
function initCanvas() {
    canvas = document.getElementById('annotationCanvas');
    ctx = canvas.getContext('2d');
    
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
}

// 加载项目
async function loadProject(projectId) {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${projectId}`);
        const data = await response.json();
        
        if (data.success) {
            currentProject = data.project;
            document.getElementById('projectTitle').textContent = currentProject.name;
            
            // 更新面包屑导航
            const breadcrumbProject = document.getElementById('breadcrumbProject');
            if (breadcrumbProject) {
                breadcrumbProject.textContent = currentProject.name;
            }
            
            renderCategories();
            loadImages();
        }
    } catch (error) {
        console.error('加载项目失败:', error);
    }
}

// 加载图片列表
async function loadImages() {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${currentProject.id}/images?page_size=1000`);
        const data = await response.json();
        
        if (data.success) {
            images = data.images;
            renderImageList();
            updateProgress();
            
            if (images.length > 0) {
                loadImage(0);
            }
        }
    } catch (error) {
        console.error('加载图片列表失败:', error);
    }
}

// 渲染图片列表
function renderImageList() {
    const list = document.getElementById('imageList');
    list.innerHTML = images.map((img, index) => `
        <div class="image-item ${index === currentImageIndex ? 'active' : ''}" 
             onclick="loadImage(${index})">
            <img src="${img.path}" class="image-thumbnail" alt="${img.filename}">
            <div class="image-info">
                <div class="image-name">${img.filename}</div>
                <div class="image-status">${img.annotated ? '✅ 已标注' : '⭕ 未标注'}</div>
            </div>
        </div>
    `).join('');
}

// 加载图片
async function loadImage(index) {
    if (index < 0 || index >= images.length) return;
    
    currentImageIndex = index;
    const imageData = images[index];
    
    // 加载图片
    const img = new Image();
    img.onload = async () => {
        currentImage = img;
        
        // 调整画布大小
        const container = document.getElementById('canvasContainer');
        const maxWidth = container.clientWidth - 40;
        const maxHeight = container.clientHeight - 40;
        const scale = Math.min(maxWidth / img.width, maxHeight / img.height, 1);
        
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;
        
        // 加载标注
        await loadAnnotation(imageData.id);
        
        // 绘制
        redraw();
        
        // 更新UI
        document.getElementById('currentImageName').textContent = imageData.filename;
        document.getElementById('currentImageSize').textContent = `${img.width}x${img.height}`;
        renderImageList();
    };
    img.src = imageData.path;
}

// 加载标注
async function loadAnnotation(imageId) {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${currentProject.id}/annotations/${imageId}`);
        const data = await response.json();
        
        if (data.success && data.annotation) {
            bboxes = data.annotation.annotations || [];
        } else {
            bboxes = [];
        }
        
        renderBboxList();
    } catch (error) {
        console.error('加载标注失败:', error);
        bboxes = [];
    }
}

// 保存标注
async function saveAnnotation() {
    if (currentImageIndex < 0) return;
    
    const imageId = images[currentImageIndex].id;
    
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${currentProject.id}/annotations/${imageId}`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ annotations: bboxes })
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('保存成功', 'success');
            images[currentImageIndex].annotated = true;
            renderImageList();
            updateProgress();
        } else {
            showNotification('保存失败', 'error');
        }
    } catch (error) {
        console.error('保存标注失败:', error);
        showNotification('保存失败', 'error');
    }
}

// 渲染类别列表
function renderCategories() {
    const list = document.getElementById('categoryList');
    list.innerHTML = currentProject.categories.map(cat => `
        <button class="category-btn ${selectedCategory === cat ? 'active' : ''}" 
                onclick="selectCategory('${cat}')">
            ${cat}
        </button>
    `).join('');
    
    if (!selectedCategory && currentProject.categories.length > 0) {
        selectCategory(currentProject.categories[0]);
    }
}

// 选择类别
function selectCategory(category) {
    selectedCategory = category;
    
    // 如果有选中的bbox，则更新其类别
    if (selectedBboxIndex >= 0 && selectedBboxIndex < bboxes.length) {
        const bbox = bboxes[selectedBboxIndex];
        const oldCategory = bbox.category;
        
        // 更新类别
        bbox.category = category;
        bbox.color = getCategoryColor(category);
        
        console.log(`类别更新: ${oldCategory} -> ${category}`);
        
        // 更新UI
        renderBboxList();
        redraw();
        
        // 确保canvas刷新
        requestAnimationFrame(() => {
            redraw();
        });
    }
    
    renderCategories();
}

// 渲染bbox列表
function renderBboxList() {
    const list = document.getElementById('bboxList');
    
    if (bboxes.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无标注</div>';
        return;
    }
    
    list.innerHTML = bboxes.map((bbox, index) => `
        <div class="bbox-item ${index === selectedBboxIndex ? 'selected' : ''}" 
             onclick="selectBbox(${index})">
            <span>#${index + 1} ${bbox.category}</span>
            <button class="btn btn-sm btn-danger" 
                    onclick="event.stopPropagation(); deleteBbox(${index})">删除</button>
        </div>
    `).join('');
}

// 选择bbox
function selectBbox(index) {
    selectedBboxIndex = index;
    renderBboxList();
    redraw();
}

// 删除bbox
function deleteBbox(index) {
    bboxes.splice(index, 1);
    selectedBboxIndex = -1;
    renderBboxList();
    redraw();
}

// 鼠标事件处理
function handleMouseDown(e) {
    if (!currentImage || !selectedCategory) return;
    
    const rect = canvas.getBoundingClientRect();
    const scaleX = currentImage.width / canvas.width;
    const scaleY = currentImage.height / canvas.height;
    
    startX = (e.clientX - rect.left) * scaleX;
    startY = (e.clientY - rect.top) * scaleY;
    isDrawing = true;
}

function handleMouseMove(e) {
    if (!isDrawing || !currentImage) return;
    
    const rect = canvas.getBoundingClientRect();
    const scaleX = currentImage.width / canvas.width;
    const scaleY = currentImage.height / canvas.height;
    
    const currentX = (e.clientX - rect.left) * scaleX;
    const currentY = (e.clientY - rect.top) * scaleY;
    
    redraw();
    
    // 绘制临时框
    const x = Math.min(startX, currentX);
    const y = Math.min(startY, currentY);
    const w = Math.abs(currentX - startX);
    const h = Math.abs(currentY - startY);
    
    ctx.strokeStyle = '#00ff00';
    ctx.lineWidth = 2;
    ctx.strokeRect(x / scaleX, y / scaleY, w / scaleX, h / scaleY);
}

function handleMouseUp(e) {
    if (!isDrawing || !currentImage || !selectedCategory) return;
    
    const rect = canvas.getBoundingClientRect();
    const scaleX = currentImage.width / canvas.width;
    const scaleY = currentImage.height / canvas.height;
    
    const endX = (e.clientX - rect.left) * scaleX;
    const endY = (e.clientY - rect.top) * scaleY;
    
    const x = Math.min(startX, endX);
    const y = Math.min(startY, endY);
    const w = Math.abs(endX - startX);
    const h = Math.abs(endY - startY);
    
    if (w > 10 && h > 10) {
        bboxes.push({
            bbox: [x, y, w, h],
            category: selectedCategory
        });
        renderBboxList();
    }
    
    isDrawing = false;
    redraw();
}

// 重绘画布
function redraw() {
    if (!currentImage) return;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(currentImage, 0, 0, canvas.width, canvas.height);
    
    const scaleX = canvas.width / currentImage.width;
    const scaleY = canvas.height / currentImage.height;
    
    bboxes.forEach((bbox, index) => {
        const [x, y, w, h] = bbox.bbox;
        const isSelected = index === selectedBboxIndex;
        
        ctx.strokeStyle = isSelected ? '#ff0000' : '#00ff00';
        ctx.lineWidth = isSelected ? 3 : 2;
        ctx.strokeRect(x * scaleX, y * scaleY, w * scaleX, h * scaleY);
        
        // 绘制标签
        ctx.fillStyle = isSelected ? '#ff0000' : '#00ff00';
        ctx.fillRect(x * scaleX, y * scaleY - 20, ctx.measureText(bbox.category).width + 10, 20);
        ctx.fillStyle = '#ffffff';
        ctx.font = '14px Arial';
        ctx.fillText(bbox.category, x * scaleX + 5, y * scaleY - 5);
    });
}

// 上一张/下一张
function previousImage() {
    if (currentImageIndex > 0) {
        loadImage(currentImageIndex - 1);
    }
}

function nextImage() {
    if (currentImageIndex < images.length - 1) {
        loadImage(currentImageIndex + 1);
    }
}

// 更新进度
function updateProgress() {
    const annotated = images.filter(img => img.annotated).length;
    const total = images.length;
    
    document.getElementById('progressText').textContent = `${annotated} / ${total}`;
    document.getElementById('totalImages').textContent = total;
    document.getElementById('annotatedImages').textContent = annotated;
    document.getElementById('unannotatedImages').textContent = total - annotated;
}

// 快捷键
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'n' || e.key === 'N') {
            nextImage();
        } else if (e.key === 'p' || e.key === 'P') {
            previousImage();
        } else if (e.key === 's' || e.key === 'S') {
            e.preventDefault();
            saveAnnotation();
        } else if (e.key === 'd' || e.key === 'D') {
            if (selectedBboxIndex >= 0) {
                deleteBbox(selectedBboxIndex);
            }
        } else if (e.key === 'Escape') {
            isDrawing = false;
            redraw();
        }
    });
}

// 上传图片
async function handleUpload(event) {
    const files = event.target.files;
    if (!files.length) return;
    
    const formData = new FormData();
    for (let file of files) {
        formData.append('images', file);
    }
    
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${currentProject.id}/upload`,
            {
                method: 'POST',
                body: formData
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            showNotification(`成功上传 ${data.uploaded} 张图片`, 'success');
            loadImages();
        } else {
            showNotification('上传失败', 'error');
        }
    } catch (error) {
        console.error('上传失败:', error);
        showNotification('上传失败', 'error');
    }
}

// 通知
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? '#10B981' : type === 'error' ? '#EF4444' : '#4F46E5'};
        color: white;
        border-radius: 0.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        z-index: 9999;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => notification.remove(), 3000);
}

