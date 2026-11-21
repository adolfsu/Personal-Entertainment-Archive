/* 展示层共享协调：实体仍由 app.js 的 S 持有，系列统计仍由服务端计算。 */
(() => {
  const core = {
    isMutation(path, method) {
      return method !== "GET" && (
        /^\/api\/(works|series)(\/|$)/.test(path) ||
        ["/api/tmdb/import", "/api/import", "/api/import-records", "/api/clear-data",
          "/api/undo", "/api/backups/restore", "/api/recover/new-start"].includes(path)
      );
    },
    createQueue() {
      let tail = Promise.resolve();
      return task => {
        const result = tail.then(task, task);
        tail = result.catch(() => {});
        return result;
      };
    },
    validSnapshot(data) {
      return !!data && data.ok !== false && Array.isArray(data.works) && Array.isArray(data.series);
    },
    showEmptySeries(filters) {
      return filters.group === "series" && filters.cat === "all" && filters.status === "all" &&
        filters.time === "all" && !filters.q.trim();
    },
    exhibitionItems(works, series, filters) {
      if (filters.group !== "series") return works.map(work => ({ type: "work", entity: work }));
      const byId = new Map(series.map(item => [item.id, item]));
      const seen = new Set();
      const visibleIds = new Set(works.map(work => work.id));
      const filtered = filters.cat !== "all" || filters.status !== "all" || filters.time !== "all" || !!filters.q.trim();
      const items = [];
      for (const work of works) {
        const collection = byId.get(work.primarySeriesId);
        if (!collection) { items.push({ type: "work", entity: work }); continue; }
        if (seen.has(collection.id)) continue;
        seen.add(collection.id);
        items.push({ type: "series", entity: collection, filtered,
          matchedCount: (collection.members || []).filter(member => visibleIds.has(member.id)).length });
      }
      if (core.showEmptySeries(filters)) {
        for (const collection of series) {
          if (collection.memberCount === 0 && !seen.has(collection.id)) {
            items.push({ type: "series", entity: collection, filtered: false, matchedCount: 0 });
          }
        }
      }
      return items;
    },
  };
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { core });
})();
