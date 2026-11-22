/* 系列只读展示与背景协调；成员实体和统计始终来自现有档案。 */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
  const score = value => value == null ? "未评分" : Number(value).toFixed(1);
  function images(entity) {
    const raw = Array.isArray(entity?.immersiveBackgroundUrls) ? entity.immersiveBackgroundUrls : [entity?.immersiveBackgroundUrl];
    return [...new Set(raw.map(ArchiveV2.backgrounds.safeBackgroundUrl).filter(Boolean))];
  }
  function members(series, getWork) {
    return (series.members || []).map(member => getWork(member.id)).filter(Boolean);
  }
  function pool(series, works) { return [...new Set([series, ...works].flatMap(images))]; }
  function select(works, category, query) {
    const text = query.trim().toLocaleLowerCase();
    return works.filter(work => (category === "all" || work.category === category) &&
      (!text || [work.title, work.originalTitle, ...(work.aliases || [])].join(" ").toLocaleLowerCase().includes(text)));
  }
  function memberCard(work, labels) {
    return `<button type="button" class="ims-member" data-im-action="member" data-im-member="${esc(work.id)}" aria-label="沉浸浏览《${esc(work.title)}》">
      <span class="ims-member-cover"><span class="ims-placeholder">${esc(labels.category)}<small>暂无封面</small></span>${work.coverUrl ? `<img src="${esc(work.coverUrl)}" alt="" loading="lazy" decoding="async" data-im-poster>` : ""}</span>
      <span class="ims-member-title">${esc(work.title || "未命名作品")}</span>
      <span class="ims-member-meta">${esc([labels.category, work.year].filter(Boolean).join(" · "))}</span>
      <span class="ims-member-foot"><span>${esc(labels.status)}</span><strong>${work.rating == null ? "未评" : score(work.rating)}</strong></span>
    </button>`;
  }
  function content(series, works, labels, state) {
    const covers = series.coverUrl ? [{title:series.name, coverUrl:series.coverUrl}] : works.filter(work => work.coverUrl).slice(0, 3);
    const summary = series.summary || "每一部作品，都是这个系列的一部分。";
    const categories = [...new Set(works.map(work => work.category))];
    const intro = summary.length > 280 ? `${esc(summary.slice(0, 280))}…<details class="im-summary-more"><summary>展开系列简介</summary><p>${esc(summary)}</p></details>` : esc(summary);
    const matched = state.matchedIds ? works.filter(work => state.matchedIds.includes(work.id)).length : null;
    const total = series.memberCount ?? works.length, completed = series.completedCount || 0;
    return `<section class="ims-hero">
      <div class="ims-intro"><p class="im-eyebrow">系列典藏 <span>／</span> ${esc([series.kindLabel, series.yearRange].filter(Boolean).join(" · "))}</p>
        <h1 id="immersiveTitle" class="im-title">${esc(series.name)}</h1>
        ${series.originalTitle ? `<p class="im-original">${esc(series.originalTitle)}</p>` : ""}
        <div class="ims-summary im-synopsis">${intro}</div>
        <div class="ims-stats"><div><span>系列个人评分</span><strong>${score(series.rating)}</strong></div><div><span>成员均分 · ${series.ratedCount || 0} 部已评</span><strong>${score(series.avgRating)}</strong></div><div><span>已完成 / 全部</span><strong>${completed}<small> / ${total}</small></strong></div></div>
        <div class="ims-progress" role="progressbar" aria-label="系列完成进度" aria-valuemin="0" aria-valuemax="${total || 1}" aria-valuenow="${completed}"><span style="width:${total ? Math.min(100, completed / total * 100) : 0}%"></span></div>
        <p class="ims-caption">${esc(series.baseStatusLabel || "未开始")}${matched != null ? ` · 首页筛选匹配 ${matched} / ${total} 部，以下展示全系列` : ""}</p>
      </div>
      <div class="ims-art${covers.length > 1 ? " is-composite" : ""}" aria-hidden="true">${covers.length ? covers.map((cover, i) => `<div class="ims-art-cover" style="--ims-index:${i}"><span class="ims-placeholder">${esc(series.name)}</span><img src="${esc(cover.coverUrl)}" alt="" decoding="async" data-im-poster></div>`).join("") : `<div class="ims-art-empty"><span>系列典藏</span><strong>${esc(series.name)}</strong></div>`}</div>
    </section>
    <section class="ims-members" aria-labelledby="imsMembersTitle"><div class="ims-members-head"><div><p class="im-eyebrow">COLLECTION</p><h2 id="imsMembersTitle">系列作品 <small>${total}</small></h2></div><input type="search" data-im-series-search aria-label="搜索系列作品" placeholder="搜索系列作品" value="${esc(state.query || "")}"></div>
      <div class="ims-categories" role="group" aria-label="按作品分类"><button type="button" data-im-action="category" data-im-category="all" aria-pressed="${state.category === "all"}">全部</button>${categories.map(category => `<button type="button" data-im-action="category" data-im-category="${esc(category)}" aria-pressed="${state.category === category}">${esc(labels(works.find(work => work.category === category)).category)} <small>${works.filter(work => work.category === category).length}</small></button>`).join("")}</div>
      <div class="ims-grid">${select(works, state.category, state.query).map(work => memberCard(work, labels(work))).join("")}</div>
      <p class="ims-empty" ${select(works, state.category, state.query).length ? "hidden" : ""}>${works.length ? "没有匹配的作品，试试其他分类或关键词。" : "系列还没有成员，可在完整详情中添加。"}</p>
    </section>`;
  }
  function createBackgrounds({ loader = ArchiveV2.backgrounds.createLoader(), schedule = setTimeout, unschedule = clearTimeout } = {}) {
    let series, works, display, settings, sharedUrl = "", visibleUrl = "", activeId = null, timer = null, generation = 0, running = false;
    function cancel() { generation++; running = false; unschedule(timer); timer = null; loader.cancel(); }
    function shared() {
      if (!running) return;
      activeId = null;
      loader.load({ immersiveBackgroundUrls: pool(series, works), coverUrl: series.coverUrl }, (img, kind) => {
        if (img) visibleUrl = img.src;
        if (kind === "dedicated") sharedUrl = img.src;
        display(img, kind === "cover" ? "ambient" : kind);
      }, settings, {keepCurrent:true, startUrl:sharedUrl, fallbackCovers:works.filter(work => work.coverUrl).slice(0, 3).map(work => work.coverUrl), onExhausted:() => { visibleUrl = ""; display(null, "default"); }});
    }
    function preview(work) {
      if (!running) return;
      unschedule(timer);
      const token = generation;
      timer = schedule(() => {
        if (!running || token !== generation) return;
        const urls = images(work);
        if (!urls.length) { if (activeId !== null) shared(); return; }
        if (activeId === work.id) return;
        activeId = work.id;
        loader.load({immersiveBackgroundUrls:urls}, (img, kind) => {
          if (img) { visibleUrl = img.src; display(img, kind); }
        }, settings, {keepCurrent:true, startUrl:urls.includes(visibleUrl) ? visibleUrl : "", onExhausted:shared});
      }, 300);
    }
    return {
      start(s, items, paint, preferences, resumeUrl = "") {
        cancel(); series = s; works = items; display = paint; settings = preferences; sharedUrl = resumeUrl; visibleUrl = ""; running = true; shared();
      },
      preview,
      resume() { if (!running) return; unschedule(timer); const token = generation; timer = schedule(() => { if (running && token === generation && activeId !== null) shared(); }, 300); },
      cancel,
      current: () => ({sharedUrl, visibleUrl}),
    };
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, {seriesImmersive:{images, members, pool, select, memberCard, content, createBackgrounds}});
})();
