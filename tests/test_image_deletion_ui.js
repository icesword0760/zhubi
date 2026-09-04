const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const scriptPath = path.join(root, 'frontend/js/annotator_enhanced.js');
const htmlPath = path.join(root, 'frontend/annotate_enhanced.html');
const source = fs.readFileSync(scriptPath, 'utf8');

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
}

function makeElement(id) {
    const classes = new Set();
    const listeners = new Map();
    const attributes = new Map();
    const element = {
        id,
        tagName: String(id).toUpperCase(),
        innerHTML: '',
        textContent: '',
        value: 'all',
        checked: false,
        clientWidth: 800,
        clientHeight: 600,
        width: 0,
        height: 0,
        style: {},
        childNodes: [],
        classList: {
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            contains: name => classes.has(name),
            toggle(name, force) { force === false ? classes.delete(name) : classes.add(name); }
        },
        addEventListener(type, fn) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(fn);
        },
        dispatchEvent(event) {
            event.target ||= element;
            event.currentTarget = element;
            event.preventDefault ||= function () { this.defaultPrevented = true; };
            event.stopPropagation ||= function () { this.propagationStopped = true; };
            for (const fn of listeners.get(event.type) || []) fn(event);
            if (event.type === 'keydown' && event.key === 'Enter' && element.tagName === 'BUTTON' && !event.defaultPrevented) {
                element.click();
            }
            return !event.defaultPrevented;
        },
        click() { element.dispatchEvent({ type: 'click' }); },
        appendChild(child) { element.childNodes.push(child); child.parentNode = element; return child; },
        append(...children) { children.forEach(child => element.appendChild(child)); },
        replaceChildren(...children) { element.childNodes = []; element.innerHTML = ''; element.append(...children); },
        setAttribute(name, value) { attributes.set(name, String(value)); },
        getAttribute(name) { return attributes.get(name) ?? null; },
        removeAttribute(name) { attributes.delete(name); },
        getContext() { return makeContext2d(); },
        getBoundingClientRect() { return { left: 0, top: 0 }; },
        querySelector(selector) {
            if (selector.startsWith('.')) return findByClass(element, selector.slice(1))[0] || null;
            return null;
        },
        insertBefore() {},
        removeChild() {},
        firstChild: null,
        children: [],
        requestFullscreen() {},
        inert: false
    };
    Object.defineProperty(element, 'className', {
        get: () => Array.from(classes).join(' '),
        set: value => { classes.clear(); String(value).split(/\s+/).filter(Boolean).forEach(name => classes.add(name)); }
    });
    return element;
}

function findByClass(root, className) {
    const found = [];
    for (const child of root.childNodes || []) {
        if (child.classList && child.classList.contains(className)) found.push(child);
        found.push(...findByClass(child, className));
    }
    return found;
}

function makeContext2d() {
    return {
        clearRect() {}, save() {}, restore() {}, scale() {}, translate() {},
        drawImage() {}, strokeRect() {}, fillRect() {}, fillText() {},
        measureText: text => ({ width: String(text).length * 8 })
    };
}

function harness(fetchImpl = async () => ({ json: async () => ({ success: true }) }), options = {}) {
    const elements = new Map();
    const storage = new Map();
    const timerDelays = [];
    const document = {
        addEventListener() {},
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, makeElement(id));
            return elements.get(id);
        },
        querySelector(selector) {
            if (selector === '.annotate-enhanced-page') return this.getElementById('page');
            return makeElement(selector);
        },
        querySelectorAll() { return []; },
        createElement(tag) { const element = makeElement(tag); element.tagName = tag.toUpperCase(); return element; },
        documentElement: makeElement('documentElement'),
        fullscreenElement: null,
        exitFullscreen() {}
    };
    class FakeImage {
        constructor() { this.width = 640; this.height = 480; }
        set src(value) {
            this._src = value;
            if (options.controlImages) options.controlImages.push(this);
            else queueMicrotask(() => this.onload && this.onload());
        }
        get src() { return this._src; }
    }
    const context = vm.createContext({
        document,
        window: { addEventListener() {}, location: {} },
        localStorage: {
            getItem: key => storage.has(key) ? storage.get(key) : null,
            setItem: (key, value) => storage.set(key, String(value)),
            removeItem: key => storage.delete(key)
        },
        fetch: fetchImpl,
        Image: FakeImage,
        console: { log() {}, error() {}, warn() {} },
        setTimeout: (fn, delay, ...args) => {
            timerDelays.push(delay);
            return setTimeout(fn, delay, ...args);
        },
        clearTimeout,
        queueMicrotask,
        requestAnimationFrame: fn => fn(),
        alert() {}, confirm() { throw new Error('image deletion must not confirm'); },
        prompt() {}, FormData: class {}, Blob: class {}, URL: { createObjectURL() {}, revokeObjectURL() {} }
    });
    vm.runInContext(source, context, { filename: scriptPath });
    vm.runInContext("canvas = document.getElementById('annotationCanvas'); ctx = canvas.getContext('2d');", context);
    return {
        context, elements, storage, timerDelays,
        run(code) { return vm.runInContext(code, context); },
        value(expression) { return vm.runInContext(expression, context); }
    };
}

test('deletion index transition follows current-image identity rules', () => {
    const h = harness();
    assert.equal(h.run('getImageIndexAfterDeletion(1, 1, 3)'), 1, 'middle current selects following');
    assert.equal(h.run('getImageIndexAfterDeletion(2, 2, 3)'), 1, 'last current selects previous');
    assert.equal(h.run('getImageIndexAfterDeletion(0, 2, 4)'), 1, 'earlier non-current decrements');
    assert.equal(h.run('getImageIndexAfterDeletion(3, 1, 4)'), 1, 'later non-current keeps index');
    assert.equal(h.run('getImageIndexAfterDeletion(0, 0, 1)'), -1, 'only image clears selection');
});

test('toolbar and keyboard delete remain bbox-only', () => {
    const html = fs.readFileSync(htmlPath, 'utf8');
    assert.match(html, /class="tool-btn" onclick="deleteSelected\(\)" title="删除 \(Del\)"/);
    assert.match(source, /case 'delete': deleteSelected\(\); break;/);
    assert.match(source, /function setupKeyboardShortcuts\(\)[\s\S]*if \(imageDeletionInProgress\) return;/);
});

test('image cards use safe DOM text and behaviorally support selection and isolated deletion', () => {
    const h = harness();
    h.context.hostileImages = [{ id: "a'\"<script>", filename: '<script>alert("x")</script>', path: 'x" onerror=evil' }];
    h.run(`cardActions=[]; loadImage=index=>cardActions.push(['load',index]);
           deleteImage=(event,id)=>{ event.stopPropagation(); cardActions.push(['delete',id]); };
           images = hostileImages;
           currentImageIndex = 0; renderImageList(images);`);
    const list = h.elements.get('imageList');
    assert.equal(list.innerHTML, '');
    const select = findByClass(list, 'image-select-btn')[0];
    const trash = findByClass(list, 'image-delete-btn')[0];
    const name = findByClass(list, 'image-name')[0];
    const thumbnail = findByClass(list, 'image-thumbnail')[0];
    assert.equal(name.textContent, '<script>alert("x")</script>');
    assert.equal(thumbnail.src, 'x" onerror=evil');
    assert.equal(select.tagName, 'BUTTON');
    assert.equal(trash.getAttribute('aria-label'), '删除图片 <script>alert("x")</script>');
    select.click();
    select.dispatchEvent({ type: 'keydown', key: 'Enter' });
    trash.click();
    assert.equal(h.value('JSON.stringify(cardActions)'), JSON.stringify([['load',0],['load',0],['delete',"a'\"<script>"]]));
});

test('delete locks interaction, ignores duplicate deletion, blocks target saves, and awaits an in-flight save', async () => {
    const saveGate = deferred();
    const calls = [];
    const h = harness(async (url, options = {}) => {
        calls.push({ url, method: options.method || 'GET' });
        if ((options.method || 'GET') === 'POST') {
            await saveGate.promise;
            return { json: async () => ({ success: true }) };
        }
        return { json: async () => ({ success: true }) };
    });
    h.run(`currentProject={id:'p',categories:['cat']}; images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'}];
           currentImageIndex=0; currentImage={marker:'same'}; bboxes=[{bbox:[1,2,3,4]}];`);
    const save = h.run('saveAnnotation(true)');
    await Promise.resolve();
    const deletion = h.run("deleteImage({stopPropagation(){}}, 'a')");
    assert.equal(h.elements.get('page').classList.contains('deletion-locked'), true);
    assert.equal(h.elements.get('page').inert, true);
    assert.equal(h.elements.get('page').getAttribute('aria-busy'), 'true');
    assert.equal(h.value('imageDeletionInProgress'), true);
    assert.equal(await h.run('saveAnnotation(true)'), false, 'new target save rejected');
    const duplicate = await h.run("deleteImage({stopPropagation(){}}, 'a')");
    assert.equal(duplicate, false);
    assert.equal(calls.filter(call => call.method === 'DELETE').length, 0, 'DELETE waits for save');
    saveGate.resolve();
    await save;
    await deletion;
    assert.equal(calls.filter(call => call.method === 'DELETE').length, 1);
    assert.equal(h.elements.get('page').classList.contains('deletion-locked'), false);
    assert.equal(h.elements.get('page').inert, false);
    assert.equal(h.elements.get('page').getAttribute('aria-busy'), null);
});

test('stale image and annotation completion cannot overwrite a newer navigation', async () => {
    const imageControls = [];
    const annotations = { a: deferred(), b: deferred() };
    const h = harness(async url => {
        const id = url.endsWith('/a') ? 'a' : 'b';
        return annotations[id].promise;
    }, { controlImages: imageControls });
    h.run(`currentProject={id:'p',categories:['cat']};
           images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'}];
           currentImageIndex=-1; bboxes=[];`);
    const oldLoad = h.run('loadImage(0)');
    imageControls[0].onload();
    const newLoad = h.run('loadImage(1)');
    await Promise.resolve();
    imageControls[1].onload();
    annotations.b.resolve({ json: async () => ({ success:true, annotation:{annotations:[{id:'box-b',bbox:[2,2,2,2],category:'cat'}]} }) });
    await newLoad;
    annotations.a.resolve({ json: async () => ({ success:true, annotation:{annotations:[{id:'box-a',bbox:[1,1,1,1],category:'cat'}]} }) });
    await oldLoad;
    assert.equal(h.value('currentImageIndex'), 1);
    assert.equal(h.value('bboxes[0].id'), 'box-b');
    assert.equal(h.elements.get('currentImageName').textContent, 'B');
    assert.equal(h.storage.get('lastImage_p'), 'b');
});

test('replacement image error after deleting current clears deleted visual and keeps error visible', async () => {
    const imageControls = [];
    const h = harness(async (url, options = {}) => {
        if (options.method === 'DELETE') return { json: async () => ({ success:true }) };
        return { json: async () => ({ success:true, annotation:{annotations:[]} }) };
    }, { controlImages: imageControls });
    h.run(`currentProject={id:'p',categories:[]};
           images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'}];
           currentImageIndex=0; currentImage={marker:'deleted-a'}; bboxes=[{id:'box-a',bbox:[1,1,1,1]}];
           document.getElementById('currentImageName').textContent='A';`);
    const deletion = h.run("deleteImage({stopPropagation(){}}, 'a')");
    for (let i = 0; i < 10 && imageControls.length === 0; i++) await Promise.resolve();
    imageControls[0].onerror();
    assert.equal(await deletion, true);
    assert.equal(h.value('currentImage'), null);
    assert.equal(h.value('bboxes.length'), 0);
    assert.notEqual(h.elements.get('currentImageName').textContent, 'A');
    assert.match(h.elements.get('statusText').textContent, /加载图片失败/);
});

test('delete and annotation requests percent-encode hostile project and image path segments', async () => {
    const calls = [];
    const projectId = '项目 #? 100%';
    const imageId = '图像 #? 50%';
    const h = harness(async (url, options = {}) => {
        calls.push({ url, method: options.method || 'GET' });
        return { json: async () => ({ success: true, annotation: { annotations: [] } }) };
    });
    h.context.specialProjectId = projectId;
    h.context.specialImageId = imageId;
    h.run(`currentProject={id:specialProjectId,categories:[]};
           images=[{id:specialImageId,filename:'unsafe',path:'/provided/path'}];
           currentImageIndex=0; currentImage={marker:'current'}; bboxes=[];`);

    await h.run('fetchAnnotationData(specialImageId)');
    await h.run('saveAnnotationForImage(specialImageId, [], true)');
    await h.run('deleteImage({stopPropagation(){}}, specialImageId)');

    const encodedProject = encodeURIComponent(projectId);
    const encodedImage = encodeURIComponent(imageId);
    const annotationUrls = calls.filter(call => call.url.includes('/annotations/')).map(call => call.url);
    const deleteCall = calls.find(call => call.method === 'DELETE');
    assert.deepEqual(annotationUrls, [
        `/api/projects/${encodedProject}/annotations/${encodedImage}`,
        `/api/projects/${encodedProject}/annotations/${encodedImage}`
    ]);
    assert.equal(deleteCall.url, `/api/projects/${encodedProject}/images/${encodedImage}`);
    for (const url of [...annotationUrls, deleteCall.url]) {
        assert.equal(url.includes(projectId), false);
        assert.equal(url.includes(imageId), false);
        assert.equal(url.includes('#'), false);
        assert.equal(url.includes('?'), false);
    }
});

test('failed deletion preserves data and reschedules exactly one pending empty autosave', async () => {
    const calls = [];
    const h = harness(async (url, options = {}) => {
        calls.push({ url, method: options.method || 'GET' });
        if (options.method === 'DELETE') return { json: async () => ({ success: false, error: 'denied' }) };
        return { json: async () => ({ success: true }) };
    });
    h.run(`currentProject={id:'p'}; images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'}];
           currentImageIndex=0; currentImage={marker:'same'}; bboxes=[]; selectedBboxIndex=-1;
           autoSaveTimer=setTimeout(()=>{}, 60000); autoSavePendingImageId='a';`);
    const before = h.value('JSON.stringify(images)');
    const result = await h.run("deleteImage({stopPropagation(){}}, 'a')");
    assert.equal(result, false);
    assert.equal(h.value('JSON.stringify(images)'), before);
    assert.equal(h.value('currentImageIndex'), 0);
    assert.equal(h.value('currentImage.marker'), 'same');
    assert.match(h.elements.get('statusText').textContent, /删除图片失败/);
    assert.equal(h.value("deletingImageIds.has('a')"), false);
    assert.equal(h.elements.get('page').classList.contains('deletion-locked'), false);
    assert.equal(h.value("autoSaveTimer !== null && autoSavePendingImageId === 'a'"), true);
    assert.equal(h.timerDelays.filter(delay => delay === 500).length, 1);
    h.run('clearTimeout(autoSaveTimer); autoSaveTimer=null;');
});

test('failed non-current deletion restores the target-owned autosave without saving the current neighbor', async () => {
    const calls = [];
    const h = harness(async (url, options = {}) => {
        calls.push({ url, method: options.method || 'GET', body: options.body });
        if (options.method === 'DELETE') {
            return { json: async () => ({ success: false, error: 'denied' }) };
        }
        return { json: async () => ({ success: true }) };
    });
    h.run(`currentProject={id:'p'};
           images=[{id:'a',filename:'A',path:'/a',annotated:false},{id:'b',filename:'B',path:'/b',annotated:false}];
           currentImageIndex=1; currentImage={marker:'b'}; bboxes=[{id:'bbox-b',bbox:[9,9,9,9]}];
           scheduleAutoSave('a', [{id:'bbox-a',bbox:[1,2,3,4]}]);`);

    assert.equal(await h.run("deleteImage({stopPropagation(){}}, 'a')"), false);
    assert.equal(h.value('autoSavePendingImageId'), 'a');
    assert.equal(h.timerDelays.filter(delay => delay === 500).length, 2, 'A timer was cancelled and restored once');
    assert.equal(h.value("images[1].id + ':' + images[1].annotated"), 'b:false');

    await new Promise(resolve => setTimeout(resolve, 550));
    const posts = calls.filter(call => call.method === 'POST');
    assert.equal(posts.length, 1);
    assert.match(posts[0].url, /\/annotations\/a$/);
    assert.deepEqual(JSON.parse(posts[0].body), { annotations: [{ id: 'bbox-a', bbox: [1, 2, 3, 4] }] });
    assert.equal(h.value("images.find(image => image.id === 'b').annotated"), false);
});

test('next navigation flushes an outgoing empty pending autosave before opening the next image', async () => {
    const calls = [];
    const h = harness(async (url, options = {}) => {
        calls.push({ url, method: options.method || 'GET', body: options.body });
        return { json: async () => ({ success: true, annotation: { annotations: [] } }) };
    });
    h.run(`currentProject={id:'p',categories:[]};
           images=[{id:'a',filename:'A',path:'/a',annotated:false},{id:'b',filename:'B',path:'/b',annotated:false}];
           currentImageIndex=0; currentImage={marker:'a'}; bboxes=[];
           scheduleAutoSave('a', []);`);

    await h.run('nextImage()');
    const posts = calls.filter(call => call.method === 'POST');
    assert.equal(posts.length, 1);
    assert.match(posts[0].url, /\/annotations\/a$/);
    assert.deepEqual(JSON.parse(posts[0].body), { annotations: [] });
    assert.equal(h.value('autoSaveTimer'), null);
    assert.equal(h.value('autoSavePendingImageId'), null);
});

test('successful current deletion switches directly to following image at same index', async () => {
    const calls = [];
    const h = harness(async (url, options = {}) => {
        calls.push({ url, method: options.method || 'GET' });
        return { json: async () => ({ success: true, annotation: { annotations: [] } }) };
    });
    h.run(`currentProject={id:'p'}; images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'},{id:'c',filename:'C',path:'/c'}];
           currentImageIndex=1; currentImage={marker:'old'}; bboxes=[];
           document.getElementById('progressText').textContent='0 / 3';
           document.getElementById('totalImages').textContent='3';
           document.getElementById('annotatedImages').textContent='0';
           document.getElementById('progressBar').style.width='0%';`);
    assert.equal(await h.run("deleteImage({stopPropagation(){}}, 'b')"), true);
    assert.equal(h.value("images.map(x=>x.id).join(',')"), 'a,c');
    assert.equal(h.value('currentImageIndex'), 1);
    assert.equal(h.storage.get('lastImage_p'), 'c');
    assert.equal(h.elements.get('currentImageName').textContent, 'C');
    assert.equal(h.elements.get('progressText').textContent, '0 / 2');
    assert.equal(String(h.elements.get('totalImages').textContent), '2');
    assert.equal(String(h.elements.get('annotatedImages').textContent), '0');
    assert.equal(h.elements.get('progressBar').style.width, '0%');
    assert.equal(calls.filter(call => call.method === 'POST').length, 0, 'no pre-navigation autosave');
    assert.equal(h.value("deletingImageIds.has('b')"), false);
});

test('successful last-current deletion selects previous', async () => {
    const h = harness(async () => ({ json: async () => ({ success: true, annotation: { annotations: [] } }) }));
    h.run(`currentProject={id:'p'}; images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'}];
           currentImageIndex=1; currentImage={marker:'old'}; bboxes=[];`);
    await h.run("deleteImage({stopPropagation(){}}, 'b')");
    assert.equal(h.value('currentImageIndex'), 0);
    assert.equal(h.storage.get('lastImage_p'), 'a');
});

test('successful non-current deletion keeps the current image object and corrects index', async () => {
    const h = harness(async () => ({ json: async () => ({ success: true }) }));
    h.run(`currentProject={id:'p'}; images=[{id:'a',filename:'A',path:'/a'},{id:'b',filename:'B',path:'/b'},{id:'c',filename:'C',path:'/c'}];
           currentImageIndex=2; currentImage={marker:'keep-me'}; bboxes=[{bbox:[1,2,3,4]}];`);
    await h.run("deleteImage({stopPropagation(){}}, 'a')");
    assert.equal(h.value('currentImageIndex'), 1);
    assert.equal(h.value('currentImage.marker'), 'keep-me');
    assert.equal(h.storage.get('lastImage_p'), 'c');
    assert.equal(h.elements.get('currentImageIndex').textContent, '2 / 2');
});

test('deleting the only image fully resets annotation and UI state', async () => {
    const h = harness(async () => ({ json: async () => ({ success: true }) }));
    h.run(`currentProject={id:'p'}; images=[{id:'a',filename:'A',path:'/a'}]; currentImageIndex=0;
           currentImage={marker:'old'}; bboxes=[{bbox:[1,2,3,4]}]; selectedBboxIndex=0;
           selectedCategory='cat'; isDrawing=true; isDragging=true; isResizing=true; resizeHandle='se';
           history=[[{bbox:[1,2,3,4]}]]; historyIndex=0;
           canvas.width=100; canvas.height=80; localStorage.setItem('lastImage_p','a');`);
    assert.equal(await h.run("deleteImage({stopPropagation(){}}, 'a')"), true);
    assert.equal(h.value('images.length'), 0);
    assert.equal(h.value('currentImage'), null);
    assert.equal(h.value('currentImageIndex'), -1);
    assert.equal(h.value('bboxes.length'), 0);
    assert.equal(h.value('selectedBboxIndex'), -1);
    assert.equal(h.value('history.length'), 0);
    assert.equal(h.value('historyIndex'), -1);
    assert.equal(h.value('isDrawing || isDragging || isResizing || resizeHandle !== null'), false);
    assert.equal(h.value('canvas.width'), 0);
    assert.equal(h.value('canvas.height'), 0);
    assert.equal(h.elements.get('currentImageName').textContent, '未选择图片');
    assert.equal(h.elements.get('currentImageSize').textContent, '');
    assert.equal(h.elements.get('currentImageIndex').textContent, '');
    assert.equal(String(h.elements.get('currentBoxes').textContent), '0');
    assert.equal(h.elements.get('bboxCount').textContent, '标注数: 0');
    assert.equal(h.elements.get('imageList').innerHTML, '');
    assert.equal(h.elements.get('progressText').textContent, '0 / 0');
    assert.equal(h.storage.has('lastImage_p'), false);
    assert.equal(h.elements.get('statusText').textContent, '暂无图片');
});

test('deletion styles reserve card space, place a neutral trash action, and expose a busy lock', () => {
    const css = fs.readFileSync(path.join(root, 'frontend/css/annotate_enhanced.css'), 'utf8');
    assert.match(css, /\.image-item\s*\{[^}]*position:\s*relative;[^}]*padding-right:/s);
    assert.match(css, /\.image-delete-btn\s*\{[^}]*position:\s*absolute;[^}]*right:[^}]*bottom:/s);
    assert.match(css, /\.image-delete-btn:(?:hover|focus-visible)[^{]*\{[^}]*#(?:DC2626|EF4444)/s);
    assert.match(css, /\.annotate-enhanced-page\.deletion-locked\s*\{[^}]*pointer-events:\s*none;[^}]*opacity:/s);
});
