(function () {
  "use strict";

  var JSON_LIMIT = 120000;

  function txt(value) {
    return (value == null ? "" : String(value)).replace(/\s+/g, " ").trim();
  }

  function first(value) {
    if (Array.isArray(value)) return value.length ? value[0] : "";
    return value;
  }

  function names(value) {
    if (!value) return [];
    var list = Array.isArray(value) ? value : [value];
    return list.map(function (item) {
      if (typeof item === "string") return txt(item);
      return txt(item && (item.name || item.alternateName || item["@id"]));
    }).filter(Boolean);
  }

  function imageUrl(value) {
    if (!value) return "";
    if (typeof value === "string") return txt(value);
    if (Array.isArray(value)) return imageUrl(first(value));
    return txt(value.url || value.contentUrl || value["@id"]);
  }

  function pageImages() {
    var out = [];
    var scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < scripts.length; i++) {
      try {
        var parsed = JSON.parse(scripts[i].textContent);
        if (Array.isArray(parsed)) out = out.concat(parsed);
        else if (parsed && Array.isArray(parsed["@graph"])) out = out.concat(parsed["@graph"]);
        else if (parsed) out.push(parsed);
      } catch (e) {}
    }
    return out;
  }

  function mainRecord() {
    var records = pageImages();
    for (var i = 0; i < records.length; i++) {
      var type = records[i] && records[i]["@type"];
      if (Array.isArray(type)) type = type[0];
      if (type === "Movie" || type === "TVSeries") return records[i];
    }
    return null;
  }

  function metaContent(name) {
    var node = document.querySelector('meta[property="' + name + '"], meta[name="' + name + '"]');
    return node ? txt(node.getAttribute("content")) : "";
  }

  function domPeople(label) {
    var out = [];
    var nodes = document.querySelectorAll("p.character");
    for (var i = 0; i < nodes.length; i++) {
      if (txt(nodes[i].textContent) !== label) continue;
      var parent = nodes[i].parentElement;
      var link = parent && parent.querySelector("a");
      if (link && txt(link.textContent)) out.push(txt(link.textContent));
    }
    return out;
  }

  function unique(list) {
    var seen = {};
    return (list || []).filter(function (value) {
      var key = txt(value);
      if (!key || seen[key]) return false;
      seen[key] = true;
      return true;
    });
  }

  function durationText(value) {
    var raw = txt(value);
    if (!raw) return "";
    var match = raw.match(/^P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/i);
    if (!match) return raw;
    var parts = [];
    if (match[1]) parts.push(parseInt(match[1], 10) + " 天");
    if (match[2]) parts.push(parseInt(match[2], 10) + " 小时");
    if (match[3]) parts.push(parseInt(match[3], 10) + " 分钟");
    if (!parts.length && match[4]) parts.push(parseInt(match[4], 10) + " 秒");
    return parts.join(" ");
  }

  function tmdbCover(value) {
    var raw = txt(value);
    if (!raw) return "";
    if (!/^https:\/\/(?:image\.tmdb\.org|media\.themoviedb\.org)\//i.test(raw)) return "";
    if (!/\/t\/p\/(?:w\d+|original)\//i.test(raw)) return "";
    return raw.replace(/\/t\/p\/w\d+\//i, "/t/p/original/");
  }

  function show(message, isError) {
    var box = document.createElement("div");
    box.textContent = message;
    box.setAttribute("role", "status");
    box.style.cssText =
      "position:fixed;left:16px;bottom:16px;z-index:2147483647;" +
      "max-width:min(420px,calc(100vw - 32px));" +
      "background:" + (isError ? "#8b1e1e" : "#153d2b") + ";color:#fff;" +
      "padding:11px 14px;border-radius:9px;font:14px/1.55 system-ui,sans-serif;" +
      "box-shadow:0 4px 16px rgba(0,0,0,.3)";
    document.body.appendChild(box);
    setTimeout(function () { box.remove(); }, isError ? 5200 : 3200);
  }

  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;left:0;top:0;width:1px;height:1px;opacity:0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(area);
    if (ok) {
      show("TMDB 资料已复制，请粘贴到娱乐档案");
    } else {
      window.prompt("自动复制失败，请手动复制下面的 JSON", text);
    }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        show("TMDB 资料已复制，请粘贴到娱乐档案");
      }, function () {
        fallbackCopy(text);
      });
    } else {
      fallbackCopy(text);
    }
  }

  var urlMatch = location.href.match(
    /^https?:\/\/(?:www\.)?themoviedb\.org\/(movie|tv)\/(\d+)(?:-[^/?#]*)?\/?(?:\?[^#]*)?(?:#.*)?$/i
  );
  if (!urlMatch) {
    show("当前页面不是 TMDB 电影或剧集详情页", true);
    return;
  }

  var kind = urlMatch[1].toLowerCase();
  var id = urlMatch[2];
  var main = mainRecord();
  if (!main) {
    show("未找到 TMDB 作品 JSON-LD，请确认详情页已完全加载", true);
    return;
  }

  var title = txt(main.name) || metaContent("og:title");
  if (!title) {
    show("页面没有作品名称，已停止复制", true);
    return;
  }

  var date = txt(main.datePublished || main.startDate || main.releaseDate || main.dateCreated);
  var year = /\d{4}/.test(date) ? date.slice(0, 4) : "";
  var originalNames = unique(names(main.alternateName));
  var originalTitle = originalNames.length ? originalNames[0] : "";
  var aliases = originalNames.length > 1 ? originalNames.slice(1) : [];

  var imdb = "";
  var sameAs = Array.isArray(main.sameAs) ? main.sameAs : (main.sameAs ? [main.sameAs] : []);
  for (var i = 0; i < sameAs.length; i++) {
    var same = typeof sameAs[i] === "string" ? sameAs[i] : (sameAs[i] && (sameAs[i].url || sameAs[i]["@id"]));
    var found = txt(same).match(/imdb\.com\/title\/(tt\d+)/i);
    if (found) { imdb = found[1]; break; }
  }

  var directors = unique(names(main.director).concat(domPeople("导演"), domPeople("Director")));
  var creators = unique(names(main.creator).concat(domPeople("原创作者"), domPeople("创作人")));
  var writers = unique(names(main.writer).concat(domPeople("编剧"), domPeople("Writer")));
  var actors = unique(names(main.actor));

  var creatorList = [];
  if (directors.length) creatorList.push({ role: "导演", name: directors.join("、") });
  if (creators.length) creatorList.push({ role: "原创作者", name: creators.join("、") });
  if (writers.length) creatorList.push({ role: "编剧", name: writers.join("、") });
  if (actors.length) creatorList.push({ role: "主演", name: actors.join("、") });

  var genres = unique(names(main.genre));
  var countries = unique(names(main.countryOfOrigin));
  var rating = main.aggregateRating ? txt(main.aggregateRating.ratingValue) : "";
  var votes = main.aggregateRating ? txt(main.aggregateRating.ratingCount) : "";
  var episodes = main.numberOfEpisodes ? txt(main.numberOfEpisodes) : "";
  var duration = durationText(main.duration);
  var coverUrl = tmdbCover(imageUrl(main.image) || metaContent("og:image"));
  var canonical = "https://www.themoviedb.org/" + kind + "/" + id + "?language=zh-CN";

  var infobox = [];
  function addInfo(key, value) {
    var text = txt(value);
    if (text) infobox.push({ key: key, value: text });
  }
  addInfo("条目类型", kind === "movie" ? "电影" : "剧集");
  addInfo(kind === "movie" ? "上映日期" : "首播日期", date ? date.slice(0, 10) : "");
  addInfo("国家/地区", countries.join("、"));
  addInfo("集数", episodes);
  addInfo("时长", duration);
  addInfo("IMDb ID", imdb);
  addInfo("TMDB ID", id);
  addInfo("评分", rating);
  addInfo("评分人数", votes);

  var draft = {
    category: "movie",
    title: title,
    originalTitle: originalTitle,
    aliases: aliases,
    year: year,
    summary: txt(main.description) || metaContent("og:description"),
    tags: genres,
    creators: creatorList,
    infobox: infobox,
    coverUrl: coverUrl,
    previewUrl: coverUrl ? "/api/img?url=" + encodeURIComponent(coverUrl) : "",
    coverProxy: false,
    coverReferer: canonical,
    ratingRef: rating || null,
    ratingMeta: rating ? { source: "TMDB", total: votes || undefined } : null,
    source: {
      name: "tmdb",
      label: "TMDB",
      type: kind,
      id: id,
      url: canonical
    }
  };

  if (JSON.stringify(draft).length > JSON_LIMIT) {
    show("提取的资料过长，已停止复制", true);
    return;
  }

  window.__tmdbBookmarkletDraft = draft;
  copyText(JSON.stringify(draft, null, 2));
})();
