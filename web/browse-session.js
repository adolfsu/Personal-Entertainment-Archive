/* 纯浏览会话：只保存来源顺序和 ID，始终由调用方读取最新实体。 */
(() => {
  const browse = {
    create(ids, currentId, surface = "overlay") {
      const sequence = [...new Set(ids)];
      if (!sequence.includes(currentId)) return null;
      return { ids: sequence, currentId, page: "work", surface: surface === "fullscreen" ? "fullscreen" : "overlay" };
    },
    adjacent(session, offset) {
      return session.ids[session.ids.indexOf(session.currentId) + offset] || null;
    },
    reconcile(session, existingIds) {
      const valid = new Set(existingIds);
      const index = session.ids.indexOf(session.currentId);
      session.ids = session.ids.filter(id => valid.has(id));
      if (!valid.has(session.currentId)) session.currentId = session.ids[Math.min(Math.max(0, index), session.ids.length - 1)] || null;
      return !!session.currentId;
    },
  };
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { browse });
})();
