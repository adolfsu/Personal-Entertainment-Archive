/* 读取当前档案快照，构建首页、系列、历程和洞察。 */
(() => {
  const headings = { home: "正在进行", archive: "作品库", series: "系列宇宙", journey: "我的历程", insights: "档案洞察" };
  const colors = { anime: "#cdb37d", manga: "#a58c65", game: "#409cff", novel: "#30b85b", book: "#ff9f0a", movie: "#89a7c4", shortdrama: "#b38bbf" };
  const dateOnly = value => /^\d{4}-\d{2}-\d{2}/.test(value || "") ? value.slice(0, 10) : "";
  const state = { seriesFilter: "all", journeyType: "experience", year: "all", category: "all" };
  const image = (url, eager = false) => url ? `<img src="${esc(url)}" alt="" loading="${eager ? "eager" : "lazy"}" decoding="async" data-collection-image>` : "";
  const empty = message => `<p class="collection-empty">${esc(message)}</p>`;
  const progress = work => (work.userFields || []).filter(field => /^(进度|阅读进度|观看进度|游玩进度|当前进度|当前集数|当前章节|完成进度|已读章节|已看集数)$/.test(field.key || "") && field.value).slice(0, 2).map(field => `${field.key}：${field.value}`).join(" · ");
  function bindImages(container) {
    if (!container || container.dataset.collectionImages) return;
    container.dataset.collectionImages = "true";
    container.addEventListener("error", event => {
      if (event.target.matches?.("[data-collection-image]")) event.target.hidden = true;
    }, true);
  }

  function collect(works) {
    const experiences = [], ratings = [];
    for (const work of works) {
      (work.experiences || []).forEach((record, index) => experiences.push({
        work, date: dateOnly(record.date), order: record.createdAt || "", index,
        status: record.status, text: record.content,
      }));
      (work.ratingHistory || []).forEach((record, index) => {
        const recordedAt = record.at || record.date || "";
        if (record.score != null && record.score !== "" && Number.isFinite(Number(record.score))) {
          ratings.push({ work, date: dateOnly(recordedAt), order: recordedAt, index, score: Number(record.score), text: record.reason });
        }
      });
    }
    const recent = (a, b) => b.date.localeCompare(a.date) || b.order.localeCompare(a.order) || b.index - a.index;
    return { experiences: experiences.sort(recent), ratings: ratings.sort(recent) };
  }

  function mediaCounts(works) {
    const counts = Object.fromEntries(CAT_ORDER.map(key => [key, 0]));
    works.forEach(work => { if (Object.hasOwn(counts, work.category)) counts[work.category]++; });
    return counts;
  }

  function sidebar() {
    const slot = el("#sideCategories");
    if (!slot) return;
    const counts = mediaCounts(S.works);
    el("#navWorkCount").textContent = S.works.length;
    el("#navSeriesCount").textContent = S.series.length;
    el("#sidebarArchiveSummary").textContent = `${S.works.length} 件收藏 · ${S.series.length} 个系列`;
    slot.innerHTML = CAT_ORDER.map(key => `<button class="sidebar-nav-item" data-collection-category="${key}" aria-pressed="${S.view === "archive" && S.filters.cat === key}"><i class="collection-dot" style="--media-color:${colors[key]}"></i><span>${esc(catLabel(key))}</span><small class="collection-rail-count">${counts[key]}</small></button>`).join("");
  }

  function home() {
    const hero = el("#homeHero"), feed = el("#homeFeed");
    if (!hero || !feed) return;
    const active = activeHomeWorks();
    const featured = active[0];
    const picks = active.slice(1, 3);
    const homeAction = (work, label, className = "btn") => `<button class="${className}" data-home-action="immersive" data-home-id="${esc(work.id)}">${label}</button>`;
    const manage = '<button class="btn" data-home-action="manage">管理首页作品</button>';
    const cover = (work, eager) => image(work.coverUrl, eager);
    hero.innerHTML = featured ? `<div class="collection-hero-grid"><article class="collection-hero">
      ${cover(featured, true)}<div class="collection-hero-copy"><p class="collection-kicker">IN PROGRESS · ${esc(catLabel(featured.category))}${featured.year ? ` · ${esc(featured.year)}` : ""}</p>
      <h1 id="homeTitle">${esc(featured.title || "未命名作品")}</h1>
      ${progress(featured) ? `<p class="collection-hero-note">${esc(progress(featured))}</p>` : ""}
      ${homeRecentRecord(featured)?.content ? `<p class="collection-hero-note">${esc(homeRecentRecord(featured).content)}</p>` : ""}
      <div class="collection-hero-actions">${homeAction(featured, "进入沉浸展厅 ↗", "btn btn-primary")}${manage}</div></div>
      <span class="collection-hero-page">01 / ${String(active.length).padStart(2, "0")}</span>
    </article>${picks.length ? `<aside class="collection-picks" aria-label="最近拾起"><div class="collection-picks-head"><span class="collection-kicker">RECENTLY PICKED · 最近拾起</span><span>${String(picks.length).padStart(2, "0")}</span></div>
      ${picks.map(work => `<button class="collection-pick" data-home-action="immersive" data-home-id="${esc(work.id)}">${cover(work, true)}<span><small>${esc(catLabel(work.category))}${work.year ? ` · ${esc(work.year)}` : ""}</small><b>${esc(work.title || "未命名作品")}</b><small>${esc(work.lastExperienceAt || statusLabel(work))}</small></span></button>`).join("")}</aside>` : ""}</div>` :
      `<div class="collection-empty collection-home-empty"><p class="collection-kicker">PERSONAL ARCHIVE</p><h1 id="homeTitle">从这里继续</h1><p>${S.works.some(work => work.status === "active") ? "首页作品暂时都已隐藏。" : "还没有进行中的作品。"}</p><div class="collection-hero-actions"><button class="btn btn-primary" data-home-action="${S.works.length ? "archive" : "add"}">${S.works.length ? "打开作品库" : "添加作品"}</button>${manage}</div></div>`;
    const progressCard = work => {
      const record = homeRecentRecord(work);
      const rating = work.rating == null ? null : Number(work.rating);
      return `<article class="collection-progress-item"><button class="collection-progress-card" data-home-action="immersive" data-home-id="${esc(work.id)}">
        <span class="collection-thumb">${cover(work)}</span><span class="collection-progress-copy">
        <small>${esc(catLabel(work.category))} · ${esc(statusLabel(work))}</small><b>${esc(work.title || "未命名作品")}</b>
        ${progress(work) || record?.content ? `<span class="collection-record-preview">${esc(progress(work) || record.content)}</span>` : ""}
        <span class="collection-track" aria-hidden="true"><i style="width:${rating == null ? 0 : Math.min(100, Math.max(0, rating * 10))}%"></i></span><small class="collection-score"><span>个人评分</span><span>${rating == null ? "未评" : fmtScore(rating)}</span></small>
        </span></button><button class="collection-hide" data-home-action="hide" data-home-id="${esc(work.id)}" title="从首页隐藏" aria-label="从首页隐藏《${esc(work.title)}》">×</button></article>`;
    };
    const counts = mediaCounts(S.works);
    const recent = collect(S.works).experiences.filter(record => record.date).slice(0, 6);
    feed.innerHTML = `${active.length ? `<section class="collection-block"><header class="collection-block-head"><div><span class="collection-kicker">IN PROGRESS · 继续体验</span><h2>故事还在继续</h2></div><button class="collection-link" data-collection-page="journey">查看我的历程 ↗</button></header><div class="collection-progress-grid">${active.slice(0, 6).map(progressCard).join("")}</div>
      ${active.length > 6 ? `<details class="collection-more"><summary>其余 ${active.length - 6} 部进行中作品</summary><div class="collection-progress-grid">${active.slice(6).map(progressCard).join("")}</div></details>` : ""}</section>` : ""}
      <section class="collection-block"><header class="collection-block-head"><div><span class="collection-kicker">SEVEN MEDIA · 七种媒介</span><h2>每一种收藏，都有自己的展厅</h2></div><button class="collection-link" data-collection-category="all">浏览作品库 ↗</button></header>
        <div class="collection-world-grid">${Object.entries(counts).map(([key, count]) => `<button class="collection-world" data-collection-category="${key}"><i class="collection-dot" style="--media-color:${colors[key]}"></i><b>${esc(catLabel(key))}</b><span>${count}</span></button>`).join("")}</div></section>
      <section class="collection-block"><header class="collection-block-head"><div><span class="collection-kicker">RECENT MEMORIES · 最近的记忆</span><h2>收藏也有时间的温度</h2></div><button class="collection-link" data-collection-page="journey">完整历程 ↗</button></header>
        ${recent.length ? `<div class="collection-memory-layout"><div class="collection-memory-list">${recent.map(({ work, date, status }) => `<button class="collection-memory" data-collection-work="${esc(work.id)}"><time datetime="${date}">${date}</time><b>${esc(work.title)}</b><span>${esc(catLabel(work.category))} · ${esc(genericLabel(status))}</span></button>`).join("")}</div>
        ${recent.find(record => record.text) ? (() => { const quote = recent.find(record => record.text); return `<aside class="collection-quote"><span class="collection-kicker">A LINE TO KEEP · 私人摘录</span><blockquote>${esc(quote.text)}</blockquote><cite>《${esc(quote.work.title)}》 · ${quote.date}</cite></aside>`; })() : ""}</div>` : empty("暂无体验记录。")}</section>`;
  }

  function seriesArt(series) {
    const covers = [...new Set([series.coverUrl, ...(series.members || []).map(member => member.coverUrl)].filter(Boolean))].slice(0, 3);
    return `<div class="collection-series-art" aria-hidden="true">${covers.length ? covers.map(cover => image(cover)).join("") : "<span>系列收藏</span>"}</div>`;
  }
  function series() {
    const out = el("#seriesCollection");
    const items = S.series.filter(item => state.seriesFilter === "all" ||
      (state.seriesFilter === "cross" ? item.catMix?.length > 1 : item.catMix?.length === 1));
    out.innerHTML = `<div class="seg collection-filters" role="group" aria-label="系列筛选">${[["all","全部系列"],["cross","跨媒介"],["single","单一媒介"]].map(([key,label]) => `<button data-collection-series-filter="${key}" class="${state.seriesFilter === key ? "on" : ""}" aria-pressed="${state.seriesFilter === key}">${label}</button>`).join("")}</div>
      <p class="collection-caption">${items.length} 个系列</p>${items.length ? `<div class="collection-series-grid">${items.map(item => `<button class="collection-series-tile" data-collection-series="${esc(item.id)}">${seriesArt(item)}<h2>${esc(item.name)}</h2><p>${item.memberCount ?? item.members?.length ?? 0} 部成员${item.catMix?.length ? " · " + esc(item.catMix.map(cat => cat.label).join(" / ")) : ""} · 已完成 ${item.completedCount || 0} 部</p></button>`).join("")}</div>` : empty("暂无符合条件的系列。")}`;
  }

  function journey() {
    const out = el("#journeyCollection");
    const { experiences, ratings } = collect(S.works);
    const years = [...new Set([...experiences, ...ratings].map(row => row.date.slice(0, 4)).filter(Boolean))].sort().reverse();
    if (!years.includes(state.year)) state.year = "all";
    const isExperience = state.journeyType === "experience";
    const records = (isExperience ? experiences : ratings).filter(row => (state.year === "all" || row.date.startsWith(state.year)) && (state.category === "all" || row.work.category === state.category));
    let month = null;
    const timeline = records.map(row => {
      const key = row.date.slice(0, 7);
      const heading = month !== key ? `<h2 class="collection-month">${key ? key.replace("-", " / ") : "日期未记录"}</h2>` : "";
      month = key;
      const label = isExperience ? genericLabel(row.status) : `评分 ${fmtScore(row.score)}`;
      return `${heading}<div class="collection-timeline-entry"><time${row.date ? ` datetime="${row.date}"` : ""}>${row.date ? row.date.replaceAll("-", ".") : "日期未记录"}</time>
        <button class="collection-journey-record" data-collection-work="${esc(row.work.id)}"><span class="collection-thumb">${image(row.work.coverUrl)}</span>
        <span><small class="collection-kicker">${esc(catLabel(row.work.category))} / ${esc(label)}</small><b>${esc(row.work.title)}</b>${row.text ? `<span class="collection-journey-text">${esc(row.text)}</span>` : ""}</span></button></div>`;
    }).join("");
    out.innerHTML = `<div class="collection-journey"><aside class="collection-journey-sidebar" aria-label="历程筛选"><h2>Memories.</h2>
      <div class="seg" role="group" aria-label="记录类型"><button data-collection-journey-type="experience" class="${isExperience ? "on" : ""}" aria-pressed="${isExperience}">体验</button><button data-collection-journey-type="rating" class="${!isExperience ? "on" : ""}" aria-pressed="${!isExperience}">评分</button></div>
      <label>媒介<select id="collectionJourneyCategory" class="mini"><option value="all">全部媒介</option>${CAT_ORDER.map(key => `<option value="${key}"${state.category === key ? " selected" : ""}>${esc(catLabel(key))}</option>`).join("")}</select></label>
      <div class="collection-years" role="group" aria-label="年份">${["all", ...years].map(y => `<button data-collection-year="${y}" aria-pressed="${state.year === y}">${y === "all" ? "全部年份" : y}</button>`).join("")}</div>
      <small>以经历日期回顾，补录时间不改写过去。</small></aside>
      <div><p class="collection-caption" role="status">展示 ${records.length} 条${isExperience ? "经历" : "评分"}</p>${timeline || empty("这段时间还没有记录。")}</div></div>`;
  }

  function insights() {
    const { experiences, ratings } = collect(S.works);
    const rated = S.works.filter(work => work.rating != null && work.rating !== "" && Number.isFinite(Number(work.rating)));
    const average = rated.length ? (rated.reduce((sum, work) => sum + Number(work.rating), 0) / rated.length).toFixed(2) : "—";
    const stats = [[S.works.length, "部收藏作品"], [S.series.length, "个系列世界"], [experiences.length, "次体验记录"], [ratings.length, "条评分历史"]];
    const now = new Date();
    const months = Array.from({length: 12}, (_, index) => {
      const date = new Date(now.getFullYear(), now.getMonth() - 11 + index, 1);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    });
    const steps = months.map(m => experiences.filter(row => row.date.startsWith(m)).length);
    const max = Math.max(1, ...steps);
    const bars = rows => {
      const high = Math.max(1, ...rows.map(row => row[1]));
      return `<div class="collection-bars">${rows.map(([label,count,color]) => `<div class="collection-bar-row"><span>${esc(label)}</span><span class="collection-track" aria-hidden="true"><i style="width:${count / high * 100}%;background:${color || "var(--collection-gold)"}"></i></span><b>${count}</b></div>`).join("")}</div>`;
    };
    const panel = (eyebrow, title, body) => `<article class="collection-chart"><span class="collection-kicker">${eyebrow}</span><h2>${title}</h2>${body}</article>`;
    const cross = S.series.filter(item => item.catMix?.length > 1).length;
    el("#insightsCollection").innerHTML = `<div class="collection-stats">${stats.map(([value, label]) => `<div><small>${label}</small><strong>${value}</strong></div>`).join("")}</div>
      <div class="collection-insights-grid">
      ${panel("ACTIVITY · 过去十二个月","体验节奏",`<div class="collection-month-chart" aria-label="近十二个月体验次数">${months.map((m,i) => `<div title="${m} · ${steps[i]} 次"><b>${steps[i]}</b><i aria-hidden="true" style="height:${steps[i] / max * 78}%"></i><span>${Number(m.slice(5))}月</span></div>`).join("")}</div>`)}
      ${panel("MEDIA MIX · 收藏构成","跨越不同媒介",bars(Object.entries(mediaCounts(S.works)).map(([key,n]) => [catLabel(key),n,colors[key]])))}
      ${panel("CURRENT STATUS · 当前状态","每一部，都有自己的进度",bars(Object.keys(GENERIC_STATUS).map(key => [genericLabel(key),S.works.filter(work => work.status === key).length,key === "completed" ? "var(--lenso-system-green)" : "var(--lenso-tint-text)"])))}
      ${panel("YOUR RATINGS · 评分档案","给喜爱留下一个刻度",bars([["低于 5 分",0,5],["5 至 <7 分",5,7],["7 至 <9 分",7,9],["9–10 分",9,11]].map(([label,low,high]) => [label,rated.filter(work => work.rating >= low && work.rating < high).length])) + `<p class="collection-caption">已评分平均分：<b>${average}</b></p>`)}
      </div><aside class="collection-quote collection-discovery"><span class="collection-kicker">A SMALL DISCOVERY · 一次发现</span><h2>同一个故事，会跨越媒介继续生长</h2><p>${S.series.length} 个系列中，有 ${cross} 个跨媒介系列。</p><button class="collection-link" data-collection-page="series">打开系列宇宙 ↗</button></aside>`;
  }

  function render(view) {
    ({ series, journey, insights })[view]?.();
  }

  function bind() {
    ["#homeView", "#seriesView", "#journeyView"].forEach(selector => bindImages(el(selector)));
    function navigate(event) {
      const button = event.target.closest("button");
      if (!button) return;
      const d = button.dataset;
      if (d.collectionPage) setAppView(d.collectionPage);
      else if (d.collectionCategory) {
        S.filters.cat = d.collectionCategory;
        S.filters.status = "all";
        renderTabs(); renderStatusChips(); renderWall(); setAppView("archive");
      } else if (d.collectionWork) openCurrentWork(d.collectionWork);
      else if (d.collectionSeries) openCurrentSeries(d.collectionSeries);
      else if (d.collectionSeriesFilter) {
        state.seriesFilter = d.collectionSeriesFilter;
        series(); el(`[data-collection-series-filter="${state.seriesFilter}"]`)?.focus({ preventScroll: true });
      } else if (d.collectionJourneyType || d.collectionYear) {
        const typeChanged = Boolean(d.collectionJourneyType);
        if (typeChanged) state.journeyType = d.collectionJourneyType;
        else state.year = d.collectionYear;
        journey();
        el(typeChanged ? `[data-collection-journey-type="${state.journeyType}"]` : `[data-collection-year="${state.year}"]`)?.focus({ preventScroll: true });
      }
    }
    ["#sideCategories", "#homeView", "#seriesView", "#journeyView", "#insightsView"].forEach(selector => el(selector)?.addEventListener("click", navigate));
    el("#journeyView")?.addEventListener("change", event => {
      if (event.target.id !== "collectionJourneyCategory") return;
      state.category = event.target.value;
      journey();
      el("#collectionJourneyCategory").focus({ preventScroll: true });
    });
    el("#randomWorkBtn").onclick = () => {
      if (!S.works.length) return toast("还没有收藏作品");
      openCurrentWork(S.works[Math.floor(Math.random() * S.works.length)].id);
    };
  }

  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { collection: { headings, sidebar, home, render, bind } });
})();
