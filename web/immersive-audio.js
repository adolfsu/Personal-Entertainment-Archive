/* 一个持久播放器服务所有沉浸页面；图像渲染、悬停和容器切换不触发换曲。 */
(() => {
  function source(value) {
    if (typeof value !== "string" || value.length > 4096 || /[\s\x00-\x1f\x7f]/.test(value)) return "";
    if (/^\/audio\/[a-f0-9]{64}\.mp3$/.test(value)) return value;
    try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url.href : ""; } catch (_) { return ""; }
  }
  function binding(entity) {
    const src = source(entity?.bgm?.src);
    return src ? {src, title:String(entity.bgm.title || "背景音乐").slice(0, 200)} : null;
  }
  function resolve(work, series, isSeries = false) {
    const own = binding(isSeries ? series : work), shared = !isSeries && binding(series);
    return own ? {...own, owner:isSeries ? "系列音乐" : "作品音乐"} : shared ? {...shared, owner:"沿用系列音乐"} : null;
  }
  function create({mediaFactory = () => new Audio(), storage = globalThis.localStorage, schedule = setTimeout, unschedule = clearTimeout,
    repeat = setInterval, unrepeat = clearInterval, now = () => Date.now(), onChange = () => {}} = {}) {
    const key = "grdag_immersive_audio";
    let prefs = {enabled:false, volume:.2, loop:true, pauseHidden:true};
    try {
      const saved = JSON.parse(storage?.getItem(key) || "null");
      if (saved && typeof saved === "object") prefs = {enabled:saved.enabled === true, volume:Number.isFinite(saved.volume) ? Math.max(0, Math.min(1, saved.volume)) : .2,
        loop:saved.loop !== false, pauseHidden:saved.pauseHidden !== false};
    } catch (_) { /* 浏览器不允许保存偏好时仍可播放。 */ }
    const slots = [0, 1].map(() => ({audio:mediaFactory(), src:"", gain:0, fade:null, token:0}));
    const positions = new Map();
    let target = null, active = null, opened = false, paused = false, hidden = false, epoch = 0, waiting = null, state = "off", error = "";
    function save() { try { storage?.setItem(key, JSON.stringify(prefs)); } catch (_) {} }
    function emit() { onChange(snapshot()); }
    function snapshot() { return {...prefs, target, state, error, paused}; }
    function remember(slot) {
      if (slot.src && Number.isFinite(slot.audio.currentTime)) {
        positions.delete(slot.src); positions.set(slot.src, slot.audio.currentTime);
        if (positions.size > 40) positions.delete(positions.keys().next().value);
      }
    }
    function gain(slot, value) { slot.gain = value; slot.audio.volume = prefs.volume * value; }
    function stopFade(slot) { if (slot.fade != null) unrepeat(slot.fade); slot.fade = null; }
    function release(slot) {
      stopFade(slot); remember(slot); slot.audio.pause(); slot.token++;
      slot.audio.onloadedmetadata = null; slot.audio.onerror = null; slot.audio.onended = null;
      slot.audio.removeAttribute("src"); slot.audio.load(); slot.src = ""; gain(slot, 0);
    }
    function fade(slot, to, done = () => {}) {
      stopFade(slot);
      const start = now(), from = slot.gain;
      slot.fade = repeat(() => {
        const fraction = Math.min(1, (now() - start) / 1000);
        gain(slot, from + (to - from) * fraction);
        if (fraction >= 1) { stopFade(slot); done(); }
      }, 40);
    }
    function shouldPlay() { return opened && prefs.enabled && !paused && !(hidden && prefs.pauseHidden) && !!target; }
    function clearWait() { unschedule(waiting); waiting = null; }
    function halt(immediate = false) {
      clearWait(); active = null;
      for (const slot of slots) {
        if (!slot.src) continue;
        slot.token++; // 所有未完成 play() 结果立即失效。
        slot.audio.onerror = null; slot.audio.onended = null; slot.audio.onloadedmetadata = null;
        if (immediate || slot.gain === 0) release(slot);
        else fade(slot, 0, () => release(slot));
      }
    }
    function drive() {
      if (!shouldPlay()) {
        epoch++; halt(hidden && prefs.pauseHidden || paused);
        state = !prefs.enabled ? "off" : paused ? "paused" : hidden && prefs.pauseHidden ? "hidden" : target ? "idle" : "empty";
        error = ""; emit(); return;
      }
      if (active?.src === target.src && ["playing", "loading", "ended"].includes(state)) { emit(); return; }
      const token = ++epoch; error = ""; clearWait();
      const old = active;
      active = null;
      if (old?.src) { old.token++; old.audio.onerror = null; old.audio.onloadedmetadata = null; old.audio.onended = null; fade(old, 0, () => release(old)); }
      const slot = slots.find(item => item !== old) || slots[0]; release(slot);
      active = slot; slot.src = target.src; slot.token++;
      const slotToken = slot.token, src = slot.src;
      const alive = () => token === epoch && slot.token === slotToken && active === slot && shouldPlay();
      state = "loading";
      slot.audio.preload = "auto"; slot.audio.loop = prefs.loop; slot.audio.src = src; gain(slot, 0);
      slot.audio.onloadedmetadata = () => {
        if (!alive()) return;
        const position = positions.get(src) || 0;
        try { slot.audio.currentTime = Number.isFinite(slot.audio.duration) && position >= slot.audio.duration - .1 ? 0 : position; } catch (_) {}
      };
      function fail(reason) {
        if (!alive()) return;
        clearWait(); halt(true); state = reason?.name === "NotAllowedError" ? "blocked" : "error";
        error = state === "blocked" ? "点击播放，允许浏览器开始音乐" : "音乐加载失败，请检查文件或音频直链";
        emit();
      }
      slot.audio.onerror = () => fail(new Error("media"));
      slot.audio.onended = () => { if (alive() && !prefs.loop) { state = "ended"; emit(); } };
      waiting = schedule(() => fail(new Error("timeout")), 15000);
      emit();
      try {
        // 直接在点击开启/播放的事件中调用，保留浏览器的用户手势。
        Promise.resolve(slot.audio.play()).then(() => {
          if (!alive()) return;
          clearWait(); state = "playing"; fade(slot, 1); emit();
        }, fail);
      } catch (reason) { fail(reason); }
    }
    return {
      snapshot,
      setTarget(next) {
        const valid = next && source(next.src) ? {...next, src:source(next.src)} : null;
        if (!opened) paused = false;
        opened = true;
        const same = target?.src === valid?.src;
        target = valid;
        if (same && ["blocked", "error"].includes(state)) { emit(); return; }
        drive();
      },
      setEnabled(value) { prefs.enabled = !!value; paused = false; save(); drive(); },
      toggle() {
        if (!prefs.enabled) { prefs.enabled = true; paused = false; save(); }
        else if (["playing", "loading"].includes(state)) paused = true;
        else { paused = false; if (state === "ended" && target) positions.delete(target.src); }
        drive();
      },
      setVolume(value) { prefs.volume = Math.max(0, Math.min(1, Number(value) || 0)); slots.forEach(slot => gain(slot, slot.gain)); save(); emit(); },
      setLoop(value) { prefs.loop = !!value; slots.forEach(slot => { slot.audio.loop = prefs.loop; }); save(); emit(); },
      setPauseHidden(value) { prefs.pauseHidden = !!value; save(); drive(); },
      visibility(value) { hidden = !!value; drive(); },
      close() { opened = false; epoch++; halt(); state = "off"; emit(); },
      destroy() { opened = false; epoch++; halt(true); },
    };
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, {audio:{source,binding,resolve,create}});
})();
