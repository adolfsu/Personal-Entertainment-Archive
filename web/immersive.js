/* 单作品沉浸展示：容器、导航与历史；写入始终交给原有完整详情。 */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[char]);
  const progressKeys = /^(进度|阅读进度|观看进度|游玩进度|当前进度|当前集数|当前章节|完成进度|已读章节|已看集数)$/;

  function workContent(work, labels) {
    const rating = work.rating == null ? "未评分" : Number(work.rating).toFixed(1);
    const creators = (work.creators || []).slice(0, 3).map(person => `${person.role} ${person.name}`).join(" · ");
    const experiences = (work.experiences || []).slice(-3).reverse();
    const progress = (work.userFields || []).filter(field => progressKeys.test(field.key)).slice(0, 3);
    const summary = work.summary || "暂未填写作品简介。";
    const intro = summary.length > 260 ? `${esc(summary.slice(0, 260))}…<details class="im-summary-more"><summary>展开完整简介</summary><p>${esc(summary)}</p></details>` : esc(summary);
    return `<div class="im-art">
      <div class="im-poster"><div class="im-poster-empty"><span>${esc(labels.category)}</span><small>暂无封面</small></div>
        ${work.coverUrl ? `<img src="${esc(work.coverUrl)}" alt="《${esc(work.title)}》封面" decoding="async" data-im-poster>` : ""}</div>
      ${labels.series ? `<p class="im-series-caption"><span>所属系列</span>${esc(labels.series)}</p>` : ""}
    </div>
    <div class="im-copy">
      <p class="im-eyebrow">个人典藏 <span>／</span> ${esc([labels.category, work.year].filter(Boolean).join(" · "))}</p>
      <h1 id="immersiveTitle" class="im-title">${esc(work.title)}</h1>
      ${work.originalTitle && work.originalTitle !== work.title ? `<p class="im-original">${esc(work.originalTitle)}</p>` : ""}
      ${creators ? `<p class="im-creators">${esc(creators)}</p>` : ""}
      <div class="im-personal"><div class="im-score"><span>个人评分</span><strong>${rating}</strong>${work.rating == null ? "" : "<small>/ 10</small>"}</div>
        <span class="im-status" data-status="${esc(work.status)}">${esc(labels.status)}</span></div>
      <section class="im-section"><h2>作品简介</h2><div class="im-synopsis">${intro}</div></section>
      <section class="im-section im-records"><h2>我的记录</h2>
        ${progress.length ? `<dl class="im-progress-fields">${progress.map(field => `<div><dt>${esc(field.key)}</dt><dd>${esc(field.value)}</dd></div>`).join("")}</dl>` : ""}
        ${experiences.length ? experiences.map(record => `<div class="im-record"><div class="im-record-meta"><time>${esc(record.date)}</time><span>${esc(labels.recordStatus(record.status))}</span>${record.id === work.currentExperienceId ? "<span>当前状态</span>" : ""}</div><p>${esc(record.content || "已记录此状态")}</p></div>`).join("") : "<p class=\"im-muted\">还没有个人经历记录。</p>"}
      </section>
    </div>`;
  }

  function create({ root, getWork, getWorks, getSeries = () => null, getLabels, getBackgroundSettings = () => ({}), openDetails, openSeriesDetails, closeDetails, captureOrigin, restoreOrigin, mainRoots, notify = () => {} }) {
    const loader = ArchiveV2.backgrounds.createLoader();
    const seriesBackgrounds = ArchiveV2.seriesImmersive.createBackgrounds();
    const music = ArchiveV2.audioPlayer;
    let session = null, lastSession = null, detail = false, origin = null;
    let inertBefore = [], overflowBefore = "", scrollRestorationBefore = "auto", transitionPending = false;
    const historyState = () => history.state?.archiveImmersive;
    const ownsHistory = () => session && historyState()?.token === session.token;
    let backgroundTone = "soft";
    try { if (localStorage.getItem("grdag_immersive_brightness") === "bright") backgroundTone = "bright"; } catch (_) { /* 存储不可用时本次浏览仍可切换。 */ }

    function viewControls() {
      const bright = backgroundTone === "bright";
      return `<div class="im-toolbar-controls"><button type="button" class="im-button im-brightness" data-im-action="brightness" aria-label="明亮背景" aria-pressed="${bright}" title="背景：${bright ? "明亮，点击切换为柔和" : "柔和，点击切换为明亮"}"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/></svg><span>${bright ? "明亮" : "柔和"}</span></button>
        <button type="button" class="im-button im-music-toggle" data-im-action="music" aria-label="打开音乐播放列表" title="音乐播放列表"><span aria-hidden="true">♫</span><span class="im-music-label">音乐</span></button>
        <div class="im-surfaces" role="group" aria-label="沉浸呈现方式"><button type="button" class="im-button" data-im-action="overlay" aria-pressed="${session.surface === "overlay"}">浮层</button><button type="button" class="im-button" data-im-action="fullscreen" aria-pressed="${session.surface === "fullscreen"}">全屏展厅</button></div></div>`;
    }
    function mountMusic() {
      const series = session.seriesId ? getSeries(session.seriesId) : null;
      music.setTarget(ArchiveV2.audio.resolve(getWork(session.currentId), series, session.page === 'series'));
    }
    function toggleBackgroundTone() {
      backgroundTone = backgroundTone === "bright" ? "soft" : "bright";
      root.dataset.backgroundTone = backgroundTone;
      const button = root.querySelector('[data-im-action="brightness"]'), bright = backgroundTone === "bright";
      button.setAttribute("aria-pressed", String(bright));
      button.title = `背景：${bright ? "明亮，点击切换为柔和" : "柔和，点击切换为明亮"}`;
      button.querySelector("span").textContent = bright ? "明亮" : "柔和";
      try { localStorage.setItem("grdag_immersive_brightness", backgroundTone); } catch (_) { /* 偏好写入失败不影响当前显示。 */ }
      notify(bright ? "明亮背景" : "柔和背景");
    }

    function lock() {
      overflowBefore = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      scrollRestorationBefore = history.scrollRestoration;
      history.scrollRestoration = "manual";
      inertBefore = mainRoots().map(node => [node, node.inert]);
      inertBefore.forEach(([node]) => { node.inert = true; });
    }
    function writeHistory(push = false) {
      if (!session) return;
      const state = { ...(history.state && typeof history.state === "object" ? history.state : {}),
        archiveImmersive: { token: session.token, currentId: session.currentId, seriesId: session.seriesId, page: session.page, surface: session.surface, detail } };
      try { history[push ? "pushState" : "replaceState"](state, ""); } catch (_) { /* 显式导航仍可使用。 */ }
    }
    function end() {
      if (!session) return;
      if (detail) closeDetails();
      lastSession = { ...session, ids: session.ids.slice() };
      session = null; detail = false; transitionPending = false; loader.cancel(); seriesBackgrounds.cancel();
      music.close();
      root.hidden = true; root.innerHTML = "";
      inertBefore.forEach(([node, value]) => { node.inert = value; }); inertBefore = [];
      document.body.style.overflow = overflowBefore;
      history.scrollRestoration = scrollRestorationBefore;
      restoreOrigin(origin);
    }
    function reconcile() {
      if (session?.seriesId) {
        const series = getSeries(session.seriesId);
        if (!series) return false;
        session.ids = ArchiveV2.seriesImmersive.members(series, getWork).map(work => work.id);
        if (!session.ids.includes(session.currentId)) { session.page = "series"; session.currentId = null; }
        return true;
      }
      return session && ArchiveV2.browse.reconcile(session, getWorks().map(work => work.id));
    }
    function paint(scene, image, kind) {
      if (!scene.isConnected) return;
      scene.dataset.background = kind; root.dataset.background = kind;
      if (!image) { scene.replaceChildren(); return; }
      if ([...scene.children].some(node => node.classList.contains("is-visible") && node.src === image.src)) return;
      const previous = [...scene.children]; scene.append(image); scene.getBoundingClientRect(); image.classList.add("is-visible");
      previous.forEach(node => node.classList.remove("is-visible"));
      const removePrevious = () => previous.forEach(node => node.remove());
      image.addEventListener("transitionend", removePrevious, {once:true}); setTimeout(removePrevious, 1500);
    }
    function bindPosters() {
      root.querySelectorAll("[data-im-poster]").forEach(poster => {
        poster.onerror = () => { poster.hidden = true; };
        if (poster.complete && !poster.naturalWidth) poster.hidden = true;
      });
    }
    function focus(action, memberId) {
      requestAnimationFrame(() => {
        if (!session || detail) return;
        const target = memberId ? [...root.querySelectorAll("[data-im-member]")].find(node => node.dataset.imMember === memberId) : root.querySelector(`[data-im-action="${action}"]:not([disabled])`);
        target?.focus({preventScroll:true});
      });
    }
    function renderSeries(focusAction) {
      const series = getSeries(session.seriesId), works = ArchiveV2.seriesImmersive.members(series, getWork);
      session.category ||= "all"; session.query ||= "";
      if (session.category !== "all" && !works.some(work => work.category === session.category)) session.category = "all";
      root.dataset.view = "series";
      root.innerHTML = `<div class="im-window"><div class="im-scene" aria-hidden="true"></div><div class="im-shade" aria-hidden="true"></div>
        <header class="im-toolbar"><div class="im-toolbar-start"><button type="button" class="im-button im-return" data-im-action="close">← 返回陈列</button></div><div class="im-location"><span>系列展厅</span><strong>${works.length} 件典藏</strong></div>${viewControls()}</header>
        <div class="im-scroll ims-scroll">${ArchiveV2.seriesImmersive.content(series, works, getLabels, session)}</div><button type="button" class="im-details-corner" data-im-action="details" aria-label="查看系列完整详情">系列详情 ↗</button></div>`;
      bindPosters();
      mountMusic();
      const scene = root.querySelector(".im-scene");
      seriesBackgrounds.start(series, works, (image, kind) => paint(scene, image, kind), getBackgroundSettings(), session.sharedUrl);
      root.querySelector(".im-scroll").scrollTop = session.seriesScroll || 0;
      if (session.focusMember) { focus(null, session.focusMember); session.focusMember = null; }
      else focus(focusAction);
    }
    function rememberSeries() {
      session.seriesScroll = root.querySelector(".im-scroll")?.scrollTop || 0;
      session.sharedUrl = seriesBackgrounds.current().sharedUrl;
    }
    function enterMember(id) {
      if (!session?.seriesId || !session.ids.includes(id) || !getWork(id)) return;
      rememberSeries(); session.startUrl = seriesBackgrounds.current().visibleUrl;
      session.page = "work"; session.currentId = id; session.contentScroll = 0;
      render(); writeHistory(true);
    }
    function backToSeries() {
      if (!session?.seriesId || session.page !== "work" || transitionPending) return;
      session.focusMember = session.currentId;
      if (ownsHistory()) { transitionPending = true; history.back(); }
      else { session.page = "series"; render(); writeHistory(); }
    }
    function render(focusAction = "close") {
      if (!reconcile()) { end(); return; }
      if (detail) return;
      loader.cancel(); seriesBackgrounds.cancel();
      root.dataset.surface = session.surface; root.dataset.background = "default"; root.hidden = false;
      root.dataset.backgroundTone = backgroundTone;
      if (session.page === "series") { renderSeries(focusAction); return; }
      root.dataset.view = "work";
      const work = getWork(session.currentId);
      const labels = getLabels(work);
      const index = session.ids.indexOf(session.currentId);
      const previous = getWork(ArchiveV2.browse.adjacent(session, -1));
      const next = getWork(ArchiveV2.browse.adjacent(session, 1));
      const source = session.seriesId ? getSeries(session.seriesId).name : session.source || "当前筛选结果";
      root.dataset.surface = session.surface;
      root.hidden = false;
      root.innerHTML = `<div class="im-window">
        <div class="im-scene" aria-hidden="true" data-background="default"></div><div class="im-shade" aria-hidden="true"></div>
        <header class="im-toolbar"><div class="im-toolbar-start"><button type="button" class="im-button im-return" data-im-action="close">${session.seriesId ? `← 返回系列<span class="im-return-name"> · ${esc(source)}</span>` : "← 返回陈列"}</button><button type="button" class="im-catalog-toggle" data-im-action="catalog" aria-expanded="false" aria-controls="imCatalog">☷ <span>作品目录</span></button></div>
          <div class="im-location" aria-live="polite"><span>${esc(source)}</span><strong>${index + 1} <i>/</i> ${session.ids.length}</strong></div>
          ${viewControls()}</header>
        <div class="im-scroll"><article class="im-card">${workContent(work, labels)}</article></div>
        <button type="button" class="im-side-arrow im-side-prev" data-im-action="previous" ${previous ? "" : "disabled"} aria-label="前一件">‹</button><button type="button" class="im-side-arrow im-side-next" data-im-action="next" ${next ? "" : "disabled"} aria-label="后一件">›</button>
        <button type="button" class="im-details-corner" data-im-action="details" aria-label="查看完整详情">详情 ↗</button>
        <aside id="imCatalog" class="im-catalog" hidden><div class="im-catalog-head"><strong>作品目录</strong><button type="button" data-im-action="catalog-close" aria-label="关闭目录">×</button></div><input type="search" data-im-catalog-search placeholder="搜索作品" aria-label="搜索作品"><div class="im-catalog-list"></div></aside>
      </div>`;
      bindPosters();
      mountMusic();
      const scene = root.querySelector(".im-scene");
      const catalogWorks = session.seriesId ? session.ids.map(getWork).filter(Boolean) : getWorks();
      const grouped = catalogWorks.reduce((map, item) => { const key = getLabels(item).category || "其它"; (map[key] ||= []).push(item); return map; }, {});
      root.querySelector(".im-catalog-list").innerHTML = Object.entries(grouped).map(([key, items]) => `<details class="im-catalog-group"><summary>${esc(key)} <small>${items.length}</small></summary><div>${items.map(item => `<button type="button" class="im-catalog-item${item.id === session.currentId ? " is-current" : ""}" data-im-action="jump" data-im-jump="${esc(item.id)}">${esc(item.title || "未命名作品")}</button>`).join("")}</div></details>`).join("");
      loader.load(work, (image, kind) => paint(scene, image, kind), getBackgroundSettings(), {startUrl:session.startUrl});
      session.startUrl = "";
      requestAnimationFrame(() => {
        if (!session || detail) return;
        const target = root.querySelector(`[data-im-action="${focusAction}"]:not([disabled])`) || root.querySelector('[data-im-action="close"]');
        target?.focus({ preventScroll: true });
      });
    }
    function showDetails() {
      if (!session || detail) return;
      if (session.page === "series") rememberSeries();
      else if (!getWork(session.currentId)) return;
      session.contentScroll = root.querySelector(".im-scroll")?.scrollTop || 0;
      detail = true; root.hidden = true; loader.cancel(); seriesBackgrounds.cancel();
      writeHistory(true); openEntityDetails();
    }
    function openEntityDetails() { if (session.page === "series") openSeriesDetails(session.seriesId); else openDetails(session.currentId); }
    function showBrowse() {
      closeDetails(); detail = false; render("details");
      const scroll = root.querySelector(".im-scroll");
      if (scroll) scroll.scrollTop = session?.contentScroll || 0;
      writeHistory();
    }
    function navigate(offset) {
      if (!session || detail || transitionPending || session.page === "series") return;
      const target = ArchiveV2.browse.adjacent(session, offset);
      if (!target) return;
      session.currentId = target; session.contentScroll = 0;
      render(offset > 0 ? "next" : "previous"); writeHistory();
    }
    function close() {
      if (!session || transitionPending) return;
      if (!detail && session.seriesId && session.page === "work") { backToSeries(); return; }
      if (!detail && session.page === "series") rememberSeries();
      if (ownsHistory()) { transitionPending = true; history.go(detail ? -2 : -1); }
      else end();
    }
    function returnFromDetails() {
      if (!session || !detail || transitionPending) return;
      if (ownsHistory() && historyState().detail) { transitionPending = true; history.back(); }
      else showBrowse();
    }
    root.onclick = event => {
      if (event.target === root && session?.surface === "overlay") { close(); return; }
      const action = event.target.closest("[data-im-action]")?.dataset.imAction;
      if (!action || transitionPending) return;
      if (action === "close") close();
      else if (action === "brightness") toggleBackgroundTone();
      else if (action === "music") document.dispatchEvent(new Event('archive-music-open'));
      else if (action === "previous") navigate(-1);
      else if (action === "next") navigate(1);
      else if (action === "details") showDetails();
      else if (action === "member") enterMember(event.target.closest("[data-im-member]").dataset.imMember);
      else if (action === "category") {
        session.category = event.target.closest("[data-im-category]").dataset.imCategory;
        root.querySelectorAll("[data-im-category]").forEach(button => button.setAttribute("aria-pressed", button.dataset.imCategory === session.category));
        filterMembers();
      }
      else if (action === "catalog" || action === "catalog-close") {
        const panel = root.querySelector(".im-catalog");
        const open = action === "catalog" && panel.hidden;
        panel.style.setProperty("--im-catalog-top", `${root.querySelector(".im-toolbar").offsetHeight + 4}px`);
        panel.hidden = !open;
        root.querySelector(".im-catalog-toggle")?.setAttribute("aria-expanded", open);
        root.querySelector(open ? "[data-im-catalog-search]" : ".im-catalog-toggle")?.focus();
      }
      else if (action === "jump") {
        const id = event.target.closest("[data-im-jump]").dataset.imJump;
        if (!getWork(id)) return;
        if (!session.ids.includes(id)) { session.ids = getWorks().map(work => work.id); session.source = "全部作品"; }
        session.currentId = id; session.contentScroll = 0; render("catalog"); writeHistory();
      }
      else if (session && ["overlay", "fullscreen"].includes(action)) {
        session.surface = action; root.dataset.surface = action;
        root.querySelectorAll('.im-surfaces button').forEach(button => button.setAttribute("aria-pressed", button.dataset.imAction === action));
        writeHistory();
      }
    };
    root.oninput = event => {
      if (event.target.dataset.imMusic === 'volume') { music.setVolume(Number(event.target.value) / 100); return; }
      if (event.target.matches("[data-im-series-search]")) { session.query = event.target.value; filterMembers(); return; }
      if (!event.target.matches("[data-im-catalog-search]")) return;
      const query = event.target.value.trim().toLocaleLowerCase();
      root.querySelectorAll(".im-catalog-item").forEach(item => { item.hidden = query && !item.textContent.toLocaleLowerCase().includes(query); });
      root.querySelectorAll(".im-catalog-group").forEach(group => { group.hidden = query && ![...group.querySelectorAll(".im-catalog-item")].some(item => !item.hidden); if (query) group.open = true; });
    };
    root.onchange = event => {
      const field = event.target.dataset.imMusic;
      if (field === 'enabled') music.setEnabled(event.target.checked);
      else if (field === 'loop') music.setLoop(event.target.checked);
      else if (field === 'pauseHidden') music.setPauseHidden(event.target.checked);
    };
    window.addEventListener('pagehide', () => music.destroy());
    function filterMembers() {
      if (session?.page !== "series") return;
      const works = ArchiveV2.seriesImmersive.members(getSeries(session.seriesId), getWork);
      const selected = ArchiveV2.seriesImmersive.select(works, session.category, session.query);
      root.querySelector(".ims-grid").innerHTML = selected.map(work => ArchiveV2.seriesImmersive.memberCard(work, getLabels(work))).join("");
      root.querySelector(".ims-empty").hidden = !!selected.length;
      seriesBackgrounds.resume(); bindPosters();
    }
    root.onpointerover = event => {
      if (event.pointerType === "touch" || session?.page !== "series") return;
      const card = event.target.closest("[data-im-member]");
      if (card && !card.contains(event.relatedTarget)) seriesBackgrounds.preview(getWork(card.dataset.imMember));
    };
    root.onpointerout = event => {
      if (event.pointerType === "touch" || session?.page !== "series") return;
      const card = event.target.closest("[data-im-member]");
      if (card && !card.contains(event.relatedTarget)) seriesBackgrounds.resume();
    };
    root.onfocusin = event => {
      if (session?.page !== "series" || !event.target.matches(":focus-visible")) return;
      const card = event.target.closest("[data-im-member]");
      if (card) seriesBackgrounds.preview(getWork(card.dataset.imMember));
    };
    root.onfocusout = event => { if (session?.page === "series" && event.target.closest("[data-im-member]")) seriesBackgrounds.resume(); };
    root.onkeydown = event => {
      const catalog = root.querySelector(".im-catalog");
      if (event.key === "Escape" && catalog && !catalog.hidden) {
        event.preventDefault(); event.stopPropagation(); catalog.hidden = true;
        root.querySelector(".im-catalog-toggle")?.setAttribute("aria-expanded", false);
        root.querySelector(".im-catalog-toggle")?.focus(); return;
      }
      if (event.target.closest(".im-catalog")) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest("input,textarea,select,[contenteditable=true],summary")) return;
      if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); event.stopPropagation(); navigate(event.key === "ArrowLeft" ? -1 : 1); }
    };
    window.addEventListener("popstate", event => {
      transitionPending = false;
      const state = event.state?.archiveImmersive;
      const remembered = session || lastSession;
      if (!state || state.token !== remembered?.token) { if (session) end(); return; }
      if (!session) { session = { ...lastSession, ids: lastSession.ids.slice() }; lock(); }
      session.currentId = state.currentId;
      session.page = state.page;
      session.surface = state.surface === "fullscreen" ? "fullscreen" : "overlay";
      if (!reconcile()) { end(); return; }
      if (state.detail) {
        if (!detail) { detail = true; root.hidden = true; loader.cancel(); seriesBackgrounds.cancel(); openEntityDetails(); }
      } else if (detail) showBrowse();
      else render();
    });
    return {
      open(ids, currentId, surface = "overlay", source = "当前筛选结果") {
        if (session) return;
        session = ArchiveV2.browse.create(ids, currentId, surface);
        if (!session || !getWork(currentId)) { session = null; return; }
        session.token = `${Date.now()}-${Math.random().toString(36).slice(2)}`; session.source = source;
        origin = captureOrigin(currentId); detail = false; lock(); render(); writeHistory(true);
      },
      openSeries(seriesId, surface = "overlay", matchedIds = null) {
        if (session || !getSeries(seriesId)) return;
        session = {seriesId, page:"series", currentId:null, ids:[], surface:surface === "fullscreen" ? "fullscreen" : "overlay", category:"all", query:"", matchedIds,
          token:`${Date.now()}-${Math.random().toString(36).slice(2)}`};
        origin = captureOrigin(seriesId); detail = false; lock(); render(); writeHistory(true);
      },
      close, returnFromDetails,
      playWork(id) {
        const work = getWork(id);
        if (!work) return false;
        if (!session) return false;
        if (!session.ids.includes(id)) session.ids = [...new Set([id, ...session.ids])];
        detail = false; session.page = "work"; session.currentId = id; session.contentScroll = 0;
        session.seriesId = null; session.source = "音乐播放列表";
        render(); writeHistory(); return true;
      },
      isOpen: () => !!session,
      isDetail: () => detail,
      overlayRoot: () => session && !detail ? root : null,
      refresh() {
        if (!session) return;
        if (!reconcile()) { close(); return; }
        if (!detail) {
          if (session.page === "series") rememberSeries();
          const action = document.activeElement?.dataset.imAction || "close";
          const scroll = root.querySelector(".im-scroll")?.scrollTop || 0;
          render(action); if (root.querySelector(".im-scroll")) root.querySelector(".im-scroll").scrollTop = scroll;
        }
      },
    };
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { immersive: { create, workContent } });
})();
