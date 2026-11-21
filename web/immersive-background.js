/* 仅浏览器加载：多张自定义背景 → 封面 → 默认；异步结果按版本隔离。 */
(() => {
  function safeRemoteUrl(value) {
    if (typeof value !== "string" || value.length > 4096 || /[\s\x00-\x1f\x7f]/.test(value.trim())) return "";
    try {
      const url = new URL(value.trim());
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : "";
    } catch (_) { return ""; }
  }
  function createLoader({ imageFactory = () => new Image(), timeout = 6000, schedule = setTimeout, unschedule = clearTimeout } = {}) {
    let version = 0, cleanup = () => {};
    function cancel() { version++; cleanup(); cleanup = () => {}; }
    function load(work, display, settings = {}, options = {}) {
      cancel();
      const current = version;
      const raw = Array.isArray(work.immersiveBackgroundUrls) ? work.immersiveBackgroundUrls : [work.immersiveBackgroundUrl];
      let urls = [...new Set(raw.map(safeRemoteUrl).filter(Boolean))];
      const start = urls.indexOf(options.startUrl);
      if (start > 0) urls = [...urls.slice(start), ...urls.slice(0, start)];
      const covers = [...new Set([work.coverUrl, ...(options.fallbackCovers || [])])]
        .filter(url => typeof url === "string" && /^\/covers\/[^/]+$/.test(url));
      const interval = Math.max(5, Math.min(300, Number(settings.immersive_background_interval) || 12)) * 1000;
      const random = settings.immersive_background_order === "random";
      const failedUrls = new Set();
      let position = -1, timer = null, pendingCancel = () => {};
      if (!options.keepCurrent) display(null, "default");
      const alive = () => current === version;
      function makeImage(url, kind, onload, onerror) {
        const img = imageFactory();
        let finished = false;
        const timeoutId = schedule(fail, timeout);
        function detach() { unschedule(timeoutId); img.onload = null; img.onerror = null; }
        function fail() { if (finished || !alive()) return; finished = true; detach(); onerror(); }
        img.onload = () => {
          if (finished || !alive()) return;
          if (!img.naturalWidth || !img.naturalHeight) { fail(); return; }
          finished = true; detach(); onload(img, kind);
        };
        img.onerror = fail; img.referrerPolicy = "no-referrer"; img.decoding = "async"; img.src = url;
        return () => { if (finished) return; finished = true; detach(); img.removeAttribute("src"); };
      }
      function selectNext() {
        const candidates = urls.map((url, index) => index).filter(index => index !== position && !failedUrls.has(urls[index]));
        if (!candidates.length) return -1;
        if (random) return candidates[Math.floor(Math.random() * candidates.length)];
        for (let step = 1; step < urls.length; step++) {
          const index = (position + step) % urls.length;
          if (!failedUrls.has(urls[index])) return index;
        }
        return -1;
      }
      function rotate() {
        if (!alive() || urls.length < 2) return;
        const index = selectNext();
        if (index < 0) return;
        pendingCancel = makeImage(urls[index], "dedicated", (img) => {
          position = index; display(img, "dedicated");
          if (selectNext() >= 0) timer = schedule(rotate, interval);
        }, () => { failedUrls.add(urls[index]); rotate(); });
      }
      function initial(index) {
        if (!alive()) return;
        if (index < urls.length) {
          pendingCancel = makeImage(urls[index], "dedicated", (img) => {
            position = index; display(img, "dedicated");
            if (urls.length > 1 && selectNext() >= 0) timer = schedule(rotate, interval);
          }, () => { failedUrls.add(urls[index]); initial(index + 1); });
          return;
        }
        fallback(0);
      }
      function fallback(index) {
        if (!alive()) return;
        if (index < covers.length) pendingCancel = makeImage(covers[index], "cover", (img, kind) => display(img, kind), () => fallback(index + 1));
        else options.onExhausted?.();
      }
      cleanup = () => { unschedule(timer); pendingCancel(); };
      initial(0);
    }
    return { load, cancel };
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, { backgrounds: { safeRemoteUrl, createLoader } });
})();
