/* 统一作品浏览：沉浸视图承载完整详情，编辑与档案写入由应用层管理。 */
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

  function completeWorkContent(work, labels, seriesLinks = []) {
    const creators = work.creators || [];
    const experiences = (work.experiences || []).slice().sort((a, b) => (b.date || "").localeCompare(a.date || "") || (b.createdAt || "").localeCompare(a.createdAt || ""));
    const fields = [["年份", work.year], ["状态", labels.status], ["收藏于", (work.createdAt || "").replace("T", " ").slice(0, 16)],
      ["最近经历", work.lastExperienceAt], ["来源", work.source?.label || work.source?.name],
      ["来源评分", work.ratingRef == null ? "" : `${Number(work.ratingRef).toFixed(1)}${work.ratingMeta?.total ? ` · ${work.ratingMeta.total} 人` : ""}`]]
      .filter(([, value]) => value != null && value !== "");
    const tags = (work.tags || []).filter(Boolean), infobox = (work.infobox || []).filter(item => item?.key && item?.value != null);
    const userFields = (work.userFields || []).filter(item => item?.key && item?.value != null), history = work.ratingHistory || [];
    const statusOptions = Object.entries(labels.statusOptions || {}).filter(([key]) => key !== "not_started");
    const info = rows => rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join("");
    const sourceUrl = /^https?:\/\//i.test(work.source?.url || "") ? work.source.url : "";
    return `<div class="im-art"><div class="im-poster"><div class="im-poster-empty"><span>${esc(labels.category)}</span><small>暂无封面</small></div>${work.coverUrl ? `<img src="${esc(work.coverUrl)}" alt="《${esc(work.title)}》封面" decoding="async" data-im-poster>` : ""}</div>${labels.series ? `<p class="im-series-caption"><span>所属系列</span>${esc(labels.series)}</p>` : ""}</div>
      <div class="im-copy"><p class="im-eyebrow">个人典藏 <span>／</span> ${esc([labels.category, work.year].filter(Boolean).join(" · "))}</p>
        <h1 id="immersiveTitle" class="im-title">${esc(work.title)}</h1>${work.originalTitle && work.originalTitle !== work.title ? `<p class="im-original">${esc(work.originalTitle)}</p>` : ""}
        ${creators.length ? `<div class="im-creators">${creators.map(person => `<span>${esc(person.role)} ${esc(person.name)}</span>`).join("<i>·</i>")}</div>` : ""}
        <div class="im-personal"><div class="im-score"><span>个人评分</span><strong>${work.rating == null ? "未评分" : Number(work.rating).toFixed(1)}</strong>${work.rating == null ? "" : "<small>/ 10</small>"}</div><span class="im-status" data-status="${esc(work.status)}">${esc(labels.status)}</span></div>
        ${tags.length ? `<div class="im-tags">${tags.map(tag => `<span>${esc(tag)}</span>`).join("")}</div>` : ""}
        ${sourceUrl ? `<a class="im-source-link" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(work.source.label || work.source.name || "来源条目")} ↗</a>` : ""}
        <section class="im-section"><h2>作品简介</h2><div class="im-synopsis">${esc(work.summary || "暂未填写作品简介。")}</div></section>
        <section class="im-section"><h2>作品资料</h2><dl class="im-info-grid">${info(fields) || "<p class='im-muted'>暂无补充资料。</p>"}</dl></section>
        ${infobox.length ? `<section class="im-section"><h2>来源详情 <small>${infobox.length} 项</small></h2><dl class="im-info-grid">${info(infobox.map(item => [item.key, item.value]))}</dl></section>` : ""}
        ${seriesLinks.length ? `<section class="im-section"><h2>所属系列</h2><div class="im-series-links">${seriesLinks.map(link => `<button type="button" data-im-action="series" data-im-series="${esc(link.id)}">${esc(link.name)}<small>${esc(link.role || "")}</small></button>`).join("")}</div></section>` : ""}
        <section class="im-section im-records"><h2>我的经历 <small>${experiences.length}</small></h2>${experiences.length ? experiences.map(record => `<div class="im-record"><div class="im-record-meta"><time>${esc(record.date)}</time><span>${esc(labels.recordStatus(record.status))}</span>${record.id === work.currentExperienceId ? "<span>当前状态</span>" : ""}<button type="button" data-im-action="delete-experience" data-im-experience="${esc(record.id)}">删除</button></div><p>${esc(record.content || "已记录此状态")}</p></div>`).join("") : "<p class='im-muted'>还没有经历记录。</p>"}
          <div class="im-work-form"><label>添加经历 <input type="date" data-im-experience-date></label><select data-im-experience-status aria-label="经历状态">${statusOptions.map(([key, value]) => `<option value="${esc(key)}">${esc(value)}</option>`).join("")}</select><textarea data-im-experience-content rows="2" placeholder="进度或备注"></textarea><button type="button" class="im-button" data-im-action="add-experience">添加经历</button></div>
        </section>
        <section class="im-section"><h2>评分记录</h2><div class="im-work-form im-score-form"><label>个人评分 <input type="range" min="0" max="10" step="0.5" value="${work.rating == null ? 8 : Number(work.rating)}" data-im-score-range><output data-im-score-output>${work.rating == null ? "8.0" : Number(work.rating).toFixed(1)}</output></label><input type="text" data-im-score-reason placeholder="评分原因（可选）"><button type="button" class="im-button" data-im-action="save-rating">记录评分</button></div>
          ${history.length ? `<div class="im-rating-history">${history.slice().reverse().map(entry => `<div><time>${esc((entry.at || "").replace("T", " ").slice(0, 16))}</time><strong>${Number(entry.score).toFixed(1)}</strong><span>${esc(entry.reason || "")}</span></div>`).join("")}</div>` : "<p class='im-muted'>还没有评分变化记录。</p>"}
        </section>
        <section class="im-section"><h2>我的字段</h2>${userFields.length ? `<dl class="im-info-grid">${info(userFields.map(field => [field.key, field.value]))}</dl>` : "<p class='im-muted'>还没有自定义字段。</p>"}<div class="im-work-form im-user-field-form"><input type="text" data-im-user-field-key placeholder="字段名"><input type="text" data-im-user-field-value placeholder="内容"><button type="button" class="im-button" data-im-action="add-user-field">添加字段</button></div></section>
        <section class="im-section im-work-actions"><button type="button" class="im-button" data-im-action="delete-work">删除作品</button></section>
      </div>`;
  }

  function create({ root, getWork, getWorks, getSeries = () => null, getLabels, getSeriesLinks = () => [], getBackgroundSettings = () => ({}), openEdit = () => {}, onOpenSeries = () => {}, onManageSeries = () => {}, onRateWork = () => {}, onAddExperience = () => {}, onDeleteExperience = () => {}, onAddUserField = () => {}, onDeleteWork = () => {}, captureOrigin, restoreOrigin, mainRoots, notify = () => {} }) {
    const loader = ArchiveV2.backgrounds.createLoader();
    const seriesBackgrounds = ArchiveV2.seriesImmersive.createBackgrounds();
    const music = ArchiveV2.audioPlayer;
    let session = null, lastSession = null, origin = null, closeCompletion = null;
    let inertBefore = [], overflowBefore = "", scrollRestorationBefore = "auto", transitionPending = false;
    const historyState = () => history.state?.archiveImmersive;
    const ownsHistory = () => session && historyState()?.token === session.token;
    const catalogState = {query:"",category:"all",edge:0,edgeFrame:0,edgeAt:0};
    const entityIndex = () => {
      if (!session?.entities?.length) return 0;
      const current = session.entities.findIndex(item => item.id === (session.seriesId || session.currentId));
      return Math.max(0, current >= 0 ? current : session.entities.findIndex(item => item.id === session.navigationAnchor));
    };
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
    function queueItems() {
      if (!session) return [];
      if (session.entities?.length) return session.entities.map(item => item.type === "series"
        ? {type:"series",id:item.id,entity:getSeries(item.id)}
        : {type:"work",id:item.id,entity:getWork(item.id)}).filter(item=>item.entity);
      if(session.page==="series"&&session.seriesId)return ArchiveV2.seriesImmersive.members(getSeries(session.seriesId),getWork).map(work=>({type:"work",id:work.id,entity:work}));
      const ids=session.ids;
      return ids.map(id=>({type:"work",id,entity:getWork(id)})).filter(item=>item.entity);
    }
    function filmCategory(item) {
      if(item.type==="work")return getLabels(item.entity).category||"其它";
      const cats=[...new Set(ArchiveV2.seriesImmersive.members(item.entity,getWork).map(work=>getLabels(work).category||"其它"))];
      return cats.length===1?cats[0]:"系列";
    }
    function filmMatches(item) {
      const members=item.type==="series"?ArchiveV2.seriesImmersive.members(item.entity,getWork):[item.entity];
      const categoryOk=catalogState.category==="all"||(item.type==="series"?members.some(work=>(getLabels(work).category||"其它")===catalogState.category):filmCategory(item)===catalogState.category);
      const q=catalogState.query.trim().toLocaleLowerCase();
      const text=[item.entity.title,item.entity.name,...members.flatMap(work=>[work.title,work.originalTitle])].filter(Boolean).join(" ").toLocaleLowerCase();
      return categoryOk&&(!q||text.includes(q));
    }
    function renderFilmstrip() {
      const strip=root.querySelector(".im-filmstrip");if(!strip||!session)return;
      const items=queueItems(), currentId=session.page==="series"?(session.navigationAnchor||session.seriesId):session.currentId;
      const current=items.find(item=>item.id===currentId)||(session.page==="series"&&session.seriesId?items.find(item=>item.type==="work"&&(item.entity.primarySeriesId===session.seriesId||getSeries(session.seriesId)?.members?.some(member=>member.id===item.id))):null);
      const selectedId=current?.id||currentId;
      const cats=[...new Set(items.flatMap(item=>item.type==="series"?ArchiveV2.seriesImmersive.members(item.entity,getWork).map(work=>getLabels(work).category||"其它"):[filmCategory(item)]))];
      if(catalogState.category!=="all"&&!cats.includes(catalogState.category))catalogState.category="all";
      const visible=items.filter(item=>filmMatches(item)||item.id===selectedId);
      const options=[`<option value="all">全部分类</option>`,...cats.map(cat=>`<option value="${esc(cat)}" ${catalogState.category===cat?"selected":""}>${esc(cat)}</option>`)].join("");
      const cards=visible.map(item=>{const entity=item.entity,title=entity.title||entity.name||"未命名",cover=entity.coverUrl||(item.type==="series"?ArchiveV2.seriesImmersive.members(entity,getWork).find(work=>work.coverUrl)?.coverUrl:""),selected=item.id===selectedId,filterExempt=selected&&!filmMatches(item),index=items.findIndex(x=>x.id===item.id)+1;
        const kind=item.type==="series"?"系列":filmCategory(item);
        return `<button type="button" class="im-film-item${selected?" is-current":""}${filterExempt?" is-filter-exempt":""}" data-im-action="film-jump" data-im-film-id="${esc(item.id)}" data-im-film-type="${item.type}" aria-label="${esc(kind+" · "+title+(filterExempt?"，当前项，不符合筛选":""))}" aria-current="${selected?"true":"false"}" title="${esc(title+(filterExempt?" · 当前项，不符合筛选":""))}"><span class="im-film-cover">${cover?`<img src="${esc(cover)}" alt="" loading="lazy" decoding="async" data-im-poster>`:`<span class="im-film-placeholder">${esc(kind)}</span>`}<span class="im-film-index">${index}</span>${filterExempt?`<span class="im-film-filter-note">当前</span>`:""}</span><span class="im-film-title">${esc(title)}</span></button>`;
      }).join("");
      strip.innerHTML=`<div class="im-film-controls"><input type="search" data-im-film-search aria-label="搜索浏览队列" placeholder="搜索队列" value="${esc(catalogState.query)}"><select data-im-film-category aria-label="按分类筛选">${options}</select></div><div class="im-film-track" role="region" aria-label="当前浏览队列">${cards||`<span class="im-film-empty-state">没有匹配项</span>`}</div><div class="im-film-edge im-film-edge-left" data-film-edge="-1" aria-hidden="true"></div><div class="im-film-edge im-film-edge-right" data-film-edge="1" aria-hidden="true"></div>`;
      strip.dataset.count=String(items.length);strip.dataset.queueMode=items.some(item=>item.type==="series")?"entities":"works";
      requestAnimationFrame(()=>strip.querySelector(".im-film-item.is-current")?.scrollIntoView({block:"nearest",inline:"nearest"}));bindPosters();
    }
    function stopFilmEdge() { cancelAnimationFrame(catalogState.edgeFrame);catalogState.edgeFrame=0;catalogState.edge=0; }
    function runFilmEdge() {
      if(!catalogState.edge||globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches)return stopFilmEdge();
      const track=root.querySelector(".im-film-track");if(!track)return stopFilmEdge();
      const now=performance.now(),delta=Math.min(32,now-catalogState.edgeAt||16);catalogState.edgeAt=now;
      track.scrollLeft+=catalogState.edge*delta*.42;catalogState.edgeFrame=requestAnimationFrame(runFilmEdge);
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
        archiveImmersive: { token: session.token, currentId: session.currentId, seriesId: session.seriesId, page: session.page, surface: session.surface } };
      try { history[push ? "pushState" : "replaceState"](state, ""); } catch (_) { /* 显式导航仍可使用。 */ }
    }
    function end() {
      if (!session) return;
      lastSession = { ...session, ids: session.ids.slice() };
      session = null; transitionPending = false; loader.cancel(); seriesBackgrounds.cancel();
      stopFilmEdge();root.classList.remove("filmstrip-open");
      music.close();
      root.hidden = true; root.innerHTML = "";
      inertBefore.forEach(([node, value]) => { node.inert = value; }); inertBefore = [];
      document.body.style.overflow = overflowBefore;
      history.scrollRestoration = scrollRestorationBefore;
      restoreOrigin(origin);
      const completion = closeCompletion;
      closeCompletion = null;
      if (completion) requestAnimationFrame(completion);
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
        if (!session) return;
        const target = memberId ? [...root.querySelectorAll("[data-im-member]")].find(node => node.dataset.imMember === memberId) : root.querySelector(`[data-im-action="${action}"]:not([disabled])`);
        target?.focus({preventScroll:true});
      });
    }
    function renderSeries(focusAction) {
      const series = getSeries(session.seriesId), works = ArchiveV2.seriesImmersive.members(series, getWork);
      session.category ||= "all"; session.query ||= "";
      if (session.category !== "all" && !works.some(work => work.category === session.category)) session.category = "all";
      const hasEntityQueue = session.entities?.length > 1;
      const position = entityIndex();
      root.dataset.view = "series";
      root.innerHTML = `<div class="im-window"><div class="im-scene" aria-hidden="true"></div><div class="im-shade" aria-hidden="true"></div>
        <header class="im-toolbar"><div class="im-toolbar-start"><button type="button" class="im-button im-return" data-im-action="close">${origin?.view === "series" ? "← 返回系列宇宙" : "← 返回作品库"}</button><button type="button" class="im-button im-manage-series" data-im-action="manage-series">管理系列</button></div><div class="im-location"><span>系列典藏</span><strong>${session.entities?.length ? `${entityIndex() + 1} / ${session.entities.length}` : `${works.length} 件作品`}</strong></div>${viewControls()}</header>
        <div class="im-scroll ims-scroll">${ArchiveV2.seriesImmersive.content(series, works, getLabels, session)}</div>
        ${hasEntityQueue ? `<button type="button" class="im-side-arrow im-side-prev" data-im-action="previous" ${position === 0 ? "disabled" : ""} aria-label="上一个展示项目">‹</button><button type="button" class="im-side-arrow im-side-next" data-im-action="next" ${position === session.entities.length - 1 ? "disabled" : ""} aria-label="下一个展示项目">›</button>` : ""}<div class="im-filmstrip" data-im-filmstrip></div><button type="button" class="im-film-reveal" data-im-action="film-reveal" data-film-reveal aria-label="显示浏览队列"></button></div>`;
      bindPosters();
      mountMusic();
      const scene = root.querySelector(".im-scene");
      seriesBackgrounds.start(series, works, (image, kind) => paint(scene, image, kind), getBackgroundSettings(), session.sharedUrl);
      root.querySelector(".im-scroll").scrollTop = session.seriesScroll || 0;
      renderFilmstrip();
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
      loader.cancel(); seriesBackgrounds.cancel();
      root.dataset.surface = session.surface; root.dataset.background = "default"; root.hidden = false;
      root.dataset.backgroundTone = backgroundTone;
      if (session.page === "series") { renderSeries(focusAction); return; }
      root.dataset.view = "work";
      const work = getWork(session.currentId);
      const labels = getLabels(work);
      const index = session.ids.indexOf(session.currentId);
      const memberBrowse = !!session.seriesId;
      const previous = !memberBrowse && session.entities?.length ? entityIndex() > 0 : getWork(ArchiveV2.browse.adjacent(session, -1));
      const next = !memberBrowse && session.entities?.length ? entityIndex() < session.entities.length - 1 : getWork(ArchiveV2.browse.adjacent(session, 1));
      const source = session.seriesId ? getSeries(session.seriesId).name : session.source || "当前筛选结果";
      root.dataset.surface = session.surface;
      root.hidden = false;
      root.innerHTML = `<div class="im-window">
        <div class="im-scene" aria-hidden="true" data-background="default"></div><div class="im-shade" aria-hidden="true"></div>
        <header class="im-toolbar"><div class="im-toolbar-start"><button type="button" class="im-button im-return" data-im-action="close">${session.seriesId ? `← 返回系列<span class="im-return-name"> · ${esc(source)}</span>` : "← 返回作品库"}</button></div>
          <div class="im-location" aria-live="polite"><span>${esc(source)}</span><strong>${session.entities?.length ? `${entityIndex() + 1} <i>/</i> ${session.entities.length}` : `${index + 1} <i>/</i> ${session.ids.length}`}</strong></div>
          <div class="im-toolbar-controls"><button type="button" class="im-button im-edit" data-im-action="edit" aria-label="编辑作品" title="编辑作品">编辑</button>${viewControls()}</div></header>
        <div class="im-scroll"><article class="im-card">${completeWorkContent(work, labels, getSeriesLinks(work))}</article></div>
        <button type="button" class="im-side-arrow im-side-prev" data-im-action="previous" ${previous ? "" : "disabled"} aria-label="前一个展示项目">‹</button><button type="button" class="im-side-arrow im-side-next" data-im-action="next" ${next ? "" : "disabled"} aria-label="下一个展示项目">›</button>
        <div class="im-filmstrip" data-im-filmstrip></div><button type="button" class="im-film-reveal" data-im-action="film-reveal" data-film-reveal aria-label="显示浏览队列"></button>
      </div>`;
      bindPosters();
      mountMusic();
      const experienceDate = root.querySelector("[data-im-experience-date]");
      if (experienceDate && !experienceDate.value) experienceDate.value = new Date().toISOString().slice(0, 10);
      const scene = root.querySelector(".im-scene");
      renderFilmstrip();
      loader.load(work, (image, kind) => paint(scene, image, kind), getBackgroundSettings(), {startUrl:session.startUrl});
      session.startUrl = "";
      requestAnimationFrame(() => {
        if (!session) return;
        const target = root.querySelector(`[data-im-action="${focusAction}"]:not([disabled])`) || root.querySelector('[data-im-action="close"]');
        target?.focus({ preventScroll: true });
      });
    }
    function navigateEntities(offset) {
      if (!session?.entities?.length) return false;
      const target = session.entities[entityIndex() + offset];
      if (!target) return false;
      session.navigationAnchor = null;
      session.seriesScroll = 0; session.contentScroll = 0; session.focusMember = null;
      if (target.type === "series") {
        session.seriesId = target.id; session.page = "series"; session.currentId = null;
        session.ids = ArchiveV2.seriesImmersive.members(getSeries(target.id), getWork).map(work => work.id);
        session.category = "all"; session.query = "";
      } else {
        session.seriesId = null; session.page = "work"; session.currentId = target.id;
        session.ids = session.entities.filter(item => item.type === "work").map(item => item.id);
        session.source = "全部作品";
      }
      render(offset > 0 ? "next" : "previous"); writeHistory();
      return true;
    }
    function navigate(offset) {
      if (!session || transitionPending) return;
      if (session.page === "series") { navigateEntities(offset); return; }
      if (!session.seriesId && navigateEntities(offset)) return;
      const target = ArchiveV2.browse.adjacent(session, offset);
      if (!target) return;
      session.currentId = target; session.contentScroll = 0;
      render(offset > 0 ? "next" : "previous"); writeHistory();
    }
    function close(completion = null) {
      if (!session || transitionPending) return;
      if (session.seriesId && session.page === "work") { backToSeries(); return; }
      if (session.page === "series") rememberSeries();
      closeCompletion = completion;
      if (ownsHistory()) { transitionPending = true; history.back(); }
      else end();
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
      else if (action === "edit") {
        const work = getWork(session?.currentId);
        if (work) {
          const scroll = root.querySelector(".im-scroll")?.scrollTop || 0;
          session.editing = true; session.editScroll = scroll; root.hidden = true;
          openEdit(work, scroll);
        }
      }
      else if (action === "manage-series" && session?.page === "series") {
        const id = session.seriesId;
        close(() => onManageSeries(id));
      }
      else if (action === "save-rating" && session?.page === "work") {
        const score = Number(root.querySelector("[data-im-score-range]")?.value);
        const reason = root.querySelector("[data-im-score-reason]")?.value || "";
        onRateWork(session.currentId, score, reason);
      }
      else if (action === "add-experience" && session?.page === "work") {
        onAddExperience(session.currentId, {
          date: root.querySelector("[data-im-experience-date]")?.value || "",
          status: root.querySelector("[data-im-experience-status]")?.value || "",
          content: root.querySelector("[data-im-experience-content]")?.value || "",
        });
      }
      else if (action === "delete-experience" && session?.page === "work") {
        onDeleteExperience(session.currentId, event.target.closest("[data-im-experience]")?.dataset.imExperience);
      }
      else if (action === "add-user-field" && session?.page === "work") {
        onAddUserField(session.currentId, root.querySelector("[data-im-user-field-key]")?.value || "", root.querySelector("[data-im-user-field-value]")?.value || "");
      }
      else if (action === "delete-work" && session?.page === "work") onDeleteWork(session.currentId);
      else if (action === "series") {
        const id = event.target.closest("[data-im-series]")?.dataset.imSeries;
        if (id) onOpenSeries(id);
      }
      else if (action === "member") enterMember(event.target.closest("[data-im-member]").dataset.imMember);
      else if (action === "category") {
        session.category = event.target.closest("[data-im-category]").dataset.imCategory;
        root.querySelectorAll("[data-im-category]").forEach(button => button.setAttribute("aria-pressed", button.dataset.imCategory === session.category));
        filterMembers();
      }
      else if (action === "film-reveal") {
        root.classList.toggle("filmstrip-open");
      }
      else if (action === "film-jump") {
        const button=event.target.closest("[data-im-film-id]"),id=button?.dataset.imFilmId;
        if(!button||!id)return;
        if(button.dataset.imFilmType==="series"&&getSeries(id)){
          session.seriesId=id;session.page="series";session.currentId=null;session.ids=ArchiveV2.seriesImmersive.members(getSeries(id),getWork).map(work=>work.id);session.navigationAnchor=null;session.category="all";session.query="";
        }else if(getWork(id)){
          session.page="work";session.currentId=id;session.seriesId=null;session.ids=session.entities?.length?session.entities.filter(item=>item.type==="work").map(item=>item.id):session.ids;session.contentScroll=0;
        }
        render("close");writeHistory();
      }
      else if (session && ["overlay", "fullscreen"].includes(action)) {
        session.surface = action; root.dataset.surface = action;
        root.querySelectorAll('.im-surfaces button').forEach(button => button.setAttribute("aria-pressed", button.dataset.imAction === action));
        writeHistory();
      }
    };
    root.oninput = event => {
      if (event.target.dataset.imMusic === 'volume') { music.setVolume(Number(event.target.value) / 100); return; }
      if (event.target.matches("[data-im-score-range]")) { root.querySelector("[data-im-score-output]").value = Number(event.target.value).toFixed(1); return; }
      if (event.target.matches("[data-im-series-search]")) { session.query = event.target.value; filterMembers(); return; }
      if(event.target.matches("[data-im-film-search]")){catalogState.query=event.target.value;renderFilmstrip();const input=root.querySelector("[data-im-film-search]");input?.focus();input?.setSelectionRange(input.value.length,input.value.length);}
    };
    root.onchange = event => {
      const field = event.target.dataset.imMusic;
      if (field === 'enabled') music.setEnabled(event.target.checked);
      else if (field === 'loop') music.setLoop(event.target.checked);
      else if (field === 'pauseHidden') music.setPauseHidden(event.target.checked);
      else if(event.target.matches("[data-im-film-category]")){catalogState.category=event.target.value;renderFilmstrip();}
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
      if(event.pointerType!=="touch"){
        const edge=event.target.closest("[data-film-edge]");
        if(edge){catalogState.edge=Number(edge.dataset.filmEdge);catalogState.edgeAt=performance.now();if(!catalogState.edgeFrame)catalogState.edgeFrame=requestAnimationFrame(runFilmEdge);}
        if(event.target.closest("[data-film-reveal]"))root.classList.add("filmstrip-open");
      }
      if (event.pointerType === "touch" || session?.page !== "series") return;
      const card = event.target.closest("[data-im-member]");
      if (card && !card.contains(event.relatedTarget)) seriesBackgrounds.preview(getWork(card.dataset.imMember));
    };
    root.onpointerout = event => {
      const edge=event.target.closest("[data-film-edge]");if(edge&&!edge.contains(event.relatedTarget))stopFilmEdge();
      if(event.target.closest("[data-film-reveal]")&&!root.querySelector(".im-filmstrip")?.contains(event.relatedTarget))root.classList.remove("filmstrip-open");
      if (event.pointerType === "touch" || session?.page !== "series") return;
      const card = event.target.closest("[data-im-member]");
      if (card && !card.contains(event.relatedTarget)) seriesBackgrounds.resume();
    };
    root.onfocusin = event => {
      if(event.target.closest(".im-filmstrip"))root.classList.add("filmstrip-open");
      if (session?.page !== "series" || !event.target.matches(":focus-visible")) return;
      const card = event.target.closest("[data-im-member]");
      if (card) seriesBackgrounds.preview(getWork(card.dataset.imMember));
    };
    root.onfocusout = event => {
      if(event.target.closest(".im-filmstrip")&&!root.querySelector(".im-filmstrip")?.contains(event.relatedTarget))root.classList.remove("filmstrip-open");
      if (session?.page === "series" && event.target.closest("[data-im-member]")) seriesBackgrounds.resume();
    };
    root.onpointermove=event=>{
      if(event.pointerType==="touch")return;
      const rect=root.getBoundingClientRect();
      if(event.clientY>=rect.bottom-14)root.classList.add("filmstrip-open");
      else if(!event.target.closest(".im-filmstrip,[data-film-reveal]"))root.classList.remove("filmstrip-open");
    };
    root.onkeydown = event => {
      if (event.key === "Escape" && root.classList.contains("filmstrip-open")) {
        event.preventDefault(); event.stopPropagation(); root.classList.remove("filmstrip-open"); return;
      }
      if (event.target.closest(".im-filmstrip")) {
        if(event.target.matches(".im-film-item")&&(event.key==="ArrowLeft"||event.key==="ArrowRight")){
          const buttons=[...root.querySelectorAll(".im-film-item")],index=buttons.indexOf(document.activeElement),target=buttons[index+(event.key==="ArrowRight"?1:-1)];
          if(target){event.preventDefault();target.focus();target.scrollIntoView({block:"nearest",inline:"nearest"});}
        }
        return;
      }
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
      render();
    });
    return {
      open(ids, currentId, surface = "overlay", source = "当前筛选结果", entities = null) {
        if (session) return;
        root.classList.remove("filmstrip-open");
        catalogState.query="";catalogState.category="all";stopFilmEdge();
        session = ArchiveV2.browse.create(ids, currentId, surface);
        if (!session || !getWork(currentId)) { session = null; return; }
        session.token = `${Date.now()}-${Math.random().toString(36).slice(2)}`; session.source = source; session.entities = entities;
        origin = captureOrigin(currentId); lock(); render(); writeHistory(true);
      },
      openSeries(seriesId, surface = "overlay", matchedIds = null, entities = null) {
        if (session || !getSeries(seriesId)) return;
        root.classList.remove("filmstrip-open");
        catalogState.query="";catalogState.category="all";stopFilmEdge();
        session = {seriesId, page:"series", currentId:null, ids:[], surface:surface === "fullscreen" ? "fullscreen" : "overlay", category:"all", query:"", matchedIds, entities,
          token:`${Date.now()}-${Math.random().toString(36).slice(2)}`};
        if(entities?.length&&!entities.some(item=>item.type==="series"&&item.id===seriesId)){
          const memberIds=new Set(ArchiveV2.seriesImmersive.members(getSeries(seriesId),getWork).map(work=>work.id));
          session.navigationAnchor=entities.find(item=>item.type==="work"&&memberIds.has(item.id))?.id||null;
        }
        origin = captureOrigin(seriesId); lock(); render(); writeHistory(true);
      },
      editReturned(scroll = 0) {
        if (!session || !getWork(session.currentId)) return false;
        session.editing = false;
        render("edit");
        const scroller = root.querySelector(".im-scroll");
        if (scroller) scroller.scrollTop = scroll;
        writeHistory();
        return true;
      },
      suspendForEdit(scroll = 0) {
        if (!session || session.page !== "work") return false;
        session.editing = true;
        session.editScroll = scroll;
        root.hidden = true;
        return true;
      },
      enterRelatedSeries(id) {
        if (!session || !getSeries(id) || transitionPending) return false;
        const currentEntity = session.entities?.find(item => item.id === session.currentId || item.id === session.seriesId);
        const navigationAnchor = session.navigationAnchor || currentEntity?.id || session.currentId;
        session = {...session,seriesId:id,page:"series",currentId:null,ids:[],surface:"fullscreen",category:"all",query:"",matchedIds:null,navigationAnchor};
        render("catalog"); writeHistory(); return true;
      },
      ensureOpen() {
        if (!session) return false;
        return true;
      },
      close,
      playWork(id) {
        const work = getWork(id);
        if (!work) return false;
        if (!session) return false;
        if (!session.ids.includes(id)) session.ids = [...new Set([id, ...session.ids])];
        session.page = "work"; session.currentId = id; session.contentScroll = 0;
        session.seriesId = null; session.source = "音乐播放列表";
        render(); writeHistory(); return true;
      },
      isOpen: () => !!session,
      overlayRoot: () => session ? root : null,
      refresh() {
        if (!session) return;
        if (session.editing) return;
        if (!reconcile()) { close(); return; }
        if (session.page === "series") rememberSeries();
        const action = document.activeElement?.dataset.imAction || "close";
        const scroll = root.querySelector(".im-scroll")?.scrollTop || 0;
        render(action); if (root.querySelector(".im-scroll")) root.querySelector(".im-scroll").scrollTop = scroll;
      },
    };
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { immersive: { create, workContent, completeWorkContent } });
})();
