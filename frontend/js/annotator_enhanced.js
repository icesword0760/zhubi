// 增强标注系统 - Label Studio风格
// 参考Label Studio的交互和功能设计

const API_BASE = '';

function encodePathSegment(value) {
    return encodeURIComponent(String(value));
}

// 全局状态
let currentProject = null;
let images = [];
let currentImageIndex = -1;
let currentImage = null;
let bboxes = [];
let selectedBboxIndex = -1;
let selectedCategory = null;
let currentTool = 'rect';

// 画布相关
let canvas, ctx;
let zoomLevel = 1.0;
let panX = 0, panY = 0;
let showGrid = false;
let showLabels = true;
let snapToGrid = false;

// 交互状态
let isDrawing = false;
let isDragging = false;
let isResizing = false;
let dragStartX, dragStartY;
let resizeHandle = null;

// 历史记录（撤销/重做）
let history = [];
let historyIndex = -1;
const MAX_HISTORY = 50;

// 图片删除与保存串行化状态
const deletingImageIds = new Set();
const inFlightImageSaves = new Map();
let imageDeletionInProgress = false;
let imageLoadGeneration = 0;

// 快捷键映射
const shortcuts = {
    'a': 'previous',
    'ArrowLeft': 'previous',
    'd': 'next',
    'ArrowRight': 'next',
    ' ': 'skip',
    'v': 'selectTool',
    'r': 'rectTool',
    '+': 'zoomIn',
    '=': 'zoomIn',
    '-': 'zoomOut',
    '0': 'resetZoom',
    'f': 'fullscreen',
    '?': 'showShortcuts',
    'Delete': 'delete',
    'Backspace': 'delete'
};

// 类别颜色
const categoryColors = [
    '#EF4444', '#F59E0B', '#10B981', '#3B82F6', '#8B5CF6',
    '#EC4899', '#14B8A6', '#F97316', '#06B6D4', '#6366F1'
];

// ==================== 初始化 ====================

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
    setupCanvasInteractions();
    
    // 页面关闭前自动保存
    window.addEventListener('beforeunload', (e) => {
        if (currentImageIndex >= 0 && bboxes.length > 0) {
            // 使用同步方式保存（虽然不推荐，但在 beforeunload 中需要）
            autoSaveIfNeeded();
        }
    });
});

function initCanvas() {
    canvas = document.getElementById('annotationCanvas');
    ctx = canvas.getContext('2d');
    
    // 禁用右键菜单
    canvas.addEventListener('contextmenu', e => e.preventDefault());
}

function setupCanvasInteractions() {
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    
    // 触摸支持
    canvas.addEventListener('touchstart', handleTouchStart);
    canvas.addEventListener('touchmove', handleTouchMove);
    canvas.addEventListener('touchend', handleTouchEnd);
}

// ==================== 项目和图片管理 ====================

async function loadProject(projectId) {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${encodePathSegment(projectId)}`);
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
        updateStatus('加载项目失败', 'error');
    }
}

async function loadImages() {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/images?page_size=1000`);
        const data = await response.json();
        
        if (data.success) {
            images = data.images;
            filterImages();
            updateProgress();
            
            if (images.length > 0) {
                // 尝试恢复上次查看的图片
                const lastImageId = localStorage.getItem(`lastImage_${currentProject.id}`);
                let targetIndex = 0;
                
                if (lastImageId) {
                    const foundIndex = images.findIndex(img => img.id === lastImageId);
                    if (foundIndex >= 0) {
                        targetIndex = foundIndex;
                    }
                }
                
                loadImage(targetIndex);
            }
        }
    } catch (error) {
        console.error('加载图片列表失败:', error);
    }
}

function filterImages() {
    const filter = document.getElementById('filterStatus').value;
    let filtered = images;
    
    if (filter === 'annotated') {
        filtered = images.filter(img => img.annotated);
    } else if (filter === 'unannotated') {
        filtered = images.filter(img => !img.annotated && !img.skipped);
    } else if (filter === 'skipped') {
        filtered = images.filter(img => img.skipped);
    }
    
    renderImageList(filtered);
}

function renderImageList(filteredImages) {
    const list = document.getElementById('imageList');
    list.replaceChildren();
    filteredImages.forEach(img => {
        const globalIndex = images.indexOf(img);
        const card = document.createElement('div');
        card.className = `image-item${globalIndex === currentImageIndex ? ' active' : ''}${img.skipped ? ' skipped' : ''}`;

        const selectButton = document.createElement('button');
        selectButton.type = 'button';
        selectButton.className = 'image-select-btn';
        selectButton.setAttribute('aria-label', `打开图片 ${img.filename}`);
        selectButton.addEventListener('click', () => loadImage(globalIndex));

        const thumbnail = document.createElement('img');
        thumbnail.className = 'image-thumbnail';
        thumbnail.src = img.path;
        thumbnail.alt = img.filename;

        const info = document.createElement('div');
        info.className = 'image-info';
        const name = document.createElement('div');
        name.className = 'image-name';
        name.textContent = img.filename;
        const status = document.createElement('div');
        status.className = 'image-status';
        if (img.skipped || img.annotated) {
            const badge = document.createElement('span');
            badge.className = `badge ${img.skipped ? 'badge-warning' : 'badge-success'}`;
            badge.textContent = img.skipped ? '已跳过' : '已标注';
            status.appendChild(badge);
        }
        const number = document.createElement('span');
        number.textContent = `#${globalIndex + 1}`;
        status.appendChild(number);
        info.append(name, status);
        selectButton.append(thumbnail, info);

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'image-delete-btn';
        deleteButton.title = `删除图片 ${img.filename}`;
        deleteButton.setAttribute('aria-label', `删除图片 ${img.filename}`);
        deleteButton.textContent = '🗑️';
        deleteButton.addEventListener('click', event => deleteImage(event, img.id));
        card.append(selectButton, deleteButton);
        list.appendChild(card);
    });
}

async function loadImage(index, skipPreNavigationSave = false) {
    if (index < 0 || index >= images.length) return false;
    const loadToken = ++imageLoadGeneration;
    const imageData = images[index];
    
    // 如果要切换到不同的图片，先自动保存当前图片的标注
    if (!skipPreNavigationSave && currentImageIndex !== index && currentImageIndex >= 0) {
        const outgoingImageId = images[currentImageIndex].id;
        const flushedPendingSave = await flushPendingAutoSave(outgoingImageId);
        if (!flushedPendingSave) await autoSaveIfNeeded();
    }
    if (loadToken !== imageLoadGeneration) return false;
    
    updateStatus('加载图片...', 'loading');
    
    const img = new Image();
    const imagePromise = new Promise((resolve, reject) => {
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('图片资源加载失败'));
        img.src = imageData.path;
    });
    const annotationPromise = fetchAnnotationData(imageData.id);

    try {
        const [loadedImage, annotations] = await Promise.all([imagePromise, annotationPromise]);
        if (loadToken !== imageLoadGeneration) return false;
        const committedIndex = images.findIndex(image => image.id === imageData.id);
        if (committedIndex < 0) return false;

        currentImageIndex = committedIndex;
        currentImage = loadedImage;
        bboxes = annotations;
        selectedBboxIndex = -1;
        if (currentProject) localStorage.setItem(`lastImage_${currentProject.id}`, imageData.id);

        // 重置视图
        resetZoom();
        
        // 调整画布大小
        fitImageToCanvas();
        
        saveToHistory();
        renderBboxList();
        updateStats();
        redraw();
        
        // 更新UI
        document.getElementById('currentImageName').textContent = imageData.filename;
        document.getElementById('currentImageSize').textContent = `${loadedImage.width}x${loadedImage.height}`;
        document.getElementById('currentImageIndex').textContent = `${committedIndex + 1} / ${images.length}`;
        
        filterImages();
        updateStatus('准备就绪', 'ready');
        addToHistory(`加载图片: ${imageData.filename}`);
        return true;
    } catch (error) {
        if (loadToken !== imageLoadGeneration) return false;
        clearImageViewState();
        updateStatus('加载图片失败', 'error');
        return false;
    }
}

function invalidateImageLoads() {
    imageLoadGeneration++;
}

function clearImageViewState() {
    currentImage = null;
    currentImageIndex = -1;
    bboxes = [];
    selectedBboxIndex = -1;
    history = [];
    historyIndex = -1;
    if (canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        canvas.width = 0;
        canvas.height = 0;
    }
    document.getElementById('currentImageName').textContent = '未选择图片';
    document.getElementById('currentImageSize').textContent = '';
    document.getElementById('currentImageIndex').textContent = '';
    renderBboxList();
    updateStats();
    if (currentProject) localStorage.removeItem(`lastImage_${currentProject.id}`);
    filterImages();
}

async function fetchAnnotationData(imageId) {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/annotations/${encodePathSegment(imageId)}`);
        const data = await response.json();
        const annotations = data.success && data.annotation ? (data.annotation.annotations || []) : [];
        return annotations.map(bbox => ({
            ...bbox,
            id: bbox.id || generateId(),
            color: bbox.color || getCategoryColor(bbox.category),
            locked: bbox.locked === undefined ? false : bbox.locked
        }));
    } catch (error) {
        console.error('加载标注失败:', error);
        return [];
    }
}

function getImageIndexAfterDeletion(deletedIndex, selectedIndex, totalImages) {
    if (totalImages <= 1) return -1;
    if (deletedIndex === selectedIndex) {
        return Math.min(deletedIndex, totalImages - 2);
    }
    return deletedIndex < selectedIndex ? selectedIndex - 1 : selectedIndex;
}

function setImageDeletionLock(locked) {
    imageDeletionInProgress = locked;
    const page = document.querySelector('.annotate-enhanced-page');
    if (!page) return;
    page.classList.toggle('deletion-locked', locked);
    page.inert = locked;
    if (locked) {
        page.setAttribute('inert', '');
        page.setAttribute('aria-busy', 'true');
    } else {
        page.removeAttribute('inert');
        page.removeAttribute('aria-busy');
    }
}

function resetAfterLastImageDeletion() {
    currentImage = null;
    currentImageIndex = -1;
    bboxes = [];
    selectedBboxIndex = -1;
    selectedCategory = null;
    isDrawing = false;
    isDragging = false;
    isResizing = false;
    resizeHandle = null;
    history = [];
    historyIndex = -1;
    zoomLevel = 1;
    panX = 0;
    panY = 0;

    if (canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        canvas.width = 0;
        canvas.height = 0;
    }
    document.getElementById('currentImageName').textContent = '未选择图片';
    document.getElementById('currentImageSize').textContent = '';
    document.getElementById('currentImageIndex').textContent = '';
    document.getElementById('currentBoxes').textContent = '0';
    document.getElementById('bboxCount').textContent = '标注数: 0';
    document.getElementById('bboxList').innerHTML = '<div class="empty-state">暂无标注</div>';
    document.getElementById('historyList').innerHTML = '';
    document.getElementById('imageList').innerHTML = '';
    hideProperties();
    updateProgress();
    updateStats();
    if (currentProject) localStorage.removeItem(`lastImage_${currentProject.id}`);
    updateStatus('暂无图片', 'ready');
}

async function deleteImage(event, imageId) {
    if (event && event.stopPropagation) event.stopPropagation();
    if (imageDeletionInProgress || deletingImageIds.has(imageId)) return false;

    const deletedIndex = images.findIndex(image => image.id === imageId);
    if (deletedIndex < 0) return false;

    const selectedIndexBefore = currentImageIndex;
    const deletingCurrent = deletedIndex === selectedIndexBefore;
    let pendingAutosave = null;
    let succeeded = false;

    invalidateImageLoads();
    deletingImageIds.add(imageId);
    setImageDeletionLock(true);
    updateStatus('正在删除图片...', 'loading');

    pendingAutosave = takePendingAutoSave(imageId);

    try {
        const saves = inFlightImageSaves.get(imageId);
        if (saves && saves.size) await Promise.allSettled(Array.from(saves));

        const response = await fetch(
            `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/images/${encodePathSegment(imageId)}`,
            { method: 'DELETE' }
        );
        const data = await response.json();
        if (response.ok === false || !data.success) {
            throw new Error(data.error || '服务器拒绝删除');
        }

        const nextIndex = getImageIndexAfterDeletion(deletedIndex, selectedIndexBefore, images.length);
        images.splice(deletedIndex, 1);

        if (images.length === 0) {
            resetAfterLastImageDeletion();
        } else if (deletingCurrent) {
            clearImageViewState();
            const replacementLoaded = await loadImage(nextIndex, true);
            if (replacementLoaded) {
                updateProgress();
            } else {
                updateStatus('加载图片失败', 'error');
            }
        } else {
            currentImageIndex = nextIndex;
            const selectedImage = images[currentImageIndex];
            if (currentProject && selectedImage) {
                localStorage.setItem(`lastImage_${currentProject.id}`, selectedImage.id);
            }
            document.getElementById('currentImageIndex').textContent =
                `${currentImageIndex + 1} / ${images.length}`;
            filterImages();
            updateProgress();
        }
        if (!deletingCurrent || images.length === 0 || currentImage) {
            updateStatus(images.length ? '图片已删除' : '暂无图片', images.length ? 'success' : 'ready');
        }
        succeeded = true;
    } catch (error) {
        console.error('删除图片失败:', error);
        updateStatus(`删除图片失败: ${error.message}`, 'error');
    } finally {
        deletingImageIds.delete(imageId);
        setImageDeletionLock(false);
    }

    if (!succeeded && pendingAutosave) {
        scheduleAutoSave(pendingAutosave.imageId, pendingAutosave.annotations);
    }
    return succeeded;
}

function fitImageToCanvas() {
    const container = document.getElementById('canvasContainer');
    const containerWidth = Math.max(container.clientWidth - 40, 400);
    const containerHeight = Math.max(container.clientHeight - 40, 400);
    
    const maxWidth = containerWidth;
    const maxHeight = containerHeight;
    const scale = Math.min(maxWidth / currentImage.width, maxHeight / currentImage.height, 1);
    
    canvas.width = currentImage.width * scale;
    canvas.height = currentImage.height * scale;
    
    // 确保画布有实际尺寸
    if (canvas.width < 100) canvas.width = currentImage.width;
    if (canvas.height < 100) canvas.height = currentImage.height;
    
    zoomLevel = scale;
    panX = 0;
    panY = 0;
    
    updateZoomLevel();
}

// ==================== 标注管理 ====================

async function loadAnnotation(imageId) {
    try {
        const response = await fetch(`${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/annotations/${encodePathSegment(imageId)}`);
        const data = await response.json();
        
        if (data.success && data.annotation) {
            bboxes = data.annotation.annotations || [];
            // 为每个bbox添加唯一ID和颜色
            bboxes.forEach((bbox, i) => {
                if (!bbox.id) bbox.id = generateId();
                if (!bbox.color) bbox.color = getCategoryColor(bbox.category);
                if (bbox.locked === undefined) bbox.locked = false;
            });
        } else {
            bboxes = [];
        }
        
        selectedBboxIndex = -1;
        saveToHistory();
        renderBboxList();
        updateStats();
    } catch (error) {
        console.error('加载标注失败:', error);
        bboxes = [];
    }
}

async function saveAnnotation(silent = false) {
    if (currentImageIndex < 0) return false;
    const imageId = images[currentImageIndex].id;
    const annotations = JSON.parse(JSON.stringify(bboxes));
    return saveAnnotationForImage(imageId, annotations, silent);
}

async function saveAnnotationForImage(imageId, annotations, silent = false) {
    if (deletingImageIds.has(imageId)) return false;

    if (!silent) {
        updateStatus('保存中...', 'loading');
    }

    const savePromise = (async () => {
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/annotations/${encodePathSegment(imageId)}`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ annotations })
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            // 如果之前是跳过状态，清除跳过标记
            const imageIndex = images.findIndex(image => image.id === imageId);
            if (imageIndex < 0) return false;
            const wasSkipped = images[imageIndex].skipped;

            images[imageIndex].annotated = true;
            images[imageIndex].skipped = false;
            
            if (wasSkipped) {
                try {
                    await fetch(
                        `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/images/${encodePathSegment(imageId)}/skip`,
                        {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ skipped: false })
                        }
                    );
                } catch (error) {
                    console.error('清除跳过状态失败:', error);
                }
            }
            
            if (!silent) {
                updateStatus('保存成功', 'success');
            }
            filterImages();
            updateProgress();
            if (!silent) {
                addToHistory('保存标注');
            }
            return true;
        } else {
            if (!silent) {
                updateStatus('保存失败', 'error');
            }
            return false;
        }
    } catch (error) {
        console.error('保存标注失败:', error);
        if (!silent) {
            updateStatus('保存失败', 'error');
        }
        return false;
    }
    })();

    if (!inFlightImageSaves.has(imageId)) inFlightImageSaves.set(imageId, new Set());
    inFlightImageSaves.get(imageId).add(savePromise);
    try {
        return await savePromise;
    } finally {
        const saves = inFlightImageSaves.get(imageId);
        if (saves) {
            saves.delete(savePromise);
            if (saves.size === 0) inFlightImageSaves.delete(imageId);
        }
    }
}

// 防抖定时器
let autoSaveTimer = null;
let autoSavePendingImageId = null;
let autoSavePendingAnnotations = null;

function takePendingAutoSave(imageId) {
    if (autoSaveTimer === null || autoSavePendingImageId !== imageId) return null;

    const pending = {
        imageId: autoSavePendingImageId,
        annotations: JSON.parse(JSON.stringify(autoSavePendingAnnotations || []))
    };
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
    autoSavePendingImageId = null;
    autoSavePendingAnnotations = null;
    return pending;
}

async function flushPendingAutoSave(imageId) {
    const pending = takePendingAutoSave(imageId);
    if (!pending) return false;
    await saveAnnotationForImage(pending.imageId, pending.annotations, true);
    return true;
}

function scheduleAutoSave(imageId, annotations) {
    if (autoSaveTimer) clearTimeout(autoSaveTimer);
    autoSavePendingImageId = imageId;
    autoSavePendingAnnotations = JSON.parse(JSON.stringify(annotations));
    const ownedAnnotations = JSON.parse(JSON.stringify(autoSavePendingAnnotations));
    const timer = setTimeout(async () => {
        if (autoSaveTimer === timer) {
            autoSaveTimer = null;
            autoSavePendingImageId = null;
            autoSavePendingAnnotations = null;
        }
        await saveAnnotationForImage(imageId, ownedAnnotations, true);
        console.log('✅ 实时自动保存完成');
    }, 500);
    autoSaveTimer = timer;
}

async function autoSaveIfNeeded() {
    // 如果当前有标注且未保存，自动保存
    if (currentImageIndex >= 0 && bboxes.length > 0) {
        await saveAnnotation(true);  // 静默保存
    }
}

// 实时自动保存（带防抖）
function autoSaveRealtime() {
    // 清除之前的定时器
    if (currentImageIndex < 0) return;
    const imageId = images[currentImageIndex].id;
    if (deletingImageIds.has(imageId)) return;
    scheduleAutoSave(imageId, JSON.parse(JSON.stringify(bboxes)));
}

async function saveAndNext() {
    await saveAnnotation(false);  // 显式保存，显示提示
    setTimeout(() => nextImage(), 300);
}

// ==================== 类别管理 ====================

function renderCategories() {
    const list = document.getElementById('categoryList');
    const propCategory = document.getElementById('propCategory');
    
    const html = currentProject.categories.map((cat, index) => {
        const shortcut = index < 9 ? index + 1 : '';
        const color = categoryColors[index % categoryColors.length];
        
        return `
            <button class="category-btn ${selectedCategory === cat ? 'active' : ''}" 
                    onclick="selectCategory('${cat}')">
                <div class="category-color" style="background: ${color};"></div>
                <div class="category-info">
                    <div class="category-name">${cat}</div>
                </div>
                ${shortcut ? `<span class="category-shortcut">${shortcut}</span>` : ''}
            </button>
        `;
    }).join('');
    
    // 添加"新增类别"按钮
    const addButton = `
        <button class="category-btn" onclick="showAddCategoryDialog()" style="border-style: dashed;">
            <div class="category-color" style="background: #E5E7EB;">
                <span style="font-size: 1.2rem;">+</span>
            </div>
            <div class="category-info">
                <div class="category-name">新增类别</div>
            </div>
        </button>
    `;
    
    list.innerHTML = html + addButton;
    
    // 更新属性面板下拉框
    if (propCategory) {
        propCategory.innerHTML = currentProject.categories.map(cat => 
            `<option value="${cat}">${cat}</option>`
        ).join('');
    }
    
    // 默认选择第一个类别
    if (!selectedCategory && currentProject.categories.length > 0) {
        selectCategory(currentProject.categories[0]);
    }
}

function selectCategory(category) {
    selectedCategory = category;
    
    // 如果有选中的bbox，则更新其类别
    if (selectedBboxIndex >= 0 && selectedBboxIndex < bboxes.length) {
        const bbox = bboxes[selectedBboxIndex];
        const oldCategory = bbox.category;
        
        // 更新类别
        bbox.category = category;
        bbox.color = getCategoryColor(category);
        
        console.log(`✅ 类别更新: ${oldCategory} -> ${category}`);
        
        // 同步更新属性面板
        const propCategory = document.getElementById('propCategory');
        if (propCategory) {
            propCategory.value = category;
        }
        
        // 保存历史记录
        saveToHistory();
        
        // 更新UI
        renderBboxList();
        redraw();
        
        // 确保canvas刷新
        requestAnimationFrame(() => {
            redraw();
        });
        
        updateStatus(`✅ 已更新标注类别: ${oldCategory} → ${category}`, 'success');
    } else {
        // 没有选中的bbox，只是设置新建标注时的默认类别
        updateStatus(`已选择类别: ${category}（用于创建新标注）`, 'info');
    }
    
    renderCategories();
}

function getCategoryColor(category) {
    const index = currentProject.categories.indexOf(category);
    return categoryColors[index % categoryColors.length];
}

// ==================== 绘制和渲染 ====================

function redraw() {
    if (!currentImage) return;
    
    // 清空画布
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    
    // 应用缩放和平移
    ctx.scale(zoomLevel, zoomLevel);
    ctx.translate(panX, panY);
    
    // 绘制图片
    ctx.drawImage(currentImage, 0, 0);
    
    // 绘制网格
    if (showGrid) {
        drawGrid();
    }
    
    // 绘制所有bbox
    bboxes.forEach((bbox, index) => {
        drawBbox(bbox, index === selectedBboxIndex);
    });
    
    ctx.restore();
    
    // 更新bbox计数
    document.getElementById('currentBoxes').textContent = bboxes.length;
    document.getElementById('bboxCount').textContent = `标注数: ${bboxes.length}`;
}

function drawBbox(bbox, isSelected) {
    const [x, y, w, h] = bbox.bbox;
    const color = bbox.color || getCategoryColor(bbox.category);
    
    // 绘制矩形
    ctx.strokeStyle = isSelected ? '#FF0000' : color;
    ctx.lineWidth = isSelected ? 3 / zoomLevel : 2 / zoomLevel;
    ctx.strokeRect(x, y, w, h);
    
    // 填充半透明背景
    if (isSelected) {
        ctx.fillStyle = 'rgba(255, 0, 0, 0.1)';
        ctx.fillRect(x, y, w, h);
    }
    
    // 绘制调整手柄（仅选中时）
    if (isSelected && !bbox.locked) {
        drawResizeHandles(x, y, w, h);
    }
    
    // 绘制标签
    if (showLabels && bbox.category) {
        drawLabel(x, y, bbox.category, color, isSelected);
    }
    
    // 锁定图标
    if (bbox.locked) {
        ctx.fillStyle = '#F59E0B';
        ctx.font = `${12 / zoomLevel}px Arial`;
        ctx.fillText('🔒', x + w - 20 / zoomLevel, y + 20 / zoomLevel);
    }
}

function drawLabel(x, y, text, color, isSelected) {
    const fontSize = Math.max(12 / zoomLevel, 10);
    ctx.font = `${fontSize}px Arial`;
    
    const textWidth = ctx.measureText(text).width;
    const padding = 4 / zoomLevel;
    const labelHeight = fontSize + padding * 2;
    
    // 背景
    ctx.fillStyle = isSelected ? '#FF0000' : color;
    ctx.fillRect(x, y - labelHeight, textWidth + padding * 2, labelHeight);
    
    // 文本
    ctx.fillStyle = '#FFFFFF';
    ctx.fillText(text, x + padding, y - padding);
}

function drawResizeHandles(x, y, w, h) {
    const handleSize = 6 / zoomLevel;
    const handles = [
        [x, y],           // 左上
        [x + w / 2, y],   // 上中
        [x + w, y],       // 右上
        [x + w, y + h / 2], // 右中
        [x + w, y + h],   // 右下
        [x + w / 2, y + h], // 下中
        [x, y + h],       // 左下
        [x, y + h / 2]    // 左中
    ];
    
    ctx.fillStyle = '#FFFFFF';
    ctx.strokeStyle = '#4F46E5';
    ctx.lineWidth = 1 / zoomLevel;
    
    handles.forEach(([hx, hy]) => {
        ctx.fillRect(hx - handleSize / 2, hy - handleSize / 2, handleSize, handleSize);
        ctx.strokeRect(hx - handleSize / 2, hy - handleSize / 2, handleSize, handleSize);
    });
}

function drawGrid() {
    const gridSize = 50;
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.1)';
    ctx.lineWidth = 1 / zoomLevel;
    
    for (let x = 0; x < currentImage.width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, currentImage.height);
        ctx.stroke();
    }
    
    for (let y = 0; y < currentImage.height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(currentImage.width, y);
        ctx.stroke();
    }
}

// ==================== 鼠标交互 ====================

function handleMouseDown(e) {
    if (!currentImage) return;
    
    const pos = getMousePos(e);
    
    if (currentTool === 'select') {
        // 检查是否点击了bbox
        const clickedIndex = findBboxAtPos(pos.x, pos.y);
        if (clickedIndex >= 0) {
            selectedBboxIndex = clickedIndex;
            const bbox = bboxes[clickedIndex];
            
            if (!bbox.locked) {
                // 检查是否点击了调整手柄
                resizeHandle = getResizeHandle(bbox, pos.x, pos.y);
                if (resizeHandle) {
                    isResizing = true;
                } else {
                    isDragging = true;
                }
                dragStartX = pos.x;
                dragStartY = pos.y;
            }
            
            renderBboxList();
            showProperties(bbox);
            redraw();
        } else {
            selectedBboxIndex = -1;
            hideProperties();
            renderBboxList();
            redraw();
        }
    } else if (currentTool === 'rect') {
        if (!selectedCategory) {
            updateStatus('请先选择类别', 'warning');
            return;
        }
        isDrawing = true;
        dragStartX = pos.x;
        dragStartY = pos.y;
    }
}

function handleMouseMove(e) {
    if (!currentImage) return;
    
    const pos = getMousePos(e);
    
    // 更新鼠标坐标显示
    document.getElementById('mousePos').textContent = `X: ${Math.round(pos.x)}, Y: ${Math.round(pos.y)}`;
    
    if (isDrawing && currentTool === 'rect') {
        // 绘制临时矩形
        redraw();
        
        ctx.save();
        ctx.scale(zoomLevel, zoomLevel);
        ctx.translate(panX, panY);
        
        const x = Math.min(dragStartX, pos.x);
        const y = Math.min(dragStartY, pos.y);
        const w = Math.abs(pos.x - dragStartX);
        const h = Math.abs(pos.y - dragStartY);
        
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2 / zoomLevel;
        ctx.setLineDash([5 / zoomLevel, 5 / zoomLevel]);
        ctx.strokeRect(x, y, w, h);
        ctx.setLineDash([]);
        
        ctx.restore();
    } else if (isDragging && selectedBboxIndex >= 0) {
        // 拖拽移动bbox
        const bbox = bboxes[selectedBboxIndex];
        const dx = pos.x - dragStartX;
        const dy = pos.y - dragStartY;
        
        bbox.bbox[0] += dx;
        bbox.bbox[1] += dy;
        
        dragStartX = pos.x;
        dragStartY = pos.y;
        
        redraw();
    } else if (isResizing && selectedBboxIndex >= 0) {
        // 调整bbox大小
        const bbox = bboxes[selectedBboxIndex];
        resizeBbox(bbox, resizeHandle, pos.x, pos.y, dragStartX, dragStartY);
        
        dragStartX = pos.x;
        dragStartY = pos.y;
        
        redraw();
    }
}

function handleMouseUp(e) {
    if (!currentImage) return;
    
    const pos = getMousePos(e);
    
    if (isDrawing && currentTool === 'rect') {
        const x = Math.min(dragStartX, pos.x);
        const y = Math.min(dragStartY, pos.y);
        const w = Math.abs(pos.x - dragStartX);
        const h = Math.abs(pos.y - dragStartY);
        
        if (w > 10 && h > 10) {
            const newBbox = {
                id: generateId(),
                bbox: [x, y, w, h],
                category: selectedCategory,
                color: getCategoryColor(selectedCategory),
                locked: false
            };
            
            bboxes.push(newBbox);
            saveToHistory();
            renderBboxList();
            updateStats();
            updateStatus(`添加标注: ${selectedCategory}`, 'success');
            
            // 实时自动保存
            autoSaveRealtime();
        }
    }
    
    if (isDragging || isResizing) {
        saveToHistory();
        updateStats();
        
        // 实时自动保存
        autoSaveRealtime();
    }
    
    isDrawing = false;
    isDragging = false;
    isResizing = false;
    resizeHandle = null;
    
    redraw();
}

function handleWheel(e) {
    e.preventDefault();
    
    if (e.ctrlKey || e.metaKey) {
        // 缩放
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        zoomLevel = Math.max(0.1, Math.min(5, zoomLevel * delta));
        updateZoomLevel();
        redraw();
    } else {
        // 平移
        panX -= e.deltaX / zoomLevel;
        panY -= e.deltaY / zoomLevel;
        redraw();
    }
}

// 触摸支持（移动端）
function handleTouchStart(e) {
    if (e.touches.length === 1) {
        const touch = e.touches[0];
        handleMouseDown({ clientX: touch.clientX, clientY: touch.clientY });
    }
}

function handleTouchMove(e) {
    if (e.touches.length === 1) {
        const touch = e.touches[0];
        handleMouseMove({ clientX: touch.clientX, clientY: touch.clientY });
    }
}

function handleTouchEnd(e) {
    handleMouseUp({ clientX: 0, clientY: 0 });
}

// ==================== 辅助函数 ====================

function getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return {
        x: (e.clientX - rect.left) / zoomLevel - panX,
        y: (e.clientY - rect.top) / zoomLevel - panY
    };
}

function findBboxAtPos(x, y) {
    for (let i = bboxes.length - 1; i >= 0; i--) {
        const [bx, by, bw, bh] = bboxes[i].bbox;
        if (x >= bx && x <= bx + bw && y >= by && y <= by + bh) {
            return i;
        }
    }
    return -1;
}

function getResizeHandle(bbox, x, y) {
    const [bx, by, bw, bh] = bbox.bbox;
    const handleSize = 10 / zoomLevel;
    
    const handles = {
        'nw': [bx, by],
        'n': [bx + bw / 2, by],
        'ne': [bx + bw, by],
        'e': [bx + bw, by + bh / 2],
        'se': [bx + bw, by + bh],
        's': [bx + bw / 2, by + bh],
        'sw': [bx, by + bh],
        'w': [bx, by + bh / 2]
    };
    
    for (const [key, [hx, hy]] of Object.entries(handles)) {
        if (Math.abs(x - hx) < handleSize && Math.abs(y - hy) < handleSize) {
            return key;
        }
    }
    
    return null;
}

function resizeBbox(bbox, handle, x, y, startX, startY) {
    const [bx, by, bw, bh] = bbox.bbox;
    const dx = x - startX;
    const dy = y - startY;
    
    switch (handle) {
        case 'nw':
            bbox.bbox = [bx + dx, by + dy, bw - dx, bh - dy];
            break;
        case 'n':
            bbox.bbox = [bx, by + dy, bw, bh - dy];
            break;
        case 'ne':
            bbox.bbox = [bx, by + dy, bw + dx, bh - dy];
            break;
        case 'e':
            bbox.bbox = [bx, by, bw + dx, bh];
            break;
        case 'se':
            bbox.bbox = [bx, by, bw + dx, bh + dy];
            break;
        case 's':
            bbox.bbox = [bx, by, bw, bh + dy];
            break;
        case 'sw':
            bbox.bbox = [bx + dx, by, bw - dx, bh + dy];
            break;
        case 'w':
            bbox.bbox = [bx + dx, by, bw - dx, bh];
            break;
    }
    
    // 确保宽高为正
    if (bbox.bbox[2] < 0) {
        bbox.bbox[0] += bbox.bbox[2];
        bbox.bbox[2] = -bbox.bbox[2];
    }
    if (bbox.bbox[3] < 0) {
        bbox.bbox[1] += bbox.bbox[3];
        bbox.bbox[3] = -bbox.bbox[3];
    }
}

function generateId() {
    return 'bbox_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// ==================== 工具和视图控制 ====================

function setTool(tool) {
    currentTool = tool;
    
    document.querySelectorAll('.tool-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    document.getElementById('tool' + tool.charAt(0).toUpperCase() + tool.slice(1)).classList.add('active');
    
    canvas.style.cursor = tool === 'select' ? 'default' : 'crosshair';
    updateStatus(`已切换到${tool === 'select' ? '选择' : '矩形'}工具`, 'info');
}

function zoomIn() {
    zoomLevel = Math.min(5, zoomLevel * 1.2);
    updateZoomLevel();
    redraw();
}

function zoomOut() {
    zoomLevel = Math.max(0.1, zoomLevel / 1.2);
    updateZoomLevel();
    redraw();
}

function resetZoom() {
    fitImageToCanvas();
    redraw();
}

function updateZoomLevel() {
    const percent = Math.round(zoomLevel * 100);
    document.getElementById('zoomLevel').textContent = `${percent}%`;
    document.getElementById('zoomText').textContent = `${percent}%`;
    
    // 显示缩放指示器
    const indicator = document.getElementById('zoomIndicator');
    indicator.style.display = 'block';
    setTimeout(() => {
        indicator.style.display = 'none';
    }, 1000);
}

function toggleGrid() {
    showGrid = document.getElementById('showGrid').checked;
    redraw();
}

function toggleSnap() {
    snapToGrid = document.getElementById('snapToGrid').checked;
}

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen();
    } else {
        document.exitFullscreen();
    }
}

// ==================== 标注操作 ====================

function deleteSelected() {
    if (selectedBboxIndex >= 0) {
        const bbox = bboxes[selectedBboxIndex];
        bboxes.splice(selectedBboxIndex, 1);
        selectedBboxIndex = -1;
        
        saveToHistory();
        hideProperties();
        renderBboxList();
        updateStats();
        redraw();
        
        updateStatus(`删除标注: ${bbox.category}`, 'success');
        
        // 实时自动保存
        autoSaveRealtime();
    }
}

function duplicateSelected() {
    if (selectedBboxIndex >= 0) {
        const original = bboxes[selectedBboxIndex];
        const duplicate = {
            ...original,
            id: generateId(),
            bbox: [original.bbox[0] + 10, original.bbox[1] + 10, original.bbox[2], original.bbox[3]]
        };
        
        bboxes.push(duplicate);
        selectedBboxIndex = bboxes.length - 1;
        
        saveToHistory();
        renderBboxList();
        updateStats();
        redraw();
        
        updateStatus('复制标注', 'success');
        
        // 实时自动保存
        autoSaveRealtime();
    }
}

function clearAllAnnotations() {
    if (bboxes.length === 0) return;
    
    if (confirm(`确定要清空当前图片的所有${bboxes.length}个标注吗？`)) {
        bboxes = [];
        selectedBboxIndex = -1;
        
        saveToHistory();
        hideProperties();
        renderBboxList();
        updateStats();
        redraw();
        
        updateStatus('清空所有标注', 'success');
        
        // 实时自动保存（保存空标注）
        autoSaveRealtime();
    }
}

// ==================== 历史记录（撤销/重做） ====================

function saveToHistory() {
    // 移除当前位置之后的历史
    history = history.slice(0, historyIndex + 1);
    
    // 添加新状态
    history.push(JSON.parse(JSON.stringify(bboxes)));
    
    // 限制历史记录数量
    if (history.length > MAX_HISTORY) {
        history.shift();
    } else {
        historyIndex++;
    }
}

function undo() {
    if (historyIndex > 0) {
        historyIndex--;
        bboxes = JSON.parse(JSON.stringify(history[historyIndex]));
        renderBboxList();
        updateStats();
        redraw();
        updateStatus('撤销', 'info');
        
        // 实时自动保存
        autoSaveRealtime();
    }
}

function redo() {
    if (historyIndex < history.length - 1) {
        historyIndex++;
        bboxes = JSON.parse(JSON.stringify(history[historyIndex]));
        renderBboxList();
        updateStats();
        redraw();
        updateStatus('重做', 'info');
        
        // 实时自动保存
        autoSaveRealtime();
    }
}

// ==================== UI更新 ====================

function renderBboxList() {
    const list = document.getElementById('bboxList');
    
    if (bboxes.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无标注</div>';
        return;
    }
    
    list.innerHTML = bboxes.map((bbox, index) => {
        const [x, y, w, h] = bbox.bbox;
        return `
            <div class="bbox-item ${index === selectedBboxIndex ? 'selected' : ''}" 
                 onclick="selectBbox(${index})">
                <div class="bbox-item-color" style="background: ${bbox.color};"></div>
                <div class="bbox-item-info">
                    <div class="bbox-item-label">
                        ${bbox.locked ? '🔒 ' : ''}${bbox.category}
                    </div>
                    <div class="bbox-item-coords">
                        ${Math.round(x)}, ${Math.round(y)}, ${Math.round(w)}×${Math.round(h)}
                    </div>
                </div>
                <div class="bbox-item-actions">
                    <button class="icon-btn" onclick="event.stopPropagation(); deleteBboxAt(${index})" title="删除">
                        🗑️
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function selectBbox(index) {
    selectedBboxIndex = index;
    renderBboxList();
    showProperties(bboxes[index]);
    redraw();
}

function deleteBboxAt(index) {
    bboxes.splice(index, 1);
    if (selectedBboxIndex === index) {
        selectedBboxIndex = -1;
        hideProperties();
    } else if (selectedBboxIndex > index) {
        selectedBboxIndex--;
    }
    
    saveToHistory();
    renderBboxList();
    updateStats();
    redraw();
}

function showProperties(bbox) {
    const panel = document.getElementById('propertiesPanel');
    panel.style.display = 'block';
    
    const [x, y, w, h] = bbox.bbox;
    document.getElementById('propX').value = Math.round(x);
    document.getElementById('propY').value = Math.round(y);
    document.getElementById('propWidth').value = Math.round(w);
    document.getElementById('propHeight').value = Math.round(h);
    document.getElementById('propCategory').value = bbox.category;
    document.getElementById('propLocked').checked = bbox.locked || false;
}

function hideProperties() {
    document.getElementById('propertiesPanel').style.display = 'none';
}

function updateSelectedBbox() {
    if (selectedBboxIndex < 0) return;
    
    const bbox = bboxes[selectedBboxIndex];
    
    // 更新bbox属性
    bbox.bbox = [
        parseFloat(document.getElementById('propX').value),
        parseFloat(document.getElementById('propY').value),
        parseFloat(document.getElementById('propWidth').value),
        parseFloat(document.getElementById('propHeight').value)
    ];
    
    // 获取新的类别值
    const newCategory = document.getElementById('propCategory').value;
    
    // 如果类别发生了变化，更新类别和颜色
    if (bbox.category !== newCategory) {
        console.log(`类别更新: ${bbox.category} -> ${newCategory}`);
        bbox.category = newCategory;
        bbox.color = getCategoryColor(newCategory);
        
        // 更新状态提示
        updateStatus(`已更新类别为: ${newCategory}`, 'success');
    }
    
    bbox.locked = document.getElementById('propLocked').checked;
    
    // 保存历史记录
    saveToHistory();
    
    // 立即更新UI
    renderBboxList();
    redraw();
    
    // 确保canvas刷新
    requestAnimationFrame(() => {
        redraw();
    });
    
    // 实时自动保存
    autoSaveRealtime();
}

function updateProgress() {
    const annotated = images.filter(img => img.annotated).length;
    const total = images.length;
    const percent = total > 0 ? (annotated / total) * 100 : 0;
    
    document.getElementById('progressBar').style.width = `${percent}%`;
    document.getElementById('progressText').textContent = `${annotated} / ${total}`;
    document.getElementById('totalImages').textContent = total;
    document.getElementById('annotatedImages').textContent = annotated;
}

function updateStats() {
    const totalBoxes = images.reduce((sum, img) => sum + (img.annotated ? 1 : 0), 0);
    document.getElementById('totalBoxes').textContent = totalBoxes;
    document.getElementById('currentBoxes').textContent = bboxes.length;
}

function updateStatus(message, type = 'info') {
    const statusText = document.getElementById('statusText');
    statusText.textContent = message;
    statusText.style.color = type === 'error' ? '#EF4444' : 
                            type === 'success' ? '#10B981' :
                            type === 'warning' ? '#F59E0B' : 
                            'var(--text-secondary)';
}

function addToHistory(action) {
    const historyList = document.getElementById('historyList');
    const time = new Date().toLocaleTimeString();
    
    const item = document.createElement('div');
    item.className = 'history-item';
    item.textContent = `${time} - ${action}`;
    
    if (historyList.querySelector('.empty-state')) {
        historyList.innerHTML = '';
    }
    
    historyList.insertBefore(item, historyList.firstChild);
    
    // 限制显示数量
    while (historyList.children.length > 20) {
        historyList.removeChild(historyList.lastChild);
    }
}

// ==================== 导航 ====================

async function previousImage() {
    if (currentImageIndex > 0) {
        // 自动保存当前标注
        await autoSaveIfNeeded();
        loadImage(currentImageIndex - 1);
    }
}

async function nextImage() {
    if (currentImageIndex < images.length - 1) {
        // 自动保存当前标注
        await autoSaveIfNeeded();
        loadImage(currentImageIndex + 1);
    }
}

async function skipImage() {
    if (currentImageIndex < 0) return;
    
    // 如果有标注，先自动保存
    if (bboxes.length > 0) {
        await autoSaveIfNeeded();
        // 已保存标注的图片不应该被标记为跳过
        nextImage();
        return;
    }
    
    const imageId = images[currentImageIndex].id;
    
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/images/${encodePathSegment(imageId)}/skip`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ skipped: true })
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            images[currentImageIndex].skipped = true;
            images[currentImageIndex].annotated = false;
            filterImages();
            updateProgress();
            nextImage();
        } else {
            updateStatus('跳过失败', 'error');
        }
    } catch (error) {
        console.error('跳过图片失败:', error);
        // 即使失败也允许前端继续，保持原有行为
        images[currentImageIndex].skipped = true;
        images[currentImageIndex].annotated = false;
        nextImage();
    }
}

// ==================== 快捷键 ====================

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (imageDeletionInProgress) return;
        // 忽略输入框中的按键
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }
        
        const key = e.key;
        
        // Ctrl组合键
        if (e.ctrlKey || e.metaKey) {
            switch (key.toLowerCase()) {
                case 'z':
                    e.preventDefault();
                    undo();
                    break;
                case 'y':
                    e.preventDefault();
                    redo();
                    break;
                case 'd':
                    e.preventDefault();
                    duplicateSelected();
                    break;
                case 'enter':
                    e.preventDefault();
                    saveAndNext();
                    break;
            }
            return;
        }
        
        // 数字键选择类别
        if (key >= '1' && key <= '9') {
            const index = parseInt(key) - 1;
            if (index < currentProject.categories.length) {
                selectCategory(currentProject.categories[index]);
            }
            return;
        }
        
        // 其他快捷键
        const action = shortcuts[key];
        if (action) {
            e.preventDefault();
            
            switch (action) {
                case 'previous': previousImage(); break;
                case 'next': nextImage(); break;
                case 'skip': skipImage(); break;
                case 'selectTool': setTool('select'); break;
                case 'rectTool': setTool('rect'); break;
                case 'zoomIn': zoomIn(); break;
                case 'zoomOut': zoomOut(); break;
                case 'resetZoom': resetZoom(); break;
                case 'fullscreen': toggleFullscreen(); break;
                case 'showShortcuts': showShortcuts(); break;
                case 'delete': deleteSelected(); break;
            }
        }
    });
}

// ==================== 弹窗 ====================

function showShortcuts() {
    document.getElementById('shortcutsModal').classList.add('active');
}

function hideShortcuts() {
    document.getElementById('shortcutsModal').classList.remove('active');
}

function showStatistics() {
    const modal = document.getElementById('statisticsModal');
    const content = document.getElementById('statisticsContent');
    
    // 统计各类别数量
    const categoryCounts = {};
    images.forEach(img => {
        if (img.annotated) {
            // 这里简化处理，实际需要从标注数据中统计
            currentProject.categories.forEach(cat => {
                categoryCounts[cat] = (categoryCounts[cat] || 0) + Math.floor(Math.random() * 5);
            });
        }
    });
    
    content.innerHTML = `
        <div style="padding: 1.5rem;">
            <h4>类别分布</h4>
            <div class="stats-grid" style="margin-top: 1rem;">
                ${Object.entries(categoryCounts).map(([cat, count]) => `
                    <div class="stat-card">
                        <div class="stat-value">${count}</div>
                        <div class="stat-label">${cat}</div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    modal.classList.add('active');
}

function hideStatistics() {
    document.getElementById('statisticsModal').classList.remove('active');
}

function showCategoryManager() {
    alert('类别管理功能：可以添加、编辑、删除类别（待实现）');
}

function exportAnnotations() {
    const data = JSON.stringify(bboxes, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `annotations_${images[currentImageIndex].id}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

// ==================== 上传 ====================

async function handleUpload(event) {
    const files = event.target.files;
    if (!files.length) return;
    
    const formData = new FormData();
    for (let file of files) {
        formData.append('images', file);
    }
    
    updateStatus('上传中...', 'loading');
    
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/upload`,
            {
                method: 'POST',
                body: formData
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            updateStatus(`成功上传 ${data.uploaded} 张图片`, 'success');
            loadImages();
        } else {
            updateStatus('上传失败', 'error');
        }
    } catch (error) {
        console.error('上传失败:', error);
        updateStatus('上传失败', 'error');
    }
    
    event.target.value = '';
}

// ==================== 动态添加类别 ====================

function showAddCategoryDialog() {
    const categoryName = prompt('请输入新类别名称:');
    
    if (categoryName && categoryName.trim()) {
        const trimmedName = categoryName.trim();
        
        // 检查是否已存在
        if (currentProject.categories.includes(trimmedName)) {
            alert('该类别已存在！');
            return;
        }
        
        // 添加到项目
        currentProject.categories.push(trimmedName);
        
        // 更新项目配置
        updateProjectCategories(currentProject.categories);
        
        // 重新渲染
        renderCategories();
        selectCategory(trimmedName);
        
        updateStatus(`已添加新类别: ${trimmedName}`, 'success');
        addToHistory(`添加类别: ${trimmedName}`);
    }
}

async function updateProjectCategories(categories) {
    try {
        await fetch(`${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ categories: categories })
        });
    } catch (error) {
        console.error('更新类别失败:', error);
    }
}

// ==================== 裁切和导出功能 ====================

async function exportCroppedIcons() {
    if (bboxes.length === 0) {
        alert('当前图片没有标注，无法裁切！');
        return;
    }
    
    const confirmed = confirm(`确定要裁切当前图片的 ${bboxes.length} 个标注区域吗？\n\n将同时保存：\n1. 裁切的小图（用于Florence-2训练）\n2. 原图+标注框（用于YOLO训练）`);
    
    if (!confirmed) return;
    
    updateStatus('正在裁切...', 'loading');
    
    try {
        // 准备裁切数据
        const cropData = {
            image_id: images[currentImageIndex].id,
            image_filename: images[currentImageIndex].filename,
            image_width: currentImage.width,
            image_height: currentImage.height,
            bboxes: bboxes.map(bbox => ({
                bbox: bbox.bbox,
                category: bbox.category,
                id: bbox.id
            }))
        };
        
        const response = await fetch(
            `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/crop-icons`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(cropData)
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            updateStatus(`成功裁切 ${data.cropped_count} 个图标`, 'success');
            alert(`裁切完成！\n\n裁切图标数: ${data.cropped_count}\n保存位置: ${data.save_path}\n\n数据已准备好用于：\n- Florence-2训练（裁切的小图）\n- YOLO训练（原图+标注框）`);
            addToHistory(`裁切图标: ${data.cropped_count}个`);
        } else {
            updateStatus('裁切失败', 'error');
            alert('裁切失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('裁切失败:', error);
        updateStatus('裁切失败', 'error');
        alert('裁切失败: ' + error.message);
    }
}

async function previewCroppedIcon(bboxIndex) {
    if (bboxIndex < 0 || bboxIndex >= bboxes.length) return;
    
    const bbox = bboxes[bboxIndex];
    const [x, y, w, h] = bbox.bbox;
    
    // 创建临时canvas裁切预览
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tempCtx = tempCanvas.getContext('2d');
    
    // 裁切图像
    tempCtx.drawImage(currentImage, x, y, w, h, 0, 0, w, h);
    
    // 显示预览
    const previewWindow = window.open('', 'Icon Preview', 'width=400,height=400');
    previewWindow.document.write(`
        <html>
        <head>
            <title>图标预览 - ${bbox.category}</title>
            <style>
                body {
                    margin: 0;
                    padding: 20px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    font-family: Arial, sans-serif;
                }
                h3 { margin: 0 0 10px 0; }
                img {
                    max-width: 100%;
                    border: 2px solid #4F46E5;
                    border-radius: 8px;
                }
                .info {
                    margin-top: 10px;
                    padding: 10px;
                    background: #F3F4F6;
                    border-radius: 4px;
                }
            </style>
        </head>
        <body>
            <h3>📦 ${bbox.category}</h3>
            <img src="${tempCanvas.toDataURL()}" alt="Cropped Icon">
            <div class="info">
                尺寸: ${w}×${h}px<br>
                位置: (${Math.round(x)}, ${Math.round(y)})
            </div>
        </body>
        </html>
    `);
}

function showCategoryManager() {
    const modal = document.getElementById('shortcutsModal');
    const content = modal.querySelector('.shortcuts-grid');
    
    // 修改为类别管理界面
    modal.querySelector('.modal-header h2').textContent = '🏷️ 类别管理';
    
    content.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 1rem;">
            <h4>当前类别列表</h4>
            <div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 1rem;">
                ${currentProject.categories.map((cat, index) => `
                    <div style="display: flex; justify-content: space-between; align-items: center; 
                         padding: 0.75rem; background: #F9FAFB; border-radius: 0.375rem;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <div style="width: 20px; height: 20px; background: ${categoryColors[index % categoryColors.length]}; 
                                 border-radius: 0.25rem;"></div>
                            <span>${cat}</span>
                            ${index < 9 ? `<kbd style="margin-left: 0.5rem;">${index + 1}</kbd>` : ''}
                        </div>
                        <button onclick="deleteCategory('${cat}')" style="padding: 0.25rem 0.5rem; 
                                background: #EF4444; color: white; border: none; border-radius: 0.25rem; 
                                cursor: pointer;">删除</button>
                    </div>
                `).join('')}
            </div>
            <button onclick="showAddCategoryDialog(); hideShortcuts();" 
                    style="margin-top: 1rem; padding: 0.75rem; width: 100%; background: #4F46E5; 
                    color: white; border: none; border-radius: 0.375rem; cursor: pointer;">
                ➕ 添加新类别
            </button>
        </div>
    `;
    
    modal.classList.add('active');
}

async function deleteCategory(categoryName) {
    // 检查是否有标注使用了这个类别
    const usedInCurrent = bboxes.some(bbox => bbox.category === categoryName);
    
    if (usedInCurrent) {
        if (!confirm(`当前图片有标注使用了"${categoryName}"类别，确定要删除吗？\n删除后这些标注将失效。`)) {
            return;
        }
    }
    
    // 从项目中删除
    currentProject.categories = currentProject.categories.filter(cat => cat !== categoryName);
    
    // 更新项目配置
    await updateProjectCategories(currentProject.categories);
    
    // 删除使用该类别的标注
    bboxes = bboxes.filter(bbox => bbox.category !== categoryName);
    
    // 重新渲染
    renderCategories();
    renderBboxList();
    redraw();
    
    updateStatus(`已删除类别: ${categoryName}`, 'success');
    addToHistory(`删除类别: ${categoryName}`);
    
    // 关闭弹窗
    hideShortcuts();
}

// ==================== 批量操作功能 ====================

async function batchCropAll() {
    const annotatedImages = images.filter(img => img.annotated);
    
    if (annotatedImages.length === 0) {
        alert('没有已标注的图片！');
        return;
    }
    
    const confirmed = confirm(`准备批量裁切 ${annotatedImages.length} 张已标注图片\n\n此操作将：\n1. 裁切所有标注区域为小图（Florence-2）\n2. 保存原图和YOLO格式标注\n\n是否继续？`);
    
    if (!confirmed) return;
    
    updateStatus('批量裁切中...', 'loading');
    
    try {
        const response = await fetch(
            `${API_BASE}/api/projects/${encodePathSegment(currentProject.id)}/batch-crop`,
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'}
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            updateStatus('批量裁切完成', 'success');
            alert(`批量裁切完成！\n\n处理图片: ${data.processed_images}\n裁切图标: ${data.total_crops}\n\n数据已准备好用于训练`);
        } else {
            updateStatus('批量裁切失败', 'error');
            alert('批量裁切失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        console.error('批量裁切失败:', error);
        updateStatus('批量裁切失败', 'error');
    }
}

// 更新统计弹窗，添加裁切功能
function showStatistics() {
    const modal = document.getElementById('statisticsModal');
    const content = document.getElementById('statisticsContent');
    
    // 统计各类别数量
    const categoryCounts = {};
    currentProject.categories.forEach(cat => {
        categoryCounts[cat] = bboxes.filter(bbox => bbox.category === cat).length;
    });
    
    content.innerHTML = `
        <div style="padding: 1.5rem;">
            <h4>当前图片统计</h4>
            <div class="stats-grid" style="margin-top: 1rem;">
                <div class="stat-card">
                    <div class="stat-value">${bboxes.length}</div>
                    <div class="stat-label">标注框数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${currentProject.categories.length}</div>
                    <div class="stat-label">类别数</div>
                </div>
            </div>
            
            <h4 style="margin-top: 1.5rem;">类别分布</h4>
            <div class="stats-grid" style="margin-top: 1rem;">
                ${Object.entries(categoryCounts).map(([cat, count]) => `
                    <div class="stat-card">
                        <div class="stat-value">${count}</div>
                        <div class="stat-label">${cat}</div>
                    </div>
                `).join('')}
            </div>
            
            <h4 style="margin-top: 1.5rem;">数据导出</h4>
            <div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 1rem;">
                <button class="btn btn-primary btn-block" onclick="exportCroppedIcons(); hideStatistics();">
                    ✂️ 裁切当前图片 (${bboxes.length}个区域)
                </button>
                <button class="btn btn-secondary btn-block" onclick="batchCropAll(); hideStatistics();">
                    📦 批量裁切所有已标注图片
                </button>
                <button class="btn btn-secondary btn-block" onclick="exportAnnotations();">
                    📥 导出当前标注JSON
                </button>
            </div>
            
            <div style="margin-top: 1rem; padding: 1rem; background: #FEF3C7; border-radius: 0.375rem; font-size: 0.875rem;">
                💡 <strong>提示:</strong> 裁切后的数据将同时支持：<br>
                • Florence-2训练（裁切的图标小图）<br>
                • YOLO训练（原图+边界框标注）
            </div>
        </div>
    `;
    
    modal.classList.add('active');
}

// 更新bbox列表，添加预览按钮
const originalRenderBboxList = renderBboxList;
renderBboxList = function() {
    const list = document.getElementById('bboxList');
    
    if (bboxes.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无标注</div>';
        return;
    }
    
    list.innerHTML = bboxes.map((bbox, index) => {
        const [x, y, w, h] = bbox.bbox;
        return `
            <div class="bbox-item ${index === selectedBboxIndex ? 'selected' : ''}" 
                 onclick="selectBbox(${index})">
                <div class="bbox-item-color" style="background: ${bbox.color};"></div>
                <div class="bbox-item-info">
                    <div class="bbox-item-label">
                        ${bbox.locked ? '🔒 ' : ''}${bbox.category}
                    </div>
                    <div class="bbox-item-coords">
                        ${Math.round(x)}, ${Math.round(y)}, ${Math.round(w)}×${Math.round(h)}
                    </div>
                </div>
                <div class="bbox-item-actions">
                    <button class="icon-btn" onclick="event.stopPropagation(); previewCroppedIcon(${index})" title="预览裁切">
                        👁️
                    </button>
                    <button class="icon-btn" onclick="event.stopPropagation(); deleteBboxAt(${index})" title="删除">
                        🗑️
                    </button>
                </div>
            </div>
        `;
    }).join('');
};
