/* 作品与系列共用的本地背景图管理器；添加资源与保存作品分开。 */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
  const states = new WeakMap();
  const unique = values => [...new Set(values.map(ArchiveV2.backgrounds.safeBackgroundUrl).filter(Boolean))];
  const imageTypes = /^image\/(png|jpeg|webp|gif)$/i;
  function pastedFiles(event) {
    return Array.from(event.clipboardData?.items || [])
      .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
      .map(item => item.getAsFile()).filter(Boolean);
  }
  async function clipboardFiles() {
    const files = [];
    for (const item of await navigator.clipboard.read()) {
      const type = item.types.find(value => imageTypes.test(value));
      if (type) files.push(await item.getType(type));
    }
    return files;
  }
  async function uploadImage(file) {
    if ((file.type && !imageTypes.test(file.type)) || !file.size || file.size > 20 * 1024 * 1024) {
      throw Error('仅支持 20 MB 内的 PNG、JPEG、WebP 或 GIF 图片。');
    }
    const response = await fetch('/api/backgrounds/local', {
      method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file, signal:AbortSignal.timeout(45000),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw Error(result.error || '图片保存失败');
    const url = ArchiveV2.backgrounds.safeBackgroundUrl(result.image?.url);
    if (!url.startsWith('/covers/')) throw Error('未收到有效的本地图片');
    return {...result.image, url};
  }
  function images(entity) {
    return unique(Array.isArray(entity?.immersiveBackgroundUrls) ? entity.immersiveBackgroundUrls : [entity?.immersiveBackgroundUrl]);
  }
  function reorder(values, from, to) {
    const result = values.slice();
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= result.length || to >= result.length) return result;
    result.splice(to, 0, result.splice(from, 1)[0]);
    return result;
  }
  function form(entity, id, label = "沉浸背景图片") {
    return `<div class="form-item full background-editor" data-background-editor="${id}">
      <label for="${id}Link">${esc(label)} <span class="background-count" data-background-count></span></label>
      <div class="background-add-row"><input id="${id}Link" type="url" data-background-link placeholder="粘贴 HTTP / HTTPS 图片直链" autocomplete="off" aria-describedby="${id}Tip"><button type="button" class="btn" data-background-add>添加链接</button></div>
      <div class="background-local-row"><button type="button" class="btn" data-background-paste>粘贴剪贴板图片</button><button type="button" class="btn" data-background-choose>选择本地图片</button><input type="file" data-background-file accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden></div>
      <textarea id="${id}" data-background-value hidden>${esc(images(entity).join("\n"))}</textarea>
      <ol class="background-grid" data-background-grid aria-label="沉浸图片顺序"></ol>
      <p class="background-empty" data-background-empty>还没有背景图，粘贴图片直链后点击「添加」。</p>
      <div class="tip" id="${id}Tip">最多 20 张，单张最多 20 MB。添加时保存原图到本地；拖动缩略图调整播放顺序，也可使用前移 / 后移按钮。保存作品或系列后生效。</div>
      <p class="background-message" data-background-message role="status" aria-live="polite"></p>
    </div>`;
  }
  function editor(root, id) { return root.querySelector(`[data-background-editor="${id}"]`); }
  function bind(root, id, notify = () => {}, onChange = () => {}) {
    const box = editor(root, id); if (!box) return;
    const get = selector => box.querySelector(selector);
    const value = get('[data-background-value]'), input = get('[data-background-link]');
    const grid = get('[data-background-grid]'), add = get('[data-background-add]'), message = get('[data-background-message]');
    const fileInput = get('[data-background-file]'), pasteButton = get('[data-background-paste]'), chooseButton = get('[data-background-choose]');
    const state = {busy:false, drag:null}; states.set(box, state);
    const urls = () => unique(value.value.split(/\r?\n/));
    function draw() {
      const list = urls();
      get('[data-background-count]').textContent = `${list.length} / 20`;
      get('[data-background-empty]').hidden = list.length > 0;
      grid.innerHTML = list.map((url, index) => {
        const local = url.startsWith('/covers/');
        return `<li class="background-item" data-background-item data-background-url="${esc(url)}">
          <div class="background-preview" data-background-preview tabindex="0" role="img" aria-label="沉浸图片 ${index + 1}，拖动或用左右方向键排序" title="拖动缩略图调整顺序">
            <span class="background-unavailable">无法预览</span><img src="${esc(url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" draggable="false">
            <span class="background-number">${index + 1}</span><span class="background-storage">${local ? '本地' : '远程'}</span>
          </div>
          <div class="background-item-actions"><button type="button" data-background-move="-1" aria-label="前移第 ${index + 1} 张图片" ${index === 0 ? 'disabled' : ''}>前移</button><button type="button" data-background-move="1" aria-label="后移第 ${index + 1} 张图片" ${index === list.length - 1 ? 'disabled' : ''}>后移</button><button type="button" data-background-remove aria-label="移除第 ${index + 1} 张图片">移除</button></div>
          ${local ? '' : '<button type="button" class="background-localize" data-background-localize>存到本地</button>'}
        </li>`;
      }).join('');
      grid.querySelectorAll('img').forEach(img => { img.onerror = () => { img.hidden = true; }; });
    }
    function commit(list, text) {
      const next = unique(list);
      value.value = next.join('\n'); onChange(next.slice()); draw();
      if (text) message.textContent = text;
    }
    function move(url, direction) {
      const list = urls(), from = list.indexOf(url), to = from + direction;
      if (from < 0 || to < 0 || to >= list.length) return;
      commit(reorder(list, from, to), '顺序已调整，保存后生效。');
      grid.children[to]?.querySelector('[data-background-preview]').focus({preventScroll:true});
    }
    async function download(url, replaceUrl = null) {
      if (state.busy) return;
      const remote = ArchiveV2.backgrounds.safeRemoteUrl(url);
      if (!remote) { message.textContent = '请填写完整的 HTTP 或 HTTPS 图片直链。'; input.focus(); return; }
      if (!replaceUrl && urls().length >= 20) { message.textContent = '最多添加 20 张图片，请先移除不需要的图片。'; return; }
      state.busy = true; box.setAttribute('aria-busy', 'true'); input.disabled = true; add.disabled = true;
      message.textContent = '正在下载原图并保存到本地…';
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
      try {
        const response = await fetch('/api/backgrounds', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url:remote}), signal:controller.signal});
        const result = await response.json();
        if (!response.ok || !result.ok) throw Error(result.error || '图片添加失败');
        const local = ArchiveV2.backgrounds.safeBackgroundUrl(result.image?.url);
        if (!local?.startsWith('/covers/')) throw Error('未收到有效的本地图片，请重试');
        if (!box.isConnected) return;
        const list = urls();
        if (replaceUrl) {
          const index = list.indexOf(replaceUrl); if (index < 0) return;
          list[index] = local;
        } else if (!list.includes(local)) list.push(local);
        commit(list, `原图已保存至本地（${result.image.width} × ${result.image.height}），保存后生效。`);
        if (!replaceUrl) input.value = '';
      } catch (error) {
        if (!box.isConnected) return;
        const text = error.name === 'AbortError' ? '图片下载超时，请检查链接后重试。' : error.message || '图片添加失败，请重试。';
        message.textContent = text; notify(text, true);
      } finally {
        clearTimeout(timer); state.busy = false; box.removeAttribute('aria-busy'); input.disabled = false; add.disabled = false;
      }
    }
    async function uploadFiles(files) {
      if (state.busy) return;
      for (const file of Array.from(files || [])) {
        if (urls().length >= 20) { message.textContent = '最多添加 20 张图片，剩余图片未添加。'; break; }
        state.busy = true; box.setAttribute('aria-busy', 'true'); input.disabled = true; add.disabled = true; pasteButton.disabled = true; chooseButton.disabled = true;
        message.textContent = `正在保存：${file.name || '剪贴板图片'}…`;
        try {
          const image = await uploadImage(file);
          if (!box.isConnected) return;
          const list = urls(); if (!list.includes(image.url)) list.push(image.url);
          commit(list, `图片已保存至本地（${image.width} × ${image.height}），保存后生效。`);
        } catch (error) { const text = error.message || '图片保存失败，请重试。'; message.textContent = text; notify(text, true); }
        finally { state.busy = false; box.removeAttribute('aria-busy'); input.disabled = false; add.disabled = false; pasteButton.disabled = false; chooseButton.disabled = false; }
      }
    }
    chooseButton.onclick = () => fileInput.click();
    fileInput.onchange = () => { uploadFiles(fileInput.files); fileInput.value = ''; };
    pasteButton.onclick = async () => {
      try {
        const files = await clipboardFiles();
        if (!files.length) { message.textContent = '剪贴板中没有可用图片。'; return; }
        uploadFiles(files);
      } catch (_) { message.textContent = '无法读取剪贴板；请聚焦此编辑区后按 Ctrl+V，或选择本地图片。'; }
    };
    box.addEventListener('paste', event => {
      const files = pastedFiles(event);
      if (!files.length) return;
      event.preventDefault(); uploadFiles(files);
    });
    add.onclick = () => download(input.value.trim());
    input.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); download(input.value.trim()); } };
    grid.onclick = event => {
      if (state.busy) return;
      const item = event.target.closest('[data-background-item]'); if (!item) return;
      const url = item.dataset.backgroundUrl;
      if (event.target.closest('[data-background-remove]')) commit(urls().filter(value => value !== url), '已移除，保存后生效。本地原图保留以支持撤销。');
      else if (event.target.closest('[data-background-localize]')) download(url, url);
      else {
        const button = event.target.closest('[data-background-move]');
        if (button) move(url, Number(button.dataset.backgroundMove));
      }
    };
    grid.onkeydown = event => {
      if (state.busy || !event.target.matches('[data-background-preview]') || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
      event.preventDefault(); move(event.target.closest('[data-background-item]').dataset.backgroundUrl, event.key === 'ArrowLeft' ? -1 : 1);
    };
    grid.ondragstart = event => event.preventDefault();
    grid.onpointerdown = event => {
      if (state.busy || event.button !== 0 || !event.target.closest('[data-background-preview]')) return;
      const item = event.target.closest('[data-background-item]');
      state.drag = {item, pointer:event.pointerId, x:event.clientX, y:event.clientY, moved:false};
      grid.setPointerCapture(event.pointerId);
    };
    grid.onpointermove = event => {
      const drag = state.drag; if (!drag || drag.pointer !== event.pointerId) return;
      if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 6) return;
      drag.moved = true; drag.item.classList.add('is-dragging'); event.preventDefault();
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-background-item]');
      if (!target || target === drag.item || target.parentElement !== grid) return;
      const children = [...grid.children], after = children.indexOf(target) > children.indexOf(drag.item);
      grid.insertBefore(drag.item, after ? target.nextSibling : target);
    };
    function endDrag(event, cancel = false) {
      const drag = state.drag; if (!drag || drag.pointer !== event.pointerId) return;
      state.drag = null;
      if (grid.hasPointerCapture(event.pointerId)) grid.releasePointerCapture(event.pointerId);
      if (drag.moved && !cancel) commit([...grid.children].map(item => item.dataset.backgroundUrl), '顺序已调整，保存后生效。');
      else draw();
    }
    grid.onpointerup = event => endDrag(event);
    grid.onpointercancel = event => endDrag(event, true);
    draw();
  }
  function read(root, id) {
    const box = editor(root, id); if (!box) return [];
    if (states.get(box)?.busy) throw Error('图片正在下载，请完成后再保存');
    if (box.querySelector('[data-background-link]').value.trim()) throw Error('还有未添加的图片链接，请点击「添加」或清空链接后再保存');
    const list = box.querySelector('[data-background-value]').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (list.length > 20) throw Error('沉浸背景最多添加 20 张图片');
    return list;
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, {backgroundEditor:{form,bind,read,images,reorder,uploadImage,pastedFiles,clipboardFiles}});
})();
