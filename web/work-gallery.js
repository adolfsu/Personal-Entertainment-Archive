(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[char]);
  const localImage = /^\/covers\/[a-zA-Z0-9_-]+\.(?:png|jpe?g|webp|gif)$/;
  const limit = 20;

  function collect(work, records) {
    const backgrounds = ArchiveV2.backgroundEditor.images(work).map(url => ({url, label:"沉浸大图"}));
    const byRecord = new Map();
    const entries = backgrounds.slice();
    for (const record of records) {
      const urls = Array.isArray(record.imageUrls)
        ? [...new Set(record.imageUrls.filter(url => typeof url === "string" && localImage.test(url)))]
        : [];
      const indexes = urls.map(url => entries.push({
        url, label: record.date ? "经历配图 · " + record.date : "经历配图",
      }) - 1);
      if (indexes.length) byRecord.set(record, indexes);
    }
    const thumb = (index) => {
      const { url, label } = entries[index];
      return `<button type="button" class="im-gallery-thumb" data-gallery-index="${index}" aria-label="查看${esc(label)}（${index + 1}）">
        <span class="im-gallery-fallback">图片不可用</span><img src="${esc(url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer"></button>`;
    };
    const grid = (indexes, extra = "") => `<div class="im-gallery-grid ${extra}">${indexes.map(thumb).join("")}</div>`;
    const group = (title, indexes) => indexes.length ? `<h3>${title}</h3>${grid(indexes)}` : "";
    const indexes = entries.map((_, index) => index);
    return {
      entries,
      has: record => byRecord.has(record),
      forRecord: record => byRecord.has(record) ? grid(byRecord.get(record), "im-record-images") : "",
      section: () => `<section class="im-section im-gallery" data-im-gallery tabindex="-1" aria-labelledby="imGalleryTitle"><h2 id="imGalleryTitle">画廊 <small>${entries.length} 张</small></h2>
        ${entries.length ? group("沉浸大图", indexes.slice(0, backgrounds.length)) + group("经历配图", indexes.slice(backgrounds.length)) : '<p class="im-muted">暂无图片。</p>'}
      </section>`,
    };
  }

  const editorMarkup = `<div class="im-experience-images"><div class="im-experience-image-tools">
    <button type="button" class="im-button" data-im-choose-images>上传图片</button>
    <button type="button" class="im-button" data-im-paste-images title="也可在经历输入区直接粘贴">粘贴图片</button>
    <span data-im-image-count hidden></span>
    <input type="file" data-im-image-files accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden>
    </div><div class="im-gallery-grid im-record-images" data-im-image-draft></div><p class="im-muted" data-im-image-status role="status"></p></div>`;

  function localDate() {
    const now = new Date();
    return [now.getFullYear(), now.getMonth() + 1, now.getDate()].map(value => String(value).padStart(2, "0")).join("-");
  }

  function create(root, notify) {
    const drafts = new Map();
    let mountState = null, dialog = null;
    function draw(draft) {
      if (mountState?.draft !== draft || !mountState.form.isConnected) return;
      const { form } = mountState;
      const busy = draft.uploading || draft.saving;
      form.querySelector("[data-im-image-status]").textContent = draft.message;
      const count = form.querySelector("[data-im-image-count]");
      count.hidden = !draft.urls.length;
      count.textContent = `${draft.urls.length} / ${limit}`;
      for (const button of form.querySelectorAll("[data-im-choose-images],[data-im-paste-images],[data-im-action='add-experience']")) {
        button.disabled = busy;
      }
      const preview = form.querySelector("[data-im-image-draft]");
      const focused = document.activeElement?.dataset.imRemoveImage;
      preview.innerHTML = draft.urls.map((url, i) => `<div class="im-draft-thumb">
        <img src="${esc(url)}" alt="待添加图片 ${i + 1}" decoding="async">
        <button type="button" data-im-remove-image="${i}" aria-label="移除第 ${i + 1} 张图片" title="移除图片" ${busy ? "disabled" : ""}>×</button>
      </div>`).join("");
      if (focused !== undefined) (preview.children[Math.min(Number(focused), preview.children.length - 1)]?.querySelector("button") || form.querySelector("[data-im-choose-images]")).focus({preventScroll:true});
    }

    async function upload(draft, getFiles) {
      if (draft.uploading || draft.saving) return;
      draft.uploading = true;
      draft.message = "";
      draw(draft);
      const errors = new Set();
      try {
        const files = await getFiles();
        if (!files.length) draft.message = "剪贴板中没有可用图片。";
        for (const file of files) {
          if (draft.urls.length >= limit) { errors.add("每条经历最多添加 20 张图片。"); break; }
          draft.message = "正在保存图片…";
          draw(draft);
          try {
            const { url } = await ArchiveV2.backgroundEditor.uploadImage(file);
            if (!draft.urls.includes(url)) draft.urls.push(url);
          } catch (error) { errors.add(error.message || "图片保存失败，请重试。"); }
        }
      } catch (_) {
        errors.add("无法读取剪贴板。可以在经历输入区直接粘贴，或选择本地图片。");
      } finally {
        if (errors.size) draft.message = [...errors].join(" ");
        else if (draft.message === "正在保存图片…") draft.message = "";
        draft.uploading = false;
        draw(draft);
      }
    }

    function mountViewer(entries) {
      const window = root.querySelector(".im-window");
      window.insertAdjacentHTML("beforeend", `<dialog class="im-image-viewer" aria-labelledby="imImageTitle"><div class="im-image-panel">
        <header><div><h2 id="imImageTitle">画廊</h2><span data-im-image-position></span></div><button type="button" class="im-button" data-image-close aria-label="关闭大图" title="关闭大图" autofocus>×</button></header>
        <div class="im-image-stage"><button type="button" class="im-button" data-image-prev aria-label="上一张图片" title="上一张">‹</button>
          <figure><img alt="" referrerpolicy="no-referrer"><figcaption hidden>无法加载图片</figcaption></figure>
          <button type="button" class="im-button" data-image-next aria-label="下一张图片" title="下一张">›</button></div>
      </div></dialog>`);
      dialog = window.querySelector(".im-image-viewer");
      const current = dialog, image = current.querySelector("img"), title = current.querySelector("h2");
      const previous = current.querySelector("[data-image-prev]"), next = current.querySelector("[data-image-next]");
      const close = current.querySelector("[data-image-close]"), caption = current.querySelector("figcaption");
      let index = 0;
      function show(position) {
        const item = entries[position];
        if (!item) return;
        index = position;
        image.hidden = caption.hidden = true;
        image.alt = item.label;
        image.src = item.url;
        if (image.complete && image.naturalWidth) image.hidden = false;
        title.textContent = item.label;
        current.querySelector("[data-im-image-position]").textContent = `${position + 1} / ${entries.length}`;
        previous.disabled = position === 0;
        next.disabled = position === entries.length - 1;
        if (document.activeElement?.disabled) close.focus();
      }
      image.onload = () => { image.hidden = false; caption.hidden = true; };
      image.onerror = () => { image.hidden = true; caption.hidden = false; };
      previous.onclick = () => show(index - 1);
      next.onclick = () => show(index + 1);
      close.onclick = () => current.close();
      current.onclick = event => { if (event.target === current) current.close(); };
      current.onkeydown = event => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        show(index + (event.key === "ArrowLeft" ? -1 : 1));
      };
      root.querySelectorAll("[data-gallery-index]").forEach(button => {
        const thumb = button.querySelector("img");
        const unavailable = () => { thumb.hidden = true; };
        thumb.addEventListener("error", unavailable, {once:true});
        if (thumb.complete && !thumb.naturalWidth) unavailable();
        button.onclick = () => {
          show(Number(button.dataset.galleryIndex));
          current.showModal();
        };
      });
    }

    function mount(work, records) {
      mountViewer(collect(work, records).entries);
      const form = root.querySelector("[data-im-experience-form]");
      const fields = {date:form.querySelector("[data-im-experience-date]"), status:form.querySelector("[data-im-experience-status]"), content:form.querySelector("[data-im-experience-content]")};
      if (!drafts.has(work.id)) drafts.set(work.id, {
        date:localDate(), status:fields.status.value, content:"", urls:[], message:"", uploading:false, saving:false,
      });
      const draft = drafts.get(work.id);
      mountState = { form, fields, draft, id:work.id };
      for (const [key, field] of Object.entries(fields)) {
        field.value = draft[key];
        field.oninput = () => { draft[key] = field.value; };
      }
      const input = form.querySelector("[data-im-image-files]");
      form.querySelector("[data-im-choose-images]").onclick = () => input.click();
      input.onchange = () => {
        const files = Array.from(input.files);
        input.value = "";
        if (files.length) upload(draft, () => files);
      };
      form.querySelector("[data-im-paste-images]").onclick = () => upload(draft, ArchiveV2.backgroundEditor.clipboardFiles);
      form.onpaste = event => {
        const files = ArchiveV2.backgroundEditor.pastedFiles(event);
        if (!files.length) return;
        event.preventDefault();
        upload(draft, () => files);
      };
      form.querySelector("[data-im-image-draft]").onclick = event => {
        const remove = event.target.closest("[data-im-remove-image]");
        if (!remove || draft.uploading || draft.saving) return;
        draft.urls.splice(Number(remove.dataset.imRemoveImage), 1);
        draft.message = "";
        draw(draft);
      };
      draw(draft);
    }

    async function save(id, commit) {
      const draft = drafts.get(id);
      if (!draft || draft.uploading || draft.saving) return;
      for (const [key, field] of Object.entries(mountState.fields)) draft[key] = field.value;
      draft.saving = true;
      draw(draft);
      try {
        if (await commit({ date:draft.date, status:draft.status, content:draft.content, imageUrls:draft.urls.slice() })) {
          draft.content = draft.message = "";
          draft.urls = [];
          if (mountState?.draft === draft) mountState.fields.content.value = "";
        }
      } catch (error) { notify(error.message || "经历添加失败", true); }
      finally { draft.saving = false; draw(draft); }
    }

    function closeViewer() { if (dialog?.open) dialog.close(); }
    return {
      mount, save, closeViewer,
      viewer: () => dialog?.open ? dialog : null,
      reset() { closeViewer(); dialog = mountState = null; drafts.clear(); },
    };
  }

  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, {gallery:{collect, create, editorMarkup}});
})();
