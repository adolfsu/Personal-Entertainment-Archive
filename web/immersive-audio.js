/* 一个持久播放器服务所有沉浸页面；图像渲染、悬停和容器切换不触发换曲。 */
(() => {
  function source(value) {
    if (typeof value !== "string" || value.length > 4096 || /[\s\x00-\x1f\x7f]/.test(value)) return "";
    if (/^\/audio\/[a-f0-9]{64}\.mp3$/.test(value)) return value;
    try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url.href : ""; } catch (_) { return ""; }
  }
  function binding(entity) {
    const src = source(entity?.bgm?.src);
    return src ? {src, title:String(entity.bgm.title || "背景音乐").slice(0, 200), artist:String(entity.bgm.artist || "").slice(0, 200)} : null;
  }
  function resolve(work, series, isSeries = false) {
    const own = binding(isSeries ? series : work), shared = !isSeries && binding(series);
    return own ? {...own, owner:isSeries ? "系列音乐" : "作品音乐"} : shared ? {...shared, owner:"沿用系列音乐"} : null;
  }
  const MODES = ["global", "immersive", "playlist"];
  const CATEGORIES = ["anime", "manga", "game", "novel", "book", "movie", "shortdrama"];

  function playlist(works = [], series = []) {
    const tracks = [];
    for (const work of works) {
      const bgm = binding(work);
      if (bgm && work?.id) tracks.push({...bgm, id:`work:${work.id}`, workId:String(work.id), workTitle:work.title || "未命名作品", category:CATEGORIES.includes(work.category) ? work.category : "", owner:"作品音乐"});
    }
    for (const item of series) {
      const bgm = binding(item);
      if (!bgm) continue;
      const member = (item.members || []).find(entry => entry?.id && works.some(work => String(work.id) === String(entry.id)));
      const work = member && works.find(candidate => String(candidate.id) === String(member.id));
      tracks.push({...bgm, id:`series:${item.id}`, workId:work?.id ? String(work.id) : "", workTitle:work?.title || item.name || "未绑定作品", category:CATEGORIES.includes(work?.category) ? work.category : "", owner:"系列音乐"});
    }
    return tracks;
  }

  function create({mediaFactory = () => typeof Audio === "function" ? new Audio() : {volume:0,currentTime:0,paused:true,play(){return Promise.resolve();},pause(){this.paused=true;},load(){},removeAttribute(){this.src="";}}, storage = globalThis.localStorage, schedule = setTimeout, unschedule = clearTimeout,
    repeat = setInterval, unrepeat = clearInterval, now = () => Date.now(), onChange = () => {}, onTrackStart = () => {}, onNavigate = () => {}} = {}) {
    const key = "grdag_audio_player";
    let prefs = {mode:"immersive",enabled:true,volume:.2,loop:true,pauseHidden:true,shuffle:false};
    try {
      const saved = JSON.parse(storage?.getItem(key) || storage?.getItem("grdag_immersive_audio") || "null");
      if (saved && typeof saved === "object") prefs = {mode:MODES.includes(saved.mode) ? saved.mode : "immersive",enabled:saved.enabled !== false,
        volume:Number.isFinite(saved.volume) ? Math.max(0, Math.min(1, saved.volume)) : .2,loop:saved.loop !== false,
        pauseHidden:saved.pauseHidden !== false,shuffle:saved.shuffle === true};
    } catch (_) { /* 浏览器不允许保存偏好时仍可播放。 */ }
    const slots = [0, 1].map(() => ({audio:mediaFactory(), src:"", gain:0, fade:null, token:0}));
    const positions = new Map();
    const played = new Set();
    let catalog = [], queue = [], index = -1, target = null, active = null, opened = false, paused = false, hidden = false, epoch = 0, waiting = null, state = "off", error = "", startPending = false;
    function save() { try { storage?.setItem(key, JSON.stringify(prefs)); } catch (_) {} }
    function emit() { onChange(snapshot()); }
    function currentTrack() { return index >= 0 && index < queue.length ? queue[index] : null; }
    function desired() { return prefs.mode === "immersive" ? (opened ? target : null) : currentTrack(); }
    function snapshot() { const item = desired(); return {...prefs,target:item,track:item,state,error,paused,currentIndex:index,queueCount:queue.length,canNext:queue.length>1,canPrevious:queue.length>1}; }
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
    function shouldPlay() { return prefs.enabled && !paused && !(hidden && prefs.pauseHidden) && !!desired(); }
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
    function advance(direction = 1) {
      if (!queue.length) return;
      if (prefs.shuffle && direction > 0 && queue.length > 1) {
        played.add(index); if (played.size >= queue.length) played.clear();
        const candidates = queue.map((_, i) => i).filter(i => i !== index && !played.has(i));
        index = candidates[Math.floor(Math.random() * candidates.length)] ?? (index + 1) % queue.length;
      } else index = (index + direction + queue.length) % queue.length;
      paused = false; prefs.enabled = true; startPending = true; save();
      if (prefs.mode === "playlist") onNavigate(currentTrack(), snapshot());
      drive();
    }
    function drive() {
      const desiredTarget = desired();
      if (!shouldPlay()) {
        epoch++; halt(hidden && prefs.pauseHidden || paused || !desiredTarget);
        state = !prefs.enabled ? "off" : paused ? "paused" : hidden && prefs.pauseHidden ? "hidden" : desiredTarget ? "idle" : "empty";
        error = ""; emit(); return;
      }
      if (active?.src === desiredTarget.src && ["playing", "loading"].includes(state)) { emit(); return; }
      const token = ++epoch; error = ""; clearWait();
      const old = active;
      active = null;
      if (old?.src) { old.token++; old.audio.onerror = null; old.audio.onloadedmetadata = null; old.audio.onended = null; fade(old, 0, () => release(old)); }
      const slot = slots.find(item => item !== old) || slots[0]; release(slot);
      active = slot; slot.src = desiredTarget.src; slot.token++;
      const slotToken = slot.token, src = slot.src;
      const alive = () => token === epoch && slot.token === slotToken && active === slot && shouldPlay();
      state = "loading";
      slot.audio.preload = "auto"; slot.audio.loop = prefs.mode === "immersive" && prefs.loop; slot.audio.src = src; gain(slot, 0);
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
      slot.audio.onended = () => {
        if (!alive()) return;
        if (prefs.mode === "immersive") {
          if (!prefs.loop) { state = "ended"; emit(); }
        } else advance(1);
      };
      waiting = schedule(() => fail(new Error("timeout")), 15000);
      emit();
      try {
        // 直接在点击开启/播放的事件中调用，保留浏览器的用户手势。
        Promise.resolve(slot.audio.play()).then(() => {
          if (!alive()) return;
          clearWait(); state = "playing"; fade(slot, 1);
          if (startPending && prefs.mode === "playlist") onTrackStart(desiredTarget, snapshot());
          startPending = false; emit();
        }, fail);
      } catch (reason) { fail(reason); }
    }
    return {
      snapshot, catalog:() => catalog.slice(), tracks:() => queue.slice(),
      setCatalog(items) {
        const previous = currentTrack()?.id;
        catalog = (Array.isArray(items) ? items : []).map((item, i) => { const src = source(item?.src); return src ? {...item,id:String(item.id || `${src}:${i}`),src} : null; }).filter(Boolean);
        queue = catalog.slice();
        if (previous) { const found = queue.findIndex(item => item.id === previous); index = found >= 0 ? found : queue.length ? 0 : -1; }
        if (index < 0 && queue.length) index = 0;
        if (prefs.mode === "immersive") emit(); else drive();
      },
      setQueue(items) {
        const previousTrack = currentTrack();
        const previous = previousTrack?.id;
        const previousSrc = previousTrack?.src;
        const activePosition = active?.audio.currentTime;
        queue = (Array.isArray(items) ? items : []).map((item, i) => { const src = source(item?.src); return src ? {...item,id:String(item.id || `${src}:${i}`),src} : null; }).filter(Boolean);
        index = previous ? queue.findIndex(item => item.id === previous) : -1;
        if (index < 0 && queue.length) index = 0;
        played.clear();
        const sameSource = previousSrc && currentTrack()?.src === previousSrc && active?.src === previousSrc;
        if (sameSource && Number.isFinite(activePosition)) positions.set(previousSrc, activePosition);
        if (prefs.mode === "playlist" && currentTrack()?.workId && active?.src !== currentTrack().src) onNavigate(currentTrack(), snapshot());
        if (prefs.mode === "immersive" || sameSource) emit(); else drive();
      },
      playTrack(id) {
        const found = queue.findIndex(item => item.id === String(id)); if (found < 0) return false;
        index = found; prefs.enabled = true; paused = false; startPending = true;
        if (prefs.mode === "immersive") prefs.mode = "playlist";
        save();
        if (prefs.mode === "playlist") onNavigate(currentTrack(), snapshot());
        drive();
        return true;
      },
      setMode(value) {
        if (!MODES.includes(value)) return;
        if (prefs.mode === value) { emit(); return; }
        prefs.mode = value; prefs.enabled = true; paused = false; startPending = true;
        if (value !== "immersive" && index < 0 && queue.length) index = 0;
        save();
        if (value === "playlist" && currentTrack()?.workId) onNavigate(currentTrack(), snapshot());
        drive();
      },
      setTarget(next) {
        const valid = next && source(next.src) ? {...next, src:source(next.src)} : null;
        if (!opened) paused = false;
        opened = true;
        const same = target?.src === valid?.src;
        target = valid;
        if (!same && valid && prefs.mode === "immersive" && !paused) { prefs.enabled = true; startPending = true; save(); }
        if (prefs.mode === "immersive") { if (same && ["blocked", "error"].includes(state)) { emit(); return; } drive(); }
        else emit();
      },
      toggle() {
        this.play();
      },
      play() {
        if (prefs.mode !== "immersive" && !queue.length) queue = catalog.slice();
        if (prefs.mode !== "immersive" && index < 0 && queue.length) index = 0;
        if (["playing", "loading"].includes(state)) paused = true;
        else { prefs.enabled = true; paused = false; const item = desired(); if (state === "ended" && item) positions.delete(item.src); }
        if (prefs.mode === "playlist" && !opened && currentTrack()?.workId) onNavigate(currentTrack(), snapshot());
        save(); drive();
      },
      next() { advance(1); }, previous() { advance(-1); },
      setEnabled(value) { prefs.enabled = !!value; paused = false; save(); drive(); },
      setShuffle(value) { prefs.shuffle = !!value; played.clear(); save(); emit(); },
      setVolume(value) { prefs.volume = Math.max(0, Math.min(1, Number(value) || 0)); slots.forEach(slot => gain(slot, slot.gain)); save(); emit(); },
      setLoop(value) { prefs.loop = !!value; slots.forEach(slot => { slot.audio.loop = prefs.mode === "immersive" && prefs.loop; }); save(); emit(); },
      setPauseHidden(value) { prefs.pauseHidden = !!value; save(); drive(); },
      visibility(value) { hidden = !!value; drive(); },
      close() {
        opened = false;
        if (prefs.mode === "immersive") { target = null; paused = false; }
        drive();
      },
      destroy() { opened = false; epoch++; halt(true); },
    };
  }
  globalThis.ArchiveV2 = Object.assign(globalThis.ArchiveV2 || {}, {audio:{source,binding,resolve,playlist,create,modes:MODES,categories:CATEGORIES}});
})();
