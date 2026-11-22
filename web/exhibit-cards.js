/* 陈列卡片：只接收实体与显示文案，不访问 S、不发送请求、不修改业务数据。 */
(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const score = value => value == null || value === "" ? null :
    (Number.isFinite(Number(value)) ? Number(value).toFixed(1) : null);
  const boundWalls = new WeakSet();

  function image(url, fallbacks = []) {
    const candidates = [...new Set(fallbacks)].filter(candidate => candidate && candidate !== url);
    return url ? `<img src="${escape(url)}" alt="" loading="lazy" decoding="async" data-exhibit-image${candidates.length ? ` data-cover-fallbacks="${escape(JSON.stringify(candidates))}"` : ""}>` : "";
  }

  function workCard(work, labels) {
    const rating = score(work.rating);
    const metadata = [labels.category, work.year].filter(Boolean).join(" · ");
    return `<article class="card exhibit-work" data-id="${escape(work.id)}" data-cat="${escape(work.category)}" role="group" aria-label="查看《${escape(work.title)}》完整详情，${escape(labels.status)}，${rating === null ? "未评分" : `个人评分 ${rating}`}" title="${escape(work.title)}">
      <div class="exhibit-cover">
        <div class="exhibit-placeholder" aria-hidden="true"><span class="exhibit-placeholder-label">${escape(labels.category)}</span><span class="exhibit-placeholder-note">暂无封面</span></div>
        ${image(work.coverUrl)}
        <span class="exhibit-rating${rating === null ? " is-unrated" : ""}" aria-hidden="true">${rating ?? "未评"}</span>
      </div>
      <div class="exhibit-label">
        <div class="exhibit-title">${escape(work.title || "未命名作品")}</div>
        <div class="exhibit-meta" title="${escape(metadata)}">${escape(metadata)}</div>
        <div><span class="exhibit-status" data-status="${escape(work.status)}">${escape(labels.status)}</span></div>
        <div class="exhibit-series-name" title="${escape(labels.series || "")}">${labels.series ? escape(labels.series) : "<span aria-hidden=\"true\">独立收藏</span>"}</div>
      </div>
    </article>`;
  }

  function seriesCard(series, context = {}) {
    const members = series.members || [];
    const total = series.memberCount ?? members.length;
    const completed = series.completedCount || 0;
    const percent = total ? Math.max(0, Math.min(100, completed / total * 100)) : 0;
    const average = score(series.avgRating);
    const membersWithCover = members.filter(member => member.coverUrl);
    const memberCovers = membersWithCover.slice(0, 3).map(member => member.coverUrl);
    const visuals = (membersWithCover.length ? membersWithCover : members).slice(0, 3)
      .map(member => ({ url: member.coverUrl || "", label: member.title || series.name }));
    if (series.coverUrl) visuals.unshift({ url: series.coverUrl, label: series.name });
    if (!visuals.length) visuals.push({ url: "", label: series.name });
    const covers = visuals.slice(0, 3).map((item, i) => `<div class="exhibit-series-cover" style="--cover-index:${i}">
      <div class="exhibit-placeholder" aria-hidden="true"><span class="exhibit-placeholder-label">${escape(item.label)}</span><span class="exhibit-placeholder-note">${total ? "系列收藏" : "暂无成员"}</span></div>${image(item.url, memberCovers)}
    </div>`).join("");
    const mix = (series.catMix || []).map(category => `${category.label} ${category.count}`).join(" / ");
    return `<article class="series-card exhibit-series" data-sid="${escape(series.id)}" tabindex="0" role="group" aria-label="查看系列「${escape(series.name)}」完整详情，共 ${total} 部，全系列已完成 ${completed} 部" title="${escape(series.name)}">
      <span class="exhibit-kind">系列</span>
      <div class="exhibit-series-visual" aria-hidden="true">${covers}</div>
      <div class="exhibit-series-info">
        <div class="exhibit-series-title">${escape(series.name)}</div>
        <div class="exhibit-series-count">共 ${total} 部${context.filtered ? ` · 当前匹配 ${context.matchedCount ?? 0} 部` : ""}</div>
        <div class="exhibit-series-mix" title="${escape(mix)}">${escape(mix || "等待第一件收藏")}</div>
        <div class="exhibit-series-status"><span class="exhibit-status" data-status="${escape(series.baseStatus)}">${escape(series.baseStatusLabel || "未开始")}</span></div>
        <div class="exhibit-progress-label">${total ? `全系列已完成 ${completed} / ${total}` : "暂无成员，进入详情添加"}</div>
        <div class="exhibit-progress" aria-hidden="true"><span style="width:${percent}%"></span></div>
        <div class="exhibit-series-average">${average !== null ? `成员均分 ${average}` : "成员尚未评分"}</div>
        <button type="button" class="exhibit-series-launch" data-series-immersive="${escape(series.id)}" aria-label="浏览系列《${escape(series.name)}》">浏览系列 ↗</button>
      </div>
    </article>`;
  }

  function bindWall(wall, actions) {
    const activate = event => {
      const card = event.target.closest(".exhibit-work, .exhibit-series");
      if (!card || !wall.contains(card)) return;
      const launch = event.target.closest("[data-series-immersive]");
      if (launch?.dataset.seriesImmersive) { if (event.type === "click") actions.openSeriesImmersive?.(launch.dataset.seriesImmersive); return; }
      if (event.type === "keydown") {
        if (event.target !== card || event.repeat || !["Enter", " "].includes(event.key)) return;
        event.preventDefault();
      }
      if (card.dataset.sid) actions.openSeries(card.dataset.sid);
      else actions.openWork(card.dataset.id);
    };
    wall.onclick = activate;
    wall.onkeydown = activate;
    const failed = event => {
      const target = event.target;
      if (!target.matches?.("img[data-exhibit-image]")) return;
      const candidates = JSON.parse(target.dataset.coverFallbacks || "[]");
      const next = candidates.shift();
      target.dataset.coverFallbacks = JSON.stringify(candidates);
      if (next) {
        target.src = next;
        if (typeof target.setAttribute === "function") target.setAttribute("src", next);
      }
      else { target.hidden = true; target.removeAttribute("src"); }
    };
    if (!boundWalls.has(wall)) {
      boundWalls.add(wall);
      wall.addEventListener("error", failed, true);
    }
    // 缓存中的失败图片可能在绑定前已完成。
    wall.querySelectorAll("img[data-exhibit-image]").forEach(target => {
      if (target.complete && !target.naturalWidth) failed({ target });
    });
  }

  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { cards: { workCard, seriesCard, bindWall } });
})();


