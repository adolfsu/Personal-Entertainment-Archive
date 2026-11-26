/* 娱乐档案 · 前端逻辑（原生 JS，无依赖） */
const GENERIC_STATUS = { not_started: "未开始", planned: "计划中", active: "进行中", completed: "已完成", paused: "搁置", dropped: "弃坑" };
const CAT_ORDER = ["anime", "manga", "game", "novel", "book", "movie", "shortdrama"];
const EXPECT_FIELDS = {
  anime: ["放送开始", "话数", "导演", "制作"],
  manga: ["连载杂志", "册数", "作者"],
  game: ["平台", "游戏类型", "发行日期", "开发商"],
  novel: ["作者", "字数"],
  book: ["出版社", "页数", "ISBN"],
  movie: ["上映日", "片长", "导演"],
  shortdrama: ["集数", "上线日期"],
};
const ICONS = {
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  archive: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="4"/><path d="M5 8v12h14V8M10 12h4"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
};

/* 站外搜索：只生成平台搜索入口，不参与解析。
   关键词占位符固定为 {q}，渲染时统一用 encodeURIComponent 编码。 */
const EXTERNAL_SEARCH_PLATFORMS = {
  movie: [
    { label: "爱奇艺", template: "https://www.iqiyi.com/so/q_{q}" },
    { label: "腾讯视频", template: "https://v.qq.com/x/search/?q={q}" },
    { label: "优酷", template: "https://search.youku.com/search_video?keyword={q}" },
    { label: "哔哩哔哩", template: "https://search.bilibili.com/all?keyword={q}" },
  ],
  novel: [
    { label: "起点中文网", template: "https://www.qidian.com/search?kw={q}" },
    { label: "番茄小说", template: "https://fanqienovel.com/search/{q}" },
    { label: "刺猬猫", template: "https://www.ciweimao.com/get-search-book-list/0-0-0-0-0-0/全部/{q}/1" },
  ],
};

const S = {
  version: "", works: [], series: [], seriesKinds: {}, seriesRoles: {}, settings: {}, categories: [], sourceLabels: {},
  filters: { cat: "all", status: "all", time: "all", sort: "recent", q: "", group: "flat" },
  currentSeriesId: null,
  view: "home",
  seriesRating: 8,
  add: { step: 1, category: null, source: null, items: [], draft: null, mode: "create", editId: null, busy: false, refItems: [], refSource: null, tmdbRaw: "", tmdbPreview: null, youshuRaw: "", youshuPreview: null, youshuApplied: null },
  seriesDraft: { mode: "create", attachTo: null },
  backups: [], undoAvailable: false, dataState: "normal", syncPending: false,
};
let immersiveView = null;
let musicSearch = "";
let musicCategory = "all";
let musicPlaylistOpen = false;
const audioPlayer = ArchiveV2.audio.create({
  onChange: updateAudioPlayerUI,
  onNavigate: navigateAudioTrack,
});
ArchiveV2.audioPlayer = audioPlayer;
document.addEventListener("visibilitychange", () => audioPlayer.visibility(document.hidden));
document.addEventListener("archive-audio-preview", () => {
  if (["playing", "loading"].includes(audioPlayer.snapshot().state)) audioPlayer.play();
});

/* ------------------------------------------------------------ 外观（明暗 / 主题） */
const APPEARANCE = {
  scale: ["100", "115", "130", "150"].includes(localStorage.getItem("grdag_ui_scale")) ? localStorage.getItem("grdag_ui_scale") : "100",
  mode: localStorage.getItem("grdag_mode") || "dark",
  theme: localStorage.getItem("grdag_theme") || "stage",
  size: localStorage.getItem("grdag_size") || "small",
};
const SIZE_LABEL = { small: "小", medium: "中", large: "大" };
const MODE_ICON = {
  dark: '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8.2 8.2 0 1 0 10.5 10.5z"/></svg>',
  light: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.2"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.7 5.7l1.4 1.4M16.9 16.9l1.4 1.4M18.3 5.7l-1.4 1.4M7.1 16.9l-1.4 1.4"/></svg>',
};
const THEME_ICON = {
  stage: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="1.5"/><path d="M8 21h8M12 17v4"/></svg>',
  shelf: '<svg viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H19"/><path d="M8 7h7M8 10h5"/></svg>',
};

function applyAppearance(save = true) {
  document.documentElement.dataset.uiScale = APPEARANCE.scale;
  document.documentElement.dataset.mode = APPEARANCE.mode;
  document.documentElement.dataset.theme = APPEARANCE.theme;
  document.documentElement.dataset.size = APPEARANCE.size;
  if (save) {
    try {
      localStorage.setItem("grdag_mode", APPEARANCE.mode);
      localStorage.setItem("grdag_theme", APPEARANCE.theme);
      localStorage.setItem("grdag_size", APPEARANCE.size);
      localStorage.setItem("grdag_ui_scale", APPEARANCE.scale);
    } catch (e) {}
  }
  const mBtn = el("#modeBtn");
  if (mBtn) {
    mBtn.innerHTML = MODE_ICON[APPEARANCE.mode] || MODE_ICON.dark;
    mBtn.title = APPEARANCE.mode === "dark" ? "当前深色，点击切浅色" : "当前浅色，点击切深色";
  }
  const tBtn = el("#themeBtn");
  if (tBtn) {
    tBtn.innerHTML = THEME_ICON[APPEARANCE.theme] || THEME_ICON.stage;
    tBtn.title = APPEARANCE.theme === "stage" ? "当前展厅主题，点击切书架" : "当前书架主题，点击切展厅";
  }
  elAll("#setModeSeg button").forEach(b => { const on = b.dataset.v === APPEARANCE.mode; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
  elAll("#setThemeSeg button").forEach(b => { const on = b.dataset.v === APPEARANCE.theme; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
  elAll("#sizeSeg button").forEach(b => { const on = b.dataset.size === APPEARANCE.size; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
  applyWallDensity();
}

function setMode(mode) {
  APPEARANCE.mode = mode === "light" ? "light" : "dark";
  applyAppearance();
  toast(APPEARANCE.mode === "dark" ? "已切到深色模式" : "已切到浅色模式");
}

function setTheme(theme) {
  APPEARANCE.theme = theme === "shelf" ? "shelf" : "stage";
  applyAppearance();
  toast(APPEARANCE.theme === "shelf" ? "已切到书架主题" : "已切回展厅主题");
}

/* 主页每行显示数量：小 = 现有自动列数；中 = 约 75%；大 = 约 50%。
   展厅用固定列数精确控制；书架由 CSS 按 data-size 放大书本尺寸。 */
function applyWallDensity() {
  const wall = el("#wall");
  if (!wall) return;
  // 测量前临时取消跨列，避免旧的双列系列在单列布局中制造隐式列。
  wall.style.setProperty("--exhibit-series-span", "1");
  wall.style.gridTemplateColumns = "";
  if (APPEARANCE.theme === "stage" && APPEARANCE.size !== "small") {
    const raw = getComputedStyle(wall).gridTemplateColumns;
    const base = raw && raw !== "none" ? raw.trim().split(/\s+/).length : 1;
    const factor = APPEARANCE.size === "medium" ? 0.75 : 0.5;
    wall.style.gridTemplateColumns = `repeat(${Math.max(1, Math.round(base * factor))}, minmax(0, 1fr))`;
  }
  const columns = getComputedStyle(wall).gridTemplateColumns.trim().split(/\s+/).filter(value => /px$/.test(value));
  wall.style.setProperty("--exhibit-series-span", columns.length > 1 ? "2" : "1");
  if (columns.length) wall.style.setProperty("--exhibit-column-width", columns[0]);
}

function setSize(size) {
  APPEARANCE.size = ["small", "medium", "large"].includes(size) ? size : "small";
  applyAppearance();
  const raw = getComputedStyle(el("#wall")).gridTemplateColumns;
  const n = (raw && raw !== "none") ? raw.trim().split(/\s+/).filter(Boolean).length : 0;
  toast(n ? `每行显示约 ${n} 部（${SIZE_LABEL[APPEARANCE.size]}）` : `已切到${SIZE_LABEL[APPEARANCE.size]}显示`);
}

let densityTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(densityTimer);
  densityTimer = setTimeout(applyWallDensity, 150);
});

const el = (sel, root = document) => root.querySelector(sel);
const elAll = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function bufToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtScore(v) { return (v == null || v === "") ? "" : Number(v).toFixed(1); }

/* 版本号展示：有效版本显示 v1.2.3，读不到时显示「版本未标注」而不是「v未标注」。 */
function versionText(v) {
  const s = String(v == null ? "" : v).trim();
  return (s && s !== "未标注") ? `v${s}` : "版本未标注";
}

/* 设置面板里的「需要重启」提示：区分「版本号变了」和「版本号文件读不出来」两种情况。 */
function versionStaleNote() {
  if (!S.versionStale) return "";
  const fileLabel = versionText(S.versionFile);
  const tip = fileLabel === "版本未标注"
    ? "项目目录里的 VERSION 文件缺失或格式不正确，重启程序后会显示「版本未标注」"
    : `项目目录里的 VERSION 已是 ${fileLabel}，重启程序后才会生效`;
  return `<div class="muted-note" style="margin-top:6px;color:var(--lenso-system-orange)">${esc(tip)}</div>`;
}

function externalSearchUrl(platform, keyword) {
  return platform.template.replace("{q}", encodeURIComponent(keyword));
}

function externalSearchLinksHTML(platforms, keyword) {
  if (!keyword) return "";
  return platforms.map(p => `<a class="source-tab external-search-link" href="${esc(externalSearchUrl(p, keyword))}" target="_blank" rel="noopener noreferrer" aria-label="在 ${esc(p.label)} 搜索 ${esc(keyword)}">${ICONS.search}<span>${esc(p.label)}</span></a>`).join("");
}

const UNDOABLE_PATH = /^\/api\/(works|series|import|import-records|tmdb\/import)(\/|$)/;
const dataQueue = ArchiveV2.core.createQueue();

async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const request = async () => {
    const out = await requestApi(path, opts);
    syncUndoState(path, method, out);
    if (out.ok === true && ArchiveV2.core.isMutation(path, method)) {
     // 写入结果和完整快照在同一队列内处理，避免较旧的快照覆盖后一次修改。
     if (out.work) applyWork(out.work);
     if (out.series) replaceSeries(out.series);
     const deletedWork = method === "DELETE" && path.match(/^\/api\/works\/([^/]+)$/);
     if (deletedWork) S.works = S.works.filter(w => w.id !== deletedWork[1]);
     const deletedSeries = method === "DELETE" && path.match(/^\/api\/series\/([^/]+)$/);
     if (deletedSeries) {
       S.series = S.series.filter(s => s.id !== deletedSeries[1]);
       if (Array.isArray(out.works)) S.works = out.works;
     }
     if (path === "/api/clear-data" || path === "/api/recover/new-start") { S.works = []; S.series = []; }
     await refreshSnapshot(true);
      refreshAudioCatalog();
    }
    return out;
  };
  return ArchiveV2.core.isMutation(path, method) ? dataQueue(request) : request();
}

async function requestApi(path, opts = {}) {
  const o = { headers: { "Content-Type": "application/json" } };
  if (opts.method) o.method = opts.method;
  if (opts.body) o.body = JSON.stringify(opts.body);
  const controller = path === "/api/bootstrap" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), 15000) : null;
  if (controller) o.signal = controller.signal;
  try {
  const res = await fetch(path, o);
    const out = await res.json();
    if (!res.ok) return { ...out, ok: false, error: out.error || "本地服务请求失败" };
  return out;
  } catch (e) {
    return { ok: false, error: "请求未完成，请刷新确认数据状态后再试" };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/* 任何成功的写操作都会生成写前快照，撤销按钮必须立刻可用；
   撤销接口自己返回 remaining，清空数据会删掉快照。这里统一维护，避免各页面漏更新。 */
function syncUndoState(path, method, res) {
  if (!res || res.ok === false) return;
  if (method !== "GET" && UNDOABLE_PATH.test(path)) {
    S.undoAvailable = true;
  } else if (path === "/api/undo" && typeof res.remaining === "number") {
    S.undoAvailable = res.remaining > 0;
  } else if (path === "/api/clear-data") {
    S.undoAvailable = false;
  } else {
    return;
  }
  updateUndoBtn();
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = el("#toast");
  t.textContent = msg;
  t.classList.toggle("err", !!isErr);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2800);
}

/* ------------------------------------------------------------ 初始化 */
async function boot() {
  const data = await api("/api/bootstrap");
  if (!data || !Array.isArray(data.works)) { toast("无法连接本地服务，请确认 server.py 正在运行", true); return; }
  S.works = data.works;
  S.series = data.series || [];
  S.seriesKinds = data.seriesKinds || {};
  S.seriesRoles = data.seriesRoles || {};
  S.settings = data.settings || {};
  refreshAudioCatalog();
  S.version = data.version || "未标注";
  S.versionFile = data.versionFile || "";
  S.versionStale = Boolean(data.versionStale);
  S.dataState = data.dataState || "normal";
  S.undoAvailable = Boolean(data.undoAvailable);
  S.backups = data.backups || [];
  const sub = el("#brandSub");
  if (sub) sub.textContent = `PERSONAL ARCHIVE · ${versionText(S.version)}`;
  document.title = `娱乐档案 ${versionText(S.version)} · 个人档案馆`;
  S.categories = data.categories || [];
  S.sourceLabels = data.sourceLabels || {};
  window.__proxy = data.proxyActive || "未探测到可用代理";
  updateUndoBtn();
  setAppView("home", false);
  if (S.dataState === "corrupt") { showCorrupt(data); return; }
  renderTabs();
  renderStatusChips();
  renderWall();
  renderStats();
  renderHome();
  ArchiveV2.collection?.sidebar();
  bindGlobal();
}

function refreshAudioCatalog() {
  audioPlayer.setCatalog(ArchiveV2.audio.playlist(S.works, S.series));
  updateAudioQueue();
}

function filteredAudioCatalog() {
  const query = musicSearch.trim().toLocaleLowerCase();
  return audioPlayer.catalog().filter(track => (musicCategory === "all" || track.category === musicCategory) &&
    (!query || [track.title, track.artist, track.workTitle].some(value => String(value || "").toLocaleLowerCase().includes(query))));
}

function updateAudioPlayerUI(state) {
  const bar = el("#audioPlayer");
  if (!bar?.querySelector) return;
  bar.dataset.playing = String(state.state === "playing");
  bar.querySelector("[data-player-title]").textContent = state.track?.title || "未选择歌曲";
  bar.querySelector("[data-player-artist]").textContent = state.track?.artist || state.track?.workTitle || "打开音乐列表";
  bar.querySelector("[data-player-status]").textContent = state.error || (state.state === "blocked" ? "点击播放以允许音乐" : state.state === "loading" ? "正在加载" : "");
  const toggle = bar.querySelector('[data-player-action="toggle"]');
  toggle.textContent = ["playing", "loading"].includes(state.state) ? "暂停" : "播放";
  toggle.setAttribute("aria-label", toggle.textContent);
  toggle.disabled = state.mode === "immersive" && !state.target;
  bar.querySelector('[data-player-action="previous"]').disabled = state.queueCount < 2 || state.mode === "immersive";
  bar.querySelector('[data-player-action="next"]').disabled = state.queueCount < 2 || state.mode === "immersive";
  bar.querySelector("[data-player-mode-label]").textContent = ({global:"全局", immersive:"沉浸", playlist:"歌单"})[state.mode] || "音乐";
  bar.querySelector("[data-player-volume]").value = Math.round(state.volume * 100);
  bar.querySelector("[data-player-volume-value]").textContent = `${Math.round(state.volume * 100)}%`;
  elAll("[data-audio-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.audioMode === state.mode)));
  const shuffle = el("#musicShuffle"); if (shuffle) shuffle.checked = state.shuffle;
  const launch = el("#audioPlayerLaunch");
  if (launch) launch.dataset.playing = String(state.state === "playing");
  if (musicPlaylistOpen) renderAudioPlaylist();
}

function renderAudioPlaylist() {
  const box = el("#musicTrackList");
  if (!box?.dataset) return;
  const tracks = filteredAudioCatalog();
  const mode = audioPlayer.snapshot().mode;
  box.innerHTML = tracks.length ? tracks.map((track, index) => `<button type="button" class="music-track${audioPlayer.snapshot().track?.id === track.id ? " is-current" : ""}" data-audio-track="${esc(track.id)}">
    <span class="music-track-index">${String(index + 1).padStart(2, "0")}</span>
    <span class="music-track-copy"><strong>${esc(track.title)}</strong><small>${esc(track.artist || "未知演唱者")} · ${esc(track.workTitle)}</small></span>
    <span class="music-track-bind">${esc(track.workTitle)}</span>
  </button>`).join("") : `<p class="music-empty">${audioPlayer.catalog().length ? "没有匹配的歌曲" : "尚无已绑定音乐的作品"}</p>`;
  box.dataset.mode = mode;
  el("#musicCount").textContent = `${tracks.length} 首歌曲`;
}

function updateAudioQueue() {
  renderAudioPlaylist();
}

function openAudioPlaylist() {
  if (!modalIsOpen("#musicModal")) rememberOverlayFocus();
  musicPlaylistOpen = true;
  el("#musicShuffle").checked = audioPlayer.snapshot().shuffle;
  setModalState("#musicModal", true);
  elAll("[data-audio-mode]").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.audioMode === audioPlayer.snapshot().mode));
  });
  renderAudioPlaylist();
  focusAfterRender("#musicSearch");
}

function closeAudioPlaylist() {
  if (!modalIsOpen("#musicModal")) return;
  musicPlaylistOpen = false;
  setModalState("#musicModal", false);
  restoreOverlayFocus();
}

function navigateAudioTrack(track) {
  if (!track?.workId) return toast("这首歌尚未绑定作品", true);
  ensureImmersive();
  if (immersiveView.isOpen()) immersiveView.playWork(track.workId);
  else immersiveView.open([track.workId], track.workId, "fullscreen", "音乐播放列表");
}

/* 主档案损坏：挡住所有操作，只留「从备份恢复」和「新建空档案」两条路 */
function showCorrupt(data) {
  const box = el("#corruptBlock");
  if (!box) return;
  const f = data.corruptFile || {};
  el("#corruptText").textContent =
    `原因：${data.dataError || "无法读取"}\n` +
    `文件：${f.name || "library.json"}${f.mtime ? " · 修改于 " + f.mtime : ""}` +
    (f.size ? ` · ${(f.size / 1024).toFixed(0)} KB` : "") +
    `\n原文件已完整保留，程序没有覆盖它，也不会在恢复前写入任何数据。`;
  const backups = (data.backups || []);
  const list = el("#corruptBackups");
  list.innerHTML = backups.length
    ? backups.map(b => `<div class="backup-row">
        <span class="b-kind">${esc(b.label || "备份")}</span>
        <span class="b-time">${esc(b.time)}</span>
        <span class="b-size">${(b.size / 1024).toFixed(0)} KB</span>
        <button class="btn btn-sm btn-primary" data-crestore="${esc(b.name)}" data-ckind="${esc(b.kind)}">恢复</button>
      </div>`).join("")
    : `<div class="muted-note">没有找到可用备份。可以先把 data\\library.json 拷出来手动修复，或确认后新建空档案。</div>`;
  elAll("[data-crestore]", list).forEach(x => x.onclick = async () => {
    x.disabled = true;
    const ok = await restoreBackup(x.dataset.ckind, x.dataset.crestore);
    x.disabled = false;
    if (ok) location.reload();
  });
  el("#corruptRetry").onclick = () => location.reload();
  el("#corruptNewBtn").onclick = async () => {
    if (!confirm("这会保留损坏文件（另存为 library.corrupt-时间.json），然后新建一份空档案。确定？")) return;
    const word = prompt("请输入「新建空档案」四个字以确认：");
    if (word !== "新建空档案") return toast("确认内容不匹配，已取消", true);
    const r = await api("/api/recover/new-start", { method: "POST", body: { confirm: "新建空档案" } });
    if (!r.ok) return toast(r.error || "操作失败", true);
    toast(`已新建空档案，损坏文件保留为 ${r.corruptCopy}`);
    setTimeout(() => location.reload(), 800);
  };
  box.hidden = false;
}

function updateUndoBtn() {
  const btn = el("#undoBtn");
  if (!btn) return;
  btn.disabled = !S.undoAvailable || S.dataState === "corrupt";
  btn.title = btn.disabled ? "没有可撤销的操作" : "撤销上一步";
}

async function doUndo() {
  if (!S.undoAvailable) return toast("没有可撤销的操作", true);
  const r = await api("/api/undo", { method: "POST", body: {} });
  if (!r.ok) return toast(r.error || "撤销失败", true);
  toast(`已撤销上一步，当前 ${r.works} 部作品`);

}

/* 恢复备份的完整流程：预览数量差异和风险 → 用户确认 → 恢复 */
async function restoreBackup(kind, name) {
  const p = await api("/api/backups/preview", { method: "POST", body: { kind, name } });
  if (!p.ok) { toast(p.error || "备份不可用", true); return false; }
  const cur = p.current || {}, st = p.stats || {};
  let msg = `备份内容：${st.works} 部作品 / ${st.series} 个系列\n当前档案：${cur.works} 部作品 / ${cur.series} 个系列`;
  if (p.warnings && p.warnings.length) msg += `\n\n注意：\n· ${p.warnings.join("\n· ")}`;
  msg += "\n\n恢复前会自动保存当前状态的安全快照。确定恢复这个备份？";
  if (!confirm(msg)) return false;
  const r = await api("/api/backups/restore", { method: "POST", body: { kind, name, confirm: "恢复" } });
  if (!r.ok) { toast(r.error || "恢复失败", true); return false; }
  toast(`已恢复：${r.count} 部作品，安全快照 ${r.safety || "已保存"}`);
  return true;
}

function reloadAll() {
  return dataQueue(() => refreshSnapshot(false));
}

async function refreshSnapshot(afterMutation) {
  const b = await requestApi("/api/bootstrap");
  if (!ArchiveV2.core.validSnapshot(b)) {
    if (afterMutation || S.syncPending) {
     S.syncPending = true;
     el("#syncNotice").hidden = false;
    } else toast(b.error || "刷新失败", true);
    return false;
  }
  S.works = b.works;
  S.series = b.series;
  S.settings = b.settings || S.settings;
  S.undoAvailable = Boolean(b.undoAvailable);
  S.dataState = b.dataState || "normal";
  S.backups = b.backups || [];
  S.syncPending = false;
  el("#syncNotice").hidden = true;
  if (S.currentSeriesId && !seriesById(S.currentSeriesId)) closeDrawer();
  updateUndoBtn();
  if (S.dataState === "corrupt") { showCorrupt(b); return false; }
  renderTabs(); renderStatusChips(); renderWall(); renderStats(); renderHome();
  ArchiveV2.collection?.sidebar();
  ArchiveV2.collection?.render(S.view);
  if (S.currentSeriesId) renderSeriesDrawer();
  if (immersiveView) immersiveView.refresh();
  return true;
}

function catLabel(key) {
  const c = S.categories.find(x => x.key === key);
  return c ? c.label : key;
}
function statusLabel(work) {
  const cat = S.categories.find(c => c.key === work.category);
  return (cat && cat.statuses[work.status]) || GENERIC_STATUS[work.status] || "未开始";
}
function genericLabel(key) {
  return GENERIC_STATUS[key] || key;
}

/* ------------------------------------------------------------ 筛选与墙 */
function renderTabs() {
  const counts = { all: S.works.length };
  CAT_ORDER.forEach(k => counts[k] = 0);
  S.works.forEach(w => { counts[w.category] = (counts[w.category] || 0) + 1; });
  const tabs = [["all", "全部"]].concat(CAT_ORDER.map(k => [k, catLabel(k)]));
  el("#tabs").innerHTML = tabs.map(([k, label]) =>
    `<button class="tab ${S.filters.cat === k ? "active" : ""}" data-cat="${k}" aria-pressed="${S.filters.cat === k}">${esc(label)}<span class="count">${counts[k] || 0}</span></button>`
  ).join("");
  elAll("#tabs .tab").forEach(b => b.onclick = () => {
    S.filters.cat = b.dataset.cat;
    S.filters.status = "all";
    renderTabs(); renderStatusChips(); renderWall();
    ArchiveV2.collection?.sidebar();
  });
}

function renderStatusChips() {
  const keys = ["all", "active", "completed", "planned", "paused", "dropped", "not_started"];
  const cat = S.filters.cat;
  const labels = { all: "全部状态" };
  keys.slice(1).forEach(k => labels[k] = cat === "all" ? genericLabel(k) : ((S.categories.find(c => c.key === cat) || {}).statuses || GENERIC_STATUS)[k]);
  el("#statusChips").innerHTML = keys.map(k =>
    `<button class="chip ${S.filters.status === k ? "active" : ""}" data-status="${k}" aria-pressed="${S.filters.status === k}">${esc(labels[k])}</button>`
  ).join("");
  elAll("#statusChips .chip").forEach(b => b.onclick = () => {
    S.filters.status = b.dataset.status;
    renderStatusChips(); renderWall();
  });
}

function timeCutoff(preset) {
  const now = new Date();
  if (preset === "y") return `${now.getFullYear()}-01-01`;
  if (preset === "m12") { const d = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate()); return d.toISOString().slice(0, 10); }
  if (preset === "y3") return `${now.getFullYear() - 3}-01-01`;
  return null;
}

function visibleWorks() {
  const f = S.filters;
  const cutoff = timeCutoff(f.time);
  const q = f.q.trim().toLowerCase();
  let list = S.works.filter(w => {
    if (f.cat !== "all" && w.category !== f.cat) return false;
    if (f.status !== "all" && w.status !== f.status) return false;
    if (cutoff && (w.createdAt || "").slice(0, 10) < cutoff) return false;
    if (q) {
      const hay = [w.title, w.originalTitle, (w.aliases || []).join(" "), (w.tags || []).join(" "), w.summary,
        (w.creators || []).map(c => c.role + c.name).join(" "),
        (w.infobox || []).map(i => i.key + i.value).join(" "),
        (w.userFields || []).map(i => i.key + i.value).join(" "),
        (w.experiences || []).map(e => e.content).join(" ")].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const sort = f.sort;
  list.sort((a, b) => {
    if (sort === "scoreDesc") return (b.rating ?? -1) - (a.rating ?? -1);
    if (sort === "scoreAsc") return (a.rating ?? 99) - (b.rating ?? 99);
    if (sort === "title") return (a.title || "").localeCompare(b.title || "", "zh");
    if (sort === "activity") return (b.lastExperienceAt || b.createdAt || "").localeCompare(a.lastExperienceAt || a.createdAt || "");
    return (b.createdAt || "").localeCompare(a.createdAt || "");
  });
  return list;
}

function seriesById(id) { return S.series.find(s => s.id === id) || null; }
function seriesNameOf(w) { const s = w.primarySeriesId ? seriesById(w.primarySeriesId) : null; return s ? s.name : ""; }

function renderWall() {
  const wall = el("#wall");
  const list = visibleWorks();
  const items = ArchiveV2.core.exhibitionItems(list, S.series, S.filters);
  wall.className = "wall exhibit-grid" + (items.some(item => item.type === "series") ? " has-series" : "");
  if (!items.length) {
    wall.innerHTML = `<div class="empty">${ICONS.archive}<div>${S.works.length ? "当前筛选下没有作品" : "档案还是空的。点右上角「添加作品」，从 Bangumi / 豆瓣 / 微信读书 / Steam 拉取信息，或粘贴链接自动填写。"}</div></div>`;
  } else {
    wall.innerHTML = items.map(item => item.type === "series"
      ? ArchiveV2.cards.seriesCard(item.entity, item)
      : ArchiveV2.cards.workCard(item.entity, {
        category: catLabel(item.entity.category), status: statusLabel(item.entity), series: seriesNameOf(item.entity),
      })).join("");
  }
  ArchiveV2.cards.bindWall(wall, {
    openWork: openCurrentWork,
    openSeries: openCurrentSeries,
    openImmersive, openSeriesImmersive,
  });
  el("#enterExhibit").disabled = !list.length;
  applyWallDensity();
  requestAnimationFrame(() => {
    if (wall.isConnected) applyWallDensity();
  });
}

function openImmersive(id = null, surface = "overlay") {
  const list = visibleWorks();
  const entities = ArchiveV2.core.exhibitionItems(list, S.series, S.filters).map(item => ({ type: item.type, id: item.entity.id }));
  if (!entities.length) return toast("当前筛选下没有可浏览的作品");
  const selected = id ? entities.find(item => item.id === id) : entities[0];
  const current = selected || entities[0];
  ensureImmersive();
  if (current.type === "series") {
    const filtered = S.filters.cat !== "all" || S.filters.status !== "all" || S.filters.time !== "all" || S.filters.q.trim();
    immersiveView.openSeries(current.id, surface, filtered ? list.filter(work => work.primarySeriesId === current.id).map(work => work.id) : null, entities);
  } else {
    const workIds = entities.filter(item => item.type === "work").map(item => item.id);
    immersiveView.open(workIds, current.id, surface, "全部作品", entities);
  }
}

function openSeriesImmersive(id, surface = "overlay") {
  if (!seriesById(id)) return;
  if (el("#seriesManager")?.classList.contains("show")) closeDrawer();
  ensureImmersive();
  if (S.view === "archive" || (S.view === "home" && surface === "fullscreen")) {
    const list = visibleWorks();
    const entities = ArchiveV2.core.exhibitionItems(list, S.series, S.filters).map(item => ({ type: item.type, id: item.entity.id }));
    if (S.view === "archive" && S.filters.group === "flat" && entities.length) {
      const filtered = S.filters.cat !== "all" || S.filters.status !== "all" || S.filters.time !== "all" || S.filters.q.trim();
      return immersiveView.openSeries(id, surface, filtered ? list.filter(work => work.primarySeriesId === id).map(work => work.id) : null, entities);
    }
    if (entities.some(item => item.type === "series" && item.id === id)) {
      const filtered = S.filters.cat !== "all" || S.filters.status !== "all" || S.filters.time !== "all" || S.filters.q.trim();
      return immersiveView.openSeries(id, surface, filtered ? list.filter(work => work.primarySeriesId === id).map(work => work.id) : null, entities);
    }
    if (S.view === "home" && surface === "fullscreen") {
      const homeQueue = ArchiveV2.homeFeed?.activeWorks(S.works, S.settings?.home_hidden_work_ids) || S.works.filter(work => work.status === "active");
      const queue = homeQueue.map(work => ({type:"work",id:work.id}));
      if (queue.length) return immersiveView.openSeries(id, surface, null, queue);
    }
  }
  immersiveView.openSeries(id, surface);
}

function ensureImmersive() {
  if (!immersiveView) {
    immersiveView = ArchiveV2.immersive.create({
      root: el("#immersiveRoot"), getWork: findWork, getWorks: () => S.works,
      getSeries: seriesById, getSeriesLinks: work => (work.seriesLinks || []).map(link => ({id:link.id,name:seriesById(link.id)?.name || "（系列已删除）",role:S.seriesRoles[link.role] || link.role})),
      openEdit: openImmersiveEdit,
      onManageSeries: id => openSeries(id),
      getBackgroundSettings: () => S.settings || {},
      onRateWork: async (id, score, reason) => {
        const result = await api(`/api/works/${id}/rating`, { method: "POST", body: { score, reason } });
        if (!result.ok) return toast(result.error || "评分保存失败", true);
        toast("评分已记录");
      },
      onAddExperience: async (id, experience) => {
        const result = await api(`/api/works/${id}/experience`, { method: "POST", body: experience });
        if (!result.ok) return toast(result.error || "经历添加失败", true);
        toast("经历已添加");
      },
      onDeleteExperience: async (id, experienceId) => {
        if (!experienceId) return;
        const result = await api(`/api/works/${id}/experience/${experienceId}`, { method: "DELETE" });
        if (!result.ok) return toast(result.error || "经历删除失败", true);
        toast("经历已删除");
      },
      onAddUserField: async (id, key, value) => {
        const work = findWork(id), name = key.trim(), text = value.trim();
        if (!work || !name || !text) return toast("字段名和值都要填写", true);
        const result = await api(`/api/works/${id}`, { method: "PATCH", body: { userFields: [...(work.userFields || []), { key: name, value: text }] } });
        if (!result.ok) return toast(result.error || "字段添加失败", true);
        toast("字段已添加");
      },
      onDeleteWork: async id => {
        const work = findWork(id);
        if (!work || !confirm(`确定删除《${work.title}》？该作品的评分与经历记录会一起删除。`)) return;
        const result = await api(`/api/works/${id}`, { method: "DELETE" });
        if (!result.ok) return toast(result.error || "删除失败", true);
        toast("作品已删除");
      },
      onOpenSeries: id => immersiveView?.enterRelatedSeries(id),
      notify: toast,
      getLabels: work => ({ category: catLabel(work.category), status: statusLabel(work), series: seriesNameOf(work),
        statusOptions: (S.categories.find(category => category.key === work.category) || {}).statuses || GENERIC_STATUS,
        recordStatus: status => ((S.categories.find(category => category.key === work.category) || {}).statuses || GENERIC_STATUS)[status] || status }),
      mainRoots: () => [el("#topbar"), el("#appSidebar"), el("#sidebarScrim"), el(".skip-link"), el("#homeView"), el("#archiveView"), el("#seriesView"), el("#seriesManager")].filter(Boolean),
      captureOrigin: workId => {
        const active = document.activeElement;
        if (S.view === "series") {
          const tile = elAll("#seriesCollection [data-collection-series]").find(card => card.dataset.collectionSeries === workId);
          return { view: S.view, scrollY: window.scrollY, seriesTileId: tile?.dataset.collectionSeries, offset: tile?.getBoundingClientRect().top };
        }
        const cards = elAll("#wall .card, #wall .series-card");
        const work = findWork(workId);
        const homeAnchor = active.closest(".home-slide") || elAll(".home-slide").find(slide => slide.dataset.id === workId);
        const anchor = homeAnchor || active.closest(".card, .series-card") || cards.find(card => card.dataset.id === workId || card.dataset.sid === workId || card.dataset.sid === work?.primarySeriesId);
        return { view: S.view, scrollY: window.scrollY, focusId: active.id,
          workId: anchor?.dataset.id, seriesId: anchor?.dataset.sid, offset: anchor?.getBoundingClientRect().top };
      },
      restoreOrigin: saved => requestAnimationFrame(() => {
        if (!saved) return;
        setAppView(saved.view || "archive", false);
        const anchor = saved.view === "series" ?
          elAll("#seriesCollection [data-collection-series]").find(card => card.dataset.collectionSeries === saved.seriesTileId) :
          elAll("#wall .card, #wall .series-card, .home-slide").find(card => saved.workId ? card.dataset.id === saved.workId : saved.seriesId && card.dataset.sid === saved.seriesId);
        if (anchor && saved.offset != null) window.scrollTo(0, window.scrollY + anchor.getBoundingClientRect().top - saved.offset);
        else window.scrollTo(0, saved.scrollY);
        const target = (saved.focusId && document.getElementById(saved.focusId)) ||
          anchor || el(saved.view === "series" ? '#seriesCollection [aria-pressed="true"]' : saved.view === "home" ? "#homeContinueBtn" : "#enterExhibit");
        target?.focus({ preventScroll: true });
      }),
    });
  }
}

function renderStats() {
  const rated = S.works.filter(w => w.rating != null);
  const avg = rated.length ? (rated.reduce((s, w) => s + w.rating, 0) / rated.length) : null;
  const active = S.works.filter(w => w.status === "active").length;
  el("#stats").innerHTML = [
    `<span><b>${S.works.length}</b>部作品</span>`,
    S.series.length ? `<span><b>${S.series.length}</b>个系列</span>` : "",
    `<span><b>${rated.length}</b>部已评分</span>`,
    avg != null ? `<span><b>${avg.toFixed(2)}</b>平均分</span>` : "",
    `<span><b>${active}</b>部进行中</span>`,
  ].join("");
}

/* ------------------------------------------------------------ 首页进行中作品 */
let homeHiddenDraft = null;

function activeHomeWorks() {
  return ArchiveV2.homeFeed.activeWorks(S.works, S.settings?.home_hidden_work_ids);
}

function homeRecentRecord(work) {
  return (work.experiences || []).slice().sort((a, b) => (b.date || "").localeCompare(a.date || ""))[0] || null;
}

function renderHome() {
  ArchiveV2.collection?.home();
}

function setAppView(view, scroll = true) {
  const titles = ArchiveV2.collection?.headings || {home:"正在进行",archive:"作品库"};
  S.view = Object.hasOwn(titles, view) ? view : "home";
  const shell = el("#appShell");
  if (shell) shell.dataset.view = S.view;
  for (const key of Object.keys(titles)) {
    const section = el(`#${key}View`);
    if (section) section.hidden = S.view !== key;
  }
  document.documentElement.dataset.homeSnap = "false";
  el("#topbarContext").textContent = titles[S.view];
  elAll("[data-app-nav]").forEach(button => {
    const current = button.dataset.appNav === S.view;
    if (current) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  ArchiveV2.collection?.sidebar();
  ArchiveV2.collection?.render(S.view);
  closeSidebar();
  if (S.view === "archive") requestAnimationFrame(() => applyWallDensity());
  if (scroll) window.scrollTo({ top: 0, behavior: "auto" });
}

function openHomeImmersive(id) {
  const list = activeHomeWorks();
  const currentId = id || list[0]?.id;
  if (!currentId || !list.some(work => work.id === currentId)) return toast("首页没有可浏览的进行中作品");
  ensureImmersive();
  immersiveView.open(list.map(work => work.id), currentId, "fullscreen", "正在进行", list.map(work => ({type:"work",id:work.id})));
}

function renderHiddenWorksManager() {
  const body = el("#hiddenWorksBody");
  if (!body) return;
  const hidden = ArchiveV2.homeFeed.normalizeHidden(homeHiddenDraft || []);
  const active = ArchiveV2.homeFeed.sortRecent(S.works.filter(work => work.status === "active"));
  const inactiveHidden = ArchiveV2.homeFeed.hiddenWorks(S.works, hidden).filter(work => work.status !== "active");
  body.innerHTML = `<div class="home-manager-group"><h3>首页展示</h3><p class="muted-note">取消勾选的进行中作品会从首页隐藏，作品状态和展厅内容不变。</p>${active.length ? active.map(work => `<label class="home-manager-row"><span class="home-manager-title">${esc(work.title)}</span><small>${esc(catLabel(work.category))}</small><input type="checkbox" data-home-visible="${esc(work.id)}" ${hidden.includes(work.id) ? "" : "checked"}><span class="home-checkmark"></span></label>`).join("") : `<div class="muted-note">当前没有进行中的作品。</div>`}</div>
    <div class="home-manager-group"><h3>已隐藏的非进行中作品</h3>${inactiveHidden.length ? inactiveHidden.map(work => `<div class="home-manager-row"><span class="home-manager-title">${esc(work.title)}</span><small>${esc(statusLabel(work))}</small><button class="btn btn-sm" data-home-restore="${esc(work.id)}">移出隐藏名单</button></div>`).join("") : `<div class="muted-note">没有已隐藏的非进行中作品。</div>`}</div>`;
  elAll("[data-home-visible]", body).forEach(input => input.onchange = () => {
    homeHiddenDraft = ArchiveV2.homeFeed.setHidden(homeHiddenDraft, input.dataset.homeVisible, !input.checked);
  });
  elAll("[data-home-restore]", body).forEach(button => button.onclick = () => {
    homeHiddenDraft = ArchiveV2.homeFeed.setHidden(homeHiddenDraft, button.dataset.homeRestore, false);
    renderHiddenWorksManager();
  });
}

function openHomeManager() {
  if (!modalIsOpen("#hiddenWorksModal")) rememberOverlayFocus();
  homeHiddenDraft = ArchiveV2.homeFeed.normalizeHidden(S.settings?.home_hidden_work_ids);
  renderHiddenWorksManager();
  setModalState("#hiddenWorksModal", true);
  focusAfterRender("#hiddenWorksClose");
}

function closeHomeManager() {
  if (!modalIsOpen("#hiddenWorksModal")) return;
  homeHiddenDraft = null;
  setModalState("#hiddenWorksModal", false);
  restoreOverlayFocus();
}

async function saveHomeManager() {
  const hidden = ArchiveV2.homeFeed.normalizeHidden(homeHiddenDraft);
  const button = el("#hiddenWorksSave");
  button.disabled = true;
  try {
    const result = await api("/api/settings", { method: "POST", body: { home_hidden_work_ids: hidden } });
    if (!result.ok) return toast(result.error || "首页设置保存失败", true);
    S.settings = result.settings || S.settings;
    renderHome();
    closeHomeManager();
    toast("首页作品设置已保存");
  } finally { button.disabled = false; }
}

function syncSidebarToggle() {
  const mobile = window.matchMedia("(max-width: 900px)").matches;
  const expanded = mobile ? document.body.classList.contains("sidebar-open") : document.documentElement.dataset.sidebarCollapsed !== "true";
  const label = expanded ? (mobile ? "关闭导航" : "收起导航") : "打开导航";
  const button = el("#sidebarToggle");
  button.setAttribute("aria-expanded", String(expanded));
  button.setAttribute("aria-label", label);
  button.title = label;
}

function toggleSidebar() {
  if (window.matchMedia("(max-width: 900px)").matches) {
    if (document.body.classList.contains("sidebar-open")) closeSidebar();
    else openSidebar();
    return;
  }
  const collapsed = document.documentElement.dataset.sidebarCollapsed !== "true";
  document.documentElement.dataset.sidebarCollapsed = String(collapsed);
  try { localStorage.setItem("grdag_sidebar_collapsed", String(collapsed)); } catch (_) { /* 本次收起状态仍然生效。 */ }
  syncSidebarToggle();
  applyWallDensity();
}

function openSidebar() {
  document.body.classList.add("sidebar-open");
  el("#sidebarScrim").hidden = false;
  syncSidebarToggle();
  focusAfterRender("#navHome");
}

function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  el("#sidebarScrim").hidden = true;
  syncSidebarToggle();
}

async function setHomeWorkHidden(id, shouldHide, button) {
  if (button) button.disabled = true;
  const current = ArchiveV2.homeFeed.normalizeHidden(S.settings?.home_hidden_work_ids);
  const home_hidden_work_ids = ArchiveV2.homeFeed.setHidden(current, id, shouldHide);
  try {
    const result = await api("/api/settings", { method: "POST", body: { home_hidden_work_ids } });
    if (!result.ok) return toast(result.error || "首页设置保存失败", true);
    S.settings = result.settings || S.settings;
    renderHome();
    toast(shouldHide ? "已从首页隐藏，可在管理中恢复" : "作品已显示在首页");
  } finally { if (button) button.disabled = false; }
}

function handleHomeAction(event) {
  const button = event.target.closest("[data-home-action]");
  if (!button) return;
  const action = button.dataset.homeAction, id = button.dataset.homeId;
  if (action === "immersive") openHomeImmersive(id);
  else if (action === "details" && id) openCurrentWork(id);
  else if (action === "hide" && id) setHomeWorkHidden(id, true, button);
  else if (action === "manage") openHomeManager();
  else if (action === "archive") setAppView("archive");
  else if (action === "add") openAdd();
}

function openCurrentWork(id) {
  if (!findWork(id)) return;
  if (el("#seriesManager")?.classList.contains("show")) closeDrawer();
  ensureImmersive();
  if (immersiveView.isOpen()) return immersiveView.playWork(id);
  const list = S.view === "home" ? (ArchiveV2.homeFeed?.activeWorks(S.works, S.settings?.home_hidden_work_ids) || S.works.filter(work => work.status === "active")) :
    S.view === "archive" ? visibleWorks() : S.works;
  const works = list.some(work => work.id === id) ? list : [findWork(id), ...list];
  const entities = S.view !== "archive" ? works.map(work => ({type:"work",id:work.id})) :
    ArchiveV2.core.exhibitionItems(works, S.series, S.filters).map(item => ({type:item.type,id:item.entity.id}));
  const focused = entities.find(item => item.id === id);
  if (focused?.type === "series") return immersiveView.openSeries(id, "fullscreen", null, entities);
  immersiveView.open(entities.filter(item => item.type === "work").map(item => item.id), id, "fullscreen", S.view === "archive" ? "全部作品" : (ArchiveV2.collection?.headings[S.view] || "正在进行"), entities);
}

function openCurrentSeries(id) {
  if (!seriesById(id)) return;
  openSeriesImmersive(id, "fullscreen");
}

/* ------------------------------------------------------------ 系列管理面板 */
const overlayFocusStack = [];
function rememberOverlayFocus() {
  const a = document.activeElement;
  if (a && a !== document.body) overlayFocusStack.push(a);
}
function restoreOverlayFocus() {
  const a = overlayFocusStack.pop();
  if (a && document.contains(a)) a.focus({ preventScroll: true });
}
function setSeriesManagerState(open) {
  const drawer = el("#seriesManager"), backdrop = el("#seriesManagerBackdrop");
  if (drawer) { drawer.classList.toggle("show", open); drawer.setAttribute("aria-hidden", open ? "false" : "true"); }
  if (backdrop) { backdrop.classList.toggle("show", open); backdrop.setAttribute("aria-hidden", open ? "false" : "true"); }
}
function focusAfterRender(sel) {
  requestAnimationFrame(() => { const t = el(sel); if (t) t.focus({ preventScroll: true }); });
}

function findWork(id) { return S.works.find(w => w.id === id); }

function openSeries(sid, keepFocus = false) {
  const s = seriesById(sid);
  if (!s) return;
  const wasOpen = el("#seriesManager").classList.contains("show");
  if (!wasOpen && !keepFocus) rememberOverlayFocus();
  S.currentSeriesId = sid;
  S.seriesRating = s.rating == null ? 8 : s.rating;
  setSeriesManagerState(true);
  renderSeriesDrawer();
  if (!wasOpen) focusAfterRender("#seriesManagerClose");
}

function closeDrawer() {
  if (!el("#seriesManager").classList.contains("show")) return;
  ArchiveV2.bgmEditor.stop(el('#seriesManager'));
  restoreOverlayFocus();
  setSeriesManagerState(false);
  S.currentSeriesId = null;
}

function kvHTML(k, v, wrap) {
  return `<div class="kv"><div class="k">${esc(k)}</div><div class="v ${wrap ? "wrap" : ""}" title="${esc(v)}">${esc(v)}</div></div>`;
}

function sparkline(history) {
  if (!history || history.length < 2) return "";
  const n = history.length;
  const W = 320, H = 64, pad = 8;
  const x = i => pad + (i * (W - pad * 2)) / (n - 1);
  const y = v => H - pad - (Math.max(0, Math.min(10, v)) / 10) * (H - pad * 2);
  let d = "";
  history.forEach((h, i) => { d += `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(h.score).toFixed(1)} `; });
  const dots = history.map((h, i) => `<circle class="spark-dot" cx="${x(i).toFixed(1)}" cy="${y(h.score).toFixed(1)}" r="2.6"/>`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="评分变化趋势">
    <line class="spark-base" x1="${pad}" y1="${y(5)}" x2="${W - pad}" y2="${y(5)}"/>
    <path class="spark-line" d="${d}" fill="none"/>
    ${dots}
  </svg>`;
}

function renderSeriesDrawer() {
  const s = seriesById(S.currentSeriesId);
  if (!s) return;
  const hist = s.ratingHistory || [];
  const exps = (s.experiences || []).slice().sort((a, b) =>
    (b.date || "").localeCompare(a.date || "") || (b.createdAt || "").localeCompare(a.createdAt || ""));
  const coverSrc = s.coverUrl || (s.members.find(m => m.coverUrl) || {}).coverUrl || "";
  el("#seriesManagerHead").innerHTML = `
    <div class="series-manager-cover${coverSrc ? " has-cover" : ""}">
      <div class="cover-fallback"><span>系列</span></div>
      ${coverSrc ? `<img src="${esc(coverSrc)}" alt="">` : ""}
    </div>
    <div style="min-width:0;flex:1">
      <h2 class="series-manager-title" id="seriesManagerTitle">${esc(s.name)}</h2>
      <div class="series-manager-sub">${esc([s.kindLabel, s.yearRange, s.memberCount ? `${s.memberCount} 部作品` : "空系列",
        ...(s.creators || []).map(c => c.role + " " + c.name)].filter(Boolean).join(" · "))}</div>
      <div class="series-manager-tags">
        <span class="pill" data-status="${s.baseStatus}">${esc(s.baseStatusLabel)}</span>
        ${(s.tags || []).slice(0, 6).map(t => `<span class="tag">${esc(t)}</span>`).join("")}
        <button type="button" class="btn btn-sm" id="seriesEnterExhibit">沉浸浏览 ↗</button>
      </div>
    </div>
    <button class="icon-btn series-manager-close" id="seriesManagerClose" title="关闭" aria-label="关闭系列管理">${ICONS.close}</button>`;

  const body = el("#seriesManagerBody");
  const html = [];
  const pct = s.memberCount ? Math.round((s.completedCount / s.memberCount) * 100) : 0;

  /* 概览 */
  html.push(`<section class="section">
    <div class="section-head"><h3>系列概览</h3><div class="line"></div></div>
    <div class="prog"><div class="prog-bar" style="width:${pct}%"></div><span>已完成 ${esc(s.progress)}</span></div>
    <div class="field-grid" style="margin-top:12px">
      ${kvHTML("成员", String(s.memberCount))}
      ${kvHTML("已完成", String(s.completedCount))}
      ${kvHTML("进行中", String(s.activeCount))}
      ${kvHTML("系列均分", s.avgRating != null ? `${fmtScore(s.avgRating)}（${s.ratedCount}/${s.memberCount}）` : "成员都没评分")}
      ${s.yearRange ? kvHTML("年代", s.yearRange) : ""}
      ${s.catMix.length ? kvHTML("分类分布", s.catMix.map(c => `${c.label} ${c.count}`).join(" · "), true) : ""}
    </div>
    ${s.summary ? `<div class="series-summary">${esc(s.summary)}</div>` : `<div class="muted-note" style="margin-top:10px">还没有系列简介。只写“这个系列是什么”，单部剧情留到各作品里。</div>`}
  </section>`);

  /* 系列评分 */
  html.push(`<section class="section">
    <div class="section-head"><h3>系列评分</h3><div class="line"></div><span class="hint">独立于成员评分</span></div>
    <div class="rating-top">
      <div class="rating-big ${s.rating == null ? "none" : ""}">${s.rating == null ? "未评分" : fmtScore(s.rating)}</div>
      <div class="rating-meta">${hist.length ? `共修改 ${hist.length} 次` : "还没有系列评分"}<br>10 分制，0.5 步进</div>
    </div>
    <div class="rating-controls">
      <input type="range" id="sRatingRange" min="0" max="10" step="0.5" value="${S.seriesRating}">
      <div class="score-num" id="sRatingNum">${fmtScore(S.seriesRating)}</div>
    </div>
    <div class="rating-controls">
      <input class="reason" id="sRatingReason" placeholder="本次修改原因（可选）">
      <button class="btn btn-primary btn-sm" id="sRatingSave">记录评分</button>
    </div>
    ${sparkline(hist)}
    ${hist.length ? `<div class="history">${hist.slice().reverse().map(h => `
      <div class="history-row">
        <div class="t">${esc((h.at || "").replace("T", " ").slice(0, 16))}</div>
        <div class="delta">${h.prev == null ? "初评" : `<span class="${h.score >= h.prev ? "up" : "down"}">${fmtScore(h.prev)} → </span>`}<b>${fmtScore(h.score)}</b></div>
        <div class="r" title="${esc(h.reason || "")}">${esc(h.reason || "")}</div>
      </div>`).join("")}</div>` : ""}
  </section>`);

  /* 成员 */
  const pickList = S.works.filter(w => !(w.seriesLinks || []).some(l => l.id === s.id));
  html.push(`<section class="section">
    <div class="section-head"><h3>成员</h3><div class="line"></div><span class="hint">手动划分，可跨分类</span></div>
    ${s.members.length ? `<div class="member-list">${s.members.map(m => `
      <div class="member-row" data-wid="${m.id}" tabindex="0" role="button" aria-label="查看成员《${esc(m.title)}》">
        <div class="mr-cover${m.coverUrl ? " has-cover" : ""}">
          <div class="cover-fallback"><span>${esc(catLabel(m.category))}</span></div>
          ${m.coverUrl ? `<img src="${esc(m.coverUrl)}" alt="">` : ""}
        </div>
        <div class="mr-main">
          <div class="mr-title">${esc(m.title)}</div>
          <div class="mr-meta">${esc([catLabel(m.category), m.year, S.seriesRoles[m.role] || m.role].filter(Boolean).join(" · "))}</div>
        </div>
        <span class="pill" data-status="${m.status}">${esc(m.statusLabel)}</span>
        <span class="mr-score ${m.rating == null ? "none" : ""}">${m.rating == null ? "—" : fmtScore(m.rating)}</span>
        <button class="btn btn-xs" data-msdel="${m.id}">移出</button>
      </div>`).join("")}</div>` : `<div class="muted-note">还没有成员。从下面选一部已有作品加进来。</div>`}
    <div class="search-row" style="margin-top:10px">
      <select id="memberPick">${pickList.map(w => `<option value="${w.id}">${esc(w.title)} · ${esc(catLabel(w.category))}</option>`).join("") || `<option value="">（可选作品为空）</option>`}</select>
      <select id="memberRole" class="mini">${Object.entries(S.seriesRoles).map(([k, v]) => `<option value="${k}" ${k === "main" ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      <button class="btn btn-sm" id="memberAdd">添加成员</button>
    </div>
  </section>`);

  /* 系列经历 */
  html.push(`<section class="section">
    <div class="section-head"><h3>系列经历</h3><div class="line"></div><span class="hint">跨作品的整体记录</span></div>
    <div class="exp-form">
      <input type="date" id="sExpDate" value="${new Date().toISOString().slice(0, 10)}">
      <select id="sExpStatus"><option value="">（不设状态）</option>${Object.entries(GENERIC_STATUS).filter(([k]) => k !== "not_started").map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
      <textarea id="sExpText" placeholder="如：开始补这个系列 / 先把正传打完（可空）"></textarea>
      <button class="btn btn-sm" id="sExpAdd">添加</button>
    </div>
    ${exps.length ? `<div class="timeline">${exps.map(e => `
      <div class="tl-item" ${e.status ? `data-status="${e.status}"` : ""}>
        <div class="tl-head">
          <span class="d">${esc(e.date || "")}</span>
          ${e.status ? `<span class="pill" data-status="${e.status}">${esc(genericLabel(e.status))}</span>` : ""}
          <button class="tl-del" data-sdel="${e.id}">删除</button>
        </div>
        ${e.content ? `<div class="tl-body">${esc(e.content)}</div>` : ""}
      </div>`).join("")}</div>` : `<div class="muted-note">还没有系列级经历。</div>`}
  </section>`);

  /* 系列信息 */
  html.push(`<section class="section">
    <div class="section-head"><h3>系列信息</h3><div class="line"></div></div>
    <div class="form-grid">
      <div class="form-item"><label>名称</label><input id="sName" value="${esc(s.name)}"></div>
      <div class="form-item"><label>原名</label><input id="sOrig" value="${esc(s.originalTitle || "")}"></div>
      <div class="form-item"><label>系列类型</label><select id="sKind">${Object.entries(S.seriesKinds).map(([k, v]) => `<option value="${k}" ${s.kind === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      <div class="form-item"><label>标签（逗号分隔）</label><input id="sTags" value="${esc((s.tags || []).join("，"))}"></div>
      <div class="form-item full"><label>代表图 URL（可留空，自动用成员封面）</label><input id="sCover" value="" placeholder="粘贴主视觉 / Logo 图片 URL"></div>
      ${ArchiveV2.backgroundEditor.form(s, 'sBackgrounds', '系列沉浸背景图片')}
      ${ArchiveV2.bgmEditor.form(s, 'seriesBgm')}
      <div class="form-item full"><label>系列简介</label><textarea id="sSummary" style="min-height:90px">${esc(s.summary || "")}</textarea></div>
      <div class="form-item full"><label>备注</label><input id="sNote" value="${esc(s.note || "")}"></div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
      <button class="btn btn-primary btn-sm" id="sSave">保存系列信息</button>
      <button class="btn btn-danger btn-sm" id="sDelete">删除系列</button>
    </div>
  </section>`);

  ArchiveV2.bgmEditor.stop(body);
  body.innerHTML = html.join("");
  ArchiveV2.bgmEditor.bind(body, 'seriesBgm', toast);
  ArchiveV2.backgroundEditor.bind(body, 'sBackgrounds', toast);

  el("#seriesManagerClose").onclick = closeDrawer;
  el("#seriesEnterExhibit").onclick = () => openSeriesImmersive(s.id);
  const rng = el("#sRatingRange");
  rng.oninput = () => { S.seriesRating = parseFloat(rng.value); el("#sRatingNum").textContent = fmtScore(S.seriesRating); };
  el("#sRatingSave").onclick = async () => {
    const r = await api(`/api/series/${s.id}/rating`, { method: "POST", body: { score: S.seriesRating, reason: el("#sRatingReason").value } });
    if (!r.ok) return toast(r.error || "保存失败", true);
    S.seriesRating = r.series.rating;
    renderSeriesDrawer(); renderWall(); toast("评分已记录");
  };
  elAll(".member-row", body).forEach(row => {
    row.onclick = (ev) => {
      if (ev.target.closest("[data-msdel]")) return;
      openCurrentWork(row.dataset.wid);
    };
    row.onkeydown = (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openCurrentWork(row.dataset.wid); }
    };
  });
  elAll("[data-msdel]", body).forEach(b => b.onclick = async (ev) => {
    ev.stopPropagation();
    const r = await api(`/api/series/${s.id}/members/${b.dataset.msdel}`, { method: "DELETE" });
    if (!r.ok) return toast(r.error || "移出失败", true);
    renderSeriesDrawer(); toast("已移出");
  });
  el("#memberAdd").onclick = async () => {
    const wid = el("#memberPick").value;
    if (!wid) return toast("没有可添加的作品", true);
    const r = await api(`/api/series/${s.id}/members`, { method: "POST", body: { workIds: [wid], role: el("#memberRole").value } });
    if (!r.ok) return toast(r.error || "添加失败", true);
    renderSeriesDrawer(); toast("成员已添加");
  };
  el("#sExpAdd").onclick = async () => {
    const body2 = { date: el("#sExpDate").value, status: el("#sExpStatus").value, content: el("#sExpText").value };
    const r = await api(`/api/series/${s.id}/experience`, { method: "POST", body: body2 });
    if (!r.ok) return toast(r.error || "添加失败", true);
    renderSeriesDrawer(); toast("经历已添加");
  };
  elAll("[data-sdel]", body).forEach(b => b.onclick = async () => {
    const r = await api(`/api/series/${s.id}/experience/${b.dataset.sdel}`, { method: "DELETE" });
    if (!r.ok) return toast(r.error || "删除失败", true);
    renderSeriesDrawer();
  });
  el("#sSave").onclick = async () => {
    let bgm, backgrounds;
    try { backgrounds = ArchiveV2.backgroundEditor.read(body, 'sBackgrounds'); bgm = await ArchiveV2.bgmEditor.read(body, 'seriesBgm'); } catch (error) { return toast(error.message, true); }
    const payload = {
      name: el("#sName").value.trim(), originalTitle: el("#sOrig").value.trim(),
      kind: el("#sKind").value, summary: el("#sSummary").value.trim(),
      tags: el("#sTags").value.split(/[，,]/).map(x => x.trim()).filter(Boolean),
      note: el("#sNote").value.trim(),
      bgm,
      immersiveBackgroundUrls: backgrounds,
    };
    const cov = el("#sCover").value.trim();
    if (cov) payload.cover = cov;
    if (!payload.name) return toast("系列名称不能为空", true);
    const r = await api(`/api/series/${s.id}`, { method: "PATCH", body: payload });
    if (!r.ok) return toast(r.error || "保存失败", true);
     renderSeriesDrawer(); toast("已保存");
  };
  el("#sDelete").onclick = async () => {
    if (!confirm(`删除系列《${s.name}》？成员作品不会被删，只会解除归属。`)) return;
    const r = await api(`/api/series/${s.id}`, { method: "DELETE" });
    if (!r.ok) return toast(r.error || "删除失败", true);
    closeDrawer(); toast("系列已删除");
  };
}

function replaceSeries(s) {
  const i = S.series.findIndex(x => x.id === s.id);
  if (i >= 0) S.series[i] = s; else S.series.push(s);
}

/* ------------------------------------------------------------ 浮层状态 */
function setModalState(selector, open) {
  const m = el(selector);
  if (!m) return;
  m.classList.toggle("show", open);
  m.setAttribute("aria-hidden", open ? "false" : "true");
}
function modalIsOpen(selector) {
  const m = el(selector);
  return !!(m && m.classList.contains("show"));
}
function activeOverlayRoot() {
  for (const sel of ["#addModal", "#seriesModal", "#settingsModal", "#hiddenWorksModal", "#musicModal"]) {
    if (modalIsOpen(sel)) return el(`${sel} .modal-box`);
  }
  if (el("#seriesManager")?.classList.contains("show")) return el("#seriesManager");
  if (immersiveView) return immersiveView.overlayRoot();
  return null;
}

/* ------------------------------------------------------------ 新建系列 */
function openSeriesModal(opts = {}) {
  if (!modalIsOpen("#seriesModal")) rememberOverlayFocus();
  S.seriesDraft = { mode: "create", attachTo: opts.attachTo || null };
  el("#seriesModalTitle").textContent = "新建系列";
  el("#seriesBody").innerHTML = `
    <div class="form-grid">
      <div class="form-item"><label>系列名称</label><input id="nsName" placeholder="例如 弹丸论破"></div>
      <div class="form-item"><label>原名</label><input id="nsOrig" placeholder="例如 ダンガンロンパ"></div>
      <div class="form-item"><label>系列类型</label><select id="nsKind">${Object.entries(S.seriesKinds).map(([k, v]) => `<option value="${k}" ${k === "mixed" ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      <div class="form-item"><label>标签（逗号分隔）</label><input id="nsTags" placeholder="如 悬疑，推理"></div>
      <div class="form-item full"><label>系列简介（只写系列是什么，不写单部剧情）</label><textarea id="nsSummary" style="min-height:90px"></textarea></div>
      <div class="form-item full"><label>代表图 URL（可留空）</label><input id="nsCover" placeholder="主视觉 / Logo 图片地址"></div>
    </div>
    <div class="tip">成员是手动添加的：创建后到系列集合页添加成员，或编辑作品时调整所属系列。</div>`;
  el("#seriesSave").textContent = "创建系列";
  setModalState("#seriesModal", true);
  setTimeout(() => { const n = el("#nsName"); if (n) n.focus(); }, 30);
}

async function saveSeriesDraft() {
  const name = (el("#nsName").value || "").trim();
  if (!name) return toast("系列名称不能为空", true);
  const payload = {
    name, originalTitle: (el("#nsOrig").value || "").trim(), kind: el("#nsKind").value,
    tags: (el("#nsTags").value || "").split(/[，,]/).map(x => x.trim()).filter(Boolean),
    summary: (el("#nsSummary").value || "").trim(),
    cover: (el("#nsCover").value || "").trim() || undefined,
  };
  const r = await api("/api/series", { method: "POST", body: payload });
  if (!r.ok) return toast(r.error || "创建失败", true);
  const attach = S.seriesDraft.attachTo;
  if (attach) {
    await api(`/api/series/${r.series.id}/members`, { method: "POST", body: { workIds: [attach], role: "main" } });
  }
  setModalState("#seriesModal", false);

  openCurrentSeries(r.series.id);
  toast("系列已创建");
}

function closeSeriesModal() {
  if (!modalIsOpen("#seriesModal")) return;
  restoreOverlayFocus();
  setModalState("#seriesModal", false);
}

function applyWork(work) {
  const i = S.works.findIndex(w => w.id === work.id);
  if (i >= 0) S.works[i] = work; else S.works.push(work);
}

/* ------------------------------------------------------------ TMDB 剪贴板导入 */
function tmdbKindLabel(draft) {
  return ((draft.source || {}).type === "tv") ? "电视剧" : "电影";
}
function tmdbInfoValue(draft, keys) {
  const info = draft.infobox || [];
  const lower = keys.map(k => k.toLowerCase());
  const hit = info.find(i => lower.includes(String(i.key || "").toLowerCase()));
  return hit ? hit.value : "";
}
function tmdbCreatorNames(draft, roles) {
  const list = draft.creators || [];
  return list.filter(c => roles.some(r => String(c.role || "").includes(r)))
    .map(c => c.name).filter(Boolean).join("、");
}
function supportsUnifiedBookmarklet(category) {
  return category === "movie" || category === "novel";
}

function tmdbImportHTML(a) {
  if (!a || !supportsUnifiedBookmarklet(a.category)) return "";
  const isMovie = a.category === "movie";
  return `
    <div class="tmdb-import" id="tmdbImportBox">
      <div class="refill-head">
        <h4>统一资料书签</h4>
        <span class="hint">在 ${isMovie ? "TMDB" : "优书网"} 详情页点击书签复制 JSON，粘贴到下方输入框即可自动识别并预览。</span>
      </div>
      <div class="tmdb-bookmark-note">
        <div class="tmdb-bookmark-title"><b>书签：导入个人娱乐档案</b><span>一个书签同时支持 TMDB 与优书网详情页。</span></div>
        <div class="tmdb-bookmark-actions">
          <button class="btn btn-sm" id="tmdbCopyBookmarklet">复制统一书签</button>
          ${isMovie ? `<a class="btn btn-ghost btn-sm tmdb-search-link is-disabled" id="tmdbSearchLink" target="_blank" rel="noopener noreferrer" aria-disabled="true">前往 TMDB 搜索</a>
          <span class="tmdb-search-hint" id="tmdbSearchHint">当前没有标题，请先在搜索框输入作品标题</span>` : `<a class="btn btn-ghost btn-sm tmdb-search-link is-disabled" id="youshuSearchLink" target="_blank" rel="noopener noreferrer" aria-disabled="true">前往优书网搜索</a>
          <span class="tmdb-search-hint" id="youshuSearchHint">当前没有标题，请先在搜索框输入作品标题</span>`}
        </div>
        <div class="tmdb-bookmark-help">Chrome / Edge：右键书签栏 → 添加网页；名称填「导入个人娱乐档案」，网址粘贴刚复制的脚本。之后在 TMDB 或优书网详情页点击该书签，回到这里把复制到的 JSON 粘进输入框。</div>
      </div>
      <div class="tmdb-preview" id="tmdbPreview">${a.tmdbPreview ? tmdbPreviewHTML(a) : (a.youshuPreview ? youshuPreviewHTML(a) : "")}</div>
    </div>`;
}

function tmdbSearchUrl(keyword) {
  return "https://www.themoviedb.org/search?query=" + encodeURIComponent(keyword);
}

function youshuSearchUrl(keyword) {
  return "https://www.youshu.me/modules/article/search.php?searchtype=all&searchkey=" + encodeURIComponent(keyword);
}

function currentTmdbTitle(a) {
  const fTitle = el("#fTitle");
  const fValue = fTitle ? (fTitle.value || "").trim() : "";
  if (fValue) return fValue;
  const rfKeyword = el("#rfKeyword");
  const rfValue = rfKeyword ? (rfKeyword.value || "").trim() : "";
  if (rfValue) return rfValue;
  const addKeyword = el("#addKeyword");
  const addValue = addKeyword ? (addKeyword.value || "").trim() : "";
  if (addValue) return addValue;
  if (a && a.draft && (a.draft.title || "").trim()) return a.draft.title.trim();
  if (a && a.tmdbPreview && a.tmdbPreview.draft && (a.tmdbPreview.draft.title || "").trim()) {
    return a.tmdbPreview.draft.title.trim();
  }
  return "";
}

function syncTmdbSearchLink(a) {
  const link = el("#tmdbSearchLink");
  const hint = el("#tmdbSearchHint");
  if (!link || !hint) return;
  const keyword = currentTmdbTitle(a);
  if (keyword) {
    link.href = tmdbSearchUrl(keyword);
    link.removeAttribute("aria-disabled");
    link.classList.remove("is-disabled");
    hint.textContent = "使用当前标题搜索 TMDB，在新标签页打开";
  } else {
    link.removeAttribute("href");
    link.setAttribute("aria-disabled", "true");
    link.classList.add("is-disabled");
    hint.textContent = "当前没有标题，请先在搜索框输入作品标题";
  }
}

function syncYoushuSearchLink(a) {
  const link = el("#youshuSearchLink");
  const hint = el("#youshuSearchHint");
  if (!link || !hint) return;
  const keyword = currentTmdbTitle(a);
  if (keyword) {
    link.href = youshuSearchUrl(keyword);
    link.removeAttribute("aria-disabled");
    link.classList.remove("is-disabled");
    hint.textContent = "使用当前标题搜索优书网，在新标签页打开";
  } else {
    link.removeAttribute("href");
    link.setAttribute("aria-disabled", "true");
    link.classList.add("is-disabled");
    hint.textContent = "当前没有标题，请先在搜索框输入作品标题";
  }
}

async function copyPlainText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (e) {}
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;left:0;top:0;width:1px;height:1px;opacity:0";
  document.body.appendChild(area);
  area.focus();
  area.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) {}
  document.body.removeChild(area);
  if (!ok) throw new Error("浏览器拒绝复制");
}

async function copyImportBookmarklet() {
  const btn = el("#tmdbCopyBookmarklet");
  if (btn) { btn.disabled = true; btn.textContent = "读取中…"; }
  try {
    const res = await fetch("/static/import-bookmarklet.js", { cache: "no-store" });
    if (!res.ok) throw new Error("读取统一书签脚本失败");
    const code = (await res.text()).trim();
    if (!code) throw new Error("统一书签脚本为空");
    await copyPlainText("javascript:" + code);
    toast("统一书签已复制。请新建书签「导入个人娱乐档案」，把脚本粘贴到网址栏");
  } catch (e) {
    toast("复制统一书签失败：" + (e && e.message ? e.message : "未知错误"), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "复制统一书签"; }
  }
}

function tmdbPreviewHTML(a) {
  const p = a.tmdbPreview;
  if (!p || !p.draft) return "";
  const d = p.draft;
  const kind = tmdbKindLabel(d);
  const cover = d.previewUrl || d.coverUrl || "";
  const episodes = tmdbInfoValue(d, ["集数"]);
  const runtime = tmdbInfoValue(d, ["时长", "片长"]);
  const directors = tmdbCreatorNames(d, ["导演", "原创", "编剧"]);
  const actors = tmdbCreatorNames(d, ["主演", "演员"]);
  const target = p.target;
  const match = p.match;
  const isEdit = a.mode === "edit";
  const actionText = isEdit
    ? "按保护规则合并到当前作品"
    : (match ? "使用这份资料（保存时更新已有 TMDB 作品）" : "使用这份资料并继续");
  const targetText = target ? `当前作品：${target.title || "未命名"}` : "";
  const matchText = match && !target ? `已有条目：${match.title || "未命名"}${match.year ? `（${match.year}）` : ""}` : "";
  const warnings = (p.warnings || []).map(w => `<div class="tmdb-warning">${esc(w)}</div>`).join("");
  const actions = isEdit
    ? `<button class="btn btn-primary btn-sm" id="tmdbMerge">仅补空字段</button>
       <button class="btn btn-ghost btn-sm" id="tmdbOverwrite">覆盖 TMDB 字段</button>`
    : (match
      ? `<button class="btn btn-primary btn-sm" id="tmdbUse">仅补空字段（更新已有 TMDB 作品）</button>
         <button class="btn btn-ghost btn-sm" id="tmdbUseOverwrite">覆盖已有 TMDB 作品</button>`
      : `<button class="btn btn-primary btn-sm" id="tmdbUse">${esc(actionText)}</button>`);
  const help = isEdit
    ? `<div class="tmdb-merge-help">「仅补空字段」保留已有非空资料；「覆盖 TMDB 字段」会用 TMDB 的非空标题、原名、年份、标签、简介、演职人员、infobox 和封面替换；评分、经历、系列和用户字段仍保留。</div>`
    : (match
      ? `<div class="tmdb-merge-help">保存时会把这份资料写入已有 TMDB 作品；「仅补空字段」保留已有非空资料，「覆盖已有 TMDB 作品」会替换 TMDB 字段，评分、经历、系列和用户字段仍保留。</div>`
      : "");
  return `
    <div class="tmdb-preview-card">
      <div class="tmdb-preview-cover">${cover ? `<img src="${esc(cover)}" alt="" onerror="this.style.display='none'">` : `<div class="cover-fallback"><span>TMDB</span></div>`}</div>
      <div class="tmdb-preview-main">
        <div class="tmdb-preview-title">${esc(d.title || "未命名")} <span class="tmdb-kind">${esc(kind)}</span></div>
        <div class="tmdb-preview-meta">${esc([d.year, `TMDB ${d.source.id}`].filter(Boolean).join(" · "))}${targetText ? ` · ${esc(targetText)}` : ""}${matchText ? ` · ${esc(matchText)}` : ""}</div>
        ${d.summary ? `<div class="tmdb-preview-summary">${esc(d.summary)}</div>` : `<div class="tmdb-preview-summary muted">没有简介</div>`}
        <div class="tmdb-preview-facts">
          ${d.tags && d.tags.length ? `<div><b>标签</b>${esc(d.tags.join("、"))}</div>` : ""}
          ${directors ? `<div><b>导演 / 原创</b>${esc(directors)}</div>` : ""}
          ${actors ? `<div><b>主演</b>${esc(actors)}</div>` : ""}
          ${episodes ? `<div><b>集数</b>${esc(episodes)}</div>` : ""}
          ${runtime ? `<div><b>片长</b>${esc(runtime)}</div>` : ""}
        </div>
        ${warnings}
        ${help}
        <div class="tmdb-preview-actions">
          ${actions}
          <span class="tmdb-import-note">确认前不会写入任何资料</span>
        </div>
      </div>
    </div>`;
}

function safeExternalUrl(url) {
  const s = String(url || "").trim();
  return /^https?:\/\//i.test(s) ? s : "";
}

function draftCoverSrc(draft) {
  const d = draft || {};
  const remote = d.previewUrl || d.coverUrl || "";
  if (remote) return remote;
  const local = String(d.cover || "").trim();
  if (!local) return "";
  if (/^https?:\/\//i.test(local)) return local;
  return local.startsWith("/") ? local : "/" + local.replace(/^\.?\//, "");
}

function youshuPreviewHTML(a) {
  const p = a.youshuPreview;
  if (!p || !p.draft) return "";
  const d = p.draft;
  const target = p.target;
  const match = p.match;
  const cover = d.previewUrl || d.coverUrl || (target && target.coverUrl) || "";
  const author = tmdbCreatorNames(d, ["作者", "原著", "原创", "创作者"]);
  const platform = tmdbInfoValue(d, ["阅读平台"]);
  const status = tmdbInfoValue(d, ["状态"]);
  const words = tmdbInfoValue(d, ["字数"]);
  const score = tmdbInfoValue(d, ["优书评分"]) || (d.ratingRef == null ? "" : String(d.ratingRef));
  const votes = tmdbInfoValue(d, ["评分人数"]);
  const bookCategory = tmdbInfoValue(d, ["分类"]);
  const readLink = safeExternalUrl(tmdbInfoValue(d, ["原书链接"]));
  const isEdit = a.mode === "edit";
  const targetText = target ? `当前作品：${target.title || "未命名"}` : "";
  const matchText = match && !target ? `已有条目：${match.title || "未命名"}${match.source.id ? `（优书 ID ${match.source.id}）` : ""}` : "";
  const warnings = (p.warnings || []).map(w => `<div class="tmdb-warning">${esc(w)}</div>`).join("");
  const actions = isEdit
    ? `<button class="btn btn-primary btn-sm" id="youshuMerge">只补空字段并填入表单</button>
       <button class="btn btn-ghost btn-sm" id="youshuOverwrite">覆盖资料字段（含封面）并填入表单</button>`
    : `<button class="btn btn-primary btn-sm" id="youshuUse">使用这份资料并继续</button>`;
  const help = isEdit
    ? `<div class="tmdb-merge-help">「只补空字段」保留已有非空资料和已有封面；「覆盖资料字段（含封面）」用优书网的非空标题、简介、标签、作者、infobox 和有效封面替换，评分、阅读经历、我的字段和系列仍保留。封面下载失败时保留旧封面。确认后只填入表单，仍需点击「保存修改」。</div>`
    : `<div class="tmdb-merge-help">确认后把资料填入下方表单，不会自动保存；仍需点击「保存作品」。缺失的字段保持为空，不推断年份、原名或别名。</div>`;
  return `
    <div class="tmdb-preview-card">
      <div class="tmdb-preview-cover">${cover ? `<img src="${esc(cover)}" alt="" onerror="this.style.display='none'">` : `<div class="cover-fallback"><span>优书网</span></div>`}</div>
      <div class="tmdb-preview-main">
        <div class="tmdb-preview-title">${esc(d.title || "未命名")} <span class="tmdb-kind">网文</span></div>
        <div class="tmdb-preview-meta">${esc([`优书 ID ${d.source.id}`, platform, bookCategory].filter(Boolean).join(" · "))}${targetText ? ` · ${esc(targetText)}` : ""}${matchText ? ` · ${esc(matchText)}` : ""}</div>
        ${d.summary ? `<div class="tmdb-preview-summary">${esc(d.summary)}</div>` : `<div class="tmdb-preview-summary muted">没有简介</div>`}
        <div class="tmdb-preview-facts">
          ${author ? `<div><b>作者</b>${esc(author)}</div>` : ""}
          ${status ? `<div><b>连载状态</b>${esc(status)}</div>` : ""}
          ${words ? `<div><b>字数</b>${esc(words)}</div>` : ""}
          ${score ? `<div><b>优书评分</b>${esc(score)}${votes ? `（${esc(votes)} 人）` : ""}</div>` : ""}
          ${d.tags && d.tags.length ? `<div><b>标签</b>${esc(d.tags.join("、"))}</div>` : ""}
          ${readLink ? `<div><b>原书</b><a href="${esc(readLink)}" target="_blank" rel="noopener noreferrer">${esc(readLink)}</a></div>` : ""}
        </div>
        ${warnings}
        ${help}
        <div class="tmdb-preview-actions">
          ${actions}
          <span class="tmdb-import-note">确认前不会写入任何资料</span>
        </div>
      </div>
    </div>`;
}

function bindYoushuPreview(a) {
  const use = el("#youshuUse");
  if (use) use.onclick = () => applyYoushuDraft("merge");
  const merge = el("#youshuMerge");
  if (merge) merge.onclick = () => applyYoushuDraft("merge");
  const overwrite = el("#youshuOverwrite");
  if (overwrite) overwrite.onclick = () => applyYoushuDraft("overwrite");
}

function mergeYoushuInfobox(current, incoming, overwrite) {
  const out = Array.isArray(current) ? JSON.parse(JSON.stringify(current)) : [];
  const index = new Map();
  out.forEach((item, i) => {
    if (item && item.key) index.set(String(item.key), i);
  });
  (incoming || []).forEach(item => {
    if (!item || !item.key || !item.value) return;
    const key = String(item.key);
    const i = index.get(key);
    if (i == undefined) {
      out.push({ key, value: item.value });
      index.set(key, out.length - 1);
    } else if (overwrite || !out[i].value) {
      out[i] = { key, value: item.value };
    }
  });
  return out;
}

function applyYoushuDraft(mode) {
  const a = S.add;
  const p = a.youshuPreview;
  if (!p || !p.draft) return;
  const d = JSON.parse(JSON.stringify(p.draft));
  const overwrite = mode === "overwrite";
  if (a.mode === "edit") {
    const out = JSON.parse(JSON.stringify(a.draft || {}));
    if (overwrite) {
      if (d.title) out.title = d.title;
      if (d.summary) out.summary = d.summary;
      if (d.tags && d.tags.length) out.tags = d.tags;
      if (d.creators && d.creators.length) out.creators = d.creators;
      out.infobox = mergeYoushuInfobox(out.infobox, d.infobox, true);
      out.source = d.source;
    } else {
      if (!out.title) out.title = d.title;
      if (!out.summary) out.summary = d.summary;
      if (!(out.tags || []).length) out.tags = d.tags;
      if (!(out.creators || []).length) out.creators = d.creators;
      out.infobox = mergeYoushuInfobox(out.infobox, d.infobox, false);
      if (!out.source || !(out.source.name) || out.source.name === "manual") out.source = d.source;
    }
    // 「只补空字段」只补空白封面；「覆盖资料字段」在优书网提供有效封面时明确替换。
    if (overwrite) {
      if (d.coverUrl) {
        out.cover = "";
        out.coverUrl = d.coverUrl;
        out.previewUrl = d.previewUrl;
        out.coverReferer = d.coverReferer;
        out.coverProxy = false;
      }
    } else if (!out.cover && !out.coverUrl && d.coverUrl) {
      out.coverUrl = d.coverUrl;
      out.previewUrl = d.previewUrl;
      out.coverReferer = d.coverReferer;
      out.coverProxy = false;
    }
    a.draft = out;
    a.youshuApplied = { mode: overwrite ? "overwrite" : "merge", draft: d };
  } else {
    a.draft = d;
    a.youshuApplied = { mode: "new", draft: d };
  }
  a.tmdbRaw = "";
  a.tmdbPreview = null;
  a.youshuRaw = "";
  a.youshuPreview = null;
  a.step = 3;
  renderAdd();
  toast(a.mode === "edit"
    ? "已填入表单，请检查后点击「保存修改」"
    : "已填入表单，请检查后点击「保存作品」");
}


function bindTmdbPreview(a) {
  const use = el("#tmdbUse");
  if (use) use.onclick = () => useTmdbDraft("merge");
  const useOverwrite = el("#tmdbUseOverwrite");
  if (useOverwrite) useOverwrite.onclick = () => useTmdbDraft("overwrite");
  const merge = el("#tmdbMerge");
  if (merge) merge.onclick = () => importTmdbToCurrent("merge");
  const overwrite = el("#tmdbOverwrite");
  if (overwrite) overwrite.onclick = () => importTmdbToCurrent("overwrite");
}

function bindTmdbImport(a) {
  const box = el("#tmdbImportBox");
  if (!box) return;
  const copyBookmark = el("#tmdbCopyBookmarklet");
  if (copyBookmark) copyBookmark.onclick = copyImportBookmarklet;
  ["#fTitle", "#rfKeyword", "#addKeyword"].forEach(selector => {
    const input = el(selector);
    if (input) input.addEventListener("input", () => {
      syncTmdbSearchLink(a);
      syncYoushuSearchLink(a);
    });
  });
  syncTmdbSearchLink(a);
  syncYoushuSearchLink(a);
  if (a.tmdbPreview) bindTmdbPreview(a);
  if (a.youshuPreview) bindYoushuPreview(a);
}

function pasteSourceInfo(raw) {
  try {
    const draft = JSON.parse(raw);
    if (!draft || typeof draft !== "object" || Array.isArray(draft)) return null;
    const source = draft.source && typeof draft.source === "object" ? draft.source : {};
    return { draft, name: String(source.name || "").trim().toLowerCase() };
  } catch (e) {
    return null;
  }
}

function showPasteNotice(message) {
  const out = el("#tmdbPreview");
  if (out) out.innerHTML = `<div class="tmdb-warning">${esc(message)}</div>`;
}

async function previewYoushu(raw) {
  const a = S.add;
  const r = await api("/api/youshu/preview", {
    method: "POST",
    body: { json: raw, targetId: a.mode === "edit" ? a.editId : null },
  });
  if (!r.ok) {
    a.youshuRaw = "";
    a.youshuPreview = null;
    a.tmdbRaw = "";
    a.tmdbPreview = null;
    const out = el("#tmdbPreview");
    if (out) out.innerHTML = `<div class="tmdb-error">${esc(r.error || "校验失败")}</div>`;
    return toast(r.error || "校验失败", true);
  }
  a.youshuRaw = raw;
  a.youshuPreview = r;
  a.tmdbRaw = "";
  a.tmdbPreview = null;
  const out = el("#tmdbPreview");
  if (out) out.innerHTML = youshuPreviewHTML(a);
  bindYoushuPreview(a);
}

async function previewTmdb(raw) {
  const a = S.add;
  raw = (raw || "").trim();
  if (!raw) return toast("请先粘贴资料 JSON", true);
  const sourceInfo = pasteSourceInfo(raw);
  const sourceName = sourceInfo ? sourceInfo.name : "";
  a.youshuRaw = "";
  a.youshuPreview = null;

  if (sourceName === "youshu") {
    a.tmdbRaw = "";
    a.tmdbPreview = null;
    if (a.category !== "novel") {
      showPasteNotice("已识别优书网资料，请到网文作品编辑页导入。");
      return toast("已识别优书网资料，请到网文作品编辑页导入", true);
    }
    return previewYoushu(raw);
  }

  if (a.category !== "movie") {
    a.tmdbRaw = "";
    a.tmdbPreview = null;
    if (sourceName === "tmdb") {
      showPasteNotice("已识别 TMDB 资料，请到影视作品编辑页导入。");
      return toast("已识别 TMDB 资料，请到影视作品编辑页导入", true);
    }
    if (!sourceInfo) {
      showPasteNotice("JSON 格式错误，无法识别来源。");
      return toast("JSON 格式错误，无法识别来源", true);
    }
    showPasteNotice("当前分类不支持剪贴板资料导入。");
    return toast("当前分类不支持剪贴板资料导入", true);
  }

  const r = await api("/api/tmdb/preview", {
    method: "POST",
    body: { json: raw, targetId: a.mode === "edit" ? a.editId : null },
  });
  if (!r.ok) {
    a.tmdbPreview = null;
    a.tmdbRaw = "";
    const out = el("#tmdbPreview");
    if (out) out.innerHTML = `<div class="tmdb-error">${esc(r.error || "校验失败")}</div>`;
    return toast(r.error || "校验失败", true);
  }
  a.tmdbRaw = raw;
  a.tmdbPreview = r;
  const out = el("#tmdbPreview");
  if (out) out.innerHTML = tmdbPreviewHTML(a);
  bindTmdbPreview(a);
  syncTmdbSearchLink(a);
}

function useTmdbDraft(mode) {
  const a = S.add;
  if (!a.tmdbPreview || !a.tmdbPreview.draft) return;
  a.tmdbMode = mode === "overwrite" ? "overwrite" : "merge";
  a.draft = JSON.parse(JSON.stringify(a.tmdbPreview.draft));
  a.step = 3;
  renderAdd();
}

async function importTmdbToCurrent(mode) {
  const a = S.add;
  if (!a.tmdbPreview || !a.tmdbRaw || a.mode !== "edit" || !a.editId) return;
  const overwrite = mode === "overwrite";
  const btn = el(overwrite ? "#tmdbOverwrite" : "#tmdbMerge");
  const originalText = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = overwrite ? "覆盖中…" : "合并中…"; }
  const r = await api("/api/tmdb/import", {
    method: "POST",
    body: { json: a.tmdbRaw, targetId: a.editId, mode: overwrite ? "overwrite" : "merge" },
  });
  if (btn) { btn.disabled = false; btn.textContent = originalText; }
  if (!r.ok) return toast(r.error || "导入失败", true);

  a.tmdbRaw = "";
  a.tmdbPreview = null;
  a.draft = JSON.parse(JSON.stringify(r.work));
  closeAdd();
  renderWall(); renderStats();
  toast(r.action === "updated"
    ? (overwrite ? "已用 TMDB 非空字段覆盖，评分、经历、系列和用户字段已保留" : "已按保护规则合并，已有非空资料未覆盖")
    : "已导入");
}

async function saveTmdbCreate() {
  let bgm, backgrounds;
  try { backgrounds = ArchiveV2.backgroundEditor.read(el('#addBody'), 'fImmersiveBackgrounds'); bgm = await ArchiveV2.bgmEditor.read(el('#addBody'), 'workBgm'); } catch (error) { return toast(error.message, true); }
  const a = S.add;
  const btn = el("#saveWork");
  const title = el("#fTitle").value.trim();
  if (!title) return toast("标题不能为空", true);
  const creatorsRaw = el("#fCreators").value.trim();
  const creators = creatorsRaw ? creatorsRaw.split(/[；;]/).map(p => {
    const m = p.split(/[：:]/);
    return m.length > 1 ? { role: m[0].trim(), name: m.slice(1).join(":").trim() } : { role: "创作者", name: p.trim() };
  }) : [];
  const body = {
    json: a.tmdbRaw,
    mode: a.tmdbMode || "merge",
    overrides: {
      title,
      originalTitle: el("#fOriginal").value.trim(),
      year: el("#fYear").value.trim(),
      tags: el("#fTags").value.split(/[，,]/).map(s => s.trim()).filter(Boolean),
      summary: el("#fSummary").value.trim(),
      immersiveBackgroundUrls: backgrounds,
      bgm,
      creators,
    },
  };
  const rEl = el("#fRating");
  if (rEl) {
    const v = parseFloat(rEl.value);
    if (!isNaN(v)) body.rating = v;
  }
  const st = el("#fFirstStatus");
  if (st) body.firstExperience = { status: st.value, content: (el("#fFirstContent") || {}).value || "" };
  if (btn) { btn.disabled = true; btn.textContent = "保存中…"; }
  const r = await api("/api/tmdb/import", { method: "POST", body });
  if (btn) { btn.disabled = false; btn.textContent = "保存入库"; }
  if (!r.ok) return toast(r.error || "保存失败", true);

  closeAdd(); renderTabs(); renderWall(); renderStats();
  toast(r.action === "updated"
    ? (a.tmdbMode === "overwrite" ? "已覆盖已有 TMDB 作品，评分、经历、系列和用户字段已保留" : "已更新相同 TMDB 条目，已有非空资料未覆盖")
    : "已入库");
  openCurrentWork(r.work.id);
}

/* ------------------------------------------------------------ 新增 / 编辑 */
function openAdd() {
  if (!modalIsOpen("#addModal")) rememberOverlayFocus();
  S.add = { step: 1, category: null, source: null, items: [], draft: null, mode: "create", editId: null, busy: false, refItems: [], refSource: null, tmdbRaw: "", tmdbPreview: null, tmdbMode: "merge", youshuRaw: "", youshuPreview: null, youshuApplied: null };
  setModalState("#addModal", true);
  renderAdd();
  focusAfterRender("#addBody .cat-choice, #addBody input");
}
function closeAdd() {
  if (!modalIsOpen("#addModal")) return;
  ArchiveV2.bgmEditor.stop(el('#addBody'));
  restoreOverlayFocus();
  setModalState("#addModal", false);
  el("#addModal").classList.remove("is-editing");
  if (S.add.returnToImmersive) {
    const scroll = S.add.returnToImmersive.scrollTop;
    requestAnimationFrame(() => { if (!S.add.saving) immersiveView?.editReturned(scroll); });
  }
}

function openEdit(w) {
  openEditWithReturn(w, null);
}

function openImmersiveEdit(work, scrollTop) {
  openEditWithReturn(work, {scrollTop});
}

function openEditWithReturn(w, returnToImmersive) {
  if (!modalIsOpen("#addModal")) rememberOverlayFocus();
  el("#addModal").classList.add("is-editing");
  S.add = { step: 3, category: w.category, source: (w.source || {}).name || null, items: [], draft: JSON.parse(JSON.stringify(w)), mode: "edit", editId: w.id, busy: false, refItems: [], refSource: (w.source || {}).name || null, tmdbRaw: "", tmdbPreview: null, tmdbMode: "merge", youshuRaw: "", youshuPreview: null, youshuApplied: null };
  S.add.returnToImmersive = returnToImmersive;
  setModalState("#addModal", true);
  renderAdd();
  focusAfterRender("#fTitle");
}

function renderAdd() {
  const a = S.add;
  el("#addSteps").innerHTML = `<span class="${a.step === 1 ? "on" : ""}">1 分类</span><span class="${a.step === 2 ? "on" : ""}">2 取信息</span><span class="${a.step === 3 ? "on" : ""}">3 填写</span>`;
  const title = a.mode === "edit" ? "编辑作品" : "添加作品";
  el("#addTitle").textContent = title;
  const body = el("#addBody");
  if (a.step === 1) {
    body.innerHTML = `<div class="cat-grid">${CAT_ORDER.map(k => {
      const c = S.categories.find(x => x.key === k) || {};
      return `<button class="cat-choice" data-cat="${k}"><div class="c-label">${esc(c.label || k)}</div><div class="c-src">${esc((c.sources || []).map(s => S.sourceLabels[s] || s).join(" / "))}</div></button>`;
    }).join("")}</div>
    <div class="tip" style="margin-top:14px">选中分类后，下一步可以按来源搜索，也可以直接粘贴 <b>起点 / 番茄 / 刺猬猫 / 豆瓣图书 / Bangumi / Steam</b> 的作品链接，自动填写。</div>`;
    elAll(".cat-choice", body).forEach(b => b.onclick = () => { a.category = b.dataset.cat; a.source = (S.categories.find(x => x.key === a.category) || {}).sources[0]; a.step = 2; a.items = []; renderAdd(); });
    el("#addFoot").innerHTML = `<button class="btn btn-ghost" id="addCancel">取消</button><button class="btn" id="addManual">跳过，手动填写</button>`;
    el("#addCancel").onclick = closeAdd;
    el("#addManual").onclick = () => { a.draft = { title: "", tags: [], creators: [], infobox: [], userFields: [] }; a.step = 3; renderAdd(); };
  } else if (a.step === 2) {
    const cat = S.categories.find(x => x.key === a.category) || {};
    const sources = cat.sources || ["douban"];
    body.innerHTML = `
      <div class="source-row">${sources.map((s, i) => `<button class="source-tab ${a.source === s ? "active" : ""}" data-src="${s}" aria-pressed="${a.source === s}">${esc(S.sourceLabels[s] || s)}${i === 0 ? " · 主" : ""}</button>`).join("")}</div>
      ${supportsUnifiedBookmarklet(a.category) ? tmdbImportHTML(a) : ""}
      <div class="search-row">
        <input id="addKeyword" placeholder="输入作品名，例如 诡秘之主 / 进击的巨人 / 艾尔登法环">
        <button class="btn btn-primary" id="addSearch">${ICONS.search} 搜索</button>
      </div>
      ${a.source === "web" ? `<div class="tip">网文兜底：先用必应定位起点 / 番茄的官方书页，再解析。命中不了就直接粘贴链接。</div>` : ""}
      <div class="link-row">
        <input id="addLink" placeholder="粘贴作品链接或书签 JSON（qidian / fanqienovel / ciweimao / douban / bangumi / steam / TMDB / 优书网）">
        <button class="btn" id="parseLink">解析</button>
      </div>
      <div class="results" id="addResults"></div>`;
    elAll(".source-tab", body).forEach(b => b.onclick = () => { a.source = b.dataset.src; a.items = []; renderAdd(); });
    el("#addSearch").onclick = doSearch;
    el("#addKeyword").onkeydown = e => { if (e.key === "Enter") doSearch(); };
    el("#parseLink").onclick = doParseLink;
    el("#addLink").onkeydown = e => { if (e.key === "Enter") doParseLink(); };
    if (supportsUnifiedBookmarklet(a.category)) bindTmdbImport(a);
    renderResults();
    el("#addFoot").innerHTML = `<button class="btn btn-ghost" id="addBack">${ICONS.back} 上一步</button><button class="btn" id="addManual">跳过，手动填写</button>`;
    el("#addBack").onclick = () => { a.step = 1; renderAdd(); };
    el("#addManual").onclick = () => { a.draft = { title: "", tags: [], creators: [], infobox: [], userFields: [] }; a.step = 3; renderAdd(); };
  } else {
    renderForm();
  }
}

function renderResults() {
  const a = S.add;
  const box = el("#addResults");
  if (!box) return;
  if (!a.items.length) { box.innerHTML = `<div class="muted-note" style="padding:10px 2px">搜索结果会显示在这里。</div>`; return; }
  box.innerHTML = a.items.map((it, i) => `
    <div class="result" data-i="${i}" tabindex="0" role="button" aria-label="选用 ${esc(it.title)}">
      <div class="result-cover">${it.cover ? `<img src="${esc(it.cover)}" loading="lazy" onerror="this.style.display='none'">` : ""}</div>
      <div class="result-main">
        <div class="result-title">${esc(it.title)}${it.subtitle ? ` <span style="color:var(--lenso-label-tertiary);font-size:11px">${esc(it.subtitle)}</span>` : ""}</div>
        <div class="result-meta">${esc([it.meta, it.year].filter(Boolean).join(" · "))}${it.coverMissing ? " · 该来源无封面" : ""}</div>
      </div>
    </div>`).join("");
  elAll(".result", box).forEach(r => {
    r.onclick = () => pickItem(Number(r.dataset.i));
    r.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickItem(Number(r.dataset.i)); } };
  });
}

async function doSearch() {
  const a = S.add;
  const kw = (el("#addKeyword").value || "").trim();
  if (!kw) return toast("请输入关键词", true);
  const btn = el("#addSearch");
  btn.disabled = true; btn.textContent = "搜索中…";
  const r = await api("/api/search", { method: "POST", body: { category: a.category, source: a.source, keyword: kw } });
  btn.disabled = false; btn.innerHTML = `${ICONS.search} 搜索`;
  if (!r.ok) return toast(r.error || "搜索失败", true);
  a.items = r.items || [];
  renderResults();
  if (!a.items.length) toast("这个来源没搜到，换个来源或粘贴链接试试");
}

async function pickItem(i) {
  const a = S.add;
  const it = a.items[i];
  if (!it) return;
  if (it.draft) { a.draft = it.draft; a.step = 3; return renderAdd(); }
  toast("正在读取条目详情…");
  const r = await api("/api/resolve", { method: "POST", body: { source: (it.ref || {}).source || a.source, ref: it.ref, category: a.category } });
  if (!r.ok || !r.draft) return toast(r.error || "读取失败", true);
  a.draft = r.draft; a.step = 3; renderAdd();
}

async function doParseLink() {
  const input = (el("#addLink").value || "").trim();
  if (!input) return toast("请粘贴链接或书签 JSON", true);
  if (input.charAt(0) === "{" || input.charAt(0) === "[") {
    return importJsonInput(input, { refill: false });
  }
  const btn = el("#parseLink"); btn.disabled = true; btn.textContent = "解析中…";
  const r = await api("/api/web-import", { method: "POST", body: { input, category: S.add.category } });
  btn.disabled = false; btn.textContent = "解析";
  if (!r.ok || !r.draft) return toast(r.error || "解析失败", true);
  S.add.draft = r.draft; S.add.step = 3; renderAdd();
  if (r.warnings && r.warnings.length) toast(`${r.sourceLabel || "导入"}：${r.warnings.join("；")}`, true);
  else toast(`${r.sourceLabel || "导入"}：已识别，请核对字段`);
}

/* 书签 JSON 与网址共用输入框后的统一分流：TMDB / 优书网走原有预览流程，
   其它合法草稿 JSON 走通用导入，保持原有能力不变。 */
async function importJsonInput(raw, opts = {}) {
  const info = pasteSourceInfo(raw);
  const name = info ? info.name : "";
  const a = S.add;
  if (!info) {
    return toast("JSON 格式不正确，请重新复制书签内容", true);
  }
  if (name === "tmdb" || (!name && (info.draft.tmdbId || info.draft.mediaType))) {
    if (a.category !== "movie") return toast("已识别 TMDB 资料，请到影视作品编辑页导入", true);
    return previewTmdb(raw);
  }
  if (name === "youshu" || (!name && info.draft.youshuId)) {
    if (a.category !== "novel") return toast("已识别优书网资料，请到网文作品编辑页导入", true);
    return previewYoushu(raw);
  }
  if (opts.refill) return toast("重新获取信息只支持 TMDB / 优书网书签 JSON；通用 JSON 请用「导入备份」", true);
  const r = await api("/api/web-import", { method: "POST", body: { input: raw, category: a.category } });
  if (!r.ok || !r.draft) return toast(r.error || "解析失败", true);
  a.draft = r.draft;
  a.step = 3;
  renderAdd();
  toast(`${r.sourceLabel || "通用草稿"}：已识别，请核对字段`);
}

function renderForm() {
  ArchiveV2.bgmEditor.stop(el('#addBody'));
  const a = S.add;
  const d = a.draft || {};
  const body = el("#addBody");
  const cat = a.category;
  const infoboxKeys = (d.infobox || []).map(i => i.key);
  const gaps = (EXPECT_FIELDS[cat] || []).filter(k => !infoboxKeys.includes(k));
  const rfSources = (S.categories.find(c => c.key === cat) || {}).sources || [];
  const rfCur = rfSources.includes(a.refSource) ? a.refSource : (rfSources[0] || "");
  const extPlatforms = EXTERNAL_SEARCH_PLATFORMS[cat] || [];
  const extTitle = (d.title || "").trim();
  const coverSrc = draftCoverSrc(d);
  const hasCover = Boolean(coverSrc);
  const extHint = extTitle
    ? "在新标签页打开平台搜索；找到作品后复制详情页链接，粘贴到下方解析。"
    : "当前标题为空，填写标题后即可使用站外搜索。";
  body.innerHTML = `
    <div class="cover-preview" style="margin-bottom:16px">
      <div class="cp-box">${hasCover ? `<img id="cpImg" src="${esc(coverSrc)}" onerror="this.style.display='none'">` : `<div class="cover-fallback"><span>${esc(catLabel(cat))}</span></div>`}</div>
      <div class="cp-info">
        <div>封面来自：${esc((d.source && (d.source.label || d.source.name)) || "手动")}</div>
        <div>${d.coverUrl ? "保存时会下载到本地，断网也能显示" : (d.cover ? "已有本地封面，保存时保留" : "没有封面，卡片会显示分类占位图")}</div>
        <div style="margin-top:6px"><input id="coverUrlInput" class="reason" style="width:100%" placeholder="可粘贴封面图片 URL 替换" value=""></div>
      </div>
    </div>
    <div class="form-grid">
      <div class="form-section-title full"><span>基本资料</span><small>标题、原名、年份、标签与创作者</small></div>
      <div class="form-item"><label>标题</label><input id="fTitle" value="${esc(d.title || "")}"></div>
      <div class="form-item"><label>原名 / 原名副标</label><input id="fOriginal" value="${esc(d.originalTitle || "")}"></div>
      <div class="form-item"><label>年份</label><input id="fYear" value="${esc(d.year || "")}"></div>
      <div class="form-item"><label>标签（逗号分隔）</label><input id="fTags" value="${esc((d.tags || []).join("，"))}"></div>
      <div class="form-item full"><label>创作者（角色：名字，句号分隔）</label><input id="fCreators" value="${esc((d.creators || []).map(c => c.role + "：" + c.name).join("；"))}"></div>
      <div class="form-section-title full"><span>沉浸体验</span><small>背景图与背景音乐只影响沉浸浏览</small></div>
      ${ArchiveV2.backgroundEditor.form(d, 'fImmersiveBackgrounds')}
      ${ArchiveV2.bgmEditor.form(d, 'workBgm')}
      <div class="form-section-title full"><span>内容与个人记录</span><small>简介和新建时的初始状态</small></div>
      <div class="form-item full"><label>简介</label><textarea id="fSummary" style="min-height:110px">${esc(d.summary || "")}</textarea></div>
      ${a.mode === "create" ? `
      <div class="form-item"><label>初始评分（可留空）</label>
        <div class="rating-controls" style="margin:0">
          <input type="range" id="fRating" min="0" max="10" step="0.5" value="${d.ratingRef != null ? Math.round(d.ratingRef * 2) / 2 : 8}">
          <div class="score-num" id="fRatingNum">${fmtScore(d.ratingRef != null ? Math.round(d.ratingRef * 2) / 2 : 8)}</div>
        </div>
      </div>
      <div class="form-item"><label>第一条经历状态</label>
        <select id="fFirstStatus">${Object.entries((S.categories.find(c => c.key === cat) || {}).statuses || GENERIC_STATUS)
          .filter(([k]) => k !== "not_started").map(([k, v]) => `<option value="${k}" ${k === "active" ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      </div>
      <div class="form-item full"><label>第一条经历内容（可留空）</label><input id="fFirstContent" placeholder="如：开始看了 / 刚买 / 朋友推荐"></div>` : ""}
      </div>
    ${a.mode === "edit" ? `
    <div class="refill-box">
      <div class="refill-head">
        <h4>重新获取作品信息</h4>
        <span class="hint">覆盖标题 / 原名 / 年份 / 标签 / 简介 / 来源字段 / 封面；评分、经历、我的字段保留</span>
      </div>
      ${supportsUnifiedBookmarklet(a.category) ? tmdbImportHTML(a) : ""}
      <div class="source-row" id="rfSources">${rfSources.map(s =>
        `<button class="source-tab ${rfCur === s ? "active" : ""}" data-rfsrc="${s}" aria-pressed="${rfCur === s}">${esc(S.sourceLabels[s] || s)}</button>`).join("")}</div>
      <div class="search-row">
        <input id="rfKeyword" value="${esc(d.title || "")}" placeholder="用标题搜索该来源">
        <button class="btn btn-primary" id="rfSearch">${ICONS.search} 搜索</button>
      </div>
      ${a.mode === "edit" && extPlatforms.length ? `
      <div class="external-search" id="externalSearch">
        <div class="external-search-head">
          <h4>站外搜索</h4>
          <span class="hint" id="externalSearchHint">${esc(extHint)}</span>
        </div>
        <div class="source-row external-search-platforms" id="externalSearchPlatforms" style="${extTitle ? "" : "display:none"}">${externalSearchLinksHTML(extPlatforms, extTitle)}</div>
      </div>` : ""}
      <div class="link-row">
        <input id="rfLink" placeholder="粘贴作品链接或 TMDB / 优书网书签 JSON">
        <button class="btn" id="rfParse">解析</button>
      </div>
      <div class="results" id="rfResults"></div>
    </div>` : ""}
    ${gaps.length ? `<div class="tip">这个分类的常见字段还缺：<div class="gap-list">${gaps.map(g => `<span class="gap-chip">${esc(g)}</span>`).join("")}</div>保存后可点「编辑信息」或用「我的字段」补上，不影响使用。</div>` : ""}
    ${(d.infobox || []).length ? `<div class="tip">已抓到 ${d.infobox.length} 项来源字段，会在沉浸详情的「来源详情」里展示。</div>` : ""}`;

  if (a.mode === "create") {
    const rg = el("#fRating");
    rg.oninput = () => el("#fRatingNum").textContent = fmtScore(parseFloat(rg.value));
  }
  el("#addFoot").innerHTML = a.mode === "edit"
    ? `<button class="btn btn-ghost" id="addCancel">取消</button><button class="btn btn-primary" id="saveWork">保存修改</button>`
    : `<button class="btn btn-ghost" id="addBack2">${ICONS.back} 重新搜索</button><button class="btn btn-primary" id="saveWork">保存入库</button>`;
  const cancelBtn = el("#addCancel"); if (cancelBtn) cancelBtn.onclick = closeAdd;
  const b2 = el("#addBack2"); if (b2) b2.onclick = () => { a.step = 2; renderAdd(); };
  ArchiveV2.bgmEditor.bind(body, 'workBgm', toast);
  ArchiveV2.backgroundEditor.bind(body, 'fImmersiveBackgrounds', toast, urls => { d.immersiveBackgroundUrls = urls; });
  el("#saveWork").onclick = saveWork;
  if (a.mode === "edit") {
    elAll("[data-rfsrc]", body).forEach(x => x.onclick = () => {
      a.refSource = x.dataset.rfsrc;
      elAll("#rfSources .source-tab").forEach(t => t.classList.toggle("active", t === x));
    });
    el("#rfSearch").onclick = doRefillSearch;
    el("#rfParse").onclick = doRefillParse;
    el("#rfKeyword").onkeydown = ev => { if (ev.key === "Enter") doRefillSearch(); };
    el("#rfLink").onkeydown = ev => { if (ev.key === "Enter") doRefillParse(); };
    const extBox = el("#externalSearchPlatforms");
    const extHintEl = el("#externalSearchHint");
    const titleInput = el("#fTitle");
    if (extBox && extHintEl && titleInput && extPlatforms.length) {
      const syncExternalSearch = () => {
        const kw = (titleInput.value || "").trim();
        extBox.style.display = kw ? "flex" : "none";
        extBox.innerHTML = externalSearchLinksHTML(extPlatforms, kw);
        extHintEl.textContent = kw
          ? "在新标签页打开平台搜索；找到作品后复制详情页链接，粘贴到下方解析。"
          : "当前标题为空，填写标题后即可使用站外搜索。";
      };
      titleInput.addEventListener("input", syncExternalSearch);
      syncExternalSearch();
    }
    bindTmdbImport(a);
    renderRefillResults();
  }
}

/* 重新获取作品信息：只更新元数据，保留个人记录 */
async function doRefillSearch() {
  const a = S.add;
  const kw = (el("#rfKeyword").value || "").trim();
  if (!kw) return toast("请输入关键词", true);
  const src = a.refSource || ((S.categories.find(c => c.key === a.category) || {}).sources || [])[0];
  const list = (S.categories.find(c => c.key === a.category) || {}).sources || [];
  const useSrc = list.includes(src) ? src : list[0];
  const btn = el("#rfSearch");
  btn.disabled = true; btn.textContent = "搜索中…";
  const r = await api("/api/search", { method: "POST", body: { category: a.category, source: useSrc, keyword: kw } });
  btn.disabled = false; btn.innerHTML = `${ICONS.search} 搜索`;
  if (!r.ok) return toast(r.error || "搜索失败", true);
  a.refSource = useSrc;
  a.refItems = r.items || [];
  renderRefillResults();
  if (!a.refItems.length) toast("这个来源没搜到，换个来源或粘贴链接");
}

function renderRefillResults() {
  const box = el("#rfResults");
  if (!box) return;
  const items = S.add.refItems || [];
  if (!items.length) {
    box.innerHTML = `<div class="muted-note" style="padding:6px 2px">搜到的条目会列在这里，点一条就把信息填进这份记录。</div>`;
    return;
  }
  box.innerHTML = items.map((it, i) => `
    <div class="result" data-rfi="${i}" tabindex="0" role="button" aria-label="用 ${esc(it.title)} 更新信息">
      <div class="result-cover">${it.cover ? `<img src="${esc(it.cover)}" loading="lazy" onerror="this.style.display='none'">` : ""}</div>
      <div class="result-main">
        <div class="result-title">${esc(it.title)}${it.subtitle ? ` <span style="color:var(--lenso-label-tertiary);font-size:11px">${esc(it.subtitle)}</span>` : ""}</div>
        <div class="result-meta">${esc([it.meta, it.year].filter(Boolean).join(" · "))}${it.coverMissing ? " · 该来源无封面" : ""}</div>
      </div>
      <span class="refill-tag">用这条更新</span>
    </div>`).join("");
  elAll("[data-rfi]", box).forEach(r => {
    r.onclick = () => pickRefill(Number(r.dataset.rfi));
    r.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickRefill(Number(r.dataset.rfi)); } };
  });
}

async function pickRefill(i) {
  const a = S.add;
  const it = (a.refItems || [])[i];
  if (!it) return;
  let draft = it.draft;
  if (!draft) {
    toast("正在读取条目详情…");
    const r = await api("/api/resolve", { method: "POST", body: { source: (it.ref || {}).source || a.refSource, ref: it.ref, category: a.category } });
    if (!r.ok || !r.draft) return toast(r.error || "读取失败", true);
    draft = r.draft;
  }
  await applyRefill(draft);
}

async function doRefillParse() {
  const input = (el("#rfLink").value || "").trim();
  if (!input) return toast("请粘贴链接", true);
  if (input.charAt(0) === "{" || input.charAt(0) === "[") {
    return importJsonInput(input, { refill: true });
  }
  const btn = el("#rfParse");
  btn.disabled = true; btn.textContent = "解析中…";
  const r = await api("/api/web-import", { method: "POST", body: { input, category: S.add.category } });
  btn.disabled = false; btn.textContent = "解析";
  if (!r.ok || !r.draft) return toast(r.error || "解析失败", true);
  await applyRefill(r.draft);
}

async function applyRefill(draft) {
  const a = S.add;
  if (a.mode !== "edit" || !a.editId) return;
  const r = await api(`/api/works/${a.editId}/refill`, { method: "POST", body: { draft } });
  if (!r.ok) return toast(r.error || "更新失败", true);

  a.draft = JSON.parse(JSON.stringify(r.work));
  a.refItems = [];
  renderWall(); renderStats(); renderAdd();
  toast(`信息已更新；保留评分 ${r.kept.rating == null ? "未评" : fmtScore(r.kept.rating)}、经历 ${r.kept.experiences} 条`);
}

async function saveWork() {
  let bgm, backgrounds;
  try { backgrounds = ArchiveV2.backgroundEditor.read(el('#addBody'), 'fImmersiveBackgrounds'); bgm = await ArchiveV2.bgmEditor.read(el('#addBody'), 'workBgm'); } catch (error) { return toast(error.message, true); }
  const a = S.add;
  const title = el("#fTitle").value.trim();
  if (!title) return toast("标题不能为空", true);
  const creatorsRaw = el("#fCreators").value.trim();
  const creators = creatorsRaw ? creatorsRaw.split(/[；;]/).map(p => {
    const m = p.split(/[：:]/);
    return m.length > 1 ? { role: m[0].trim(), name: m.slice(1).join(":").trim() } : { role: "创作者", name: p.trim() };
  }) : [];
  const draft = Object.assign({}, a.draft, {
    title,
    originalTitle: el("#fOriginal").value.trim(),
    year: el("#fYear").value.trim(),
    tags: el("#fTags").value.split(/[，,]/).map(s => s.trim()).filter(Boolean),
    summary: el("#fSummary").value.trim(),
    immersiveBackgroundUrls: backgrounds,
    bgm,
    creators,
  });
  const coverInput = el("#coverUrlInput");
  if (coverInput && coverInput.value.trim()) {
    draft.coverUrl = coverInput.value.trim();
    draft.coverReferer = "";
  }
  if (a.mode === "edit") {
    const payload = { title: draft.title, originalTitle: draft.originalTitle, year: draft.year, tags: draft.tags, summary: draft.summary, creators: draft.creators, immersiveBackgroundUrls: draft.immersiveBackgroundUrls, bgm:draft.bgm };
    if (coverInput && coverInput.value.trim()) payload.cover = coverInput.value.trim();
    if (a.youshuApplied) {
      if (draft.source && typeof draft.source === "object") payload.source = draft.source;
      if (Array.isArray(draft.infobox)) payload.infobox = draft.infobox;
      if (!draft.cover && /^https?:\/\//i.test(draft.coverUrl || "")) {
        // PATCH 会先继承现有的空 cover 字段；这里直接传 cover，避免 normalize_work 把空 cover 当成已指定而跳过 coverUrl。
        payload.cover = draft.coverUrl;
        payload.coverReferer = draft.coverReferer || "";
        payload.coverProxy = false;
      }
    }
    const r = await api(`/api/works/${a.editId}`, { method: "PATCH", body: payload });
    if (!r.ok) return toast(r.error || "保存失败", true);
    const immersiveReturn = S.add.returnToImmersive;
    if (immersiveReturn) S.add.saving = true;
    closeAdd();
    renderWall();
    if (immersiveReturn) requestAnimationFrame(() => immersiveView?.editReturned(immersiveReturn.scrollTop));
    toast("已保存");
    return;
  }
  if (a.tmdbRaw) return saveTmdbCreate();
  const body = { category: a.category, draft };
  const rEl = el("#fRating");
  if (rEl) {
    const v = parseFloat(rEl.value);
    if (!isNaN(v)) body.draft.rating = v;
  }
  const st = el("#fFirstStatus");
  if (st) body.draft.firstExperience = { status: st.value, content: (el("#fFirstContent") || {}).value || "" };
  const btn = el("#saveWork"); btn.disabled = true; btn.textContent = "保存中…";
  const r = await api("/api/works", { method: "POST", body });
  btn.disabled = false;
  if (!r.ok) return toast(r.error || "保存失败", true);

  closeAdd(); renderTabs(); renderWall(); renderStats(); toast("已入库");
  openCurrentWork(r.work.id);
}

/* ------------------------------------------------------------ 设置 / 备份 */
function bindMediaCleanup() {
  const scan = el("#mediaScan"), stage = el("#mediaStage"), status = el("#mediaStatus");
  const folder = el("#mediaFolder"), details = el("#mediaDetails"), list = el("#mediaFiles");
  let preview = null;
  const sizeLabel = bytes => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  const busy = value => {
    scan.disabled = value;
    stage.disabled = value || !preview?.files.length;
  };
  scan.onclick = async () => {
    preview = null;
    busy(true);
    details.hidden = true;
    status.textContent = "正在检查…";
    const result = await api("/api/media-cleanup");
    if (!result.ok) status.textContent = result.error || "素材检查失败";
    else {
      preview = result;
      folder.textContent = result.folder;
      const images = result.files.filter(file => file.kind === "covers").length;
      const music = result.files.length - images;
      const held = [result.backupOnly && `备份仍需 ${result.backupOnly} 个`, result.recent && `24 小时内新增或重新选用 ${result.recent} 个`].filter(Boolean);
      status.textContent = (result.files.length ? `图片 ${images} 张，音乐 ${music} 首，共 ${sizeLabel(result.bytes)}。` : "没有可移入暂存区的素材。") +
        (held.length ? `已保留：${held.join("、")}。` : "");
      list.innerHTML = result.files.map(file => `<li><code>${esc(file.kind)}/${esc(file.name)}</code><span>${sizeLabel(file.bytes)}</span></li>`).join("");
      details.hidden = !result.files.length;
      details.open = false;
    }
    busy(false);
  };
  stage.onclick = async () => {
    if (!preview?.files.length || !confirm(`将这 ${preview.files.length} 个文件移入素材暂存区？文件不会被删除。`)) return;
    busy(true);
    status.textContent = "正在移入暂存区…";
    const result = await api("/api/media-cleanup/stage", { method: "POST", body: { token: preview.token } });
    preview = null;
    details.hidden = true;
    if (!result.ok) status.textContent = result.error || "未能移入暂存区，请重新检查";
    else {
      folder.textContent = result.folder;
      status.textContent = `已移入 ${result.moved} 个文件（${sizeLabel(result.bytes)}）。` + (result.skipped.length ? `有 ${result.skipped.length} 个文件未移动，可重新检查。` : "");
    }
    busy(false);
  };
}

function bindProjectUpdate() {
  const check = el("#updateCheck"), install = el("#updateInstall"), status = el("#updateStatus");
  const notes = el("#updateNotes");
  let release;
  function busy(value) {
    check.disabled = value;
    install.disabled = value || !release;
  }
  async function follow(job) {
    busy(true);
    const end = Date.now() + 210000;
    while (check.isConnected && Date.now() < end) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      const result = await api("/api/update/status");
      if (!result.ok || result.job !== job) continue;
      status.textContent = result.message;
      if (result.phase === "installed" || result.phase === "rolled-back") {
        status.textContent += "，正在刷新页面…";
        await new Promise(resolve => setTimeout(resolve, 1000));
        location.reload();
        return;
      }
      if (result.phase === "failed") {
        busy(false);
        return;
      }
    }
    status.textContent = "服务暂未恢复，请稍后刷新查看结果。";
    busy(false);
  }
  check.onclick = async () => {
    release = null;
    notes.hidden = true;
    busy(true);
    status.textContent = "正在检查官方发布…";
    const result = await api("/api/update/check");
    if (!result.ok) status.textContent = result.error || "检查更新失败";
    else if (result.status === "unreleased") status.textContent = "暂未发布可自动安装的更新包。";
    else if (result.status === "current") status.textContent = "没有比当前版本更新的发布。";
    else if (result.status === "incompatible") status.textContent = `v${result.release.version} 需要手动升级，请查看发布说明。`;
    else if (result.status === "available") {
      release = result.release;
      status.textContent = `可更新到 v${release.version}。`;
      notes.textContent = release.notes || "";
      notes.hidden = !release.notes;
    }
    busy(false);
  };
  install.onclick = async () => {
    if (!release || !confirm(`安装 v${release.version} 并重启？请先保存正在编辑的内容。`)) return;
    const target = release;
    release = null;
    busy(true);
    status.textContent = "正在准备更新…";
    const result = await api("/api/update/install", { method: "POST", body: { version: target.version, sha256: target.sha256 } });
    if (result.ok) return follow(result.job);
    status.textContent = result.error || "未能启动更新，请重新检查";
    busy(false);
  };
  api("/api/update/status").then(result => {
    if (!result.ok || !result.job || check.disabled || !check.isConnected) return;
    status.textContent = result.message;
    if (result.phase === "downloading" || result.phase === "restarting") follow(result.job);
  });
}

function openSettings() {
  if (!modalIsOpen("#settingsModal")) rememberOverlayFocus();
  const st = S.settings || {};
  el("#settingsBody").innerHTML = `
    <div class="section-head"><h3>外观</h3><div class="line"></div></div>
    <div class="option-line">
      <span class="opt-label">明暗</span>
      <div class="seg" id="setModeSeg"><button data-v="dark">深色</button><button data-v="light">浅色</button></div>
    </div>
    <div class="option-line" style="margin-bottom:16px">
      <span class="opt-label">主题</span>
      <div class="seg" id="setThemeSeg"><button data-v="stage">展厅（默认）</button><button data-v="shelf">书架</button></div>
    </div>
    <div class="option-line" style="margin-bottom:16px">
      <label class="opt-label" for="setUiScale">界面缩放</label>
      <select id="setUiScale" class="mini">${["100", "115", "130", "150"].map(value => `<option value="${value}"${value === APPEARANCE.scale ? " selected" : ""}>${value}%${value === "100" ? "（默认）" : ""}</option>`).join("")}</select>
    </div>
    <div class="form-item" style="margin-bottom:14px">
      <label>代理设置（Bangumi、AniList 需要）</label>
      <div class="search-row" style="margin:0">
        <input id="setProxy" value="${esc(st.proxy || "auto")}" placeholder="auto / direct / http://127.0.0.1:7897">
        <button class="btn btn-sm" id="checkProxy">检查代理</button>
      </div>
      <div class="tip" id="proxyState">auto = 自动探测本机常见代理端口；当前：${esc(window.__proxy || "未知")}</div>
    </div>
    <div class="form-item" style="margin-bottom:14px">
      <label>写前快照保留份数（每日自动备份固定保留 15 天）</label>
      <input id="setKeep" type="number" min="5" max="200" value="${esc(st.backup_keep || 30)}">
    </div>
    <div class="section-head" style="margin-top:20px"><h3>沉浸背景</h3><div class="line"></div></div>
    <div class="option-line"><label class="opt-label" for="setBackgroundOrder">播放方式</label><select id="setBackgroundOrder" class="mini"><option value="ordered" ${st.immersive_background_order !== "random" ? "selected" : ""}>按作品行顺序</option><option value="random" ${st.immersive_background_order === "random" ? "selected" : ""}>随机切换</option></select></div>
    <div class="form-item" style="margin-bottom:14px"><label for="setBackgroundInterval">切换间隔（秒）</label><input id="setBackgroundInterval" type="number" min="3" max="300" step="1" value="${esc(Math.max(3, Number(st.immersive_background_interval) || 12))}"><div class="tip">全局生效，范围 3 到 300 秒。</div></div>
    <div class="section-head" style="margin-top:20px"><h3>导出与恢复</h3><div class="line"></div></div>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn" id="expJson">导出 JSON</button>
      <button class="btn" id="expZip">导出完整 ZIP（封面 / 背景 / 音乐）</button>
      <label class="btn" style="cursor:pointer">导入备份<input type="file" id="impFile" accept=".json,.zip,application/json,application/zip" style="display:none"></label>
      <select class="mini" id="impMode"><option value="merge">合并</option><option value="replace">覆盖</option></select>
    </div>
    <div class="section-head" style="margin-top:22px"><h3>导入旧记录</h3><div class="line"></div></div>
    <div class="tip">表头：标题 / 分类 / 原名 / 年份 / 评分 / 标签 / 简介 / 经历日期 / 经历状态 / 经历内容。同一标题写多行 = 同一部作品的多条经历；只导入条目和时间，作品信息之后再逐个「重新获取」。也支持 JSON。</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
      <a class="btn" href="/api/template.csv">下载 CSV 模板</a>
      <label class="btn" style="cursor:pointer">选择文件<input type="file" id="recFile" accept=".csv,.json,.txt" style="display:none"></label>
      <button class="btn" id="recPasteBtn">粘贴文本导入</button>
    </div>
    <textarea id="recPaste" class="reason" style="display:none;width:100%;min-height:120px;margin-top:10px" placeholder="把 CSV 或 JSON 粘贴到这里"></textarea>
    <div style="display:none;gap:10px;margin-top:8px" id="recImportRow">
      <button class="btn btn-primary btn-sm" id="recImport">开始导入</button>
    </div>
    <div class="backup-list" id="backupList"></div>
    <div class="section-head" style="margin-top:22px"><h3>素材清理</h3><div class="line"></div></div>
    <div class="media-cleanup">
      <div class="media-cleanup-actions">
        <button type="button" class="btn" id="mediaScan">检查闲置素材</button>
        <button type="button" class="btn" id="mediaStage" disabled>移入暂存区</button>
      </div>
      <p class="tip" id="mediaStatus" role="status"></p>
      <details id="mediaDetails" hidden><summary>候选文件</summary><ul id="mediaFiles"></ul></details>
      <p class="tip">位置：<code id="mediaFolder">data/素材暂存区</code></p>
    </div>
    <div class="section-head" style="margin-top:22px"><h3>清空数据</h3><div class="line"></div></div>
    <div class="danger-box">
      <div class="tip">准备把项目传到 GitHub 时用。执行前会先把整库和全部封面打包到 <b>娱乐档案_备份\清空前全量备份_日期.zip</b>（在项目目录之外），然后清空作品、系列、封面缓存与项目内快照；代理设置、备份份数保留。</div>
      <button class="btn btn-danger" id="wipeAll">清空全部数据</button>
    </div>
    <div class="section-head" style="margin-top:22px"><h3>关于与更新</h3><div class="line"></div></div>
    <div class="muted-note">娱乐档案 ${esc(versionText(S.version))}</div>
    ${versionStaleNote()}
    <div class="media-cleanup-actions" style="margin-top:8px">
      <a class="btn btn-sm" href="https://github.com/adolfsu/Personal-Entertainment-Archive" target="_blank" rel="noopener noreferrer">GitHub</a>
      <a class="btn btn-sm" href="https://cnb.cool/adolfsu/Personal-Entertainment-Archive" target="_blank" rel="noopener noreferrer">CNB</a>
      <button type="button" class="btn btn-sm" id="updateCheck">检查更新</button>
      <button type="button" class="btn btn-sm" id="updateInstall" disabled>更新并重启</button>
    </div>
    <p class="tip" id="updateStatus" role="status"></p>
    <p class="tip update-notes" id="updateNotes" hidden></p>
    <div class="muted-note" style="margin-top:6px">所有数据只存在这台电脑上</div>`;
  setModalState("#settingsModal", true);
  applyAppearance(false);
  focusAfterRender("#settingsClose");
  bindMediaCleanup();
  bindProjectUpdate();
  el("#setModeSeg").onclick = (e) => {
    const b = e.target.closest("button[data-v]");
    if (b) setMode(b.dataset.v);
  };
  el("#setThemeSeg").onclick = (e) => {
    const b = e.target.closest("button[data-v]");
    if (b) setTheme(b.dataset.v);
  };
  el("#setUiScale").onchange = event => {
    APPEARANCE.scale = event.target.value;
    applyAppearance();
  };
  el("#wipeAll").onclick = async () => {
    if (!confirm("会清空全部作品、经历、评分、系列和封面缓存，确定继续？")) return;
    if (!confirm("再确认一次：清空后只能靠自动备份恢复。继续？")) return;
    const btn = el("#wipeAll");
    btn.disabled = true; btn.textContent = "清理中…";
    const r = await api("/api/clear-data", { method: "POST", body: { confirm: "清空全部" } });
    btn.disabled = false; btn.textContent = "清空全部数据";
    if (!r.ok) return toast(r.error || "清空失败", true);

    closeSettings();
    toast(`已清空 ${r.cleared.works} 部作品、${r.cleared.series} 个系列、${r.cleared.covers} 张封面；备份：${r.backup}`);
  };
  el("#checkProxy").onclick = async () => {
    el("#proxyState").textContent = "检查中…";
    const r = await api("/api/proxy/check", { method: "POST", body: {} });
    el("#proxyState").textContent = "当前：" + (r.proxy || "未探测到可用代理") + (r.proxy ? "（Bangumi 可用）" : "（Bangumi 会失败，其他源不受影响）");
  };
  el("#expJson").onclick = () => location.href = "/api/export";
  el("#expZip").onclick = () => location.href = "/api/export?covers=1";
  el("#impFile").onchange = async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const mode = el("#impMode").value;
    if (mode === "replace" && !confirm("覆盖会清空当前全部作品，确定？")) { ev.target.value = ""; return; }
    const isZip = /\.zip$/i.test(file.name) || /zip/i.test(file.type || "");
    let body;
    if (isZip) {
      const buf = await file.arrayBuffer();
      body = { zip: bufToBase64(buf), mode };
    } else {
      body = { data: await file.text(), mode };
    }
    const r = await api("/api/import", { method: "POST", body });
    ev.target.value = "";
    if (!r.ok) return toast(r.error || "导入失败", true);
    toast(`导入完成，当前共 ${r.count} 部` + (r.covers ? `，补回封面 ${r.covers} 张` : "") + (r.audio ? `，补回音乐 ${r.audio} 首` : ""));
    loadBackups();
  };
  el("#recPasteBtn").onclick = () => {
    const ta = el("#recPaste");
    const row = el("#recImportRow");
    const closed = ta.style.display === "none";
    ta.style.display = closed ? "block" : "none";
    row.style.display = closed ? "flex" : "none";
    if (closed) ta.focus();
  };
  el("#recFile").onchange = async (ev) => {
    const f = ev.target.files[0];
    if (!f) return;
    const text = await f.text();
    await doImportRecords(text, f.name);
    ev.target.value = "";
  };
  el("#recImport").onclick = () => doImportRecords(el("#recPaste").value, "粘贴内容");
  loadBackups();
}

async function doImportRecords(text, label) {
  if (!text || !text.trim()) return toast("内容是空的", true);
  const r = await api("/api/import-records", { method: "POST", body: { text } });
  if (!r.ok) return toast(r.error || "导入失败", true);
  toast(`${label}：新增 ${r.created} 部、补充 ${r.updated} 部、写入经历 ${r.experiences} 条`);

}

async function loadBackups() {
  const r = await api("/api/backups");
  const box = el("#backupList");
  if (!box) return;
  S.backups = r.backups || [];
  if (!S.backups.length) { box.innerHTML = `<div class="muted-note">还没有自动快照，第一次修改后就会生成。</div>`; return; }
  box.innerHTML = S.backups.map(b => `<div class="backup-row">
    <span class="b-kind">${esc(b.label || "备份")}</span>
    <span class="b-time">${esc(b.time)}</span>
    <span class="b-size">${(b.size / 1024).toFixed(0)} KB</span>
    <button class="btn btn-sm" data-restore="${esc(b.name)}" data-rkind="${esc(b.kind)}">恢复</button>
  </div>`).join("");
  elAll("[data-restore]", box).forEach(x => x.onclick = async () => {
    x.disabled = true;
    const ok = await restoreBackup(x.dataset.rkind, x.dataset.restore);
    x.disabled = false;
    if (!ok) return;
    loadBackups();
  });
}

function closeSettings() {
  if (!modalIsOpen("#settingsModal")) return;
  restoreOverlayFocus();
  setModalState("#settingsModal", false);
}

/* ------------------------------------------------------------ 全局事件 */
function bindGlobal() {
  el("#syncRetry").onclick = async () => {
    const btn = el("#syncRetry");
    btn.disabled = true;
    try {
     if (await reloadAll()) { if (S.currentSeriesId) renderSeriesDrawer(); toast("数据已同步"); }
    } finally { btn.disabled = false; }
  };
  el("#searchInput").oninput = (e) => {
    S.filters.q = e.target.value;
    if (S.filters.q.trim() && S.view !== "archive") setAppView("archive");
    renderWall();
  };
  elAll("#sortSelect").forEach(s => s.onchange = (e) => { S.filters.sort = e.target.value; renderWall(); });
  elAll("#timeSelect").forEach(s => s.onchange = (e) => { S.filters.time = e.target.value; renderWall(); });
  el("#addBtn").onclick = openAdd;
  el("#menuBtn").onclick = openSettings;
  el("#musicOpenBtn").onclick = openAudioPlaylist;
  document.addEventListener("archive-music-open", openAudioPlaylist);
  el("#audioPlayerLaunch").onclick = openAudioPlaylist;
  el("#audioPlayer").addEventListener("click", event => {
    const action = event.target.closest("[data-player-action]")?.dataset.playerAction;
    if (action === "open") openAudioPlaylist();
    else if (action === "toggle") audioPlayer.play();
    else if (action === "next") audioPlayer.next();
    else if (action === "previous") audioPlayer.previous();
  });
  el("#audioPlayer").querySelector("[data-player-volume]").oninput = event => audioPlayer.setVolume(Number(event.target.value) / 100);
  el("#musicClose").onclick = closeAudioPlaylist;
  el("#musicCancel").onclick = closeAudioPlaylist;
  el("#musicModal").onclick = event => { if (event.target.id === "musicModal") closeAudioPlaylist(); };
  elAll("[data-audio-mode]").forEach(button => button.onclick = () => {
    audioPlayer.setMode(button.dataset.audioMode);
    if (button.dataset.audioMode !== "immersive") audioPlayer.setQueue(filteredAudioCatalog());
    elAll("[data-audio-mode]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
    renderAudioPlaylist();
  });
  el("#musicSearch").oninput = event => { musicSearch = event.target.value; updateAudioQueue(); };
  el("#musicCategory").onchange = event => { musicCategory = event.target.value; updateAudioQueue(); };
  el("#musicShuffle").onchange = event => audioPlayer.setShuffle(event.target.checked);
  el("#musicStart").onclick = () => {
    const tracks = filteredAudioCatalog();
    if (!tracks.length) return toast("没有可播放的歌曲", true);
    audioPlayer.setQueue(tracks);
    if (audioPlayer.snapshot().mode === "immersive") audioPlayer.setMode("global");
    audioPlayer.play();
  };
  el("#musicTrackList").onclick = event => {
    const track = event.target.closest("[data-audio-track]");
    if (!track) return;
    audioPlayer.setQueue(filteredAudioCatalog());
    audioPlayer.playTrack(track.dataset.audioTrack);
    renderAudioPlaylist();
  };
  el("#musicTrackList").onkeydown = event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const track = event.target.closest("[data-audio-track]");
    if (!track) return;
    event.preventDefault();
    audioPlayer.setQueue(filteredAudioCatalog());
    audioPlayer.playTrack(track.dataset.audioTrack);
  };
  el("#undoBtn").onclick = doUndo;
  el("#modeBtn").onclick = () => setMode(APPEARANCE.mode === "dark" ? "light" : "dark");
  el("#themeBtn").onclick = () => setTheme(APPEARANCE.theme === "stage" ? "shelf" : "stage");
  elAll("[data-app-nav]").forEach(button => button.onclick = () => setAppView(button.dataset.appNav));
  ArchiveV2.collection?.bind();
  el("#sidebarToggle").onclick = toggleSidebar;
  window.matchMedia("(max-width: 900px)").addEventListener("change", closeSidebar);
  el("#sidebarScrim").onclick = closeSidebar;
  el("#homeView").onclick = handleHomeAction;
  el("#hiddenWorksClose").onclick = closeHomeManager;
  el("#hiddenWorksCancel").onclick = closeHomeManager;
  el("#hiddenWorksSave").onclick = saveHomeManager;
  el("#hiddenWorksModal").onclick = event => { if (event.target.id === "hiddenWorksModal") closeHomeManager(); };
  elAll("#sizeSeg button").forEach(b => b.onclick = () => setSize(b.dataset.size));
  el("#newSeriesBtn").onclick = () => openSeriesModal();
  el("#enterExhibit").onclick = () => openImmersive(null, "fullscreen");
  el("#seriesClose").onclick = closeSeriesModal;
  el("#seriesCancel").onclick = closeSeriesModal;
  el("#seriesModal").onclick = (e) => { if (e.target.id === "seriesModal") closeSeriesModal(); };
  el("#seriesSave").onclick = saveSeriesDraft;
  el("#seriesManagerBackdrop").onclick = closeDrawer;
  el("#settingsClose").onclick = closeSettings;
  el("#settingsClose2").onclick = closeSettings;
  el("#settingsModal").onclick = (e) => { if (e.target.id === "settingsModal") closeSettings(); };
  el("#saveSettings").onclick = async () => {
    const body = { proxy: el("#setProxy").value.trim() || "auto", backup_keep: Number(el("#setKeep").value) || 30,
      immersive_background_order: el("#setBackgroundOrder").value,
      immersive_background_interval: Math.max(3, Math.min(300, Number(el("#setBackgroundInterval").value) || 12)) };
    const r = await api("/api/settings", { method: "POST", body });
    if (!r.ok) return toast("保存失败", true);
    S.settings = r.settings; toast("设置已保存"); closeSettings();
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      const root = activeOverlayRoot();
      if (root) {
        const items = Array.from(root.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'))
          .filter(x => x.getClientRects().length && getComputedStyle(x).visibility !== "hidden");
        if (items.length) {
          const first = items[0], last = items[items.length - 1];
          if (!root.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); return; }
          if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); return; }
        }
      }
    }
    if (e.key === "Escape") {
      if (el("#addModal").classList.contains("show")) closeAdd();
      else if (el("#seriesModal").classList.contains("show")) closeSeriesModal();
      else if (el("#settingsModal").classList.contains("show")) closeSettings();
      else if (el("#hiddenWorksModal").classList.contains("show")) closeHomeManager();
      else if (el("#musicModal").classList.contains("show")) closeAudioPlaylist();
      else if (S.currentSeriesId) closeDrawer();
      else if (immersiveView?.isOpen()) immersiveView.close();
      else if (document.body.classList.contains("sidebar-open")) closeSidebar();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
      const tag = (document.activeElement.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || document.activeElement.isContentEditable) return;
      if (activeOverlayRoot()) return;
      e.preventDefault();
      doUndo();
      return;
    }
    if (e.key === "/" && !activeOverlayRoot() && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      e.preventDefault(); el("#searchInput").focus();
    }
  });
}

applyAppearance(false);
boot();
