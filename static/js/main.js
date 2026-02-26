// ================== 全局 UI 组件 ==================

// 1. Toast 提示
function showToast(message, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div'); container.id = 'toast-container'; container.className = 'toast-container'; document.body.appendChild(container);
    }
    const toast = document.createElement('div'); toast.className = `toast ${type}`;
    toast.innerHTML = type === 'success' ? `✅ ${message}` : `❌ ${message}`;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 3000);
}

// 2. 增强版 Lightbox (带图片数组与左右滑动)
let galleryImages = [];
let currentGalleryIndex = 0;

function initGallery() {
    galleryImages = [];
    const photos = document.querySelectorAll('.photo-wrapper');
    photos.forEach((photo, index) => {
        galleryImages.push({
            src: photo.getAttribute('href'),
            id: photo.dataset.id
        });
        photo.onclick = (e) => {
            // 如果点的是收藏小红心，不要弹大图
            if(e.target.closest('.thumb-fav-btn')) return;
            e.preventDefault();
            openLightbox(index);
        }
    });
}

function openLightbox(index) {
    currentGalleryIndex = index;
    let lightbox = document.getElementById('lightbox');
    if (!lightbox) {
        lightbox = document.createElement('div');
        lightbox.id = 'lightbox';
        lightbox.className = 'lightbox';
        lightbox.innerHTML = `
            <div class="lightbox-close" onclick="closeLightbox()">×</div>
            <div class="lb-nav lb-prev" onclick="navLightbox(-1)">&#10094;</div>
            <img id="lightbox-img" src="" alt="Full Screen">
            <div class="lb-nav lb-next" onclick="navLightbox(1)">&#10095;</div>
        `;
        document.body.appendChild(lightbox);
        lightbox.addEventListener('click', (e) => { if (e.target === lightbox) closeLightbox(); });
        
        // 绑定键盘左右键
        document.addEventListener('keydown', (e) => {
            if(!document.getElementById('lightbox').classList.contains('show')) return;
            if(e.key === 'ArrowLeft') navLightbox(-1);
            if(e.key === 'ArrowRight') navLightbox(1);
            if(e.key === 'Escape') closeLightbox();
        });
    }
    updateLightboxImage();
    lightbox.classList.add('show');
}

function updateLightboxImage() {
    if(galleryImages.length === 0) return;
    const imgData = galleryImages[currentGalleryIndex];
    document.getElementById('lightbox-img').src = imgData.src;
}

function navLightbox(direction) {
    currentGalleryIndex += direction;
    // 循环切换
    if(currentGalleryIndex < 0) currentGalleryIndex = galleryImages.length - 1;
    if(currentGalleryIndex >= galleryImages.length) currentGalleryIndex = 0;
    updateLightboxImage();
}

function closeLightbox() {
    const lightbox = document.getElementById('lightbox');
    if (lightbox) {
        lightbox.classList.remove('show');
        setTimeout(() => { document.getElementById('lightbox-img').src = ''; }, 300);
    }
}

// 3. 页面加载完成执行
document.addEventListener("DOMContentLoaded", function() {
    // 骨架屏动画
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });
    document.querySelectorAll('.fade-up').forEach(el => observer.observe(el));

    // 画廊初始化
    initGallery();

    // 4. 滚动监听器 (ScrollSpy) - 实现右侧时间轴滑动高亮
    const sections = document.querySelectorAll('.month-section');
    const navLinks = document.querySelectorAll('.timeline-dot');
    if(sections.length > 0 && navLinks.length > 0) {
        const spyObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    navLinks.forEach(link => link.classList.remove('active'));
                    const id = entry.target.getAttribute('id');
                    const activeLink = document.querySelector(`.timeline-dot[href="#${id}"]`);
                    if(activeLink) activeLink.classList.add('active');
                }
            });
        }, { rootMargin: '-20% 0px -70% 0px' });
        sections.forEach(sec => spyObserver.observe(sec));
    }
});

// ================== 核心业务逻辑 ==================

// 红心收藏切换
function toggleFav(imageId, event, btnEl) {
    event.preventDefault(); 
    event.stopPropagation(); 
    const isCurrentlyFav = btnEl.classList.contains('active');
    const targetStatus = isCurrentlyFav ? 0 : 1;

    fetch('/api/toggle_favorite', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: imageId, is_favorite: targetStatus})
    }).then(res => res.json()).then(data => {
        if(data.success) {
            if(targetStatus === 1) {
                btnEl.classList.add('active');
                btnEl.innerHTML = '❤️';
                showToast('已加入我的收藏');
            } else {
                btnEl.classList.remove('active');
                btnEl.innerHTML = '🤍';
                showToast('已取消收藏');
                // 如果当前就在收藏页，取消收藏后直接淡出移除
                if(window.location.pathname === '/favorites') {
                    const wrap = btnEl.closest('.photo-wrapper');
                    wrap.style.opacity = '0';
                    setTimeout(() => wrap.remove(), 300);
                }
            }
        }
    });
}

let isExportMode = false;
let selectedPersons = new Set();
let progressInterval = null;

function toggleExportMode() {
    isExportMode = !isExportMode;
    const modeBtn = document.getElementById('mode-btn');
    const exportBar = document.getElementById('export-bar');
    if (isExportMode) { 
        modeBtn.innerText = "退出筛选模式"; 
        modeBtn.classList.replace('btn-outline', 'btn-danger'); 
        exportBar.classList.add('active'); 
    } else { 
        modeBtn.innerText = "🔍 开启筛选/导出模式"; 
        modeBtn.classList.replace('btn-danger', 'btn-outline'); 
        exportBar.classList.remove('active'); 
        selectedPersons.clear(); 
        document.querySelectorAll('.card.selected').forEach(el => el.classList.remove('selected')); 
        updateSelectCount(); 
    }
}

function handleCardClick(personId, event) {
    if (isExportMode) {
        event.preventDefault();
        const card = event.currentTarget;
        if (selectedPersons.has(personId)) { 
            selectedPersons.delete(personId); 
            card.classList.remove('selected'); 
        } else { 
            selectedPersons.add(personId); 
            card.classList.add('selected'); 
        }
        updateSelectCount();
    }
}

// 【增强版】更新数量并智能判断全选/取消全选按钮文字
function updateSelectCount() { 
    const countEl = document.getElementById('select-count'); 
    if(countEl) countEl.innerText = selectedPersons.size; 
    
    const selectAllBtn = document.getElementById('select-all-btn');
    if (selectAllBtn) {
        const totalCards = document.querySelectorAll('.card-container').length;
        if (totalCards > 0 && selectedPersons.size === totalCards) {
            selectAllBtn.innerText = "取消全选";
        } else {
            selectAllBtn.innerText = "全选";
        }
    }
}

// 【新增】全选逻辑
function toggleSelectAll() {
    const allCardContainers = document.querySelectorAll('.card-container');
    const totalCards = allCardContainers.length;

    if (totalCards === 0) return;

    if (selectedPersons.size === totalCards) {
        // 取消全选
        selectedPersons.clear();
        document.querySelectorAll('.card.selected').forEach(el => el.classList.remove('selected'));
    } else {
        // 一键全选
        allCardContainers.forEach(container => {
            const idStr = container.id.replace('person-card-', '');
            const personId = parseInt(idStr);
            selectedPersons.add(personId);
            container.querySelector('.card').classList.add('selected');
        });
    }
    updateSelectCount();
}

function executeExport() {
    if (selectedPersons.size === 0) return showToast("请先点击头像选择至少一个人物", 'error');
    const destPath = document.getElementById('export-path').value.trim();
    if (!destPath) return showToast("请输入需要导出存放的新路径！", 'error');
    fetch('/api/export_photos', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ person_ids: Array.from(selectedPersons), dest_path: destPath })
    }).then(res => res.json()).then(data => {
        if (data.success) { showToast(`导出成功！共提取备份 ${data.count} 张照片。`); setTimeout(() => toggleExportMode(), 1500); } 
        else { showToast("导出失败: " + data.msg, 'error'); }
    });
}

function showRenameModal(personId, oldName) {
    let modalOverlay = document.getElementById('rename-modal-overlay');
    if (!modalOverlay) {
        modalOverlay = document.createElement('div'); modalOverlay.id = 'rename-modal-overlay'; modalOverlay.className = 'modal-overlay';
        modalOverlay.innerHTML = `<div class="modal"><div class="modal-title">修改名称</div><input type="text" id="rename-input" style="width: 100%; box-sizing: border-box;" placeholder="输入相同名字可自动合并不同年龄段"><div class="modal-actions"><button class="btn btn-outline" onclick="closeRenameModal()">取消</button><button class="btn" id="rename-confirm-btn">确认修改</button></div></div>`;
        document.body.appendChild(modalOverlay);
    }
    const input = document.getElementById('rename-input'); input.value = oldName; modalOverlay.classList.add('show'); input.focus();
    const confirmBtn = document.getElementById('rename-confirm-btn');
    const newBtn = confirmBtn.cloneNode(true); confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
    newBtn.addEventListener('click', () => { const newName = input.value.trim(); if (newName && newName !== oldName) submitRename(personId, newName); closeRenameModal(); });
}

function closeRenameModal() { const modal = document.getElementById('rename-modal-overlay'); if (modal) modal.classList.remove('show'); }

function submitRename(personId, newName) {
    fetch('/api/rename', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: personId, name: newName})
    }).then(res => res.json()).then(data => {
        if(data.success) {
            if(data.merged) { showToast("发现同名，已自动为您合并相册！"); setTimeout(() => location.reload(), 1500); } 
            else { document.getElementById('name-' + personId).innerText = newName; document.querySelector(`#person-card-${personId} .edit-btn`).setAttribute('onclick', `showRenameModal(${personId}, '${newName}')`); showToast("改名成功！"); }
        }
    });
}

function hidePerson(personId) {
    if (confirm("确定要隐藏它吗？(这是非人脸时点此按钮)")) {
        fetch('/api/hide_person', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: personId})
        }).then(res => res.json()).then(data => {
            if(data.success) {
                const card = document.getElementById('person-card-' + personId);
                card.style.transform = 'scale(0.8)'; card.style.opacity = '0';
                setTimeout(() => { card.remove(); selectedPersons.delete(personId); updateSelectCount(); }, 300);
                showToast("已成功清理隐藏该目标");
            }
        });
    }
}

function startScan() {
    const path = document.getElementById('scan-path').value.trim();
    if (!path) return showToast("请输入需要扫描的路径！", 'error');
    fetch('/api/start_scan', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: path}) 
    }).then(res => res.json()).then(data => {
        if (data.success) {
            document.getElementById('scan-btn').disabled = true; document.getElementById('progress-container').style.display = 'block';
            progressInterval = setInterval(fetchProgress, 1000); showToast("扫描已启动，引擎全力运转中...");
        } else showToast(data.msg, 'error');
    });
}

function fetchProgress() {
    fetch('/api/progress').then(res => res.json()).then(data => {
        const percent = data.total > 0 ? (data.current / data.total * 100).toFixed(1) : 0;
        document.getElementById('progress-bar').style.width = percent + '%';
        document.getElementById('progress-text').innerText = data.total > 0 ? `${data.msg} (${data.current}/${data.total})` : data.msg;
        if (data.status === 'done') { clearInterval(progressInterval); showToast("整理完成！页面即将刷新"); setTimeout(() => location.reload(), 1500); }
    });
}
