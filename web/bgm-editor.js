/* 表单中的音乐导入与试听，只有保存实体时才改变绑定。 */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
  const pending = new WeakMap();
  function form(entity, prefix) {
    const bgm = ArchiveV2.audio.binding(entity), local = bgm?.src.startsWith("/audio/");
    return `<div class="form-item full bgm-editor" data-bgm-editor="${prefix}"><label for="${prefix}Mode">沉浸背景音乐 BGM（可选）</label>
      <select id="${prefix}Mode" data-bgm-mode><option value="none" ${!bgm ? "selected" : ""}>不绑定音乐</option><option value="local" ${local ? "selected" : ""}>本地 MP3</option><option value="remote" ${bgm && !local ? "selected" : ""}>在线音频直链</option></select>
      <div data-bgm-local ${local ? "" : "hidden"}><input type="file" accept=".mp3,audio/mpeg" data-bgm-file aria-label="选择本地 MP3"><input type="hidden" data-bgm-path value="${local ? esc(bgm.src) : ""}"></div>
      <div data-bgm-remote ${bgm && !local ? "" : "hidden"}><input type="url" data-bgm-url aria-label="BGM 音频直链" placeholder="https://… 直接返回音频的链接" value="${bgm && !local ? esc(bgm.src) : ""}"></div>
      <input type="text" maxlength="200" data-bgm-title aria-label="歌曲名" placeholder="歌曲名" value="${esc(bgm?.title || "")}" ${bgm ? "" : "hidden"}>
      <input type="text" maxlength="200" data-bgm-artist aria-label="演唱者" placeholder="演唱者（可选）" value="${esc(bgm?.artist || "")}" ${bgm ? "" : "hidden"}>
      <audio controls preload="none" data-bgm-preview ${bgm ? `src="${esc(bgm.src)}"` : "hidden"}></audio>
      <div class="tip" data-bgm-note>本地 MP3 最多 30 MB，导入项目后可离线播放；在线请用 HTTPS 音频直链，音乐平台分享页不能直接播放。选择后仍需保存。</div></div>`;
  }
  function editor(root, prefix) { return root.querySelector(`[data-bgm-editor="${prefix}"]`); }
  function bind(root, prefix, notify) {
    const box = editor(root, prefix); if (!box) return;
    const get = selector => box.querySelector(selector), preview = get('[data-bgm-preview]');
    function update() {
      const mode = get('[data-bgm-mode]').value;
      get('[data-bgm-local]').hidden = mode !== "local"; get('[data-bgm-remote]').hidden = mode !== "remote";
      get('[data-bgm-title]').hidden = mode === "none"; get('[data-bgm-artist]').hidden = mode === "none";
      const src = mode === "local" ? get('[data-bgm-path]').value : mode === "remote" ? ArchiveV2.audio.source(get('[data-bgm-url]').value.trim()) : "";
      preview.pause(); preview.hidden = !src;
      if (src) preview.src = src; else preview.removeAttribute('src');
      preview.load();
    }
      get('[data-bgm-mode]').onchange = update;
    get('[data-bgm-url]').onchange = update;
    preview.volume = .2;
    preview.onplay = () => document.dispatchEvent(new Event('archive-audio-preview'));
    preview.onerror = () => { if (preview.getAttribute('src')) get('[data-bgm-note]').textContent = "试听失败，请检查文件或音频直链。"; };
    get('[data-bgm-file]').onchange = () => {
      const file = get('[data-bgm-file]').files[0]; if (!file) return;
      const input = get('[data-bgm-file]'); input.disabled = true;
      const task = (async () => {
        if (!/\.mp3$/i.test(file.name) || file.size > 30 * 1024 * 1024) throw Error('请选择 30 MB 以内的 MP3 文件');
        get('[data-bgm-note]').textContent = '正在导入音乐…';
        const response = await fetch('/api/audio', {method:'POST',headers:{'Content-Type':'audio/mpeg','X-Audio-Name':encodeURIComponent(file.name.replace(/\.mp3$/i,''))},body:file});
        const result = await response.json(); if (!response.ok || !result.ok) throw Error(result.error || '音乐导入失败');
        get('[data-bgm-path]').value = result.bgm.src;
        get('[data-bgm-title]').value = result.bgm.title;
        get('[data-bgm-artist]').value = result.bgm.artist || '';
        get('[data-bgm-note]').textContent = '音乐已导入，保存后绑定；原文件可移动，项目中的副本保留。'; update();
      })();
      pending.set(box, task);
      task.catch(error => { get('[data-bgm-note]').textContent = error.message; notify(error.message, true); }).finally(() => { input.disabled = false; });
    };
  }
  async function read(root, prefix) {
    const box = editor(root, prefix); if (!box) return null;
    const mode = box.querySelector('[data-bgm-mode]').value;
    if (mode === 'none') return null;
    if (mode === 'local') await pending.get(box);
    const raw = box.querySelector(mode === 'local' ? '[data-bgm-path]' : '[data-bgm-url]').value.trim();
    const src = ArchiveV2.audio.source(raw);
    if (!src) throw Error(mode === 'local' ? '请先选择本地 MP3 文件' : '请填写有效的 HTTPS 音频直链');
    return {src,title:box.querySelector('[data-bgm-title]').value.trim() || '背景音乐',artist:box.querySelector('[data-bgm-artist]').value.trim()};
  }
  function stop(root) { root.querySelectorAll('[data-bgm-preview]').forEach(audio => audio.pause()); }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, {bgmEditor:{form,bind,read,stop}});
})();
