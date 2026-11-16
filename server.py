#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
娱乐档案 · 本地服务端
零第三方依赖，仅用 Python 标准库。默认端口 8777。
职责：数据落盘与备份、元数据抓取与聚合、封面本地化。
"""
import base64
import hashlib
import html as _html
import io
import csv
import json
import mimetypes
import os
import re
import shutil
import socket
import threading
import time
import uuid
import webbrowser
import zipfile
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, build_opener, ProxyHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.1.0"
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
COVER_DIR = os.path.join(DATA_DIR, "covers")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
SIBLING_BACKUP_DIR = os.path.join(os.path.dirname(BASE_DIR), "娱乐档案_备份")
LIB_PATH = os.path.join(DATA_DIR, "library.json")
IMAGE_CACHE_DIR = os.path.join(DATA_DIR, "image_cache")
PORT = int(os.environ.get("GRDAG_PORT", "8777"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
UA_BGM = "GRDAG/1.0 (https://bgm.tv/)"

CATEGORIES = {
    "anime": {"label": "动漫", "bangumi_type": 2, "sources": ["bangumi", "douban", "anilist"]},
    "manga": {"label": "漫画", "bangumi_type": 1, "sources": ["bangumi", "douban"]},
    "game": {"label": "游戏", "bangumi_type": 4, "sources": ["bangumi", "steam"]},
    "novel": {"label": "网文", "bangumi_type": 1, "sources": ["weread", "web"]},
    "book": {"label": "出版书", "bangumi_type": 1, "sources": ["douban", "bangumi", "weread"]},
    "movie": {"label": "影视剧", "bangumi_type": 6, "sources": ["bangumi", "bilibili", "douban"]},
    "shortdrama": {"label": "短剧", "bangumi_type": 6, "sources": ["hongguo"]},
}

STATUS_ORDER = ["not_started", "planned", "active", "completed", "paused", "dropped"]
STATUS_LABELS = {
    "anime": {"not_started": "未开始", "planned": "想看", "active": "追番中", "completed": "已看完", "paused": "搁置", "dropped": "弃坑"},
    "manga": {"not_started": "未开始", "planned": "想看", "active": "在看", "completed": "已看完", "paused": "搁置", "dropped": "弃坑"},
    "game": {"not_started": "未开始", "planned": "想玩", "active": "在玩", "completed": "已通关", "paused": "搁置", "dropped": "弃坑"},
    "novel": {"not_started": "未开始", "planned": "想读", "active": "在读", "completed": "已读完", "paused": "搁置", "dropped": "弃坑"},
    "book": {"not_started": "未开始", "planned": "想读", "active": "在读", "completed": "已读完", "paused": "搁置", "dropped": "弃坑"},
    "movie": {"not_started": "未开始", "planned": "想看", "active": "在看", "completed": "已看完", "paused": "搁置", "dropped": "弃坑"},
    "shortdrama": {"not_started": "未开始", "planned": "想看", "active": "在追", "completed": "已看完", "paused": "搁置", "dropped": "弃坑"},
}
SOURCE_LABELS = {"bangumi": "Bangumi", "douban": "豆瓣", "weread": "微信读书", "steam": "Steam",
                 "bilibili": "B站", "web": "搜索引擎", "anilist": "AniList", "manual": "手动",
                 "link": "链接解析", "hongguo": "红果"}
SERIES_KINDS = {"mixed": "跨媒介系列", "single": "单一媒介系列", "bookset": "丛书"}
SERIES_ROLES = {"main": "正传", "sequel": "续作", "side": "外传", "adaptation": "改编",
                "remake": "重制", "port": "移植", "collection": "合集", "dlc": "DLC", "crossover": "联动"}
SERIES_STATUS_LABELS = {"not_started": "未开始", "planned": "计划中", "active": "进行中",
                        "completed": "全系列完成", "paused": "搁置", "dropped": "多数弃坑"}

CATEGORY_ALIASES = {
    "动漫": "anime", "动画": "anime", "番剧": "anime", "番": "anime", "动画片": "anime",
    "漫画": "manga",
    "游戏": "game", "主机游戏": "game", "单机": "game",
    "网文": "novel", "网络小说": "novel", "小说": "novel",
    "出版书": "book", "图书": "book", "书": "book", "书籍": "book",
    "影视剧": "movie", "影视": "movie", "电影": "movie", "电视剧": "movie", "剧集": "movie",
    "电视剧/电影": "movie", "短剧": "shortdrama", "微短剧": "shortdrama",
}
STATUS_ALIASES = {
    "未开始": "not_started", "计划中": "planned", "想看": "planned", "想玩": "planned", "想读": "planned",
    "进行中": "active", "在看": "active", "在读": "active", "在玩": "active", "追番中": "active",
    "追更中": "active", "在追": "active", "正在追": "active", "观看中": "active",
    "已完成": "completed", "已看完": "completed", "已读完": "completed", "已通关": "completed", "完成": "completed",
    "看完": "completed", "读完": "completed", "通关": "completed",
    "搁置": "paused", "暂停": "paused", "弃坑": "dropped", "放弃": "dropped", "弃了": "dropped",
}
CSV_HEAD_ALIASES = {
    "标题": "标题", "名称": "标题", "书名": "标题", "作品": "标题", "作品名": "标题",
    "分类": "分类", "类型": "分类", "类别": "分类",
    "原名": "原名", "原书名": "原名", "原文名": "原名", "日文名": "原名",
    "年份": "年份", "年代": "年份", "年": "年份",
    "评分": "评分", "分数": "评分", "打分": "评分",
    "标签": "标签", "tag": "标签", "tags": "标签",
    "简介": "简介", "描述": "简介", "内容简介": "简介",
    "日期": "经历日期", "时间": "经历日期", "经历日期": "经历日期", "记录日期": "经历日期",
    "状态": "经历状态", "经历状态": "经历状态",
    "内容": "经历内容", "经历": "经历内容", "记录": "经历内容", "备注": "经历内容", "经历内容": "经历内容",
}


def parse_date_loose(value):
    """把 2024-05-01 / 2024/5/1 / 2024年5月1日 / 2024-05 / 2024 统一成 YYYY-MM-DD。"""
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-").strip()
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s)
    if not m:
        return ""
    y = int(m.group(1))
    mo = min(12, max(1, int(m.group(2) or 1)))
    d = min(31, max(1, int(m.group(3) or 1)))
    return f"{y:04d}-{mo:02d}-{d:02d}"


def status_from_label(label, category):
    t = str(label or "").strip()
    if not t:
        return None
    for k, v in STATUS_LABELS.get(category, {}).items():
        if v == t:
            return k
    return STATUS_ALIASES.get(t)


def parse_records(text):
    """解析旧记录：CSV（表头宽松）或 JSON 数组。返回分组后的条目列表。"""
    text = (text or "").lstrip("\ufeff").strip()
    if not text:
        return []
    groups = {}
    if text[0] in "[{":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("works") or data.get("items") or [data]
        for item in data:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("标题") or "").strip()
            if not title:
                continue
            cat = CATEGORY_ALIASES.get(str(item.get("category") or item.get("分类") or "").strip(), "book")
            g = groups.setdefault((cat, title), {
                "category": cat, "title": title,
                "originalTitle": str(item.get("originalTitle") or item.get("原名") or "").strip(),
                "year": str(item.get("year") or item.get("年份") or "").strip(),
                "tags": item.get("tags") or [], "summary": str(item.get("summary") or item.get("简介") or "").strip(),
                "rating": item.get("rating"), "experiences": [], "userFields": {},
            })
            uf = item.get("userFields") or {}
            if isinstance(uf, dict):
                for k, v in uf.items():
                    if str(v).strip():
                        g["userFields"].setdefault(str(k), str(v).strip())
            elif isinstance(uf, list):
                for p in uf:
                    if isinstance(p, dict) and str(p.get("key") or "").strip() and str(p.get("value") or "").strip():
                        g["userFields"].setdefault(str(p["key"]).strip(), str(p["value"]).strip())
            for e in (item.get("experiences") or []):
                date = parse_date_loose(e.get("date") or "")
                content = str(e.get("content") or "").strip()
                st = status_from_label(e.get("status"), cat) or "active"
                if date or content:
                    g["experiences"].append({"date": date, "status": st, "content": content})
            if item.get("rating") not in (None, "") and g["rating"] in (None, ""):
                try:
                    g["rating"] = round(float(item["rating"]) * 2) / 2
                except Exception:
                    pass
        return list(groups.values())

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    head = [CSV_HEAD_ALIASES.get(str(c).strip().lower(), str(c).strip().lower()) for c in rows[0]]
    known = {"标题", "分类", "原名", "年份", "评分", "标签", "简介", "经历日期", "经历状态", "经历内容"}
    extra = [i for i, h in enumerate(head) if h not in known]
    for row in rows[1:]:
        rec = {}
        for i, cell in enumerate(row):
            if i >= len(head):
                break
            rec[head[i]] = str(cell).strip()
        extras = {}
        for i in extra:
            if i < len(row) and str(row[i]).strip():
                extras[head[i]] = str(row[i]).strip()
        title = (rec.get("标题") or "").strip()
        if not title:
            continue
        cat = CATEGORY_ALIASES.get((rec.get("分类") or "").strip(), "book")
        g = groups.setdefault((cat, title), {
            "category": cat, "title": title,
            "originalTitle": rec.get("原名") or "",
            "year": rec.get("年份") or "",
            "tags": [t.strip() for t in re.split(r"[，,、;；]", rec.get("标签") or "") if t.strip()],
            "summary": rec.get("简介") or "",
            "rating": None,
            "experiences": [], "userFields": {},
        })
        for k, v in extras.items():
            g["userFields"].setdefault(k, v)
        if rec.get("评分") and g["rating"] in (None, ""):
            try:
                g["rating"] = round(float(rec["评分"]) * 2) / 2
            except Exception:
                pass
        date = parse_date_loose(rec.get("经历日期"))
        content = (rec.get("经历内容") or "").strip()
        st = status_from_label(rec.get("经历状态"), cat)
        if date or content:
            g["experiences"].append({"date": date, "status": st or "active", "content": content})
    return list(groups.values())

_lock = threading.Lock()


# ---------------------------------------------------------------- 基础工具
def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def new_id(prefix):
    return prefix + uuid.uuid4().hex[:10]


def ensure_dirs():
    for d in (DATA_DIR, COVER_DIR, IMAGE_CACHE_DIR, BACKUP_DIR, WEB_DIR):
        os.makedirs(d, exist_ok=True)


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def to_text(v):
    if isinstance(v, list):
        return "、".join(to_text(x) for x in v)
    if isinstance(v, dict):
        return "、".join(f"{k}:{to_text(val)}" for k, val in v.items())
    return str(v)


def safe_json_load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------------------------------------------------------------- 存储层
def default_library():
    return {"version": 2, "works": [], "series": [],
            "settings": {"proxy": "auto", "proxy_port": "7897", "backup_keep": 30, "deepseek_key": ""}}


def load_library():
    lib = safe_json_load(LIB_PATH)
    if not isinstance(lib, dict) or "works" not in lib:
        lib = default_library()
        save_library(lib, snapshot=False)
    lib.setdefault("settings", default_library()["settings"])
    lib.setdefault("series", [])
    lib["version"] = 2
    return lib


def snapshot_library(keep):
    if not os.path.exists(LIB_PATH):
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"library_{stamp}.json")
    try:
        shutil.copy2(LIB_PATH, dst)
    except Exception:
        return
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("library_") and f.endswith(".json"))
    while len(files) > max(1, int(keep or 30)):
        try:
            os.remove(os.path.join(BACKUP_DIR, files.pop(0)))
        except Exception:
            break


def write_library(lib):
    tmp = LIB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LIB_PATH)


def save_library(lib, snapshot=True):
    ensure_dirs()
    if snapshot:
        snapshot_library(lib.get("settings", {}).get("backup_keep", 30))
    write_library(lib)


def extract_library_zip(raw):
    """从备份 zip 里读 library.json，并把 covers/ 下的封面补回本地缓存。"""
    ensure_dirs()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        cands = [n for n in names if n.replace("\\", "/").rstrip("/").endswith("library.json")]
        if not cands:
            raise RuntimeError("zip 里没有 library.json，不像是本工具的备份")
        cands.sort(key=lambda n: n.count("/"))
        data = json.loads(z.read(cands[0]).decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("works"), list):
            raise RuntimeError("zip 里的 library.json 格式不正确")
        restored = 0
        for n in names:
            norm = n.replace("\\", "/")
            if norm.endswith("/"):
                continue
            parts = norm.split("/")
            if "covers" not in parts[:-1] and parts[0] != "covers":
                continue
            base = os.path.basename(norm)
            if not base or base in (".", "..") or "/" in base:
                continue
            dst = os.path.join(COVER_DIR, base)
            if os.path.exists(dst):
                continue
            payload = z.read(n)
            if not payload:
                continue
            with open(dst, "wb") as f:
                f.write(payload)
            restored += 1
    return data, restored


# ---------------------------------------------------------------- 网络层
_proxy_cache = {"at": 0.0, "value": None, "source": None}
_proxy_lock = threading.Lock()
PROXY_CACHE_TTL = 600
PROXY_NEGATIVE_TTL = 30
PROXY_PORTS = ["7897", "7890", "10808", "1080", "8888", "10809", "2080", "8118"]
IMAGE_HOST_SUFFIXES = (
    "bgm.tv", "doubanio.com", "douban.com", "steamstatic.com",
    "steamcdn-a.akamaihd.net", "hdslb.com", "biliimg.com", "qq.com",
    "hongguoduanju.com", "douyinpic.com", "byteimg.com",
)


def _bgm_probe(proxy_url, timeout=3):
    try:
        op = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        req = Request("https://api.bgm.tv/v0/subjects/253046", headers={"User-Agent": UA_BGM})
        with op.open(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def detect_proxy(preferred_port=""):
    ports = list(PROXY_PORTS)
    preferred = str(preferred_port or "").strip()
    if preferred:
        ports = [preferred] + [p for p in ports if p != preferred]
    for port in ports:
        try:
            socket.create_connection(("127.0.0.1", int(port)), timeout=0.25).close()
        except Exception:
            continue
        url = f"http://127.0.0.1:{port}"
        if _bgm_probe(url):
            return url, f"auto:{port}"
    return None, "auto:none"


def resolve_proxy(force=False):
    lib = load_library()
    settings = lib.get("settings", {})
    cfg = (settings.get("proxy") or "auto").strip()
    if cfg not in ("auto", ""):
        if cfg.lower() in ("direct", "none", "off", "关闭"):
            return None
        return cfg
    with _proxy_lock:
        now = time.time()
        cached = _proxy_cache["value"]
        age = now - (_proxy_cache["at"] or 0)
        if not force:
            if cached and age < PROXY_CACHE_TTL:
                return cached
            if not cached and _proxy_cache["at"] and age < PROXY_NEGATIVE_TTL:
                return None
            if cached:
                # 缓存过期时只复验原代理，避免每次把 8 个端口全扫一遍
                if _bgm_probe(cached, 3):
                    _proxy_cache["at"] = now
                    return cached
        val, src = detect_proxy(settings.get("proxy_port"))
        _proxy_cache.update({"at": time.time(), "value": val, "source": src})
        return val


def http_get(url, headers=None, proxy=None, timeout=12, data=None, method=None):
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "*/*"}
    if headers:
        h.update({k: v for k, v in headers.items() if v})
    req = Request(url, headers=h, data=data, method=method)
    if proxy:
        op = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
    else:
        op = build_opener(ProxyHandler({}))
    t0 = time.time()
    with op.open(req, timeout=timeout) as resp:
        return resp.status, resp.read(), resp.geturl(), round(time.time() - t0, 2)


def http_json(url, headers=None, proxy=None, timeout=12, data=None, method=None):
    status, body, final, elapsed = http_get(url, headers=headers, proxy=proxy, timeout=timeout, data=data, method=method)
    return json.loads(body.decode("utf-8", "ignore"))


def image_proxy_url(url):
    """把远程图片换成同源代理地址，避免浏览器直连墙外的图片站。"""
    url = (url or "").strip()
    if not url:
        return ""
    return "/api/img?url=" + quote(url, safe="")


def _is_image_url_allowed(url):
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    host = u.hostname.lower()
    return any(host == s or host.endswith("." + s) for s in IMAGE_HOST_SUFFIXES)


def _image_ext(body, url):
    if body[:4] == b"\x89PNG":
        return ".png"
    if body[:4] == b"RIFF":
        return ".webp"
    if body[:2] == b"\xff\xd8":
        return ".jpg"
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"


def _download_image(url, referer=None, timeout=10, want_proxy=False):
    """下载图片。Bangumi 图片直连必超时，有代理时只走代理，不再白等一轮直连。"""
    host = (urlparse(url).hostname or "").lower()
    is_bgm = host.endswith("bgm.tv")
    proxy_url = None
    if want_proxy or is_bgm:
        try:
            proxy_url = resolve_proxy()
        except Exception:
            proxy_url = None
    attempts = []
    if proxy_url:
        attempts.append(proxy_url)
        if not is_bgm:
            attempts.append(None)
    else:
        attempts.append(None)
    for idx, px in enumerate(attempts):
        try:
            headers = {"Referer": referer} if referer else None
            t = timeout if idx == 0 else min(5, timeout)
            status, body, final, _ = http_get(url, headers=headers, proxy=px, timeout=t)
            if status == 200 and len(body) >= 800:
                return body
        except Exception:
            continue
    return None


def _cached_image_path(url):
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    for ext in (".jpg", ".png", ".webp", ".gif"):
        path = os.path.join(IMAGE_CACHE_DIR, key + ext)
        if os.path.exists(path):
            return path
    return None


def cache_remote_image(url):
    """下载并缓存远程预览图，返回本地文件路径；失败返回 None。"""
    if not _is_image_url_allowed(url):
        return None
    try:
        ensure_dirs()
    except Exception:
        return None
    cached = _cached_image_path(url)
    if cached:
        return cached
    body = _download_image(url, referer="https://bgm.tv/" if "bgm.tv" in url else None,
                           timeout=8, want_proxy=True)
    if not body:
        return None
    ext = _image_ext(body, url)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    dst = os.path.join(IMAGE_CACHE_DIR, key + ext)
    tmp = dst + "." + uuid.uuid4().hex[:6] + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, dst)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return None
    return dst


def save_cover(url, referer=None, proxy=False, timeout=10):
    if not url:
        return None
    url = url.strip()
    if url.startswith("/covers/") or url.startswith("covers/"):
        return url
    body = _download_image(url, referer=referer, timeout=timeout, want_proxy=proxy)
    if not body:
        return None
    ext = _image_ext(body, url)
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext
    ensure_dirs()
    try:
        with open(os.path.join(COVER_DIR, name), "wb") as f:
            f.write(body)
    except Exception:
        return None
    return "covers/" + name


# ---------------------------------------------------------------- 源：Bangumi
CREATOR_KEYS = [
    ("导演", ["导演", "监督"]), ("编剧", ["编剧", "脚本", "系列构成"]),
    ("作者", ["作者", "原作", "原著"]), ("制作", ["製作", "制作", "出品", "出品方", "动画制作"]),
    ("发行", ["发行", "发行商", "出版商"]), ("开发商", ["开发", "开发商"]),
    ("出版社", ["出版社"]), ("主演", ["主演"]), ("音乐", ["音乐"]),
]


def _creators_from_infobox(infobox):
    out = []
    for role, keys in CREATOR_KEYS:
        for item in infobox:
            if item.get("key") in keys and item.get("value"):
                out.append({"role": role, "name": to_text(item["value"])})
                break
    return out


def _infobox_pairs(infobox):
    pairs = []
    for item in infobox or []:
        k = item.get("key")
        v = item.get("value")
        if not k or v in (None, "", []):
            continue
        pairs.append({"key": str(k), "value": to_text(v)})
    return pairs


def bangumi_search(keyword, category):
    bt = CATEGORIES.get(category, {}).get("bangumi_type", 1)
    types = [bt]
    out, seen = [], set()
    for t in types:
        url = ("https://api.bgm.tv/search/subject/" + quote(keyword) +
               f"?type={t}&responseGroup=large&max_results=10")
        j = http_json(url, headers={"User-Agent": UA_BGM}, proxy=resolve_proxy(), timeout=8)
        for it in (j.get("list") or []):
            sid = it.get("id")
            if sid in seen:
                continue
            seen.add(sid)
            imgs = it.get("images") or {}
            pic = imgs.get("common") or imgs.get("medium") or imgs.get("small") or imgs.get("large")
            out.append({
                "title": it.get("name_cn") or it.get("name") or "",
                "subtitle": it.get("name") if (it.get("name_cn") and it.get("name") != it.get("name_cn")) else "",
                "year": (it.get("air_date") or "")[:4],
                "cover": image_proxy_url(pic),
                "meta": (it.get("name") or "") + (" · " + it.get("air_date") if it.get("air_date") else ""),
                "ref": {"source": "bangumi", "id": sid, "url": f"https://bgm.tv/subject/{sid}"},
            })
    return out[:10]


def bangumi_draft(ref):
    sid = ref.get("id")
    detail = http_json(f"https://api.bgm.tv/v0/subjects/{sid}", headers={"User-Agent": UA_BGM},
                       proxy=resolve_proxy(), timeout=8)
    infobox = _infobox_pairs(detail.get("infobox"))
    rating = detail.get("rating") or {}
    tags = [t.get("name") for t in (detail.get("tags") or [])[:10] if t.get("name")]
    imgs = detail.get("images") or {}
    pic = imgs.get("common") or imgs.get("medium") or imgs.get("large")
    date = detail.get("date") or ""
    creators = _creators_from_infobox(detail.get("infobox") or [])
    return {
        "title": detail.get("name_cn") or detail.get("name") or "",
        "originalTitle": detail.get("name") or "",
        "aliases": [detail.get("name")] if detail.get("name") else [],
        "year": date[:4],
        "coverUrl": pic,
        "previewUrl": image_proxy_url(pic),
        "coverProxy": True,
        "coverReferer": "https://bgm.tv/",
        "summary": strip_html(detail.get("summary")),
        "tags": tags,
        "creators": creators,
        "infobox": infobox,
        "ratingRef": rating.get("score"),
        "ratingMeta": {"rank": rating.get("rank"), "total": rating.get("total")},
        "source": {"name": "bangumi", "label": "Bangumi", "url": f"https://bgm.tv/subject/{sid}", "id": str(sid)},
        "extra": {"platform": detail.get("platform"), "eps": detail.get("eps"), "volumes": detail.get("volumes"),
                  "date": date},
    }


# ---------------------------------------------------------------- 源：豆瓣
def douban_search(keyword, category):
    kind = "book" if category in ("book", "novel") else "movie"
    base = "https://book.douban.com" if kind == "book" else "https://movie.douban.com"
    url = base + "/j/subject_suggest?q=" + quote(keyword)
    try:
        raw = http_json(url, headers={"Referer": base + "/"})
    except Exception:
        return []
    out = []
    for it in (raw or [])[:12]:
        title = it.get("title") or ""
        if not title:
            continue
        out.append({
            "title": title,
            "subtitle": it.get("sub_title") or "",
            "year": it.get("year") or "",
            "cover": it.get("pic") or it.get("img"),
            "meta": " · ".join([x for x in [it.get("author_name"), it.get("year")] if x]),
            "ref": {"source": "douban", "kind": kind, "url": it.get("url"), "id": str(it.get("id") or ""),
                    "title": title, "year": it.get("year") or "", "subtitle": it.get("sub_title") or "",
                    "cover": it.get("pic") or it.get("img") or ""},
        })
    return out


def douban_draft(ref):
    url = ref.get("url")
    detail_infobox, summary, rating, votes, creators = [], "", None, None, []
    if ref.get("kind") == "book" and url:
        try:
            status, body, final, _ = http_get(url, headers={"Referer": "https://book.douban.com/"})
            txt = body.decode("utf-8", "ignore")
            m = re.search(r'property="v:average"[^>]*>\s*([\d.]+)', txt)
            if not m:
                m = re.search(r'v:average\s*">\s*([\d.]+)', txt)
            rating = float(m.group(1)) if m else None
            mv = re.search(r'property="v:votes"[^>]*>\s*(\d+)', txt) or re.search(r'v:votes\s*">\s*(\d+)', txt)
            votes = int(mv.group(1)) if mv else None
            intro = re.search(r'<div class="intro">(.*?)</div>', txt, re.S)
            summary = strip_html(intro.group(1)) if intro else ""
            info = re.search(r'<div id="info">(.*?)</div>', txt, re.S)
            if info:
                for line in re.split(r"<br\s*/?>", info.group(1)):
                    plain = strip_html(line)
                    if ":" in plain or "：" in plain:
                        k, v = re.split(r"[：:]", plain, 1)
                        k, v = k.strip(), v.strip()
                        if k and v:
                            detail_infobox.append({"key": k, "value": v})
                            if k in ("作者", "译者"):
                                creators.append({"role": k, "name": v})
        except Exception:
            pass
    title = ref.get("title") or ""
    pic = ref.get("cover") or ""
    if pic and "/view/subject/s/" in pic:
        pic_large = pic.replace("/view/subject/s/", "/view/subject/l/")
    else:
        pic_large = pic
    return {
        "title": title,
        "originalTitle": ref.get("subtitle") or "",
        "year": ref.get("year") or "",
        "coverUrl": pic_large,
        "coverReferer": "https://book.douban.com/" if ref.get("kind") == "book" else "https://movie.douban.com/",
        "summary": summary,
        "tags": [],
        "creators": creators,
        "infobox": detail_infobox,
        "ratingRef": rating,
        "ratingMeta": {"votes": votes},
        "source": {"name": "douban", "label": "豆瓣", "url": url or "", "id": ref.get("id")},
    }


# ---------------------------------------------------------------- 源：微信读书
def weread_search(keyword, category):
    url = "https://weread.qq.com/web/search/global?keyword=" + quote(keyword)
    try:
        j = http_json(url, headers={"Referer": "https://weread.qq.com/"})
    except Exception:
        return []
    out = []
    for b in (j.get("books") or [])[:12]:
        info = b.get("bookInfo") or {}
        cover = info.get("cover") or ""
        placeholder = (not cover) or ("logo_url" in cover) or ("assets/" in cover)
        out.append({
            "title": clean_weread_title(info.get("title") or ""),
            "subtitle": "",
            "year": "",
            "cover": "" if placeholder else cover,
            "meta": " · ".join([x for x in [info.get("author"), f"推荐值 {round((info.get('newRating') or 0)/100,1)}"
                                            if info.get("newRating") else ""] if x]),
            "ref": {"source": "weread", "book": info},
            "coverMissing": placeholder,
        })
    return out


def clean_weread_title(t):
    t = re.sub(r"（[^）]*）$", "", t or "").strip()
    t = re.sub(r"\([^)]*\)$", "", t).strip()
    return t


def weread_draft(ref):
    info = ref.get("book") or {}
    cover = info.get("cover") or ""
    placeholder = (not cover) or ("logo_url" in cover) or ("assets/" in cover)
    rating = round((info.get("newRating") or 0) / 100, 1) if info.get("newRating") else None
    infobox = []
    for k, label in [("author", "作者"), ("publisher", "出版社"), ("newRatingCount", "评价人数")]:
        v = info.get(k)
        if v not in (None, "", 0):
            infobox.append({"key": label, "value": str(v)})
    if info.get("finished") in (0, 1):
        infobox.append({"key": "连载状态", "value": "已完结" if info.get("finished") == 1 else "连载中"})
    return {
        "title": clean_weread_title(info.get("title") or ""),
        "originalTitle": info.get("title") or "",
        "year": "",
        "coverUrl": "" if placeholder else cover,
        "coverReferer": "https://weread.qq.com/",
        "summary": strip_html(info.get("intro")),
        "tags": [],
        "creators": [{"role": "作者", "name": info.get("author")}] if info.get("author") else [],
        "infobox": infobox,
        "ratingRef": rating,
        "ratingMeta": {"votes": info.get("newRatingCount")},
        "source": {"name": "weread", "label": "微信读书", "url": info.get("deepLink") or "", "id": str(info.get("bookId") or "")},
    }


# ---------------------------------------------------------------- 源：Steam
def steam_search(keyword, category):
    url = ("https://store.steampowered.com/api/storesearch/?term=" + quote(keyword) + "&l=schinese&cc=CN")
    try:
        j = http_json(url)
    except Exception:
        return []
    out = []
    for it in (j.get("items") or [])[:10]:
        out.append({
            "title": it.get("name") or "",
            "subtitle": "",
            "year": "",
            "cover": it.get("tiny_image"),
            "meta": f"appid {it.get('id')}" + (" · metacritic " + str(it["metascore"]) if it.get("metascore") else ""),
            "ref": {"source": "steam", "id": it.get("id"), "title": it.get("name") or "",
                    "cover": it.get("tiny_image") or ""},
        })
    return out


def steam_draft(ref):
    appid = ref.get("id")
    data = {}
    try:
        j = http_json(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese&cc=CN", timeout=25)
        data = (j.get(str(appid)) or {}).get("data") or {}
    except Exception:
        data = {}
    infobox = []
    for label, key in [("开发商", "developers"), ("发行商", "publishers")]:
        if data.get(key):
            infobox.append({"key": label, "value": "、".join(data[key])})
    if data.get("genres"):
        infobox.append({"key": "官方分类", "value": "、".join(g.get("description", "") for g in data["genres"])})
    if (data.get("release_date") or {}).get("date"):
        infobox.append({"key": "发行日期", "value": data["release_date"]["date"]})
    if data.get("price_overview"):
        infobox.append({"key": "价格", "value": data["price_overview"].get("final_formatted", "")})
    if (data.get("metacritic") or {}).get("score"):
        infobox.append({"key": "Metacritic", "value": str(data["metacritic"]["score"])})
    creators = []
    if data.get("developers"):
        creators.append({"role": "开发商", "name": "、".join(data["developers"])})
    if data.get("publishers"):
        creators.append({"role": "发行商", "name": "、".join(data["publishers"])})
    year = ""
    m = re.search(r"(\d{4})", (data.get("release_date") or {}).get("date", ""))
    if m:
        year = m.group(1)
    return {
        "title": data.get("name") or ref.get("title") or "",
        "originalTitle": "",
        "year": year,
        "coverUrl": (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
                     if data else (ref.get("cover") or f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg")),
        "coverReferer": "https://store.steampowered.com/",
        "summary": strip_html(data.get("detailed_description") or data.get("short_description")),
        "tags": [g.get("description") for g in (data.get("genres") or [])],
        "creators": creators,
        "infobox": infobox,
        "ratingRef": None,
        "ratingMeta": {},
        "source": {"name": "steam", "label": "Steam", "url": f"https://store.steampowered.com/app/{appid}", "id": str(appid)},
    }


# ---------------------------------------------------------------- 源：B站影视
def bilibili_search(keyword, category):
    st = "media_ft" if category == "movie" else "media_bangumi"
    url = ("https://api.bilibili.com/x/web-interface/search/type?search_type=" + st +
           "&keyword=" + quote(keyword) + "&page=1")
    try:
        j = http_json(url, headers={"Referer": "https://www.bilibili.com/"})
    except Exception:
        return []
    res = ((j.get("data") or {}).get("result") or [])
    out = []
    for it in res[:10]:
        out.append({
            "title": strip_html(it.get("title") or ""),
            "subtitle": "",
            "year": str(it.get("pubtime") or "")[:4],
            "cover": (it.get("cover") or "").replace("http://", "https://"),
            "meta": (it.get("styles") or "") if isinstance(it.get("styles"), str) else "",
            "ref": {"source": "bilibili", "id": it.get("season_id") or it.get("aid"),
                    "url": it.get("url") or ""},
        })
    return out


def bilibili_draft(ref):
    md = {}
    if ref.get("id"):
        try:
            url = f"https://api.bilibili.com/pgc/view/web/season?season_id={ref['id']}"
            j = http_json(url, headers={"Referer": "https://www.bilibili.com/"})
            md = (j.get("result") or {})
        except Exception:
            md = {}
    infobox = []
    if md.get("publish"):
        infobox.append({"key": "开播", "value": {"time": str(md.get("publish", {}).get("pub_time", ""))}.get("time", "")})
    if md.get("areas"):
        infobox.append({"key": "地区", "value": "、".join(a.get("name", "") for a in md["areas"])})
    if md.get("styles"):
        infobox.append({"key": "风格", "value": md["styles"]})
    if md.get("evaluate"):
        infobox.append({"key": "简介", "value": strip_html(md["evaluate"])[:400]})
    return {
        "title": md.get("title") or ref.get("title") or "",
        "originalTitle": "",
        "year": str((md.get("publish") or {}).get("pub_time") or "")[:4],
        "coverUrl": md.get("cover") or ref.get("cover"),
        "coverReferer": "https://www.bilibili.com/",
        "summary": strip_html(md.get("evaluate") or ""),
        "tags": [],
        "creators": [],
        "infobox": [p for p in infobox if p.get("value")],
        "ratingRef": (md.get("rating") or {}).get("score"),
        "ratingMeta": {"votes": (md.get("rating") or {}).get("count")},
        "source": {"name": "bilibili", "label": "B站", "url": ref.get("url") or "", "id": str(ref.get("id") or "")},
    }


# ---------------------------------------------------------------- 源：AniList（动漫兜底）
def anilist_search(keyword, category):
    q = 'query($s:String){Page(perPage:8){media(search:$s,type:ANIME){id title{romaji native} startDate{year} coverImage{large} averageScore}}}'
    payload = json.dumps({"query": q, "variables": {"s": keyword}}).encode("utf-8")
    try:
        j = http_json("https://graphql.anilist.co", headers={"Content-Type": "application/json",
                                                             "Accept": "application/json"},
                      data=payload, method="POST")
    except Exception:
        return []
    media = ((j.get("data") or {}).get("Page") or {}).get("media") or []
    out = []
    for m in media:
        out.append({
            "title": (m.get("title") or {}).get("romaji") or "",
            "subtitle": (m.get("title") or {}).get("native") or "",
            "year": str(((m.get("startDate") or {}).get("year")) or ""),
            "cover": (m.get("coverImage") or {}).get("large"),
            "meta": f"均分 {m.get('averageScore')}" if m.get("averageScore") else "",
            "ref": {"source": "anilist", "id": m.get("id")},
        })
    return out


def anilist_draft(ref):
    q = 'query($id:Int){Media(id:$id,type:ANIME){id title{romaji native} startDate{year month day} coverImage{large} averageScore description(asHtml:false) genres studios(isMain:true){nodes{name}} staff(perPage:4){nodes{name{full} primaryOccupations}}}}'
    payload = json.dumps({"query": q, "variables": {"id": ref.get("id")}}).encode("utf-8")
    j = http_json("https://graphql.anilist.co", headers={"Content-Type": "application/json"}, data=payload, method="POST")
    m = (j.get("data") or {}).get("Media") or {}
    studios = [n.get("name") for n in ((m.get("studios") or {}).get("nodes") or [])]
    return {
        "title": (m.get("title") or {}).get("native") or "",
        "originalTitle": (m.get("title") or {}).get("romaji") or "",
        "year": str(((m.get("startDate") or {}).get("year")) or ""),
        "coverUrl": (m.get("coverImage") or {}).get("large"),
        "coverReferer": "https://anilist.co/",
        "summary": strip_html(m.get("description") or ""),
        "tags": m.get("genres") or [],
        "creators": [{"role": "制作", "name": "、".join(studios)}] if studios else [],
        "infobox": [{"key": "制作公司", "value": "、".join(studios)}] if studios else [],
        "ratingRef": round((m.get("averageScore") or 0) / 10, 1) if m.get("averageScore") else None,
        "ratingMeta": {},
        "source": {"name": "anilist", "label": "AniList", "url": f"https://anilist.co/anime/{m.get('id')}"},
    }


# ---------------------------------------------------------------- 链接解析
def _unescape_js(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return (s.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\n", "\n")
                 .replace("\\/", "/").replace("\\\"", '"'))


def parse_qidian(book_id):
    url = f"https://m.qidian.com/book/{book_id}"
    status, body, final, _ = http_get(url)
    txt = body.decode("utf-8", "ignore")
    if status != 200 or len(txt) < 10000:
        raise RuntimeError("起点页面未能解析（可能被风控拦截）")

    def grab(pattern, default=""):
        m = re.search(pattern, txt, re.S)
        return _unescape_js(m.group(1)) if m else default

    name = grab(r'"bookName":"((?:[^"\\]|\\.)*)"')
    author = grab(r'"authorName":"((?:[^"\\]|\\.)*)"')
    desc = strip_html(grab(r'"desc":"((?:[^"\\]|\\.)*)"'))
    cover = ""
    mc = re.search(r'(https://bookcover\.yuewen\.com/qdbimg/[^"\s]+)', txt)
    if mc:
        cover = mc.group(1)
    # 起点页里有三类标签：bookTag（一级分类标签）、TagName 列表（编辑标签）、
    # 以及角色标签和推荐位里的 tagName。只取前两类，后两类会串味。
    book_tag = ""
    mt = re.search(r'"bookTag":\{[^}]*?"tagName":"((?:[^"\\]|\\.)*)"', txt)
    if mt:
        book_tag = _unescape_js(mt.group(1))
    edit_tags = []
    for t in re.findall(r'"TagName":"((?:[^"\\]|\\.)*)"', txt):
        t = _unescape_js(t)
        if t and t not in edit_tags:
            edit_tags.append(t)
    tags = ([book_tag] if book_tag else []) + [t for t in edit_tags if t != book_tag]
    tags = tags[:10]
    window = txt
    serial = ""
    msn = re.search(r'"actionStatus":"((?:[^"\\]|\\.)*)"', window)
    if msn:
        serial = _unescape_js(msn.group(1))
    words = ""
    mw = re.search(r'"wordsCnt":(\d+)', window)
    if mw:
        words = f"{int(mw.group(1)) / 10000:.1f} 万字"
    cat = ""
    mcat = re.search(r'"chanName":"((?:[^"\\]|\\.)*)"', window)
    if mcat:
        cat = _unescape_js(mcat.group(1))
    sub = ""
    msub = re.search(r'"subCateName":"((?:[^"\\]|\\.)*)"', window)
    if msub:
        sub = _unescape_js(msub.group(1))
    infobox = []
    if cat:
        infobox.append({"key": "分类", "value": f"{cat} · {sub}" if sub else cat})
    if author:
        infobox.append({"key": "作者", "value": author})
    if serial:
        infobox.append({"key": "连载状态", "value": serial})
    if words:
        infobox.append({"key": "字数", "value": words})
    return {
        "title": name, "originalTitle": "", "year": "", "coverUrl": cover,
        "coverReferer": "https://book.qidian.com/", "summary": desc, "tags": tags,
        "creators": [{"role": "作者", "name": author}] if author else [],
        "infobox": infobox, "ratingRef": None, "ratingMeta": {},
        "source": {"name": "qidian", "label": "起点", "url": url, "id": str(book_id)},
    }


def parse_fanqie(book_id):
    url = f"https://fanqienovel.com/page/{book_id}"
    status, body, final, _ = http_get(url, headers={"Referer": "https://fanqienovel.com/"})
    txt = body.decode("utf-8", "ignore")
    if status != 200 or len(txt) < 10000:
        raise RuntimeError("番茄页面未能解析")
    title = ""
    mt = re.search(r'<title>(.*?)</title>', txt, re.S)
    if mt:
        title = re.split(r"[_\|]", strip_html(mt.group(1)))[0].replace("完整版在线免费阅读", "").strip()
    author = ""
    ma = re.search(r'"author":"((?:[^"\\]|\\.)*)"', txt)
    if ma:
        author = _unescape_js(ma.group(1))
    desc = ""
    md = re.search(r'"abstract":"((?:[^"\\]|\\.)*)"', txt)
    if md:
        desc = strip_html(_unescape_js(md.group(1)))
    cover = ""
    mcv = re.findall(r'(https://p3-reading[^"\s]+\.(?:jpeg|jpg|webp))', txt)
    if mcv:
        cover = mcv[0]
    words = ""
    mw = re.search(r'"wordNumber":(\d+)', txt)
    if mw:
        words = mw.group(1)
    infobox = []
    if author:
        infobox.append({"key": "作者", "value": author})
    if words:
        infobox.append({"key": "字数", "value": f"{int(words)/10000:.1f} 万字" if words.isdigit() else words})
    return {
        "title": title, "originalTitle": "", "year": "", "coverUrl": cover,
        "coverReferer": "https://fanqienovel.com/", "summary": desc, "tags": [],
        "creators": [{"role": "作者", "name": author}] if author else [],
        "infobox": infobox, "ratingRef": None, "ratingMeta": {},
        "source": {"name": "fanqie", "label": "番茄", "url": url, "id": str(book_id)},
    }


def parse_ciweimao(book_id):
    url = f"https://www.ciweimao.com/book/{book_id}"
    status, body, final, _ = http_get(url)
    txt = body.decode("utf-8", "ignore")
    if status != 200 or len(txt) < 5000:
        raise RuntimeError("刺猬猫页面未能解析")
    og = dict(re.findall(r'<meta property="([^"]+)" content="([^"]*)"', txt))
    infobox = []
    if og.get("og:novel:category"):
        infobox.append({"key": "分类", "value": og["og:novel:category"]})
    if og.get("og:novel:author"):
        infobox.append({"key": "作者", "value": og["og:novel:author"]})
    return {
        "title": og.get("og:novel:book_name") or "",
        "originalTitle": "",
        "year": "",
        "coverUrl": og.get("og:image") or "",
        "coverReferer": "https://www.ciweimao.com/",
        "summary": strip_html(og.get("og:description") or ""),
        "tags": [],
        "creators": [{"role": "作者", "name": og.get("og:novel:author")}] if og.get("og:novel:author") else [],
        "infobox": infobox, "ratingRef": None, "ratingMeta": {},
        "source": {"name": "ciweimao", "label": "刺猬猫", "url": url, "id": str(book_id)},
    }


def parse_douban_link(url):
    m = re.search(r"/subject/(\d+)", url)
    if not m:
        raise RuntimeError("不是有效的豆瓣条目链接")
    kind = "book" if "book.douban.com" in url else "movie"
    if kind == "movie":
        raise RuntimeError("豆瓣影视详情页有反爬保护，无法解析；请在影视剧分类里用 Bangumi 或 B站源搜索")
    ref = {"source": "douban", "kind": "book", "url": f"https://book.douban.com/subject/{m.group(1)}/",
           "id": m.group(1), "title": "", "year": "", "cover": ""}
    # 用 suggest 兜底拿标题与封面
    try:
        status, body, final, _ = http_get(ref["url"], headers={"Referer": "https://book.douban.com/"})
        txt = body.decode("utf-8", "ignore")
        mt = re.search(r'<span property="v:itemreviewed">(.*?)</span>', txt, re.S)
        if mt:
            ref["title"] = strip_html(mt.group(1))
        mp = re.search(r'<img[^>]+src="([^"]+)"[^>]*rel="v:photo"', txt)
        if mp:
            ref["cover"] = mp.group(1)
        my = re.search(r'出版年:</span>\s*(?:<a[^>]*>)?([^<]+)', txt)
        if my:
            ref["year"] = my.group(1).strip()[:4]
    except Exception:
        pass
    draft = douban_draft(ref)
    if not draft.get("title"):
        raise RuntimeError("豆瓣条目解析失败，请手动填写")
    return draft


def parse_bangumi_link(url):
    m = re.search(r"/subject/(\d+)", url)
    if not m:
        raise RuntimeError("不是有效的 Bangumi 条目链接")
    return bangumi_draft({"id": m.group(1)})


def parse_steam_link(url):
    m = re.search(r"/app/(\d+)", url)
    if not m:
        raise RuntimeError("不是有效的 Steam 链接")
    return steam_draft({"id": m.group(1)})


def parse_link(url, category=None):
    url = (url or "").strip()
    if not url.startswith("http"):
        raise RuntimeError("请输入以 http 开头的链接")
    if "qidian.com" in url:
        m = re.search(r"/book/(\d+)", url) or re.search(r"bookid=(\d+)", url) or re.search(r"/(\d{6,})", url)
        if not m:
            raise RuntimeError("没找到起点书籍 ID")
        return parse_qidian(m.group(1))
    if "fanqienovel.com" in url:
        m = re.search(r"/page/(\d+)", url) or re.search(r"item_id=(\d+)", url) or re.search(r"book_id=(\d+)", url)
        if not m:
            raise RuntimeError("没找到番茄书籍 ID")
        return parse_fanqie(m.group(1))
    if "ciweimao.com" in url:
        m = re.search(r"/book/(\d+)", url)
        if not m:
            raise RuntimeError("没找到刺猬猫书籍 ID")
        return parse_ciweimao(m.group(1))
    if "douban.com" in url:
        return parse_douban_link(url)
    if "bgm.tv" in url or "bangumi.tv" in url:
        return parse_bangumi_link(url)
    if "steampowered.com" in url:
        return parse_steam_link(url)
    if "hongguoduanju.com" in url:
        return parse_hongguo_link(url)
    raise RuntimeError("暂不支持这个站点的链接（支持：起点 / 番茄 / 刺猬猫 / 豆瓣图书 / Bangumi / Steam / 红果搜索页）")


# ---------------------------------------------------------------- 搜索引擎桥接（网文兜底）
def bing_ids(keyword, site, pattern):
    q = keyword + " site:" + site
    url = "https://cn.bing.com/search?q=" + quote(q)
    try:
        status, body, final, _ = http_get(url)
    except Exception:
        return []
    txt = body.decode("utf-8", "ignore")
    ids = list(dict.fromkeys(re.findall(pattern, txt)))
    return ids[:3]


def web_search(keyword, category):
    """先用必应定位起点/番茄官方页，再直接解析成成品草稿。"""
    drafts, errs = [], []
    for site, pattern, parser in [
        ("qidian.com", r"qidian\.com/book/(\d{6,})", parse_qidian),
        ("fanqienovel.com", r"fanqienovel\.com/page/(\d{8,})", parse_fanqie),
    ]:
        for bid in bing_ids(keyword, site, pattern):
            try:
                d = parser(bid)
                if d.get("title"):
                    d["_ready"] = True
                    drafts.append({
                        "title": d["title"], "subtitle": d.get("originalTitle") or "",
                        "year": d.get("year") or "", "cover": d.get("coverUrl"),
                        "meta": "来自 " + d["source"]["label"] + " 官方页", "draft": d,
                    })
            except Exception as e:
                errs.append(str(e))
    return drafts


# ---------------------------------------------------------------- 红果短剧
HG_HEADERS = {"Referer": "https://hongguoduanju.com/", "Accept": "application/json, text/plain, */*"}


def _hg_draft(vd, it):
    try:
        date = datetime.fromtimestamp(int(vd.get("create_time"))).strftime("%Y-%m-%d")
    except Exception:
        date = ""
    tags = [c.get("name") for c in (vd.get("category_list") or []) if c.get("name")]
    cast = []
    for c in (vd.get("celebrities") or []):
        name = (c.get("nickname") or "").strip()
        if not name:
            continue
        role = (c.get("sub_title") or "").replace("饰", "").strip()
        cast.append({"role": "主演", "name": f"{name}（饰 {role}）" if role else name})
    infobox = []
    if vd.get("episode_cnt"):
        infobox.append({"key": "集数", "value": f"全 {vd['episode_cnt']} 集"})
    if date:
        infobox.append({"key": "上线日期", "value": date})
    for key, val in (("热度", (vd.get("hot_score_data") or {}).get("text")),
                     ("收藏", vd.get("favorite_text")), ("点赞", vd.get("like_text"))):
        if val:
            infobox.append({"key": key, "value": str(val)})
    return {
        "title": (vd.get("series_title") or it.get("name") or "").strip(),
        "originalTitle": "",
        "aliases": [],
        "year": date[:4],
        "tags": tags[:8],
        "summary": vd.get("series_intro") or "",
        "creators": cast,
        "infobox": infobox,
        "coverUrl": vd.get("series_cover") or "",
        "coverReferer": "https://hongguoduanju.com/",
        "source": {"name": "hongguo", "label": "红果"},
    }


def hongguo_search(keyword, category=None):
    url = "https://hongguoduanju.com/api/search/result?aid=8662&query=" + quote(keyword)
    j = http_json(url, headers=HG_HEADERS, timeout=20)
    out = []
    for it in (j.get("searchList") or []):
        vd = it.get("video_data") or {}
        if not vd.get("series_id"):
            continue
        draft = _hg_draft(vd, it)
        if not draft["title"]:
            continue
        meta = " · ".join([x for x in ["红果短剧", vd.get("episode_right_text") or "",
                                       (vd.get("hot_score_data") or {}).get("text") or ""] if x])
        out.append({
            "title": draft["title"],
            "subtitle": "",
            "year": draft["year"],
            "cover": draft["coverUrl"],
            "meta": meta,
            "draft": draft,
            "ref": {"source": "hongguo", "id": str(vd.get("series_id")), "title": draft["title"]},
        })
    return out[:10]


def hongguo_draft(ref):
    ref = ref or {}
    sid = str(ref.get("id") or "")
    title = (ref.get("title") or "").strip()
    if not title:
        raise RuntimeError("红果条目缺少标题，请用剧名重新搜索")
    for it in hongguo_search(title):
        if not sid or str((it.get("ref") or {}).get("id")) == sid:
            return it["draft"]
    raise RuntimeError("红果没找到这部剧")


def parse_hongguo_link(url):
    m = re.search(r"/search/([^/?#]+)", url)
    kw = ""
    if m:
        kw = unquote(m.group(1))
    else:
        q = parse_qs(urlparse(url).query)
        kw = (q.get("keyword") or q.get("q") or [""])[0]
    if not kw.strip():
        raise RuntimeError("红果只认「搜索结果页链接」或剧名搜索；/s/ 分享短链里没有剧名")
    items = hongguo_search(kw.strip())
    if not items:
        raise RuntimeError("红果没搜到这部剧，换个剧名试试")
    return items[0]["draft"]


# ---------------------------------------------------------------- 草稿 → 作品
def normalize_work(payload, existing=None):
    cat = payload.get("category") or (existing or {}).get("category") or "book"
    if cat not in CATEGORIES:
        cat = "book"
    w = existing or {}
    w["id"] = w.get("id") or new_id("w_")
    w["category"] = cat
    w["title"] = (payload.get("title") or w.get("title") or "").strip()
    w["originalTitle"] = (payload.get("originalTitle") or "").strip()
    w["aliases"] = [a for a in (payload.get("aliases") or []) if a]
    w["year"] = str(payload.get("year") or "").strip()
    w["tags"] = [t for t in (payload.get("tags") or []) if t]
    w["summary"] = (payload.get("summary") or "").strip()
    w["creators"] = [c for c in (payload.get("creators") or []) if c and c.get("name")]
    w["source"] = payload.get("source") or w.get("source") or {"name": "manual", "label": "手动"}
    w["infobox"] = [p for p in (payload.get("infobox") or []) if p.get("key") and p.get("value")]
    w["userFields"] = [p for p in (payload.get("userFields") or w.get("userFields") or [])
                       if p.get("key") and p.get("value")]
    links = payload.get("seriesLinks")
    if links is None:
        links = w.get("seriesLinks") or []
    clean = []
    for lk in links:
        sid = (lk or {}).get("id")
        if not sid:
            continue
        role = lk.get("role") if lk.get("role") in SERIES_ROLES else "main"
        clean.append({"id": sid, "role": role, "required": bool(lk.get("required", True))})
    w["seriesLinks"] = clean
    cover = payload.get("cover")
    if cover is None:
        cover = payload.get("coverUrl")
    if cover is None:
        cover = w.get("cover")
    if cover and not str(cover).startswith(("covers/", "/covers/")):
        local = save_cover(cover, referer=payload.get("coverReferer"),
                           proxy=bool(payload.get("coverProxy")))
        cover = local or ""
    w["cover"] = cover or ""
    w["createdAt"] = w.get("createdAt") or now_iso()
    w["updatedAt"] = now_iso()
    w.setdefault("rating", None)
    w.setdefault("ratingHistory", [])
    w.setdefault("experiences", [])
    return w


def effective_experience(work):
    """当前状态由『经历日期』最新的一条决定，而不是最后添加的那条。
    同一天有多条时，按添加先后，后加的算更新。"""
    exps = work.get("experiences") or []
    best_key, best = None, None
    for i, e in enumerate(exps):
        key = (str(e.get("date") or ""), str(e.get("createdAt") or ""), i)
        if best is None or key >= best_key:
            best_key, best = key, e
    return best


def effective_status(work):
    e = effective_experience(work)
    if not e:
        return "not_started"
    st = e.get("status")
    return st if st in STATUS_ORDER else "not_started"


def work_view(work):
    v = dict(work)
    v["status"] = effective_status(work)
    v["statusLabel"] = STATUS_LABELS.get(work.get("category"), {}).get(v["status"], v["status"])
    v["coverUrl"] = ("/" + work["cover"]).replace("//", "/") if work.get("cover") else ""
    exps = work.get("experiences") or []
    v["experiences"] = sorted(exps, key=lambda e: (str(e.get("date") or ""), str(e.get("createdAt") or "")))
    cur = effective_experience(work)
    v["currentExperienceId"] = cur.get("id") if cur else None
    v["lastExperienceAt"] = max([e.get("date") or "" for e in exps], default="")
    links = work.get("seriesLinks") or []
    v["seriesLinks"] = links
    v["primarySeriesId"] = links[0]["id"] if links else None
    return v


# ---------------------------------------------------------------- 系列
def normalize_series(payload, existing=None):
    s = existing or {}
    s["id"] = s.get("id") or new_id("s_")
    s["name"] = (payload.get("name") or s.get("name") or "").strip()
    s["originalTitle"] = (payload.get("originalTitle") or s.get("originalTitle") or "").strip()
    kind = payload.get("kind") or s.get("kind") or "mixed"
    s["kind"] = kind if kind in SERIES_KINDS else "mixed"
    s["summary"] = (payload.get("summary") or s.get("summary") or "").strip()
    s["note"] = (payload.get("note") or s.get("note") or "").strip()
    s["tags"] = [t for t in (payload.get("tags") or s.get("tags") or []) if t]
    s["creators"] = [c for c in (payload.get("creators") or s.get("creators") or []) if c and c.get("name")]
    s["source"] = payload.get("source") or s.get("source") or {"name": "manual", "label": "手动"}
    s["infobox"] = [p for p in (payload.get("infobox") or s.get("infobox") or [])
                    if p.get("key") and p.get("value")]
    s["userFields"] = [p for p in (payload.get("userFields") or s.get("userFields") or [])
                       if p.get("key") and p.get("value")]
    cover = payload.get("cover")
    if cover is None:
        cover = payload.get("coverUrl")
    if cover is None:
        cover = s.get("cover")
    if cover and not str(cover).startswith(("covers/", "/covers/")):
        cover = save_cover(cover, referer=payload.get("coverReferer"),
                           proxy=bool(payload.get("coverProxy"))) or ""
    s["cover"] = cover or ""
    s.setdefault("rating", None)
    s.setdefault("ratingHistory", [])
    s.setdefault("experiences", [])
    s["createdAt"] = s.get("createdAt") or now_iso()
    s["updatedAt"] = now_iso()
    return s


def series_view(s, lib):
    """系列视图：成员、分类分布、平均分、进度都由成员实时算出。"""
    members = []
    for w in lib.get("works", []):
        link = next((l for l in (w.get("seriesLinks") or []) if l.get("id") == s["id"]), None)
        if not link:
            continue
        st = effective_status(w)
        cat = w.get("category") or "book"
        members.append({
            "id": w["id"], "title": w.get("title") or "", "category": cat,
            "year": w.get("year") or "", "status": st,
            "statusLabel": STATUS_LABELS.get(cat, {}).get(st, st),
            "rating": w.get("rating"),
            "coverUrl": ("/" + w["cover"]).replace("//", "/") if w.get("cover") else "",
            "role": link.get("role") or "main", "required": bool(link.get("required", True)),
            "lastExperienceAt": max([e.get("date") or "" for e in (w.get("experiences") or [])], default=""),
        })
    members.sort(key=lambda m: (m.get("year") or "9999", m.get("title") or ""))
    total = len(members)
    cnt = {}
    for m in members:
        cnt[m["status"]] = cnt.get(m["status"], 0) + 1
    completed, active = cnt.get("completed", 0), cnt.get("active", 0)
    dropped, paused = cnt.get("dropped", 0), cnt.get("paused", 0)
    if not total:
        base = "not_started"
    elif completed == total:
        base = "completed"
    elif active:
        base = "active"
    elif paused:
        base = "paused"
    elif dropped and dropped >= max(1, total // 2):
        base = "dropped"
    elif cnt.get("planned", 0) == total:
        base = "planned"
    else:
        base = "planned"
    mix = {}
    for m in members:
        mix[m["category"]] = mix.get(m["category"], 0) + 1
    rated = [m["rating"] for m in members if m["rating"] is not None]
    years = sorted({m["year"] for m in members if m.get("year")})
    v = dict(s)
    v["coverUrl"] = ("/" + s["cover"]).replace("//", "/") if s.get("cover") else ""
    v["kindLabel"] = SERIES_KINDS.get(s.get("kind"), "")
    v["members"] = members
    v["memberCount"] = total
    v["catMix"] = [{"key": k, "label": CATEGORIES.get(k, {}).get("label", k), "count": n}
                   for k, n in sorted(mix.items(), key=lambda kv: -kv[1])]
    v["baseStatus"] = base
    v["baseStatusLabel"] = SERIES_STATUS_LABELS.get(base, "未开始")
    v["progress"] = f"{completed}/{total}" if total else "0/0"
    v["completedCount"] = completed
    v["activeCount"] = active
    v["droppedCount"] = dropped
    v["avgRating"] = round(sum(rated) / len(rated), 2) if rated else None
    v["ratedCount"] = len(rated)
    v["yearRange"] = (years[0] if len(years) == 1 else f"{years[0]} – {years[-1]}") if years else ""
    v["experiences"] = sorted(s.get("experiences") or [],
                              key=lambda e: (str(e.get("date") or ""), str(e.get("createdAt") or "")))
    return v


# ---------------------------------------------------------------- HTTP 层
class Handler(BaseHTTPRequestHandler):
    server_version = "GRDAG/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # --- 输出工具
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def send_json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def serve_file(self, path):
        if not os.path.exists(path):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # --- 路由
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        qs = parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self.serve_file(os.path.join(WEB_DIR, "index.html"))
            if p.startswith("/covers/"):
                return self.serve_file(os.path.join(COVER_DIR, os.path.basename(p)))
            if p.startswith("/static/"):
                return self.serve_file(os.path.join(WEB_DIR, os.path.basename(p)))
            if p == "/api/img":
                img_url = (qs.get("url") or [""])[0]
                cached = cache_remote_image(img_url)
                if not cached:
                    self._send(502, "image unavailable", "text/plain; charset=utf-8")
                    return
                return self.serve_file(cached)
            if p == "/api/bootstrap":
                lib = load_library()
                proxy = resolve_proxy()
                return self.send_json({
                    "version": VERSION,
                    "works": [work_view(w) for w in lib["works"]],
                    "series": [series_view(s, lib) for s in lib["series"]],
                    "seriesKinds": SERIES_KINDS,
                    "seriesRoles": SERIES_ROLES,
                    "settings": lib["settings"],
                    "proxyActive": proxy,
                    "proxySource": _proxy_cache.get("source"),
                    "categories": [{"key": k, "label": v["label"], "sources": v["sources"],
                                    "statuses": STATUS_LABELS[k]} for k, v in CATEGORIES.items()],
                    "sourceLabels": SOURCE_LABELS,
                })
            if p == "/api/export":
                return self.handle_export(bool(qs.get("covers", ["0"])[0] in ("1", "true")))
            if p == "/api/template.csv":
                return self.handle_template()
            if p == "/api/backups":
                files = []
                for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
                    if f.startswith("library_") and f.endswith(".json"):
                        fp = os.path.join(BACKUP_DIR, f)
                        files.append({"name": f, "size": os.path.getsize(fp),
                                      "time": datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")})
                return self.send_json({"ok": True, "backups": files[:40]})
            self._send(404, json.dumps({"ok": False, "error": "not found"}), "application/json")
        except Exception as e:
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        try:
            body = self.read_body()
            if p == "/api/search":
                return self.handle_search(body)
            if p == "/api/resolve":
                return self.handle_resolve(body)
            if p == "/api/link":
                cat = body.get("category")
                draft = parse_link(body.get("url") or "", cat)
                draft["_ready"] = True
                return self.send_json({"ok": True, "draft": draft})
            if p == "/api/works":
                return self.handle_create(body)
            if p == "/api/import-records":
                return self.handle_import_records(body)
            if p == "/api/import":
                return self.handle_import(body)
            if p == "/api/clear-data":
                return self.handle_clear_data(body)
            if p == "/api/settings":
                return self.handle_settings(body)
            if p == "/api/backups/restore":
                return self.handle_restore(body)
            if p == "/api/proxy/check":
                val = resolve_proxy(force=True)
                return self.send_json({"ok": True, "proxy": val, "state": "连通" if val else "未探测到可用代理"})
            m = re.match(r"^/api/works/([^/]+)/(rating|experience)$", p)
            if m:
                return self.handle_work_action(m.group(1), m.group(2), body)
            m = re.match(r"^/api/works/([^/]+)/series$", p)
            if m:
                return self.handle_work_series(m.group(1), body)
            m = re.match(r"^/api/works/([^/]+)/refill$", p)
            if m:
                return self.handle_work_refill(m.group(1), body)
            if p == "/api/series":
                return self.handle_series_create(body)
            m = re.match(r"^/api/series/([^/]+)/(rating|experience)$", p)
            if m:
                return self.handle_series_action(m.group(1), m.group(2), body)
            m = re.match(r"^/api/series/([^/]+)/members$", p)
            if m:
                return self.handle_series_members(m.group(1), body)
            self._send(404, json.dumps({"ok": False, "error": "not found"}), "application/json")
        except Exception as e:
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_PATCH(self):
        u = urlparse(self.path)
        body = self.read_body()
        m = re.match(r"^/api/series/([^/]+)$", u.path)
        if m:
            return self.handle_series_update(m.group(1), body)
        m = re.match(r"^/api/works/([^/]+)$", u.path)
        if not m:
            return self._send(404, "{}", "application/json")
        wid = m.group(1)
        with _lock:
            lib = load_library()
            existing = next((w for w in lib["works"] if w["id"] == wid), None)
        if existing is None:
            return self.send_json({"ok": False, "error": "not found"}, 404)
        merged = dict(existing)
        merged.update({k: v for k, v in body.items() if k not in ("id", "createdAt")})
        # 封面下载可能耗时，放在锁外面，避免保存封面时把评分/经历等写入一起堵住
        work = normalize_work(merged, existing=existing)
        with _lock:
            lib = load_library()
            for i, w in enumerate(lib["works"]):
                if w["id"] == wid:
                    # 下载封面期间可能有评分/经历写入，基于最新记录再归一化一次，
                    # 此时封面已是本地路径，不会再发起网络请求。
                    merged2 = dict(w)
                    merged2.update({k: v for k, v in body.items() if k not in ("id", "createdAt")})
                    merged2["cover"] = work.get("cover") or w.get("cover") or ""
                    final = normalize_work(merged2, existing=w)
                    lib["works"][i] = final
                    save_library(lib)
                    return self.send_json({"ok": True, "work": work_view(lib["works"][i])})
        return self.send_json({"ok": False, "error": "not found"}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        m = re.match(r"^/api/works/([^/]+)$", u.path)
        m2 = re.match(r"^/api/works/([^/]+)/experience/([^/]+)$", u.path)
        ms = re.match(r"^/api/series/([^/]+)$", u.path)
        ms2 = re.match(r"^/api/series/([^/]+)/experience/([^/]+)$", u.path)
        ms3 = re.match(r"^/api/series/([^/]+)/members/([^/]+)$", u.path)
        with _lock:
            lib = load_library()
            if ms3:
                for w in lib["works"]:
                    if w["id"] == ms3.group(2):
                        w["seriesLinks"] = [l for l in (w.get("seriesLinks") or []) if l.get("id") != ms3.group(1)]
                        w["updatedAt"] = now_iso()
                save_library(lib)
                return self.send_series(lib, ms3.group(1))
            if ms2:
                for s in lib["series"]:
                    if s["id"] == ms2.group(1):
                        s["experiences"] = [e for e in (s.get("experiences") or []) if e.get("id") != ms2.group(2)]
                        s["updatedAt"] = now_iso()
                        save_library(lib)
                        return self.send_series(lib, s["id"])
                return self.send_json({"ok": False, "error": "not found"}, 404)
            if ms:
                before = len(lib["series"])
                lib["series"] = [s for s in lib["series"] if s["id"] != ms.group(1)]
                if len(lib["series"]) == before:
                    return self.send_json({"ok": False, "error": "not found"}, 404)
                for w in lib["works"]:
                    w["seriesLinks"] = [l for l in (w.get("seriesLinks") or []) if l.get("id") != ms.group(1)]
                save_library(lib)
                return self.send_json({"ok": True, "works": [work_view(w) for w in lib["works"]]})
            if m2:
                for w in lib["works"]:
                    if w["id"] == m2.group(1):
                        w["experiences"] = [e for e in w.get("experiences", []) if e.get("id") != m2.group(2)]
                        w["updatedAt"] = now_iso()
                        save_library(lib)
                        return self.send_json({"ok": True, "work": work_view(w)})
                return self.send_json({"ok": False, "error": "not found"}, 404)
            if m:
                before = len(lib["works"])
                lib["works"] = [w for w in lib["works"] if w["id"] != m.group(1)]
                if len(lib["works"]) == before:
                    return self.send_json({"ok": False, "error": "not found"}, 404)
                save_library(lib)
                return self.send_json({"ok": True})
        self._send(404, "{}", "application/json")

    # --- 业务处理
    def handle_search(self, body):
        category = body.get("category") or "book"
        source = body.get("source") or "douban"
        kw = (body.get("keyword") or "").strip()
        if not kw:
            return self.send_json({"ok": False, "error": "请输入关键词"}, 400)
        fn = {"bangumi": bangumi_search, "douban": douban_search, "weread": weread_search,
              "steam": steam_search, "bilibili": bilibili_search, "anilist": anilist_search,
              "web": web_search, "hongguo": hongguo_search}.get(source)
        if not fn:
            return self.send_json({"ok": False, "error": "未知来源"}, 400)
        try:
            items = fn(kw, category) or []
        except HTTPError as e:
            return self.send_json({"ok": False, "error": f"来源请求失败 HTTP {e.code}，稍后再试"}, 200)
        except URLError as e:
            return self.send_json({"ok": False, "error": f"网络不可达：{e.reason}（Bangumi 需代理，可在设置里检查）"}, 200)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 200)
        return self.send_json({"ok": True, "items": items, "source": source})

    def handle_resolve(self, body):
        source = body.get("source")
        ref = body.get("ref") or {}
        category = body.get("category")
        fn = {"bangumi": bangumi_draft, "douban": douban_draft, "weread": weread_draft,
              "steam": steam_draft, "bilibili": bilibili_draft, "anilist": anilist_draft,
              "hongguo": hongguo_draft}.get(source)
        if not fn:
            return self.send_json({"ok": False, "error": "未知来源"}, 400)
        try:
            draft = fn(ref)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 200)
        draft["_ready"] = True
        return self.send_json({"ok": True, "draft": draft})

    def handle_create(self, body):
        draft = body.get("draft") or body
        category = body.get("category") or draft.get("category")
        payload = dict(draft)
        payload["category"] = category
        work = normalize_work(payload)
        if not work["title"]:
            return self.send_json({"ok": False, "error": "标题不能为空"}, 400)
        score = draft.get("rating")
        if score not in (None, ""):
            try:
                score = round(float(score) * 2) / 2
                work["rating"] = max(0, min(10, score))
                work["ratingHistory"].append({"at": now_iso(), "score": work["rating"],
                                              "prev": None, "reason": "初始评分"})
            except Exception:
                work["rating"] = None
        first = draft.get("firstExperience") or {}
        if first.get("status") or first.get("content"):
            work["experiences"].append({
                "id": new_id("e_"),
                "date": first.get("date") or datetime.now().strftime("%Y-%m-%d"),
                "content": (first.get("content") or "").strip(),
                "status": first.get("status") or "planned",
                "createdAt": now_iso(),
            })
        with _lock:
            lib = load_library()
            lib["works"].append(work)
            save_library(lib)
        return self.send_json({"ok": True, "work": work_view(work)})

    def handle_work_action(self, wid, action, body):
        with _lock:
            lib = load_library()
            for i, w in enumerate(lib["works"]):
                if w["id"] != wid:
                    continue
                if action == "rating":
                    try:
                        score = round(float(body.get("score")) * 2) / 2
                    except Exception:
                        return self.send_json({"ok": False, "error": "分数格式不正确"}, 400)
                    score = max(0, min(10, score))
                    prev = w.get("rating")
                    if prev is not None and abs(prev - score) < 1e-9:
                        return self.send_json({"ok": False, "error": "与当前分数相同，未记录"}, 200)
                    w["rating"] = score
                    w.setdefault("ratingHistory", []).append({
                        "at": now_iso(), "score": score, "prev": prev,
                        "reason": (body.get("reason") or "").strip(),
                    })
                elif action == "experience":
                    status = body.get("status") or "active"
                    if status not in STATUS_ORDER:
                        return self.send_json({"ok": False, "error": "状态不合法"}, 400)
                    content = (body.get("content") or "").strip()
                    if not content and not body.get("date"):
                        return self.send_json({"ok": False, "error": "经历内容不能为空"}, 400)
                    w.setdefault("experiences", []).append({
                        "id": new_id("e_"),
                        "date": body.get("date") or datetime.now().strftime("%Y-%m-%d"),
                        "content": content, "status": status, "createdAt": now_iso(),
                    })
                w["updatedAt"] = now_iso()
                save_library(lib)
                return self.send_json({"ok": True, "work": work_view(w)})
        return self.send_json({"ok": False, "error": "not found"}, 404)

    # --- 系列
    def send_series(self, lib, sid):
        for s in lib.get("series", []):
            if s["id"] == sid:
                return self.send_json({"ok": True, "series": series_view(s, lib)})
        return self.send_json({"ok": False, "error": "not found"}, 404)

    def handle_series_create(self, body):
        payload = body.get("draft") or body
        s = normalize_series(payload)
        if not s["name"]:
            return self.send_json({"ok": False, "error": "系列名称不能为空"}, 400)
        with _lock:
            lib = load_library()
            lib["series"].append(s)
            save_library(lib)
            return self.send_json({"ok": True, "series": series_view(s, lib)})

    def handle_series_update(self, sid, body):
        with _lock:
            lib = load_library()
            for i, s in enumerate(lib["series"]):
                if s["id"] != sid:
                    continue
                merged = dict(s)
                merged.update({k: v for k, v in body.items() if k not in ("id", "createdAt")})
                lib["series"][i] = normalize_series(merged, existing=s)
                save_library(lib)
                return self.send_json({"ok": True, "series": series_view(lib["series"][i], lib)})
        return self.send_json({"ok": False, "error": "not found"}, 404)

    def handle_series_action(self, sid, action, body):
        with _lock:
            lib = load_library()
            for s in lib["series"]:
                if s["id"] != sid:
                    continue
                if action == "rating":
                    try:
                        score = round(float(body.get("score")) * 2) / 2
                    except Exception:
                        return self.send_json({"ok": False, "error": "分数格式不正确"}, 400)
                    score = max(0, min(10, score))
                    prev = s.get("rating")
                    if prev is not None and abs(prev - score) < 1e-9:
                        return self.send_json({"ok": False, "error": "与当前分数相同，未记录"}, 200)
                    s["rating"] = score
                    s.setdefault("ratingHistory", []).append({
                        "at": now_iso(), "score": score, "prev": prev,
                        "reason": (body.get("reason") or "").strip(),
                    })
                elif action == "experience":
                    content = (body.get("content") or "").strip()
                    if not content and not body.get("date"):
                        return self.send_json({"ok": False, "error": "经历内容不能为空"}, 400)
                    st = body.get("status") or ""
                    if st and st not in STATUS_ORDER:
                        return self.send_json({"ok": False, "error": "状态不合法"}, 400)
                    s.setdefault("experiences", []).append({
                        "id": new_id("se_"),
                        "date": body.get("date") or datetime.now().strftime("%Y-%m-%d"),
                        "content": content, "status": st, "createdAt": now_iso(),
                    })
                s["updatedAt"] = now_iso()
                save_library(lib)
                return self.send_json({"ok": True, "series": series_view(s, lib)})
        return self.send_json({"ok": False, "error": "not found"}, 404)

    def handle_series_members(self, sid, body):
        ids = [i for i in (body.get("workIds") or []) if i]
        role = body.get("role") if body.get("role") in SERIES_ROLES else "main"
        with _lock:
            lib = load_library()
            if not any(s["id"] == sid for s in lib["series"]):
                return self.send_json({"ok": False, "error": "系列不存在"}, 404)
            for w in lib["works"]:
                if w["id"] not in ids:
                    continue
                links = w.get("seriesLinks") or []
                if any(l.get("id") == sid for l in links):
                    continue
                links.append({"id": sid, "role": role, "required": True})
                w["seriesLinks"] = links
                w["updatedAt"] = now_iso()
            save_library(lib)
            return self.send_series(lib, sid)

    def handle_work_series(self, wid, body):
        links = body.get("links") or []
        with _lock:
            lib = load_library()
            sids = {s["id"] for s in lib.get("series", [])}
            for w in lib["works"]:
                if w["id"] != wid:
                    continue
                clean = []
                for lk in links:
                    sid = (lk or {}).get("id")
                    if sid not in sids or any(c["id"] == sid for c in clean):
                        continue
                    clean.append({
                        "id": sid,
                        "role": lk.get("role") if lk.get("role") in SERIES_ROLES else "main",
                        "required": bool(lk.get("required", True)),
                    })
                w["seriesLinks"] = clean
                w["updatedAt"] = now_iso()
                save_library(lib)
                return self.send_json({"ok": True, "work": work_view(w)})
        return self.send_json({"ok": False, "error": "not found"}, 404)

    # --- 重新获取作品信息（保留评分、经历、我的字段）
    def handle_work_refill(self, wid, body):
        draft = body.get("draft") or {}
        if not isinstance(draft, dict) or not draft:
            return self.send_json({"ok": False, "error": "没有拿到新条目数据"}, 400)
        with _lock:
            lib = load_library()
            for i, w in enumerate(lib["works"]):
                if w["id"] != wid:
                    continue
                merged = dict(w)
                for k in ("title", "originalTitle", "aliases", "year", "tags", "summary",
                          "creators", "infobox", "source"):
                    v = draft.get(k)
                    if v not in (None, "", [], {}):
                        merged[k] = v
                cover = draft.get("coverUrl") or draft.get("cover")
                if cover:
                    merged["cover"] = cover
                lib["works"][i] = normalize_work(merged, existing=w)
                save_library(lib)
                return self.send_json({
                    "ok": True, "work": work_view(lib["works"][i]),
                    "kept": {"rating": lib["works"][i].get("rating"),
                             "experiences": len(lib["works"][i].get("experiences") or []),
                             "userFields": len(lib["works"][i].get("userFields") or [])},
                })
        return self.send_json({"ok": False, "error": "not found"}, 404)

    # --- 旧记录导入（CSV / JSON）
    def handle_import_records(self, body):
        text = body.get("text") or ""
        if not str(text).strip():
            return self.send_json({"ok": False, "error": "内容为空"}, 400)
        try:
            groups = parse_records(str(text))
        except Exception as e:
            return self.send_json({"ok": False, "error": f"解析失败：{type(e).__name__}: {e}"}, 400)
        if not groups:
            return self.send_json({"ok": False, "error": "没有解析到条目。检查表头是否为「标题 / 分类 / 经历日期 / 经历状态 / 经历内容」"}, 400)
        with _lock:
            lib = load_library()
            created = updated = exp_added = 0
            for g in groups:
                title, cat = g["title"], g["category"]
                target = next((w for w in lib["works"]
                               if (w.get("title") or "").strip() == title and w.get("category") == cat), None)
                if target is None:
                    target = normalize_work({
                        "category": cat, "title": title,
                        "originalTitle": g.get("originalTitle") or "",
                        "year": g.get("year") or "",
                        "tags": g.get("tags") or [],
                        "summary": g.get("summary") or "",
                        "source": {"name": "manual", "label": "导入"},
                    })
                    lib["works"].append(target)
                    created += 1
                else:
                    updated += 1
                    if not target.get("year") and g.get("year"):
                        target["year"] = g["year"]
                    if not target.get("summary") and g.get("summary"):
                        target["summary"] = g["summary"]
                    if not (target.get("tags") or []) and g.get("tags"):
                        target["tags"] = g["tags"]
                uf_keys = {p.get("key") for p in (target.get("userFields") or [])}
                for k, v in (g.get("userFields") or {}).items():
                    if k not in uf_keys:
                        target.setdefault("userFields", []).append({"key": k, "value": v})
                        uf_keys.add(k)
                if g.get("rating") not in (None, ""):
                    try:
                        score = max(0, min(10, round(float(g["rating"]) * 2) / 2))
                    except Exception:
                        score = None
                    if score is not None and target.get("rating") is None:
                        target["rating"] = score
                        target.setdefault("ratingHistory", []).append({
                            "at": now_iso(), "score": score, "prev": None, "reason": "导入初评"})
                seen = {(e.get("date") or "", (e.get("content") or "").strip())
                        for e in (target.get("experiences") or [])}
                for e in g["experiences"]:
                    key = (e["date"] or "", e["content"] or "")
                    if key in seen:
                        continue
                    target.setdefault("experiences", []).append({
                        "id": new_id("e_"), "date": e["date"] or "",
                        "content": e["content"] or "", "status": e["status"] or "active",
                        "createdAt": now_iso(),
                    })
                    seen.add(key)
                    exp_added += 1
                target["updatedAt"] = now_iso()
            save_library(lib)
            total = len(lib["works"])
        return self.send_json({"ok": True, "created": created, "updated": updated,
                               "experiences": exp_added, "works": total})

    def handle_template(self):
        rows = [
            ["标题", "分类", "原名", "年份", "评分", "标签", "简介", "经历日期", "经历状态", "经历内容"],
            ["诡秘之主", "网文", "", "2018", "9.5", "克苏鲁、西幻", "示例行，可删", "2024-03-01", "在读", "开始看第一章"],
            ["诡秘之主", "网文", "", "2018", "", "", "", "2025-06-10", "已读完", "全书看完"],
            ["弹丸论破 希望的学园与绝望高中生", "游戏", "ダンガンロンパ", "2010", "9", "推理", "", "2023-08-20", "已通关", "一周目通关"],
        ]
        buf = io.StringIO()
        w = csv.writer(buf)
        for r in rows:
            w.writerow(r)
        data = ("\ufeff" + buf.getvalue()).encode("utf-8")
        return self._send(200, data, "text/csv; charset=utf-8",
                          {"Content-Disposition": 'attachment; filename="import_template.csv"'})

    def handle_export(self, with_covers):
        lib = load_library()
        if not with_covers:
            payload = json.dumps(lib, ensure_ascii=False, indent=1).encode("utf-8")
            name = f"archive_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
            return self._send(200, payload, "application/json; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{quote(name)}"'})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("library.json", json.dumps(lib, ensure_ascii=False, indent=1))
            for w in lib["works"]:
                cov = w.get("cover") or ""
                if cov.startswith("covers/"):
                    fp = os.path.join(DATA_DIR, cov)
                    if os.path.exists(fp):
                        z.write(fp, cov)
            for s in lib.get("series", []):
                cov = s.get("cover") or ""
                if cov.startswith("covers/"):
                    fp = os.path.join(DATA_DIR, cov)
                    if os.path.exists(fp):
                        z.write(fp, cov)
        name = f"archive_with_covers_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        return self._send(200, buf.getvalue(), "application/zip",
                          {"Content-Disposition": f'attachment; filename="{quote(name)}"'})

    def handle_import(self, body):
        data = body.get("data")
        mode = body.get("mode") or "merge"
        cover_cnt = 0
        if body.get("zip"):
            b64 = body["zip"]
            if isinstance(b64, str) and b64.startswith("data:") and "," in b64:
                b64 = b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return self.send_json({"ok": False, "error": "zip 内容无法解码"}, 400)
            try:
                data, cover_cnt = extract_library_zip(raw)
            except RuntimeError as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                return self.send_json({"ok": False, "error": f"zip 读取失败：{type(e).__name__}"}, 400)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return self.send_json({"ok": False, "error": "备份文件不是合法 JSON"}, 400)
        if not isinstance(data, dict) or not isinstance(data.get("works"), list):
            return self.send_json({"ok": False, "error": "备份文件格式不正确"}, 400)
        incoming = data["works"]
        incoming_series = data.get("series") or []
        with _lock:
            lib = load_library()
            if mode == "replace":
                lib["works"] = incoming
                lib["series"] = incoming_series
            else:
                existing = {w["id"]: w for w in lib["works"]}
                for w in incoming:
                    wid = w.get("id") or new_id("w_")
                    w["id"] = wid
                    existing[wid] = w
                lib["works"] = list(existing.values())
                s_existing = {s["id"]: s for s in lib.get("series", []) if s.get("id")}
                for s in incoming_series:
                    sid = s.get("id") or new_id("s_")
                    s["id"] = sid
                    s_existing[sid] = s
                lib["series"] = list(s_existing.values())
            if isinstance(data.get("settings"), dict):
                lib["settings"].update({k: v for k, v in data["settings"].items() if k != "deepseek_key"})
            save_library(lib)
        return self.send_json({"ok": True, "count": len(lib["works"]), "covers": cover_cnt})

    def handle_clear_data(self, body):
        """清空个人记录（作品 / 系列 / 封面 / 项目内快照），清空前先整包备份到项目外的 娱乐档案_备份。"""
        if (body.get("confirm") or "").strip() != "清空全部":
            return self.send_json({"ok": False, "error": "确认词不正确，未执行"}, 400)
        lib = load_library()
        ensure_dirs()
        os.makedirs(SIBLING_BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        name = f"清空前全量备份_{stamp}.zip"
        path = os.path.join(SIBLING_BACKUP_DIR, name)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("library.json", json.dumps(lib, ensure_ascii=False, indent=1))
            for item in list(lib.get("works") or []) + list(lib.get("series") or []):
                cov = item.get("cover") or ""
                if cov.startswith("covers/"):
                    fp = os.path.join(DATA_DIR, cov)
                    if os.path.exists(fp):
                        z.write(fp, cov)
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        cleared = {"works": len(lib.get("works") or []), "series": len(lib.get("series") or []),
                   "covers": 0, "backups": 0}
        with _lock:
            newlib = default_library()
            for k in ("proxy", "proxy_port", "backup_keep"):
                if k in lib.get("settings", {}):
                    newlib["settings"][k] = lib["settings"][k]
            write_library(newlib)
            for fn in os.listdir(COVER_DIR):
                fp = os.path.join(COVER_DIR, fn)
                if os.path.isfile(fp):
                    os.remove(fp)
                    cleared["covers"] += 1
            for fn in os.listdir(BACKUP_DIR):
                fp = os.path.join(BACKUP_DIR, fn)
                if os.path.isfile(fp):
                    os.remove(fp)
                    cleared["backups"] += 1
        return self.send_json({"ok": True, "backup": name, "backup_path": path, "cleared": cleared})

    def handle_settings(self, body):
        with _lock:
            lib = load_library()
            for k in ("proxy", "proxy_port", "backup_keep", "deepseek_key"):
                if k in body:
                    lib["settings"][k] = body[k]
            save_library(lib, snapshot=False)
        _proxy_cache["at"] = 0
        return self.send_json({"ok": True, "settings": lib["settings"]})

    def handle_restore(self, body):
        name = os.path.basename(body.get("name") or "")
        fp = os.path.join(BACKUP_DIR, name)
        if not os.path.exists(fp):
            return self.send_json({"ok": False, "error": "快照不存在"}, 404)
        data = safe_json_load(fp)
        if not data:
            return self.send_json({"ok": False, "error": "快照损坏"}, 400)
        with _lock:
            save_library(data)
        return self.send_json({"ok": True, "count": len(data.get("works", []))})


def _port_alive(port):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def main():
    ensure_dirs()
    lib = load_library()
    if _port_alive(PORT):
        print("=" * 52)
        print(f"  {PORT} 端口上已经有一个实例在跑，这次不再重复启动。")
        print(f"  已为你打开：http://127.0.0.1:{PORT}")
        print("  （Windows 允许多个进程绑同一端口，所以之前会出现两个实例。）")
        print("=" * 52)
        try:
            webbrowser.open(f"http://127.0.0.1:{PORT}")
        except Exception:
            pass
        return
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("=" * 52)
        print(f"  启动失败：端口 {PORT} 无法绑定（{e}）")
        print("  想换端口就在命令行里先执行 set GRDAG_PORT=8899 再运行。")
        print("=" * 52)
        return
    print("=" * 52)
    print("  娱乐档案 · 本地服务")
    print(f"  数据文件：{LIB_PATH}")
    print(f"  封面目录：{COVER_DIR}")
    print(f"  备份目录：{BACKUP_DIR}")
    print(f"  访问地址：http://127.0.0.1:{PORT}")
    print(f"  作品数量：{len(lib['works'])}")
    print("  关闭这个窗口 = 停止服务，数据已写盘")
    print("=" * 52)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
