/* 首页进行中作品的数据整理；不修改作品或设置对象。 */
(() => {
  function normalizeHidden(ids) {
    if (!Array.isArray(ids)) return [];
    const seen = new Set();
    const result = [];
    for (const value of ids) {
      if (typeof value !== "string") continue;
      const id = value.trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      result.push(id);
    }
    return result;
  }

  function recentTime(work) {
    const values = [work?.lastExperienceAt, work?.updatedAt, work?.createdAt];
    let latest = 0;
    for (const value of values) {
      if (!value) continue;
      const timestamp = Date.parse(value);
      if (Number.isFinite(timestamp)) latest = Math.max(latest, timestamp);
    }
    return latest;
  }

  function sortRecent(works) {
    return (Array.isArray(works) ? works : [])
      .map((work, index) => ({ work, index, timestamp: recentTime(work) }))
      .sort((a, b) => b.timestamp - a.timestamp || a.index - b.index)
      .map(entry => entry.work);
  }

  function activeWorks(works, hiddenIds = []) {
    const hidden = new Set(normalizeHidden(hiddenIds));
    return sortRecent((Array.isArray(works) ? works : []).filter(work =>
      work && work.status === "active" && typeof work.id === "string" && !hidden.has(work.id)
    ));
  }

  function hiddenWorks(works, hiddenIds = []) {
    const hidden = new Set(normalizeHidden(hiddenIds));
    return (Array.isArray(works) ? works : []).filter(work => work && hidden.has(work.id));
  }

  function setHidden(hiddenIds, id, shouldHide) {
    const next = normalizeHidden(hiddenIds);
    if (typeof id !== "string" || !id.trim()) return next;
    const normalizedId = id.trim();
    return shouldHide
      ? (next.includes(normalizedId) ? next : [...next, normalizedId])
      : next.filter(value => value !== normalizedId);
  }

  const homeFeed = { normalizeHidden, recentTime, sortRecent, activeWorks, hiddenWorks, setHidden };
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { homeFeed });
  if (typeof module !== "undefined" && module.exports) module.exports = homeFeed;
})();
