#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
娱乐档案 · 本地服务端
零第三方依赖，仅用 Python 标准库。默认端口 8777。
职责：数据落盘与备份、元数据抓取与聚合、封面本地化。
"""
import base64
import difflib
import hashlib
import html as _html
import io
import csv
import json
import logging
import logging.handlers
import mimetypes
import os
import re
import socket
import stat
import struct
import threading
import time
import unicodedata
import uuid
import webbrowser
import zipfile
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, build_opener, ProxyHandler

BASE_DIR = os.path.abspath(os.environ.get("GRDAG_BASE_DIR") or os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
VERSION_UNKNOWN = "未标注"
_VERSION_CACHE = {"mtime": None, "value": ""}


def read_version():
    """版本号唯一来源：项目根目录的 VERSION 文件。

    只接受「数字.数字」或「数字.数字.数字」的写法（允许前导 v）；文件缺失、读不出、
    内容不合规都返回空字符串，由调用方决定怎么展示。按 mtime 缓存，文件被覆盖后
    重新读取，避免每个请求都读盘。
    """
    try:
        stat = os.stat(VERSION_FILE)
    except OSError:
        return ""
    if _VERSION_CACHE["mtime"] == stat.st_mtime_ns:
        return _VERSION_CACHE["value"]
    value = ""
    try:
        # utf-8-sig 兼容记事本「UTF-8 带 BOM」另存的 VERSION：BOM 会被自动丢掉，
        # 否则首字符是 \ufeff，正则匹配失败会被误判成「未标注」。
        with open(VERSION_FILE, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
        first = raw.splitlines()[0].strip() if raw else ""
        candidate = re.sub(r"^[vV]\s*", "", first)
        if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", candidate):
            value = candidate
    except Exception:
        value = ""
    _VERSION_CACHE.update({"mtime": stat.st_mtime_ns, "value": value})
    return value


# 启动时读一次：界面显示的是「本次运行加载的版本」，而不是磁盘上可能刚被同步覆盖的版本。
VERSION = read_version() or VERSION_UNKNOWN
# 写进 HTTP Server 头和 User-Agent 的版本标识只能是 ASCII；VERSION 缺失时用 unversioned。
VERSION_ASCII = read_version() or "unversioned"
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
COVER_DIR = os.path.join(DATA_DIR, "covers")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
AUDIO_LIMIT = 30 * 1024 * 1024
BACKGROUND_IMAGE_LIMIT = 20 * 1024 * 1024
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DAILY_BACKUP_DIR = os.path.join(BACKUP_DIR, "daily")          # 每日自动备份，只保留最近 15 天
PRE_RESTORE_DIR = os.path.join(BACKUP_DIR, "pre-restore")     # 恢复/撤销前的安全快照，不参与自动清理
UNDO_USED_DIR = os.path.join(BACKUP_DIR, "undo-used")         # 已被「撤销」消费掉的写前快照
LOG_DIR = os.path.join(BASE_DIR, "logs")
SIBLING_BACKUP_DIR = os.path.join(os.path.dirname(BASE_DIR), "娱乐档案_备份")
LIB_PATH = os.path.join(DATA_DIR, "library.json")
IMAGE_CACHE_DIR = os.path.join(DATA_DIR, "image_cache")
MEDIA_STAGING_DIR = os.path.join(DATA_DIR, "素材暂存区")
MEDIA_GRACE_SECONDS = 24 * 60 * 60
LIB_VERSION = 2
DAILY_KEEP = 15
PORT = int(os.environ.get("GRDAG_PORT", "8777"))

# ---------------------------------------------------------------- 日志
LOG = logging.getLogger("grdag")
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(deepseek[_-]?key|api[_-]?key|token|password|secret)\s*[=:：]\s*[^\s,;]+"), r"\1=***"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)(authorization\s*[:：]\s*)(\S+)"), r"\1***"),
)


def redact(text):
    """日志脱敏：密钥、令牌、Authorization 一律不进日志。"""
    s = str(text if text is not None else "")
    for pattern, repl in _SECRET_PATTERNS:
        s = pattern.sub(repl, s)
    return s


def log_event(module, operation, result="ok", detail="", level=logging.INFO, exc=None):
    """统一日志入口；写日志失败绝不影响业务。"""
    try:
        msg = f"{module} | {operation} | {result}"
        if detail:
            msg += " | " + redact(detail)
        LOG.log(level, msg, exc_info=exc)
    except Exception:
        pass


def setup_logging():
    """本地滚动日志：logs/app.log，2 MB × 3 份。失败时静默降级，不启动也照常跑。"""
    try:
        if LOG.handlers:
            return
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "app.log"), maxBytes=2 * 1024 * 1024,
            backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)
        LOG.propagate = False
        logging.raiseExceptions = False
    except Exception:
        pass


setup_logging()


class LibraryCorrupt(Exception):
    """主档案存在但读不出来/结构不对：拒绝一切写操作，绝不自动覆盖。"""

    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
UA_BGM = f"GRDAG/{VERSION_ASCII} (https://bgm.tv/)"

CATEGORIES = {
    "anime": {"label": "动漫", "bangumi_type": 2, "sources": ["bangumi", "douban", "anilist"]},
    "manga": {"label": "漫画", "bangumi_type": 1, "sources": ["bangumi", "douban"]},
    "game": {"label": "游戏", "bangumi_type": 4, "sources": ["bangumi", "steam"]},
    "novel": {"label": "网文", "bangumi_type": 1, "sources": ["weread", "web"]},
    "book": {"label": "出版书", "bangumi_type": 1, "sources": ["douban", "bangumi", "weread"]},
    "movie": {"label": "影视剧", "bangumi_type": 6, "sources": ["bangumi", "douban", "cinemeta", "bilibili"]},
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
                 "bilibili": "B站", "cinemeta": "Cinemeta", "web": "搜索引擎", "anilist": "AniList",
                 "manual": "手动", "link": "链接解析", "hongguo": "红果", "tmdb": "TMDB",
                 "youshu": "优书网"}
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
    for d in (DATA_DIR, COVER_DIR, AUDIO_DIR, IMAGE_CACHE_DIR, BACKUP_DIR, DAILY_BACKUP_DIR,
              PRE_RESTORE_DIR, UNDO_USED_DIR, WEB_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def atomic_write_bytes(path, data):
    """临时文件 + fsync + 原子替换：中途断电/异常只会留下 .tmp，绝不会毁掉原文件。"""
    tmp = f"{path}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


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


# ---------------------------------------------------------------- 存储层
def default_library():
    return {"version": LIB_VERSION, "works": [], "series": [],
            "settings": {"proxy": "auto", "proxy_port": "7897", "backup_keep": 30,
                         "immersive_background_interval": 12, "immersive_background_order": "ordered",
                         "home_hidden_work_ids": []}}


def check_library(lib):
    """只做结构检查，不改内容。结构不对就抛 ValueError（由调用方决定怎么处理）。"""
    if not isinstance(lib, dict):
        raise ValueError("顶层不是 JSON 对象")
    works = lib.get("works")
    if not isinstance(works, list):
        raise ValueError("缺少 works 列表")
    if not isinstance(lib.get("series", []), list):
        raise ValueError("series 不是列表")
    ver = lib.get("version")
    if isinstance(ver, int) and ver > LIB_VERSION:
        raise ValueError(f"档案版本 {ver} 比当前程序支持的 {LIB_VERSION} 新")
    if works:
        usable = [w for w in works if isinstance(w, dict) and str(w.get("id") or "").strip()]
        if not usable:
            raise ValueError("works 里没有任何带 id 的作品")


def fill_library_defaults(lib):
    """补齐前端依赖的字段，只补空的，不覆盖已有内容，也不发起网络请求。"""
    lib.setdefault("settings", {})
    for k, v in default_library()["settings"].items():
        lib["settings"].setdefault(k, v)
    lib.setdefault("series", [])
    lib["version"] = int(lib.get("version") or LIB_VERSION)
    for w in lib["works"]:
        if not isinstance(w, dict):
            continue
        w.setdefault("title", "")
        w.setdefault("tags", [])
        w.setdefault("aliases", [])
        w.setdefault("creators", [])
        w.setdefault("infobox", [])
        w.setdefault("userFields", [])
        w.setdefault("seriesLinks", [])
        w.setdefault("rating", None)
        w.setdefault("ratingHistory", [])
        w.setdefault("experiences", [])
    for s in lib["series"]:
        if not isinstance(s, dict):
            continue
        s.setdefault("rating", None)
        s.setdefault("ratingHistory", [])
        s.setdefault("experiences", [])
    return lib


def load_library():
    """读取主档案。

    - 文件不存在：首次运行，允许创建空档案。
    - 文件存在但解析失败/结构不对：抛 LibraryCorrupt，原文件一个字节都不动。
    """
    if os.path.exists(LIB_PATH):
        try:
            with open(LIB_PATH, "r", encoding="utf-8") as f:
                lib = json.load(f)
        except Exception as e:
            log_event("storage", "load", "corrupt", f"{type(e).__name__}: {e}", logging.ERROR)
            raise LibraryCorrupt("主档案无法解析", f"{type(e).__name__}: {e}")
        try:
            check_library(lib)
        except ValueError as e:
            log_event("storage", "load", "corrupt", str(e), logging.ERROR)
            raise LibraryCorrupt("主档案结构异常", str(e))
        return fill_library_defaults(lib)
    lib = default_library()
    write_library(lib)
    log_event("storage", "create", "ok", "首次运行，已创建空档案")
    return lib


def library_health():
    """给 /api/bootstrap 用的只读体检结果：normal / corrupt / missing。"""
    if not os.path.exists(LIB_PATH):
        return {"state": "missing"}
    try:
        with open(LIB_PATH, "r", encoding="utf-8") as f:
            lib = json.load(f)
        check_library(lib)
        return {"state": "normal", "works": len(lib.get("works") or []),
                "series": len(lib.get("series") or [])}
    except Exception as e:
        try:
            size = os.path.getsize(LIB_PATH)
            mtime = datetime.fromtimestamp(os.path.getmtime(LIB_PATH)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            size, mtime = 0, ""
        return {"state": "corrupt", "reason": str(e), "size": size, "mtime": mtime,
                "error_detail": f"{type(e).__name__}: {e}"}


def snapshot_library(keep):
    """写前快照（撤销也依赖它）。文件名带微秒，避免同秒多次写入互相覆盖。"""
    if not os.path.exists(LIB_PATH):
        return None
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dst = os.path.join(BACKUP_DIR, f"library_{stamp}.json")
    try:
        with open(LIB_PATH, "rb") as f:
            raw = f.read()
        atomic_write_bytes(dst, raw)
    except Exception as e:
        log_event("backup", "snapshot", "fail", f"{type(e).__name__}: {e}", logging.WARNING)
        return None
    files = sorted(f for f in os.listdir(BACKUP_DIR)
                   if re.fullmatch(r"library_\d{8}_\d{6}(?:_\d{6})?\.json", f))
    while len(files) > max(1, int(keep or 30)):
        try:
            os.remove(os.path.join(BACKUP_DIR, files.pop(0)))
        except Exception:
            break
    log_event("backup", "snapshot", "ok", os.path.basename(dst))
    return dst


def write_library(lib):
    ensure_dirs()
    raw = json.dumps(lib, ensure_ascii=False, indent=1).encode("utf-8")
    atomic_write_bytes(LIB_PATH, raw)


def save_library(lib, snapshot=True):
    ensure_dirs()
    if snapshot:
        snapshot_library(lib.get("settings", {}).get("backup_keep", 30))
    write_library(lib)
    log_event("storage", "save", "ok", f"works={len(lib.get('works') or [])}")
    ensure_daily_backup()


# ---------------------------------------------------------------- 自动备份（每日 15 天）
def daily_backup_path(day=None):
    name = (day or datetime.now().strftime("%Y-%m-%d"))
    return os.path.join(DAILY_BACKUP_DIR, f"library_{name}.json")


def cleanup_daily(keep=DAILY_KEEP):
    """只清理「每日自动备份」目录，写前快照/恢复前快照/手动导出都不动。"""
    try:
        files = sorted(f for f in os.listdir(DAILY_BACKUP_DIR)
                       if re.fullmatch(r"library_\d{4}-\d{2}-\d{2}\.json", f))
        while len(files) > max(1, int(keep)):
            os.remove(os.path.join(DAILY_BACKUP_DIR, files.pop(0)))
    except Exception as e:
        log_event("backup", "cleanup", "fail", f"{type(e).__name__}: {e}", logging.WARNING)


def ensure_daily_backup(force=False):
    """今天还没有自动备份就补一份；失败时返回 None，并且不触发任何清理。"""
    try:
        if not os.path.exists(LIB_PATH):
            return None
        ensure_dirs()
        dst = daily_backup_path()
        if os.path.exists(dst) and not force:
            return dst
        with open(LIB_PATH, "rb") as f:
            raw = f.read()
        json.loads(raw.decode("utf-8"))          # 只备份能解析的内容
        atomic_write_bytes(dst, raw)
        log_event("backup", "daily", "ok", os.path.basename(dst))
        cleanup_daily()
        return dst
    except Exception as e:
        log_event("backup", "daily", "fail", f"{type(e).__name__}: {e}", logging.WARNING)
        return None


def snapshot_before_restore(tag="恢复"):
    """恢复/撤销前的安全快照，独立目录，不参与自动清理。失败返回 None。"""
    if not os.path.exists(LIB_PATH):
        return None
    try:
        ensure_dirs()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dst = os.path.join(PRE_RESTORE_DIR, f"{tag}前_{stamp}.json")
        with open(LIB_PATH, "rb") as f:
            raw = f.read()
        atomic_write_bytes(dst, raw)
        log_event("backup", "pre-restore", "ok", os.path.basename(dst))
        return dst
    except Exception as e:
        log_event("backup", "pre-restore", "fail", f"{type(e).__name__}: {e}", logging.ERROR)
        return None


def write_snapshots():
    """写前快照列表（按时间升序），撤销就是逐步回退它们。"""
    try:
        files = [f for f in os.listdir(BACKUP_DIR)
                 if re.fullmatch(r"library_\d{8}_\d{6}(?:_\d{6})?\.json", f)]
    except Exception:
        return []
    return sorted(files)


# ---------------------------------------------------------------- 备份清单 / 校验
BACKUP_KINDS = {
    "write": (BACKUP_DIR, "写前快照"),
    "daily": (DAILY_BACKUP_DIR, "每日自动备份"),
    "pre-restore": (PRE_RESTORE_DIR, "恢复前安全快照"),
}


def list_backups(limit=60):
    """三类备份的摘要清单；只读目录，不解析内容，坏了也能列出。"""
    items = []
    for kind, (folder, label) in BACKUP_KINDS.items():
        try:
            names = os.listdir(folder)
        except Exception:
            continue
        for name in names:
            if not name.endswith(".json") or not os.path.isfile(os.path.join(folder, name)):
                continue
            try:
                st = os.stat(os.path.join(folder, name))
            except Exception:
                continue
            items.append({
                "name": name, "kind": kind, "label": label, "size": st.st_size,
                "time": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    items.sort(key=lambda x: (x["time"], x["name"]), reverse=True)
    return items[:limit]


def resolve_backup(kind, name):
    """把 (类型, 文件名) 还原成磁盘路径；只允许三类目录里的 .json，挡住路径穿越。"""
    folder, _ = BACKUP_KINDS.get(kind or "write", BACKUP_KINDS["write"])
    base = os.path.basename(str(name or ""))
    if not base or not base.endswith(".json"):
        return None
    path = os.path.join(folder, base)
    if not os.path.isfile(path):
        return None
    return path


def load_backup_payload(path):
    """读取并校验备份文件，返回 (标准化档案, 统计)。不合法抛 ValueError。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    try:
        check_library(data)
        validate_audio_bindings(data)
    except ValueError as e:
        raise ValueError(str(e))
    lib = fill_library_defaults(data)
    seen, kept, dup = set(), [], 0
    for w in lib["works"]:
        wid = str(w.get("id") or "").strip()
        if wid in seen:
            dup += 1
            continue
        seen.add(wid)
        kept.append(w)
    lib["works"] = kept
    stats = {
        "works": len(kept),
        "series": len(lib.get("series") or []),
        "rated": sum(1 for w in kept if w.get("rating") is not None),
        "duplicates": dup,
        "latest": max((str((w.get("updatedAt") or w.get("createdAt") or "")) for w in kept), default=""),
    }
    return lib, stats


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
        validate_audio_bindings(data)
        # 音频按内容寻址，先校验全部待恢复文件，避免半途遇到坏文件。
        audio_files = {}
        for info in z.infolist():
            norm = info.filename.replace("\\", "/")
            if "/audio/" not in "/" + norm:
                continue
            name = norm.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[a-f0-9]{64}\.mp3", name) or info.file_size > AUDIO_LIMIT:
                raise ValueError("备份音频文件名或大小不合法")
            payload = z.read(info)
            if hashlib.sha256(payload).hexdigest() + ".mp3" != name or not is_mp3(payload):
                raise ValueError("备份音频校验失败")
            audio_files[name] = payload
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
        for name, payload in audio_files.items():
            dst = os.path.join(AUDIO_DIR, name)
            if not os.path.exists(dst):
                atomic_write_bytes(dst, payload)
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
    "hongguoduanju.com", "douyinpic.com", "byteimg.com", "metahub.space",
    "tmdb.org", "themoviedb.org", "kuangxiangit.com", "ciweimao.com",
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
    # 测试环境/离线排查时跳过探测，避免每次 bootstrap 固定等待
    if os.environ.get("GRDAG_SKIP_PROXY_DETECT"):
        return _proxy_cache["value"]
    try:
        lib = load_library()
        settings = lib.get("settings", {})
    except LibraryCorrupt:
        # 档案损坏时不去探测代理：bootstrap 仍要能打开恢复界面
        return _proxy_cache["value"]
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
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"


def _image_size(body):
    """读图片像素尺寸（PNG/JPEG/WebP/GIF），只用于封面清晰度校验。失败返回 None。"""
    if not body:
        return None
    try:
        if body[:8] == b"\x89PNG\r\n\x1a\n" and len(body) >= 24:
            w, h = struct.unpack(">II", body[16:24])
            return (w, h) if w and h else None
        if body[:2] == b"\xff\xd8":
            i, n = 2, len(body)
            while i + 4 <= n:
                if body[i] != 0xFF:
                    i += 1
                    continue
                marker = body[i + 1]
                if marker == 0xFF:
                    i += 1
                    continue
                if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = struct.unpack(">H", body[i + 2:i + 4])[0]
                if seg < 2:
                    return None
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    if i + 9 > n:
                        return None
                    h, w = struct.unpack(">HH", body[i + 5:i + 9])
                    return (w, h) if w and h else None
                if marker == 0xDA:
                    return None
                i += 2 + seg
            return None
        if body[:4] == b"RIFF" and body[8:12] == b"WEBP" and len(body) >= 25:
            chunk = body[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(body[24:27], "little") + 1
                h = int.from_bytes(body[27:30], "little") + 1
                return (w, h)
            if chunk == b"VP8 ":
                w = struct.unpack("<H", body[26:28])[0] & 0x3FFF
                h = struct.unpack("<H", body[28:30])[0] & 0x3FFF
                return (w, h) if w and h else None
            if chunk == b"VP8L":
                v = int.from_bytes(body[21:25], "little")
                return ((v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1)
            return None
        if body[:6] in (b"GIF87a", b"GIF89a") and len(body) >= 10:
            w, h = struct.unpack("<HH", body[6:10])
            return (w, h) if w and h else None
    except Exception:
        return None
    return None


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
    candidates = [url]
    host = (urlparse(url).hostname or "").lower()
    if host in ("image.tmdb.org", "media.themoviedb.org") and "/t/p/original/" in url:
        # original 偶发超时/被 CDN 拒绝时，回退到同图 w500；不改变其他来源的图片规则。
        candidates.append(url.replace("/t/p/original/", "/t/p/w500/", 1))
    body = None
    for candidate in candidates:
        body = _download_image(candidate, referer=referer, timeout=timeout, want_proxy=proxy)
        if body:
            url = candidate
            break
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


def _bangumi_fetch_type(keyword, t):
    """查 Bangumi 某一 type 的搜索结果；请求失败时直接抛出，由调用方决定降级。"""
    url = ("https://api.bgm.tv/search/subject/" + quote(keyword) +
           f"?type={t}&responseGroup=large&max_results=10")
    j = http_json(url, headers={"User-Agent": UA_BGM}, proxy=resolve_proxy(), timeout=8)
    return j.get("list") or []


_TITLE_STRIP_RE = re.compile(
    r"[\s\u3000…·・:：;；,，.。!！?？/\\|'\"“”‘’()（）\[\]【】<>《》+＋~～*＊#＃&＆%％\-—–_]+")


def _norm_title(text):
    """标题标准化：全半角统一、去空白和标点，只留可比较的字词。"""
    s = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return _TITLE_STRIP_RE.sub("", s)


def _query_year(keyword):
    m = re.search(r"(19\d{2}|20\d{2})", keyword or "")
    return m.group(1) if m else ""


def _valid_year(value):
    y = str(value or "")
    return y if re.fullmatch(r"(19|20)\d{2}", y) else ""


def _bangumi_rank(items, keyword):
    """按标题相关度排序；标题优先级高于资料完整度，完全并列时保留原始顺序。"""
    nk = _norm_title(keyword)
    qy = _query_year(keyword)
    ranked = []
    for idx, it in enumerate(items):
        nt = _norm_title(it.get("title"))
        ratio = difflib.SequenceMatcher(None, nk, nt).ratio() if (nk and nt) else 0.0
        if nt and nt == nk:
            tier = 0                      # 标准化后完全一致
        elif nk and nk in nt:
            tier = 1                      # 标题包含搜索词
        elif nt and len(nt) >= 2 and nt in nk:
            tier = 2                      # 搜索词包含标题
        elif ratio >= 0.5:
            tier = 3                      # 模糊匹配
        else:
            tier = 4
        year_pen = 0
        if qy:
            iy = _valid_year(it.get("year"))
            year_pen = 0 if iy == qy else (1 if iy else 0.5)
        # 搜索接口不返回简介 / infobox，这里只能用封面和有效年份判断资料完整度
        comp_pen = (0 if it.get("cover") else 1) + (0 if _valid_year(it.get("year")) else 1)
        ranked.append(((tier, round(1 - ratio, 3), year_pen, comp_pen, idx), it))
    ranked.sort(key=lambda pair: pair[0])
    return [it for _, it in ranked]


def bangumi_search(keyword, category):
    bt = CATEGORIES.get(category, {}).get("bangumi_type", 1)
    # 影视剧同时查 type=6（三次元）和 type=2（动画），其余分类保持单 type 行为
    types = [6, 2] if category == "movie" else [bt]
    out, seen = [], set()
    ok_count, errors = 0, []
    for t in types:
        try:
            items = _bangumi_fetch_type(keyword, t)
            ok_count += 1
        except Exception as e:
            errors.append(e)
            continue
        for it in items:
            sid = it.get("id")
            if sid is None or sid in seen:
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
    # 一组失败、另一组成立（哪怕为空）时照常返回；两组都失败才抛错，交给现有错误处理
    if ok_count == 0 and errors:
        raise errors[0]
    if category == "movie":
        out = _bangumi_rank(out, keyword)
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


# ---------------------------------------------------------------- 源：Cinemeta
CINEMETA_BASE = "https://v3-cinemeta.strem.io"
CINEMETA_IMAGE_BASE = "https://images.metahub.space"
CINEMETA_ID_RE = re.compile(r"tt\d{5,}")


def _cinemeta_get_json(url, timeout=12):
    """优先走当前代理，代理失败时再直连；两者都失败才抛错。"""
    proxy = resolve_proxy()
    try:
        return http_json(url, proxy=proxy, timeout=timeout)
    except Exception:
        if proxy:
            return http_json(url, proxy=None, timeout=timeout)
        raise


def _cinemeta_year(value):
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return m.group(0) if m else ""


def _cinemeta_list(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _cinemeta_search_type(kind, keyword, timeout=12):
    url = (f"{CINEMETA_BASE}/catalog/{kind}/top/search="
           + quote(keyword, safe="") + ".json")
    j = _cinemeta_get_json(url, timeout=timeout)
    return j.get("metas") or []


def _cinemeta_rank(items, keyword, counts=None):
    """本地相关性排序：精确标题 > 标题包含搜索词 > 搜索词包含标题 > 模糊 > 其他。

    Cinemeta 只有英文标题，中文查询通常无法做标题相似度，因此额外用“单一类型强命中”
    作为同档内的加权：某一类型只返回 1 条、另一类型返回多条时，优先那 1 条。
    例如中文搜《绝命毒师》时，series 只有 Breaking Bad，movie 却有多条无关结果。
    """
    qn = _norm_title(keyword)
    qy = _query_year(keyword)
    counts = counts or {}
    ranked = []
    for idx, it in enumerate(items):
        nt = _norm_title(it.get("title"))
        ratio = difflib.SequenceMatcher(None, qn, nt).ratio() if qn and nt else 0
        if nt and qn and nt == qn:
            tier = 0
        elif nt and qn and qn in nt:
            tier = 1
        elif nt and qn and nt in qn:
            tier = 2
        elif ratio >= 0.5:
            tier = 3
        else:
            tier = 4
        kind = (it.get("ref") or {}).get("kind")
        other = "series" if kind == "movie" else "movie"
        type_pen = 0
        if kind and counts.get(kind) == 1 and counts.get(other, 0) > 1:
            type_pen = 0
        elif other and counts.get(other) == 1 and counts.get(kind, 0) > 1:
            type_pen = 0.5
        year_pen = 0
        if qy:
            iy = _valid_year(it.get("year"))
            year_pen = 0 if iy == qy else (1 if iy else 0.5)
        ranked.append(((tier, type_pen, round(1 - ratio, 3), year_pen, idx), it))
    ranked.sort(key=lambda pair: pair[0])
    return [it for _, it in ranked]


def cinemeta_search(keyword, category):
    """Cinemeta 影视搜索：影视剧分类同时查 movie 和 series，保留真实 IMDb ID。"""
    if category != "movie":
        return []
    out, seen, errors = [], set(), []
    counts = {}
    ok_count = 0
    for kind in ("movie", "series"):
        try:
            metas = _cinemeta_search_type(kind, keyword)
            ok_count += 1
            counts[kind] = len(metas)
        except Exception as e:
            errors.append(e)
            continue
        for it in metas:
            tt = str(it.get("imdb_id") or it.get("id") or "").strip()
            if not CINEMETA_ID_RE.fullmatch(tt):
                continue
            if it.get("type") and it.get("type") != kind:
                continue
            title = str(it.get("name") or "").strip()
            if not title or tt in seen:
                continue
            seen.add(tt)
            year = _cinemeta_year(it.get("releaseInfo") or it.get("year"))
            poster = it.get("poster") or f"{CINEMETA_IMAGE_BASE}/poster/small/{tt}/img"
            out.append({
                "title": title,
                "subtitle": "",
                "year": year,
                "cover": image_proxy_url(poster),
                "meta": ("电影" if kind == "movie" else "剧集") + (f" · {year}" if year else ""),
                "ref": {"source": "cinemeta", "id": tt, "kind": kind, "title": title,
                        "year": year, "poster": poster},
            })
    # 一组失败、另一组有结果时照常返回；两组都失败才抛错，交给 /api/search 的现有错误处理。
    if ok_count == 0 and errors:
        raise errors[0]
    return _cinemeta_rank(out, keyword, counts)[:20]


def _cinemeta_poster(tt, timeout=8):
    """下载并校验 Cinemeta 海报；original 失败时回退 large。返回实际尺寸。"""
    for label in ("original", "large"):
        url = f"{CINEMETA_IMAGE_BASE}/poster/{label}/{tt}/img"
        body = _download_image(url, referer=f"{CINEMETA_BASE}/", timeout=timeout, want_proxy=False)
        if not body:
            body = _download_image(url, referer=f"{CINEMETA_BASE}/", timeout=timeout, want_proxy=True)
        if not body:
            continue
        size = _image_size(body)
        if size:
            return {"url": url, "width": size[0], "height": size[1], "quality": label}
    return None


def cinemeta_draft(ref):
    tt = str(ref.get("id") or ref.get("imdb_id") or "").strip()
    if not CINEMETA_ID_RE.fullmatch(tt):
        raise ValueError("无效的 IMDb ID")
    kind = ref.get("kind") or ref.get("type") or "movie"
    if kind not in ("movie", "series"):
        kind = "movie"
    try:
        j = _cinemeta_get_json(f"{CINEMETA_BASE}/meta/{kind}/{tt}.json")
    except Exception:
        if kind != "movie":
            raise
        j = _cinemeta_get_json(f"{CINEMETA_BASE}/meta/series/{tt}.json")
        kind = "series"
    meta = j.get("meta") or {}
    if not meta:
        raise RuntimeError("Cinemeta 未返回详情")
    title = str(meta.get("name") or ref.get("title") or "").strip()
    if not title:
        raise RuntimeError("Cinemeta 详情缺少标题")

    genres = _cinemeta_list(meta.get("genres") or meta.get("genre"))
    directors = _cinemeta_list(meta.get("director"))
    writers = _cinemeta_list(meta.get("writer"))
    cast = _cinemeta_list(meta.get("cast"))
    creators = []
    if directors:
        creators.append({"role": "导演", "name": "、".join(directors[:8])})
    if writers:
        creators.append({"role": "编剧", "name": "、".join(writers[:8])})
    if cast:
        creators.append({"role": "主演", "name": "、".join(cast[:8])})

    infobox = []

    def add_info(key, value):
        value = to_text(value).strip() if value not in (None, "", []) else ""
        if value:
            infobox.append({"key": key, "value": value})

    add_info("条目类型", "电影" if kind == "movie" else "剧集")
    if genres:
        add_info("类型", "、".join(genres))
    add_info("国家/地区", meta.get("country"))
    add_info("时长", meta.get("runtime"))
    add_info("上映/首播", str(meta.get("released") or "")[:10] or meta.get("releaseInfo"))
    add_info("状态", meta.get("status"))
    add_info("IMDb 评分", meta.get("imdbRating"))
    add_info("获奖", meta.get("awards"))
    add_info("IMDb ID", tt)
    add_info("TMDB ID", meta.get("moviedb_id"))
    add_info("TVDB ID", meta.get("tvdb_id"))

    rating = None
    if meta.get("imdbRating") not in (None, ""):
        try:
            rating = round(float(meta.get("imdbRating")), 1)
        except Exception:
            rating = None

    poster = _cinemeta_poster(tt)
    poster_url = poster["url"] if poster else f"{CINEMETA_IMAGE_BASE}/poster/original/{tt}/img"
    draft = {
        "title": title,
        "originalTitle": "",
        "aliases": [],
        "year": _cinemeta_year(meta.get("year") or meta.get("releaseInfo") or meta.get("released")),
        "coverUrl": poster_url,
        "previewUrl": image_proxy_url(poster_url),
        "coverProxy": True,
        "coverReferer": f"{CINEMETA_BASE}/",
        "summary": strip_html(meta.get("description") or ""),
        "tags": genres,
        "creators": creators,
        "infobox": infobox,
        "ratingRef": rating,
        "ratingMeta": {"source": "IMDb"},
        "source": {"name": "cinemeta", "label": "Cinemeta",
                   "url": f"https://www.imdb.com/title/{tt}/", "id": tt},
        "extra": {"type": kind, "status": meta.get("status"),
                  "videos": len(meta.get("videos") or [])},
    }
    if poster:
        draft["coverWidth"] = poster["width"]
        draft["coverHeight"] = poster["height"]
        draft["coverNote"] = (f"Cinemeta {poster['quality']} {poster['width']}×{poster['height']}"
                              + ("（original 回退）" if poster["quality"] != "original" else ""))
    else:
        draft["coverNote"] = "Cinemeta 封面下载校验失败，保留 original 地址"
    return draft


# ---------------------------------------------------------------- 源：豆瓣
DOUBAN_POSTER_MIN_WIDTH = 300


def _douban_large_poster(pic, timeout=8):
    """豆瓣电影海报：s_ratio_poster 换成 l_ratio_poster，并验证真实像素。

    只做这一处 URL 规格替换，不访问详情页；失败/不是图片/宽度不足都返回 None。
    """
    pic = (pic or "").strip()
    if "s_ratio_poster" not in pic:
        return None
    large = pic.replace("s_ratio_poster", "l_ratio_poster")
    try:
        status, body, _, _ = http_get(
            large, headers={"Referer": "https://movie.douban.com/", "Accept": "image/*"}, timeout=timeout)
        if status != 200 or not body or len(body) < 2000:
            return None
        size = _image_size(body)
        if not size or size[0] < DOUBAN_POSTER_MIN_WIDTH:
            return None
        return {"url": large, "width": size[0], "height": size[1]}
    except Exception:
        return None


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
    is_book = ref.get("kind") == "book"
    large = None
    if pic and not is_book:
        # 电影海报只把 s_ratio_poster 换成 l_ratio_poster，验证不过就保留原图。
        large = _douban_large_poster(pic)
    if pic and "/view/subject/s/" in pic:
        pic_large = pic.replace("/view/subject/s/", "/view/subject/l/")
    else:
        pic_large = (large or {}).get("url") or pic
    draft = {
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
    if large:
        draft["coverWidth"] = large["width"]
        draft["coverHeight"] = large["height"]
        draft["coverNote"] = f"高清海报 {large['width']}×{large['height']}"
    return draft


# ---------------------------------------------------------------- 源：微信读书
WEREAD_COVER_MIN_WIDTH = 300


def _weread_cover_key(cover_url):
    """从 s_ 封面名推出对应 t8_ 封面的键，例如 s_yuewen_834464.jpg -> yuewen_834464。"""
    try:
        base = os.path.basename(urlparse(cover_url or "").path)
        stem = os.path.splitext(base)[0]
        return stem[2:] if stem.startswith("s_") else stem
    except Exception:
        return ""


def _verify_weread_cover(url, timeout=8):
    """下载并确认返回的确是图片，且宽度达到 WEREAD_COVER_MIN_WIDTH。"""
    try:
        status, body, _, _ = http_get(
            url, headers={"Referer": "https://weread.qq.com/", "Accept": "image/*"}, timeout=timeout)
        if status != 200 or not body or len(body) < 2000:
            return None
        size = _image_size(body)
        if not size or size[0] < WEREAD_COVER_MIN_WIDTH:
            return None
        return {"url": url, "width": size[0], "height": size[1]}
    except Exception:
        return None


def _weread_large_cover(deep_link, small_cover="", timeout=8):
    """从 book-detail 页提取 t8_ 大封面并校验；任何失败都返回 None，不影响草稿。"""
    link = (deep_link or "").strip()
    try:
        u = urlparse(link)
        if u.scheme not in ("http", "https"):
            return None
        if (u.hostname or "").lower() not in ("weread.qq.com", "www.weread.qq.com"):
            return None
        if "/book-detail" not in (u.path or ""):
            return None
        status, body, _, _ = http_get(link, headers={"Referer": "https://weread.qq.com/"}, timeout=timeout)
        if status != 200 or not body:
            return None
        html = body.decode("utf-8", "ignore")
        html = html.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
        found = []
        for m in re.finditer(r"https?://[^\"'<>\\\s)]+?/t8_[^\"'<>\\\s)]+?\.(?:jpg|jpeg|png|webp)", html, re.I):
            cand = _html.unescape(m.group(0))
            if cand not in found:
                found.append(cand)
        if not found:
            return None
        key = _weread_cover_key(small_cover).lower()
        if key:
            for cand in found:
                base = os.path.basename(urlparse(cand).path).lower()
                if base.startswith("t8_" + key):
                    return _verify_weread_cover(cand, timeout=timeout)
            # 有 s_ 基准名但对不上 t8_，宁可退回缩略图，也不拿别的图冒充封面。
            return None
        if len(found) == 1:
            return _verify_weread_cover(found[0], timeout=timeout)
    except Exception:
        return None
    return None


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
    if placeholder:
        cover = ""
    # 搜索接口给的是 s_ 缩略图（约 70px 宽）。详情页里存在同名 t8_ 大图，
    # 抓不到/校验不过就静默回退到 s_，绝不因为封面失败影响资料导入。
    large = None
    if cover:
        large = _weread_large_cover(info.get("deepLink") or "", cover)
    if large:
        cover = large["url"]
    rating = round((info.get("newRating") or 0) / 100, 1) if info.get("newRating") else None
    infobox = []
    for k, label in [("author", "作者"), ("publisher", "出版社"), ("newRatingCount", "评价人数")]:
        v = info.get(k)
        if v not in (None, "", 0):
            infobox.append({"key": label, "value": str(v)})
    if info.get("finished") in (0, 1):
        infobox.append({"key": "连载状态", "value": "已完结" if info.get("finished") == 1 else "连载中"})
    draft = {
        "title": clean_weread_title(info.get("title") or ""),
        "originalTitle": info.get("title") or "",
        "year": "",
        "coverUrl": cover,
        "coverReferer": "https://weread.qq.com/",
        "summary": strip_html(info.get("intro")),
        "tags": [],
        "creators": [{"role": "作者", "name": info.get("author")}] if info.get("author") else [],
        "infobox": infobox,
        "ratingRef": rating,
        "ratingMeta": {"votes": info.get("newRatingCount")},
        "source": {"name": "weread", "label": "微信读书", "url": info.get("deepLink") or "", "id": str(info.get("bookId") or "")},
    }
    if large:
        draft["coverWidth"] = large["width"]
        draft["coverHeight"] = large["height"]
        draft["coverNote"] = f"高清封面 {large['width']}×{large['height']}"
    elif cover:
        draft["coverNote"] = "微信读书缩略图（详情页高清图未取到）"
    return draft


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


def _fanqie_decode_image_url(value):
    """还原番茄页面里的 HTML 实体和 JSON 转义斜杠。"""
    if not isinstance(value, str):
        return ""
    value = _html.unescape(value).strip()
    return value.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")


def _fanqie_cover_candidates(txt, title):
    """按可信度收集番茄书籍封面；排除详情页里的作者头像。"""
    candidates = []

    def add(url):
        url = _fanqie_decode_image_url(url)
        if not url.startswith(("http://", "https://")):
            return
        if "-novel-sign" not in url and "p3-reading-sign" not in url:
            return
        if url not in candidates:
            candidates.append(url)

    # 1) JSON-LD 的 image 与书名直接关联，是主封面最可靠的来源。
    for raw in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                          txt, re.S | re.I):
        try:
            data = json.loads(_html.unescape(raw).strip())
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if node.get("@type") in ("NewsArticle", "Book", "CreativeWork") and node.get("image"):
                    headline = str(node.get("headline") or node.get("name") or "")
                    title_key = re.sub(r"\s+", "", title or "")
                    if not title_key or title_key in re.sub(r"\s+", "", headline):
                        images = node["image"]
                        if isinstance(images, str):
                            add(images)
                        elif isinstance(images, list):
                            for image in images:
                                add(image if isinstance(image, str) else (image or {}).get("url"))
                        elif isinstance(images, dict):
                            add(images.get("url") or images.get("contentUrl"))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)

    # 2) 页面 img 标签：保留 p9 主封面，排除 author-img / alt 含「作者」的头像。
    author_urls = set()
    for tag in re.findall(r'<img\b[^>]*>', txt, re.S | re.I):
        src = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I)
        alt = re.search(r'\balt=["\']([^"\']*)["\']', tag, re.I)
        cls = re.search(r'\bclass=["\']([^"\']*)["\']', tag, re.I)
        if not src:
            continue
        src = _fanqie_decode_image_url(src.group(1))
        alt = _html.unescape(alt.group(1)) if alt else ""
        cls = _html.unescape(cls.group(1)) if cls else ""
        if "作者" in alt or "author-img" in cls:
            author_urls.add(src)
            continue
        add(src)

    # 3) 兜底：只接受能明确排除作者头像的 p3 候选。
    for raw in re.findall(r'https://p3-reading-sign[^"\'\s<>\\]+', txt, re.I):
        url = _fanqie_decode_image_url(raw)
        if url not in author_urls:
            add(url)
    for raw in re.findall(r'https://p\d+-novel-sign[^"\'\s<>\\]+', txt, re.I):
        add(raw)
    for raw in re.findall(r'https://p\d+-reading-sign[^"\'\s<>\\]+', txt, re.I):
        url = _fanqie_decode_image_url(raw)
        if url not in author_urls:
            add(url)

    return candidates


def _pick_fanqie_cover(txt, title):
    """下载并校验番茄封面候选，优先书封，失败再回退。"""
    candidates = _fanqie_cover_candidates(txt, title)
    if not candidates:
        return ""
    candidates.sort(key=lambda u: (
        0 if re.search(r"/p9-novel-sign", u) else (1 if "-novel-sign" in u else 2),
        0 if "x-signature=" in u else 1,
        0 if "novel-pic" in u else 1,
    ))
    for url in candidates:
        try:
            body = _download_image(url, referer="https://fanqienovel.com/", timeout=10)
            if not body:
                continue
            size = _image_size(body)
            if not size:
                continue
            width, height = size
            if width < 150 or height < 200:
                continue
            return url
        except Exception:
            continue
    return ""


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
    try:
        cover = _pick_fanqie_cover(txt, title)
    except Exception:
        cover = ""
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
def validate_immersive_background(value):
    """兼容旧远程背景与保存在封面资源目录中的本地背景。"""
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("沉浸背景链接必须是 4096 字以内的网址")
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"/?covers/[A-Za-z0-9_-]+\.(?:png|jpe?g|webp|gif)", value):
        return "/" + value.lstrip("/")
    try:
        parsed = urlparse(value)
        valid = (parsed.scheme.lower() in ("http", "https") and parsed.netloc and parsed.hostname
                 and not parsed.username and not parsed.password and parsed.port != 0)
    except ValueError:
        valid = False
    if not valid or re.search(r"[\s\x00-\x1f\x7f]", value):
        raise ValueError("沉浸背景请填写完整的 HTTP 或 HTTPS 图片链接")
    return value


def download_background_image(url):
    """有界下载用户明确添加的图片直链，沿用现有代理设置。"""
    try:
        proxy = resolve_proxy()
    except Exception:
        proxy = None
    proxies = [proxy, None] if proxy else [None]
    for px in proxies:
        try:
            opener = build_opener(ProxyHandler({"http": px, "https": px} if px else {}))
            parsed = urlparse(url)
            request = Request(url, headers={"User-Agent": UA, "Accept": "image/*",
                                           "Referer": f"{parsed.scheme}://{parsed.netloc}/"})
            with opener.open(request, timeout=15) as response:
                if response.status != 200:
                    continue
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > BACKGROUND_IMAGE_LIMIT:
                    raise ValueError("沉浸图片不能超过 20 MB")
                raw = response.read(BACKGROUND_IMAGE_LIMIT + 1)
                if len(raw) > BACKGROUND_IMAGE_LIMIT:
                    raise ValueError("沉浸图片不能超过 20 MB")
                return raw
        except (HTTPError, URLError, OSError):
            continue
    raise ValueError("图片下载失败，请确认是可访问的图片直链后重试")


def save_immersive_image(value):
    url = validate_immersive_background(value)
    if not url or url.startswith("/covers/"):
        raise ValueError("请填写完整的 HTTP 或 HTTPS 图片直链")
    raw = download_background_image(url)
    if not raw or len(raw) > BACKGROUND_IMAGE_LIMIT:
        raise ValueError("沉浸图片为空或超过 20 MB")
    size = _image_size(raw)
    if not size:
        raise ValueError("链接没有返回有效的 PNG、JPEG、WebP 或 GIF 图片")
    name = "background_" + hashlib.sha256(raw).hexdigest() + _image_ext(raw, url)
    with _lock:
        load_library()  # 下载期间档案损坏时也不能继续写入资源。
        ensure_dirs()
        path = os.path.join(COVER_DIR, name)
        if not os.path.exists(path):
            atomic_write_bytes(path, raw)
        else:
            os.utime(path, None)
    return {"url": "/covers/" + name, "width": size[0], "height": size[1], "bytes": len(raw)}


def save_uploaded_immersive_image(raw):
    """Validate and save a locally selected or pasted image without trusting its filename or MIME type."""
    if not raw or len(raw) > BACKGROUND_IMAGE_LIMIT:
        raise ValueError("沉浸图片为空或超过 20 MB")
    size = _image_size(raw)
    if not size:
        raise ValueError("文件不是有效的 PNG、JPEG、WebP 或 GIF 图片")
    name = "background_" + hashlib.sha256(raw).hexdigest() + _image_ext(raw, "")
    with _lock:
        load_library()
        ensure_dirs()
        path = os.path.join(COVER_DIR, name)
        if not os.path.exists(path):
            atomic_write_bytes(path, raw)
        else:
            os.utime(path, None)
    return {"url": "/covers/" + name, "width": size[0], "height": size[1], "bytes": len(raw)}


def add_images_to_zip(archive, lib):
    """封面与本地沉浸原图一起迁移；相同资源只打包一次。"""
    paths = set()
    for item in lib.get("works", []) + lib.get("series", []):
        cover = (item.get("cover") or "").lstrip("/")
        if cover.startswith("covers/") and os.path.basename(cover) == cover[len("covers/"):]:
            paths.add(cover)
        backgrounds = item.get("immersiveBackgroundUrls")
        if not isinstance(backgrounds, list):
            backgrounds = [item.get("immersiveBackgroundUrl")]
        for value in backgrounds:
            if isinstance(value, str) and re.fullmatch(r"/?covers/[A-Za-z0-9_-]+\.(?:png|jpe?g|webp|gif)", value):
                paths.add(value.lstrip("/"))
    for relative in sorted(paths):
        path = os.path.join(COVER_DIR, os.path.basename(relative))
        if os.path.isfile(path):
            archive.write(path, relative)


def media_references(lib):
    """Track both formats of the background field, including older snapshots."""
    paths = set()
    for item in lib.get("works", []) + lib.get("series", []):
        if not isinstance(item, dict):
            continue
        values = [item.get("cover"), item.get("immersiveBackgroundUrl")]
        if isinstance(item.get("immersiveBackgroundUrls"), list):
            values.extend(item["immersiveBackgroundUrls"])
        if isinstance(item.get("bgm"), dict):
            values.append(item["bgm"].get("src"))
        for value in values:
            if not isinstance(value, str):
                continue
            path = unquote(urlparse(value.strip()).path).lstrip("/").lower()
            if re.fullmatch(r"(?:covers|audio)/[^/\\]+", path):
                paths.add(path)
    return paths


def media_directory(path):
    """Never scan or stage through a symbolic link or Windows junction."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"无法安全使用目录：{os.path.basename(path)}")
    return True


def scan_unused_media():
    # The settings list is capped; all restorable snapshots must protect their media.
    try:
        with open(LIB_PATH, "r", encoding="utf-8") as f:
            lib = json.load(f)
        check_library(lib)
        active = media_references(lib)
    except (OSError, ValueError):
        raise ValueError("无法检查主档案，未移动任何文件") from None
    backups = set()
    for folder, label in BACKUP_KINDS.values():
        if not media_directory(folder):
            continue
        with os.scandir(folder) as entries:
            for entry in entries:
                if not entry.name.endswith(".json") or not entry.is_file():
                    continue
                try:
                    with open(entry.path, "r", encoding="utf-8") as f:
                        lib = json.load(f)
                    check_library(lib)
                    backups.update(media_references(lib))
                except (OSError, ValueError):
                    raise ValueError(f"无法检查{label}「{entry.name}」，未移动任何文件") from None
    candidates = []
    counts = {"backupOnly": 0, "recent": 0}
    cutoff = time.time() - MEDIA_GRACE_SECONDS
    for kind, folder, pattern in (
        ("covers", COVER_DIR, r"(?:[0-9a-f]{16}|background_[0-9a-f]{64})\.(?:jpe?g|png|webp|gif)"),
        ("audio", AUDIO_DIR, r"[0-9a-f]{64}\.mp3"),
    ):
        if not media_directory(folder):
            continue
        with os.scandir(folder) as entries:
            for entry in entries:
                if not re.fullmatch(pattern, entry.name, re.IGNORECASE):
                    continue
                info = os.lstat(entry.path)
                if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    continue
                key = f"{kind}/{entry.name.lower()}"
                if key in active:
                    continue
                if key in backups:
                    counts["backupOnly"] += 1
                elif info.st_mtime > cutoff:
                    counts["recent"] += 1
                else:
                    candidates.append((kind, entry.name, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino))
    candidates.sort()
    token = hashlib.sha256(json.dumps(candidates).encode("ascii")).hexdigest()
    return candidates, counts, token


def stage_unused_media(candidates):
    # A new batch keeps filenames and provenance without overwriting earlier batches.
    if not media_directory(MEDIA_STAGING_DIR):
        os.mkdir(MEDIA_STAGING_DIR)
    batch = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    dest = os.path.join(MEDIA_STAGING_DIR, batch)
    os.mkdir(dest)
    folders = {"covers": COVER_DIR, "audio": AUDIO_DIR}
    for kind in {row[0] for row in candidates}:
        os.mkdir(os.path.join(dest, kind))
    moved = size = 0
    skipped = []
    for kind, name, length, mtime, ctime, inode in candidates:
        source = os.path.join(folders[kind], name)
        try:
            info = os.lstat(source)
            actual = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or actual != (length, mtime, ctime, inode):
                skipped.append(name)
                continue
            os.rename(source, os.path.join(dest, kind, name))
            moved += 1
            size += length
        except OSError:
            skipped.append(name)
    return {"moved": moved, "bytes": size, "skipped": skipped, "folder": dest}


def apply_immersive_background(target, payload):
    if "immersiveBackgroundUrls" in payload or "immersiveBackgroundUrl" in payload:
        raw = payload.get("immersiveBackgroundUrls")
        if raw is None:
            raw = [payload.get("immersiveBackgroundUrl", "")]
        if not isinstance(raw, list) or len(raw) > 20:
            raise ValueError("沉浸背景最多添加 20 张图片")
        values = []
        for item in raw:
            value = validate_immersive_background(item)
            if value and value not in values:
                values.append(value)
        if values:
            target["immersiveBackgroundUrls"] = values
            target["immersiveBackgroundUrl"] = values[0]
        else:
            target.pop("immersiveBackgroundUrls", None)
            target.pop("immersiveBackgroundUrl", None)


def validate_bgm(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("背景音乐配置格式不正确")
    src, title, artist = value.get("src", ""), value.get("title", ""), value.get("artist", "")
    if (not isinstance(src, str) or not isinstance(title, str) or not isinstance(artist, str)
            or len(title) > 200 or len(artist) > 200):
        raise ValueError("背景音乐链接、曲名或演唱者格式不正确（曲名和演唱者各最多 200 字）")
    src = src.strip()
    if not src:
        return None
    if not re.fullmatch(r"/audio/[a-f0-9]{64}\.mp3", src):
        try:
            parsed = urlparse(src)
            valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or len(src) > 4096 or re.search(r"[\s\x00-\x1f\x7f]", src):
            raise ValueError("背景音乐请使用本地导入的 MP3 或完整的 HTTPS 音频直链")
    return {"src": src, "title": title.strip() or "背景音乐", "artist": artist.strip()}


def apply_bgm(target, payload):
    if "bgm" in payload:
        value = validate_bgm(payload["bgm"])
        if value:
            target["bgm"] = value
        else:
            target.pop("bgm", None)


def validate_audio_bindings(lib):
    if not isinstance(lib.get("series", []), list):
        raise ValueError("备份 series 格式不正确")
    for item in lib["works"] + lib.get("series", []):
        if not isinstance(item, dict):
            raise ValueError("备份条目格式不正确")
        validate_bgm(item.get("bgm"))


def is_mp3(raw):
    """识别 ID3 后的 MPEG 音频帧头；实际解码由浏览器完成。"""
    if not raw or len(raw) > AUDIO_LIMIT:
        return False
    start = 0
    if raw[:3] == b"ID3":
        if len(raw) < 10 or any(n > 127 for n in raw[6:10]):
            return False
        start = 10 + sum(n << shift for n, shift in zip(raw[6:10], (21, 14, 7, 0)))
    for i in range(start, min(len(raw) - 3, start + 65536)):
        a, b, c = raw[i:i + 3]
        if a == 255 and b & 224 == 224 and (b >> 3) & 3 != 1 and (b >> 1) & 3 == 1 and (c >> 4) not in (0, 15) and (c >> 2) & 3 != 3:
            return True
    return False


def add_audio_to_zip(archive, lib, all_files=False):
    names = set(os.listdir(AUDIO_DIR)) if all_files and os.path.isdir(AUDIO_DIR) else {
        (item.get("bgm") or {}).get("src", "").rsplit("/", 1)[-1]
        for item in lib.get("works", []) + lib.get("series", [])
        if isinstance(item.get("bgm"), dict) and (item["bgm"].get("src") or "").startswith("/audio/")}
    for name in sorted(names):
        if re.fullmatch(r"[a-f0-9]{64}\.mp3", name):
            path = os.path.join(AUDIO_DIR, name)
            if os.path.isfile(path):
                archive.write(path, "audio/" + name)


def normalize_work(payload, existing=None):
    # 在归一化其他字段和下载封面前验证；未提交时保留已有值。
    if "immersiveBackgroundUrl" in payload or "immersiveBackgroundUrls" in payload:
        apply_immersive_background({}, payload)
    apply_bgm({}, payload)
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
    apply_immersive_background(w, payload)
    apply_bgm(w, payload)
    w["createdAt"] = w.get("createdAt") or now_iso()
    w["updatedAt"] = now_iso()
    w.setdefault("rating", None)
    w.setdefault("ratingHistory", [])
    w.setdefault("experiences", [])
    return w


# ---------------------------------------------------------------- TMDB 剪贴板导入
TMDB_JSON_LIMIT = 120000
TMDB_IMPORT_MODES = ("merge", "overwrite")
TMDB_DETAIL_RE = re.compile(
    r"^https://(?:www\.)?themoviedb\.org/(movie|tv)/(\d+)(?:-[^/?#]*)?/?(?:\?language=zh-CN)?$",
    re.I,
)
TMDB_IMAGE_HOSTS = ("image.tmdb.org", "media.themoviedb.org")
TMDB_INFOBOX_KEYS = {
    "条目类型", "首播日期", "上映日期", "国家/地区", "集数", "时长",
    "IMDb ID", "TMDB ID", "评分", "评分人数",
}


def _tmdb_text(value, max_len, label, required=False):
    """校验剪贴板里的文本字段，去掉 HTML 并限制长度。"""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本")
    value = strip_html(value).strip()
    if len(value) > max_len:
        raise ValueError(f"{label}过长（最多 {max_len} 字）")
    if required and not value:
        raise ValueError(f"{label}不能为空")
    return value


def _tmdb_detail_info(url):
    """只接受 TMDB 的 movie/tv 数字 ID 详情页，返回规范化地址。"""
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("缺少 TMDB 来源地址")
    if len(raw) > 500:
        raise ValueError("TMDB 来源地址过长")
    m = TMDB_DETAIL_RE.fullmatch(raw)
    if not m:
        raise ValueError("来源地址不是合法的 TMDB movie/tv 详情页")
    kind = m.group(1).lower()
    tid = m.group(2)
    if not tid.isdigit() or int(tid) <= 0:
        raise ValueError("TMDB 数字 ID 不合法")
    canonical = f"https://www.themoviedb.org/{kind}/{tid}?language=zh-CN"
    return kind, tid, canonical


def _tmdb_cover_url(value):
    """封面只允许 TMDB 官方图片域名，避免粘贴内容把服务端变成任意 URL 下载器。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("封面地址必须是文本")
    raw = value.strip()
    if not raw:
        return ""
    if len(raw) > 800:
        raise ValueError("封面地址过长")
    try:
        u = urlparse(raw)
    except Exception:
        raise ValueError("封面地址不合法")
    if u.scheme != "https" or (u.hostname or "").lower() not in TMDB_IMAGE_HOSTS:
        raise ValueError("封面必须来自 TMDB 官方图片域名")
    if not u.path.startswith("/t/p/") or u.query or u.fragment:
        raise ValueError("封面地址不是 TMDB 图片路径")
    return raw


def _tmdb_string_list(value, max_items, max_len, label):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label}必须是列表")
    if len(value) > max_items:
        raise ValueError(f"{label}条目过多")
    out = []
    for item in value:
        text = _tmdb_text(item, max_len, label)
        if text and text not in out:
            out.append(text)
    return out


def _tmdb_creators(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("创作者必须是列表")
    if len(value) > 60:
        raise ValueError("创作者条目过多")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("创作者条目结构不正确")
        role = _tmdb_text(item.get("role"), 20, "创作者角色") or "创作者"
        name = _tmdb_text(item.get("name"), 200, "创作者姓名", required=True)
        if any(c.get("role") == role and c.get("name") == name for c in out):
            continue
        out.append({"role": role, "name": name})
    return out


def _tmdb_infobox(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("infobox 必须是列表")
    if len(value) > 80:
        raise ValueError("infobox 条目过多")
    out = []
    keys = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("infobox 条目结构不正确")
        key = _tmdb_text(item.get("key"), 30, "infobox 键")
        val = _tmdb_text(item.get("value"), 2000, "infobox 值")
        if not key or not val:
            continue
        if key not in TMDB_INFOBOX_KEYS:
            continue
        if key in keys:
            continue
        keys.add(key)
        out.append({"key": key, "value": val})
    return out


def _tmdb_rating_ref(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("TMDB 评分格式不正确")
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise ValueError("TMDB 评分格式不正确")
    if score < 0 or score > 10:
        raise ValueError("TMDB 评分超出范围")
    return round(score, 1)


def validate_tmdb_payload(raw):
    """解析并校验 Bookmarklet 输出，返回干净、可保存的 TMDB 草稿。"""
    if isinstance(raw, dict):
        obj = raw
        try:
            size = len(json.dumps(obj, ensure_ascii=False))
        except Exception:
            size = TMDB_JSON_LIMIT + 1
        if size > TMDB_JSON_LIMIT:
            raise ValueError("粘贴内容过长")
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("请先粘贴 TMDB JSON")
        if len(text) > TMDB_JSON_LIMIT:
            raise ValueError("粘贴内容过长")
        try:
            obj = json.loads(text)
        except Exception:
            raise ValueError("JSON 格式不正确")
    else:
        raise ValueError("粘贴内容必须是 JSON 文本")
    if not isinstance(obj, dict):
        raise ValueError("JSON 顶层必须是对象")

    src = obj.get("source")
    if not isinstance(src, dict):
        raise ValueError("缺少 source 对象")
    name = str(src.get("name") or "").strip()
    if name != "tmdb":
        raise ValueError("source.name 必须是 tmdb")
    kind, tid, canonical = _tmdb_detail_info(src.get("url"))
    src_kind = str(src.get("type") or "").strip().lower()
    src_id = str(src.get("id") or "").strip()
    if src_kind and src_kind != kind:
        raise ValueError("source.type 与来源 URL 不一致")
    if src_id and src_id != tid:
        raise ValueError("source.id 与来源 URL 不一致")

    category = obj.get("category")
    if category and category != "movie":
        raise ValueError("TMDB 资料只能导入影视剧分类")

    title = _tmdb_text(obj.get("title"), 200, "标题", required=True)
    original_title = _tmdb_text(obj.get("originalTitle"), 200, "原始标题")
    year = str(obj.get("year") or "").strip()
    if year and not re.fullmatch(r"(19|20)\d{2}", year):
        raise ValueError("年份格式不正确")
    aliases = _tmdb_string_list(obj.get("aliases"), 20, 200, "别名")
    tags = _tmdb_string_list(obj.get("tags"), 40, 40, "标签")
    summary = _tmdb_text(obj.get("summary"), 20000, "简介")
    creators = _tmdb_creators(obj.get("creators"))
    infobox = _tmdb_infobox(obj.get("infobox"))
    cover_url = _tmdb_cover_url(obj.get("coverUrl"))
    rating_ref = _tmdb_rating_ref(obj.get("ratingRef"))

    return {
        "category": "movie",
        "title": title,
        "originalTitle": original_title,
        "aliases": aliases,
        "year": year,
        "tags": tags,
        "summary": summary,
        "creators": creators,
        "infobox": infobox,
        "source": {
            "name": "tmdb",
            "label": "TMDB",
            "type": kind,
            "id": tid,
            "url": canonical,
        },
        "coverUrl": cover_url,
        "previewUrl": image_proxy_url(cover_url) if cover_url else "",
        "coverReferer": canonical,
        # TMDB 图片在部分网络下直连超时，保存时允许先走本机代理再回退直连。
        "coverProxy": True,
        "ratingRef": rating_ref,
    }


def _tmdb_work_identity(work):
    src = (work or {}).get("source")
    if not isinstance(src, dict) or src.get("name") != "tmdb":
        return None
    kind = str(src.get("type") or "").strip().lower()
    tid = str(src.get("id") or "").strip()
    if kind not in ("movie", "tv") or not tid.isdigit():
        try:
            kind, tid, _ = _tmdb_detail_info(src.get("url"))
        except ValueError:
            return None
    return kind, tid


def _tmdb_work_brief(work):
    if not work:
        return None
    return {
        "id": work.get("id"),
        "title": work.get("title") or "",
        "year": work.get("year") or "",
        "category": work.get("category") or "",
        "source": {
            "name": (work.get("source") or {}).get("name") or "",
            "label": (work.get("source") or {}).get("label") or "",
            "type": (work.get("source") or {}).get("type") or "",
            "id": (work.get("source") or {}).get("id") or "",
        },
        "coverUrl": ("/" + work["cover"]).replace("//", "/") if work.get("cover") else "",
    }


def _tmdb_norm_title(value):
    return re.sub(r"\W+", "", str(value or "")).lower()


def _tmdb_find_targets(lib, draft, target_id=None):
    works = lib.get("works") or []
    target = None
    if target_id:
        target = next((w for w in works if str(w.get("id")) == str(target_id)), None)
        if not target:
            raise ValueError("要导入的作品不存在")
        if target.get("category") != "movie":
            raise ValueError("只能向影视剧作品导入 TMDB 资料")
    identity = (draft["source"]["type"], str(draft["source"]["id"]))
    match = next((w for w in works if _tmdb_work_identity(w) == identity), None)
    title_matches = []
    norm = _tmdb_norm_title(draft["title"])
    if norm:
        for w in works:
            if w.get("category") != "movie":
                continue
            if _tmdb_norm_title(w.get("title")) != norm:
                continue
            if _tmdb_work_identity(w) == identity:
                continue
            title_matches.append(w)
            if len(title_matches) >= 5:
                break
    return target, match, title_matches


def _tmdb_preview_response(lib, draft, target_id=None):
    target, match, title_matches = _tmdb_find_targets(lib, draft, target_id)
    warnings = []
    if target:
        current_identity = _tmdb_work_identity(target)
        if current_identity and current_identity != (draft["source"]["type"], str(draft["source"]["id"])):
            warnings.append("当前作品已有的 TMDB 身份与粘贴资料不一致；仅补空不会覆盖，覆盖模式会替换 TMDB 字段。")
        elif not current_identity:
            warnings.append("当前作品不是 TMDB 来源；仅补空不会覆盖，覆盖模式会把来源和资料改为 TMDB。")
    if match and (not target or match.get("id") != target.get("id")):
        warnings.append("库中已有相同 TMDB 条目，确认后会更新该作品，不会新建重复条目。")
    if title_matches and not target:
        warnings.append("存在同名但 TMDB ID 不同的作品；本次不会按标题合并，会新建独立条目。")
    action = "update" if (target or match) else "create"
    return {
        "draft": draft,
        "identity": {"type": draft["source"]["type"], "id": draft["source"]["id"]},
        "target": _tmdb_work_brief(target),
        "match": _tmdb_work_brief(match),
        "titleMatches": [_tmdb_work_brief(w) for w in title_matches],
        "action": action,
        "warnings": warnings,
    }


def _tmdb_merge_infobox(existing, incoming):
    """已有非空字段优先；只补充已有 infobox 缺失的 key。"""
    result = []
    keys = set()
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        val = str(item.get("value") or "").strip()
        if key and val:
            result.append({"key": key, "value": val})
            keys.add(key)
    for item in incoming or []:
        key = item.get("key")
        val = item.get("value")
        if key and val and key not in keys:
            result.append({"key": key, "value": val})
            keys.add(key)
    return result


def _tmdb_merge_work(work, draft):
    """已有作品只补空字段；已有封面、简介、标签、创作者、别名等均不覆盖。"""
    existing = dict(work)
    payload = dict(existing)
    payload["category"] = "movie"
    if not (existing.get("title") or "").strip():
        payload["title"] = draft["title"]
    if not (existing.get("originalTitle") or "").strip():
        payload["originalTitle"] = draft["originalTitle"]
    if not existing.get("aliases"):
        payload["aliases"] = draft["aliases"]
    if not (existing.get("year") or "").strip():
        payload["year"] = draft["year"]
    if not existing.get("tags"):
        payload["tags"] = draft["tags"]
    if not (existing.get("summary") or "").strip():
        payload["summary"] = draft["summary"]
    if not existing.get("creators"):
        payload["creators"] = draft["creators"]
    payload["infobox"] = _tmdb_merge_infobox(existing.get("infobox"), draft["infobox"])
    if not existing.get("source"):
        payload["source"] = draft["source"]
    if not existing.get("cover") and draft.get("coverUrl"):
        # payload 里如果还留着 cover=""，normalize_work() 会优先用空封面并跳过 coverUrl。
        payload.pop("cover", None)
        payload["coverUrl"] = draft["coverUrl"]
        payload["coverReferer"] = draft.get("coverReferer")
        payload["coverProxy"] = True
    return normalize_work(payload, existing=existing)


def _tmdb_overwrite_infobox(existing, incoming):
    """覆盖模式下用 TMDB 的非空 infobox 替换同名 key，保留用户自定义的其他 key。"""
    result = []
    positions = {}
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        val = str(item.get("value") or "").strip()
        if key and val:
            positions[key] = len(result)
            result.append({"key": key, "value": val})
    for item in incoming or []:
        key = str(item.get("key") or "").strip()
        val = str(item.get("value") or "").strip()
        if not key or not val:
            continue
        if key in positions:
            result[positions[key]] = {"key": key, "value": val}
        else:
            positions[key] = len(result)
            result.append({"key": key, "value": val})
    return result


def _tmdb_overwrite_work(work, draft):
    """覆盖模式：用 TMDB 的非空字段替换已有字段，保留评分、经历、系列和用户字段。"""
    existing = dict(work)
    old_cover = existing.get("cover") or ""
    payload = dict(existing)
    payload["category"] = "movie"
    payload["title"] = draft["title"]
    for field in ("originalTitle", "year", "summary"):
        incoming = draft.get(field)
        payload[field] = incoming if incoming else (existing.get(field) or "")
    for field in ("aliases", "tags", "creators"):
        incoming = draft.get(field)
        payload[field] = incoming if incoming else (existing.get(field) or [])
    payload["infobox"] = _tmdb_overwrite_infobox(existing.get("infobox"), draft["infobox"])
    payload["source"] = draft["source"]
    if draft.get("coverUrl"):
        # 覆盖封面时必须移除旧的本地 cover，否则 normalize_work() 不会下载新图。
        payload.pop("cover", None)
        payload["coverUrl"] = draft["coverUrl"]
        payload["coverReferer"] = draft.get("coverReferer")
        payload["coverProxy"] = True
    result = normalize_work(payload, existing=existing)
    # 新封面下载失败时保留旧封面，避免“覆盖”把已有图清空。
    if not result.get("cover") and old_cover:
        result["cover"] = old_cover
    return result


def _tmdb_apply_overrides(draft, overrides):
    """只接受表单里允许编辑的字段，服务端仍按同样规则复核。"""
    if not overrides:
        return draft
    if not isinstance(overrides, dict):
        raise ValueError("overrides 结构不正确")
    allowed = {"title", "originalTitle", "year", "tags", "summary", "creators", "immersiveBackgroundUrl", "immersiveBackgroundUrls", "bgm"}
    unknown = [k for k in overrides.keys() if k not in allowed]
    if unknown:
        raise ValueError("overrides 包含不允许的字段")
    if "title" in overrides:
        draft["title"] = _tmdb_text(overrides.get("title"), 200, "标题", required=True)
    if "originalTitle" in overrides:
        draft["originalTitle"] = _tmdb_text(overrides.get("originalTitle"), 200, "原始标题")
    if "year" in overrides:
        year = str(overrides.get("year") or "").strip()
        if year and not re.fullmatch(r"(19|20)\d{2}", year):
            raise ValueError("年份格式不正确")
        draft["year"] = year
    if "tags" in overrides:
        draft["tags"] = _tmdb_string_list(overrides.get("tags"), 40, 40, "标签")
    if "summary" in overrides:
        draft["summary"] = _tmdb_text(overrides.get("summary"), 20000, "简介")
    if "creators" in overrides:
        draft["creators"] = _tmdb_creators(overrides.get("creators"))
    if "immersiveBackgroundUrl" in overrides or "immersiveBackgroundUrls" in overrides:
        apply_immersive_background(draft, overrides)
    apply_bgm(draft, overrides)
    return draft


def _tmdb_first_experience(value):
    if not isinstance(value, dict):
        raise ValueError("firstExperience 结构不正确")
    status = str(value.get("status") or "planned")
    if status not in STATUS_ORDER:
        raise ValueError("firstExperience.status 不合法")
    content = _tmdb_text(value.get("content"), 2000, "第一条经历")
    date = value.get("date")
    if date:
        date = _tmdb_text(date, 10, "经历日期")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("经历日期格式不正确")
    return {"date": date or datetime.now().strftime("%Y-%m-%d"),
            "status": status, "content": content}


def import_tmdb_work(raw, target_id=None, overrides=None, rating=None, first_experience=None, mode="merge"):
    """校验并保存 TMDB 资料；mode=merge 只补空，mode=overwrite 覆盖 TMDB 字段。"""
    mode = str(mode or "merge").strip().lower()
    if mode not in TMDB_IMPORT_MODES:
        raise ValueError("导入方式不正确")
    draft = validate_tmdb_payload(raw)
    if overrides:
        draft = _tmdb_apply_overrides(draft, overrides)
    else:
        # 原始标题、年份等即使表单未提交，也保持从剪贴板校验后的值
        draft = dict(draft)
    with _lock:
        lib = load_library()
        target, match, _ = _tmdb_find_targets(lib, draft, target_id)
        existing = target or match
        if existing:
            if mode == "overwrite":
                merged = _tmdb_overwrite_work(existing, draft)
            else:
                merged = _tmdb_merge_work(existing, draft)
            # 只有用户表单明确提交才改变个人背景；资料源合并/覆盖均不能覆盖它。
            if isinstance(overrides, dict):
                apply_immersive_background(merged, overrides)
                apply_bgm(merged, overrides)
            works = lib.get("works") or []
            for i, w in enumerate(works):
                if str(w.get("id")) == str(existing.get("id")):
                    works[i] = merged
                    break
            save_library(lib)
            return "updated", merged
        work = normalize_work(dict(draft))
        if rating not in (None, ""):
            try:
                score = float(rating)
            except (TypeError, ValueError):
                raise ValueError("初始评分格式不正确")
            if score < 0 or score > 10:
                raise ValueError("初始评分超出范围")
            work["rating"] = round(score * 2) / 2
            work["ratingHistory"] = [{"date": datetime.now().strftime("%Y-%m-%d"),
                                      "score": work["rating"], "reason": "导入初评"}]
        if first_experience:
            work["experiences"] = [_tmdb_first_experience(first_experience)]
        (lib.setdefault("works", [])).append(work)
        save_library(lib)
        return "created", work


# ---------------------------------------------------------------- 优书网剪贴板导入
YOUSHU_JSON_LIMIT = 120000
YOUSHU_DETAIL_HOSTS = ("youshu.me", "www.youshu.me")
YOUSHU_COVER_SUFFIXES = ("qq.com", "byteimg.com", "yuewen.com", "qpic.cn", "kuangxiangit.com", "ciweimao.com")
YOUSHU_INFOBOX_KEYS = {
    "优书 ID", "阅读平台", "分类", "状态", "字数",
    "优书评分", "评分人数", "原书链接",
}


def _youshu_text(value, limit, label, required=False):
    if value is None:
        s = ""
    elif isinstance(value, str):
        s = value
    else:
        raise ValueError("%s格式不正确" % label)
    s = strip_html(_html.unescape(s)).strip()
    if len(s) > limit:
        s = s[:limit]
    if required and not s:
        raise ValueError("%s不能为空" % label)
    return s


def _youshu_string_list(value, limit, item_limit, label):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("%s格式不正确" % label)
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("%s格式不正确" % label)
        s = _youshu_text(item, item_limit, label)
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _youshu_creators(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("演职人员格式不正确")
    out = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("演职人员格式不正确")
        role = _youshu_text(item.get("role"), 30, "演职人员角色")
        name = _youshu_text(item.get("name"), 100, "演职人员姓名")
        if not role or not name:
            continue
        key = (role, name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"role": role, "name": name})
        if len(out) >= 30:
            break
    return out


def _youshu_infobox(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("资料表格式不正确")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("资料表格式不正确")
        key = _youshu_text(item.get("key"), 30, "资料表字段名")
        if key not in YOUSHU_INFOBOX_KEYS:
            continue
        raw = item.get("value")
        if raw is None:
            continue
        if not isinstance(raw, (str, int, float)):
            raise ValueError("资料表字段值格式不正确")
        val = _youshu_text(str(raw), 1200, "资料表字段值")
        if not val:
            continue
        out.append({"key": key, "value": val})
        if len(out) >= 20:
            break
    return out


def _youshu_detail_info(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("source.url 不能为空")
    raw = raw.strip()
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("source.url 不是合法的网址")
    if (u.hostname or "").lower() not in YOUSHU_DETAIL_HOSTS:
        raise ValueError("source.url 必须是优书网详情页")
    path = (u.path or "").rstrip("/")
    sid = ""
    if path == "/modules/article/articleinfo.php":
        ids = parse_qs(u.query).get("id") or []
        if len(ids) != 1:
            raise ValueError("优书网详情页 ID 不合法")
        sid = ids[0]
    else:
        m = re.fullmatch(r"/book/(\d+)", path)
        if m:
            sid = m.group(1)
    if not sid or not re.fullmatch(r"\d+", sid):
        raise ValueError("source.url 必须是 /book/{id} 详情页")
    return sid, "https://www.youshu.me/book/" + sid


def _youshu_cover_info(value):
    if value is None:
        return "", ""
    if not isinstance(value, str):
        raise ValueError("封面地址必须是文本")
    raw = value.strip()
    if not raw:
        return "", ""
    if len(raw) > 1600:
        return "", "封面地址过长，已忽略"
    u = urlparse(raw)
    if u.scheme != "https" or not u.hostname:
        return "", "封面地址不是 https 图片，已忽略"
    host = (u.hostname or "").lower()
    if host in YOUSHU_DETAIL_HOSTS:
        return "", "优书网占位图或详情页地址不作为封面"
    if not any(host == s or host.endswith("." + s) for s in YOUSHU_COVER_SUFFIXES):
        return "", "封面域名不在优书网支持范围，已忽略"
    if "nocover" in (u.path or "").lower():
        return "", "已识别占位图 nocover.jpg，未作为封面"
    return raw, ""


def _youshu_rating(value):
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 10:
        return None
    return round(score, 1)


def validate_youshu_payload(raw):
    """校验 Bookmarklet 生成的优书网 JSON；返回 (draft, warnings)。"""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("请先粘贴优书网书签生成的 JSON")
    if len(raw) > YOUSHU_JSON_LIMIT:
        raise ValueError("粘贴内容过长，无法导入")
    try:
        obj = json.loads(raw)
    except Exception as e:
        raise ValueError("JSON 格式不正确：%s" % e)
    if not isinstance(obj, dict):
        raise ValueError("JSON 顶层必须是对象")
    source = obj.get("source")
    if not isinstance(source, dict):
        raise ValueError("缺少 source，无法识别来源")
    if _youshu_text(source.get("name"), 30, "来源名称").lower() != "youshu":
        raise ValueError("来源不是优书网（source.name 必须为 youshu）")

    sid, canonical = _youshu_detail_info(source.get("url"))
    raw_sid = source.get("id")
    if isinstance(raw_sid, (int, float)) and not isinstance(raw_sid, bool):
        if int(raw_sid) != raw_sid:
            raise ValueError("优书网作品 ID 不合法")
        source_id = str(int(raw_sid))
    else:
        source_id = _youshu_text(raw_sid, 30, "作品 ID")
    if not source_id:
        source_id = sid
    if not re.fullmatch(r"\d+", source_id):
        raise ValueError("优书网作品 ID 不合法")
    if source_id != sid:
        raise ValueError("source.id 与详情页 URL 不一致")

    category = _youshu_text(obj.get("category"), 20, "分类")
    if category and category != "novel":
        raise ValueError("优书网资料只能导入到网文分类")
    source_type = _youshu_text(source.get("type"), 20, "来源类型")
    if source_type and source_type != "novel":
        raise ValueError("来源类型不是网文")

    title = _youshu_text(obj.get("title"), 200, "标题", required=True)
    summary = _youshu_text(obj.get("summary"), 20000, "简介")
    tags = _youshu_string_list(obj.get("tags"), 40, 40, "标签")
    creators = _youshu_creators(obj.get("creators"))
    infobox = _youshu_infobox(obj.get("infobox"))
    cover_url, cover_warning = _youshu_cover_info(obj.get("coverUrl"))
    score = _youshu_rating(obj.get("ratingRef"))
    votes = None
    for item in infobox:
        if item.get("key") == "评分人数":
            try:
                votes = int(float(item.get("value")) + 0.5)
            except (TypeError, ValueError):
                votes = None
    warnings = []
    if cover_warning:
        warnings.append(cover_warning)

    draft = {
        "category": "novel",
        "title": title,
        "originalTitle": "",
        "aliases": [],
        "year": "",
        "summary": summary,
        "tags": tags,
        "creators": creators,
        "infobox": infobox,
        "coverUrl": cover_url,
        "previewUrl": cover_url,
        "coverProxy": False,
        "coverReferer": canonical,
        "ratingRef": score,
        "source": {
            "name": "youshu",
            "label": "优书网",
            "type": "novel",
            "id": source_id,
            "url": canonical,
        },
    }
    if score is not None:
        meta = {"source": "优书网"}
        if votes is not None:
            meta["total"] = votes
        draft["ratingMeta"] = meta
    return draft, warnings


def _youshu_work_identity(work):
    src = work.get("source") if isinstance(work.get("source"), dict) else {}
    if (src.get("name") or "").strip().lower() != "youshu":
        return ""
    sid = str(src.get("id") or "").strip()
    if re.fullmatch(r"\d+", sid):
        return sid
    try:
        sid2, _ = _youshu_detail_info(src.get("url"))
        return sid2
    except Exception:
        return ""


def _youshu_work_brief(work):
    src = work.get("source") if isinstance(work.get("source"), dict) else {}
    return {
        "id": work.get("id") or "",
        "title": work.get("title") or "",
        "category": work.get("category") or "",
        "year": work.get("year") or "",
        "coverUrl": ("/" + work["cover"]).replace("//", "/") if work.get("cover") else "",
        "source": {
            "name": src.get("name") or "",
            "label": src.get("label") or SOURCE_LABELS.get(src.get("name") or "", ""),
            "id": src.get("id") or "",
            "url": src.get("url") or "",
        },
    }


def _youshu_find_targets(lib, draft, target_id):
    works = lib.get("works") or []
    target = None
    if target_id:
        target = next((w for w in works if str(w.get("id")) == str(target_id)), None)
        if target is None:
            raise ValueError("目标作品不存在")
        if target.get("category") != "novel":
            raise ValueError("目标作品不是网文")
    sid = str(draft["source"]["id"])
    match = next((w for w in works
                  if _youshu_work_identity(w) == sid and
                  (not target or str(w.get("id")) != str(target.get("id")))), None)
    nt = _norm_title(draft.get("title") or "")
    title_matches = []
    for w in works:
        if nt and _norm_title(w.get("title") or "") == nt:
            if target and str(w.get("id")) == str(target.get("id")):
                continue
            if _youshu_work_identity(w) == sid:
                continue
            title_matches.append(_youshu_work_brief(w))
            if len(title_matches) >= 5:
                break
    return target, match, title_matches


def _youshu_preview_response(lib, draft, target_id, warnings=None):
    target, match, title_matches = _youshu_find_targets(lib, draft, target_id)
    warnings = list(warnings or [])
    sid = str(draft["source"]["id"])
    if target:
        current = _youshu_work_identity(target)
        if not current:
            warnings.append("当前作品还没有优书网来源；本次只补充资料字段，不改动个人记录。")
        elif current != sid:
            warnings.append("当前作品已有其他优书网 ID（%s），请确认是否要导入这份资料。" % current)
    if match:
        warnings.append("库中已有同一优书网 ID 的作品「%s」，继续新建可能产生重复记录。"
                        % (match.get("title") or match.get("id")))
    if title_matches:
        warnings.append("库中有同名但优书 ID 不同的作品，注意避免误合并。")
    return {
        "draft": draft,
        "identity": {"source": "youshu", "id": sid, "url": draft["source"]["url"]},
        "target": _youshu_work_brief(target) if target else None,
        "match": _youshu_work_brief(match) if match else None,
        "titleMatches": title_matches,
        "action": "update" if target else ("update" if match else "create"),
        "warnings": warnings,
    }


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
    apply_immersive_background({}, payload)
    apply_bgm({}, payload)
    s = existing or {}
    s["id"] = s.get("id") or new_id("s_")
    s["name"] = (payload.get("name") or s.get("name") or "").strip()
    s["originalTitle"] = (payload.get("originalTitle", s.get("originalTitle")) or "").strip()
    kind = payload.get("kind") or s.get("kind") or "mixed"
    s["kind"] = kind if kind in SERIES_KINDS else "mixed"
    s["summary"] = (payload.get("summary", s.get("summary")) or "").strip()
    s["note"] = (payload.get("note", s.get("note")) or "").strip()
    s["tags"] = [t for t in (payload.get("tags", s.get("tags")) or []) if t]
    s["creators"] = [c for c in (payload.get("creators", s.get("creators")) or []) if c and c.get("name")]
    s["source"] = payload.get("source") or s.get("source") or {"name": "manual", "label": "手动"}
    s["infobox"] = [p for p in (payload.get("infobox", s.get("infobox")) or [])
                    if p.get("key") and p.get("value")]
    s["userFields"] = [p for p in (payload.get("userFields", s.get("userFields")) or [])
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
    apply_immersive_background(s, payload)
    apply_bgm(s, payload)
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
    # HTTP Server 头只能放 ASCII：版本号缺失时用 unversioned，避免中文写进响应头。
    server_version = "GRDAG/" + VERSION_ASCII
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

    def serve_audio(self, url, head=False):
        if not re.fullmatch(r"/audio/[a-f0-9]{64}\.mp3", url):
            return self._send(404, "not found", "text/plain")
        path = os.path.join(AUDIO_DIR, url.rsplit("/", 1)[-1])
        if not os.path.isfile(path):
            return self._send(404, "not found", "text/plain")
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                return self._send(416, b"", extra_headers={"Content-Range": f"bytes */{size}"})
            left, right = match.groups()
            if left:
                start, end = int(left), min(int(right), end) if right else end
            else:
                start = max(0, size - int(right))
            if start > end or start >= size:
                return self._send(416, b"", extra_headers={"Content-Range": f"bytes */{size}"})
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not head:
            try:
                with open(path, "rb") as audio:
                    audio.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = audio.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_HEAD(self):
        return self.serve_audio(urlparse(self.path).path, head=True)

    def handle_audio_upload(self):
        self.close_connection = True
        load_library()  # 主档案损坏时，资源写入同样停止。
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > AUDIO_LIMIT:
            self.close_connection = True
            return self.send_json({"ok": False, "error": "本地 BGM 请选择 30 MB 以内的 MP3 文件"}, 413)
        raw = self.rfile.read(length)
        if len(raw) != length or not is_mp3(raw):
            return self.send_json({"ok": False, "error": "没有识别到有效的 MP3 音频，请重新选择文件"}, 400)
        name = hashlib.sha256(raw).hexdigest() + ".mp3"
        path = os.path.join(AUDIO_DIR, name)
        with _lock:
            load_library()
            ensure_dirs()
            if not os.path.exists(path):
                atomic_write_bytes(path, raw)
            else:
                os.utime(path, None)
        title = unquote(self.headers.get("X-Audio-Name", "背景音乐"))[:200]
        return self.send_json({"ok": True, "bgm": {"src": "/audio/" + name, "title": title, "artist": ""}, "bytes": length})

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
            if p.startswith("/audio/"):
                return self.serve_audio(p)
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
                health = library_health()
                proxy = resolve_proxy()
                file_version = read_version() or VERSION_UNKNOWN
                common = {
                    # version 是本次运行加载的版本；versionFile 是磁盘上 VERSION 的当前内容。
                    # 两者不一致说明项目文件已同步但旧进程还在跑，界面会提示重启。
                    "version": VERSION,
                    "versionFile": file_version,
                    "versionStale": file_version != VERSION,
                    "seriesKinds": SERIES_KINDS,
                    "seriesRoles": SERIES_ROLES,
                    "proxyActive": proxy,
                    "proxySource": _proxy_cache.get("source"),
                    "categories": [{"key": k, "label": v["label"], "sources": v["sources"],
                                    "statuses": STATUS_LABELS[k]} for k, v in CATEGORIES.items()],
                    "sourceLabels": SOURCE_LABELS,
                }
                if health["state"] == "corrupt":
                    # 主档案坏了也照常返回 200，让界面能显示恢复入口；但所有写操作会被 409 拒绝。
                    log_event("storage", "bootstrap", "corrupt", health.get("error_detail", ""), logging.ERROR)
                    return self.send_json({**common,
                                           "dataState": "corrupt",
                                           "dataError": health.get("reason") or "主档案损坏",
                                           "corruptFile": {"name": os.path.basename(LIB_PATH),
                                                           "size": health.get("size", 0),
                                                           "mtime": health.get("mtime", "")},
                                           "works": [], "series": [],
                                           "settings": default_library()["settings"],
                                           "backups": list_backups(),
                                           "undoAvailable": False})
                lib = load_library()
                return self.send_json({**common,
                                       "dataState": "normal",
                                       "works": [work_view(w) for w in lib["works"]],
                                       "series": [series_view(s, lib) for s in lib["series"]],
                                       "settings": lib["settings"],
                                       "backups": list_backups(),
                                       "undoAvailable": bool(write_snapshots())})
            if p == "/api/export":
                return self.handle_export(bool(qs.get("covers", ["0"])[0] in ("1", "true")))
            if p == "/api/template.csv":
                return self.handle_template()
            if p == "/api/backups":
                return self.send_json({"ok": True, "backups": list_backups()})
            if p == "/api/media-cleanup":
                return self.handle_media_cleanup()
            self._send(404, json.dumps({"ok": False, "error": "not found"}), "application/json")
        except LibraryCorrupt as e:
            log_event("http", "GET " + p, "corrupt", f"{e.reason} {e.detail}", logging.ERROR)
            self.send_json({"ok": False, "dataState": "corrupt",
                            "error": f"主档案损坏，已停止写入以保护原文件：{e.reason}"}, 409)
        except Exception as e:
            log_event("http", "GET " + p, "fail", f"{type(e).__name__}: {e}", logging.ERROR, exc=True)
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        try:
            if p == "/api/audio":
                return self.handle_audio_upload()
            if p == "/api/backgrounds/local":
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > BACKGROUND_IMAGE_LIMIT:
                    return self.send_json({"ok": False, "error": "沉浸图片为空或超过 20 MB"}, 400)
                with _lock:
                    load_library()
                raw = self.rfile.read(length)
                if len(raw) != length:
                    return self.send_json({"ok": False, "error": "图片上传不完整，请重试"}, 400)
                return self.send_json({"ok": True, "image": save_uploaded_immersive_image(raw)})
            body = self.read_body()
            if p == "/api/backgrounds":
                with _lock:
                    load_library()
                return self.send_json({"ok": True, "image": save_immersive_image(body.get("url"))})
            if p == "/api/search":
                return self.handle_search(body)
            if p == "/api/resolve":
                return self.handle_resolve(body)
            if p == "/api/tmdb/preview":
                return self.handle_tmdb_preview(body)
            if p == "/api/tmdb/import":
                return self.handle_tmdb_import(body)
            if p == "/api/youshu/preview":
                return self.handle_youshu_preview(body)
            if p == "/api/link":
                cat = body.get("category")
                draft = parse_link(body.get("url") or "", cat)
                draft["_ready"] = True
                return self.send_json({"ok": True, "draft": draft})
            if p == "/api/web-import":
                return self.handle_web_import(body)
            if p == "/api/works":
                return self.handle_create(body)
            if p == "/api/import-records":
                return self.handle_import_records(body)
            if p == "/api/import":
                with _lock:
                    return self.handle_import(body)
            if p == "/api/clear-data":
                return self.handle_clear_data(body)
            if p == "/api/settings":
                return self.handle_settings(body)
            if p == "/api/media-cleanup/stage":
                if not isinstance(body, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(body.get("token") or "")):
                    return self.send_json({"ok": False, "error": "请先检查闲置素材"}, 400)
                return self.handle_media_cleanup(body["token"])
            if p == "/api/backups/restore":
                with _lock:
                    return self.handle_restore(body)
            if p == "/api/backups/preview":
                return self.handle_backup_preview(body)
            if p == "/api/recover/new-start":
                with _lock:
                    return self.handle_recover_new_start(body)
            if p == "/api/undo":
                with _lock:
                    return self.handle_undo(body)
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
        except LibraryCorrupt as e:
            log_event("http", "POST " + p, "corrupt", f"{e.reason} {e.detail}", logging.ERROR)
            self.send_json({"ok": False, "dataState": "corrupt",
                            "error": f"主档案损坏，已停止写入以保护原文件：{e.reason}"}, 409)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            log_event("http", "POST " + p, "fail", f"{type(e).__name__}: {e}", logging.ERROR, exc=True)
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_PATCH(self):
        u = urlparse(self.path)
        body = self.read_body()
        try:
            return self._patch(u, body)
        except LibraryCorrupt as e:
            log_event("http", "PATCH " + u.path, "corrupt", f"{e.reason} {e.detail}", logging.ERROR)
            self.send_json({"ok": False, "dataState": "corrupt",
                            "error": f"主档案损坏，已停止写入以保护原文件：{e.reason}"}, 409)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            log_event("http", "PATCH " + u.path, "fail", f"{type(e).__name__}: {e}", logging.ERROR, exc=True)
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _patch(self, u, body):
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
        try:
            return self._delete(u)
        except LibraryCorrupt as e:
            log_event("http", "DELETE " + u.path, "corrupt", f"{e.reason} {e.detail}", logging.ERROR)
            self.send_json({"ok": False, "dataState": "corrupt",
                            "error": f"主档案损坏，已停止写入以保护原文件：{e.reason}"}, 409)
        except Exception as e:
            log_event("http", "DELETE " + u.path, "fail", f"{type(e).__name__}: {e}", logging.ERROR, exc=True)
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _delete(self, u):
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
              "steam": steam_search, "bilibili": bilibili_search, "cinemeta": cinemeta_search,
              "anilist": anilist_search, "web": web_search, "hongguo": hongguo_search}.get(source)
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
              "steam": steam_draft, "bilibili": bilibili_draft, "cinemeta": cinemeta_draft,
              "anilist": anilist_draft, "hongguo": hongguo_draft}.get(source)
        if not fn:
            return self.send_json({"ok": False, "error": "未知来源"}, 400)
        try:
            draft = fn(ref)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 200)
        draft["_ready"] = True
        return self.send_json({"ok": True, "draft": draft})

    def handle_tmdb_preview(self, body):
        """只校验并返回预览，不写作品库。"""
        target_id = body.get("targetId")
        if target_id is not None and not isinstance(target_id, (str, int)):
            return self.send_json({"ok": False, "error": "targetId 不合法"}, 400)
        try:
            draft = validate_tmdb_payload(body.get("json"))
            with _lock:
                lib = load_library()
                preview = _tmdb_preview_response(lib, draft, str(target_id) if target_id else None)
            preview["ok"] = True
            return self.send_json(preview)
        except ValueError as e:
            return self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def handle_tmdb_import(self, body):
        """确认后保存：同 TMDB 身份更新已有作品，否则新建；不按标题合并。"""
        target_id = body.get("targetId")
        if target_id is not None and not isinstance(target_id, (str, int)):
            return self.send_json({"ok": False, "error": "targetId 不合法"}, 400)
        try:
            action, work = import_tmdb_work(
                body.get("json"),
                target_id=str(target_id) if target_id else None,
                overrides=body.get("overrides"),
                rating=body.get("rating"),
                first_experience=body.get("firstExperience"),
                mode=body.get("mode") or "merge",
            )
        except ValueError as e:
            return self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return self.send_json({"ok": True, "action": action, "work": work_view(work)})

    def handle_youshu_preview(self, body):
        """只校验优书网剪贴板 JSON 并返回预览，不写作品库。"""
        target_id = body.get("targetId")
        if target_id is not None and not isinstance(target_id, (str, int)):
            return self.send_json({"ok": False, "error": "targetId 不合法"}, 400)
        try:
            draft, warnings = validate_youshu_payload(body.get("json"))
            with _lock:
                lib = load_library()
                preview = _youshu_preview_response(
                    lib, draft, str(target_id) if target_id else None, warnings)
                if not target_id and preview.get("match"):
                    title = (preview["match"].get("title") or preview["match"].get("id") or "")
                    raise ValueError("作品库中已有同一优书网 ID 的作品「%s」，请打开已有作品编辑后再导入" % title)
            preview["ok"] = True
            return self.send_json(preview)
        except ValueError as e:
            return self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def handle_web_import(self, body):
        """统一网页导入入口：一个输入框同时接受作品链接和书签提取的 JSON。

        两种方式最终都收敛成同一个 draft，前端只用一套「预览 → 填入表单」流程。
        """
        raw = str(body.get("input") or body.get("url") or "").strip()
        if not raw:
            return self.send_json({"ok": False, "error": "请粘贴作品链接或书签 JSON"}, 400)
        category = body.get("category")
        first = raw[:1]
        if first in ("{", "["):
            try:
                data = json.loads(raw)
            except Exception:
                return self.send_json({"ok": False, "error": "粘贴的内容不是有效的 JSON"}, 400)
            if not isinstance(data, dict):
                return self.send_json({"ok": False, "error": "书签 JSON 应该是一个对象"}, 400)
            src = str((data.get("source") or {}).get("name") if isinstance(data.get("source"), dict)
                      else data.get("source") or "").lower()
            warnings = []
            try:
                if src == "tmdb" or data.get("tmdbId") or data.get("mediaType"):
                    draft = validate_tmdb_payload(raw)
                    source_label = "TMDB"
                elif src == "youshu" or data.get("youshuId"):
                    draft, warnings = validate_youshu_payload(raw)
                    source_label = "优书网"
                else:
                    if not str(data.get("title") or "").strip():
                        return self.send_json({"ok": False, "error": "JSON 里没有 title，无法识别"}, 400)
                    draft = {k: v for k, v in data.items() if not str(k).startswith("_")}
                    source_label = str((data.get("source") or {}).get("label") if isinstance(data.get("source"), dict) else "") or "通用草稿"
                    warnings = ["未识别的来源，按通用草稿填入，请核对标题和封面"]
            except ValueError as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
            if not str(draft.get("title") or "").strip():
                return self.send_json({"ok": False, "error": "书签内容缺少标题"}, 400)
            draft["_ready"] = True
            return self.send_json({"ok": True, "kind": "json", "sourceLabel": source_label,
                                   "draft": draft, "warnings": warnings})
        if not re.match(r"^https?://", raw, re.I):
            return self.send_json({"ok": False,
                                   "error": "请粘贴以 http 开头的作品链接，或书签复制的 JSON"}, 400)
        host = (urlparse(raw).hostname or "").lower()
        if host.endswith("themoviedb.org") or host.endswith("youshu.me"):
            return self.send_json({"ok": False,
                                   "error": "这个站点请在其详情页点击书签提取 JSON，再粘贴到这里（不做整页抓取）"}, 400)
        try:
            draft = parse_link(raw, category)
        except RuntimeError as e:
            return self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        draft["_ready"] = True
        return self.send_json({"ok": True, "kind": "url", "sourceLabel": "链接解析",
                               "draft": draft, "warnings": []})

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
            add_images_to_zip(z, lib)
            add_audio_to_zip(z, lib)
        name = f"archive_with_covers_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        return self._send(200, buf.getvalue(), "application/zip",
                          {"Content-Disposition": f'attachment; filename="{quote(name)}"'})

    def handle_import(self, body):
        data = body.get("data")
        mode = body.get("mode") or "merge"
        cover_cnt = 0
        audio_before = set(os.listdir(AUDIO_DIR)) if os.path.isdir(AUDIO_DIR) else set()
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
        if not isinstance(incoming_series, list):
            raise ValueError("备份 series 格式不正确")
        for item in incoming + incoming_series:
            if not isinstance(item, dict):
                raise ValueError("备份条目格式不正确")
            apply_bgm(item, item)
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
        audio_cnt = len(set(os.listdir(AUDIO_DIR)) - audio_before) if os.path.isdir(AUDIO_DIR) else 0
        return self.send_json({"ok": True, "count": len(lib["works"]), "covers": cover_cnt, "audio": audio_cnt})

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
            add_audio_to_zip(z, lib, all_files=True)
            add_images_to_zip(z, lib)
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        cleared = {"works": len(lib.get("works") or []), "series": len(lib.get("series") or []),
                   "covers": 0, "audio": 0, "backups": 0}
        with _lock:
            newlib = default_library()
            for k in ("proxy", "proxy_port", "backup_keep", "immersive_background_interval", "immersive_background_order"):
                if k in lib.get("settings", {}):
                    newlib["settings"][k] = lib["settings"][k]
            write_library(newlib)
            for fn in os.listdir(AUDIO_DIR):
                fp = os.path.join(AUDIO_DIR, fn)
                if os.path.isfile(fp):
                    os.remove(fp)
                    cleared["audio"] += 1
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

    def handle_media_cleanup(self, expected_token=None):
        with _lock:
            try:
                candidates, counts, token = scan_unused_media()
                if expected_token is None:
                    files = [{"kind": kind, "name": name, "bytes": size}
                             for kind, name, size, *_ in candidates]
                    return self.send_json({"ok": True, "files": files, "bytes": sum(f["bytes"] for f in files),
                                           "folder": MEDIA_STAGING_DIR, "token": token, **counts})
                if token != expected_token or not candidates:
                    return self.send_json({"ok": False, "error": "候选素材已变化，请重新检查"}, 409)
                result = stage_unused_media(candidates)
            except (OSError, ValueError) as e:
                return self.send_json({"ok": False, "error": str(e)}, 409)
        return self.send_json({"ok": True, **result})

    def handle_settings(self, body):
        with _lock:
            lib = load_library()
            if "home_hidden_work_ids" in body:
                hidden_ids = body["home_hidden_work_ids"]
                if not isinstance(hidden_ids, list) or any(not isinstance(work_id, str) for work_id in hidden_ids):
                    raise ValueError("首页隐藏作品必须是字符串 ID 列表")
                existing_ids = {str(work.get("id") or "").strip() for work in lib["works"]
                                if isinstance(work, dict) and str(work.get("id") or "").strip()}
                normalized_ids = []
                seen = set()
                for work_id in hidden_ids:
                    work_id = work_id.strip()
                    if work_id and work_id in existing_ids and work_id not in seen:
                        normalized_ids.append(work_id)
                        seen.add(work_id)
                lib["settings"]["home_hidden_work_ids"] = normalized_ids
            for k in ("proxy", "proxy_port", "backup_keep"):
                if k in body:
                    lib["settings"][k] = body[k]
            if "immersive_background_interval" in body:
                try:
                    interval = int(body["immersive_background_interval"])
                except (TypeError, ValueError):
                    raise ValueError("背景切换间隔必须是 3 到 300 秒")
                if not 3 <= interval <= 300:
                    raise ValueError("背景切换间隔必须是 3 到 300 秒")
                lib["settings"]["immersive_background_interval"] = interval
            if "immersive_background_order" in body:
                order = body["immersive_background_order"]
                if order not in ("ordered", "random"):
                    raise ValueError("背景播放方式无效")
                lib["settings"]["immersive_background_order"] = order
            save_library(lib, snapshot=False)
        _proxy_cache["at"] = 0
        return self.send_json({"ok": True, "settings": lib["settings"]})

    def handle_restore(self, body):
        """恢复备份：先校验，再确认，再安全快照，最后原子替换 + 回读校验，失败自动回滚。"""
        kind = body.get("kind") or "write"
        name = os.path.basename(str(body.get("name") or ""))
        if (body.get("confirm") or "") != "恢复":
            return self.send_json({"ok": False, "error": "恢复需要明确确认"}, 400)
        fp = resolve_backup(kind, name)
        if not fp:
            return self.send_json({"ok": False, "error": "备份不存在"}, 404)
        try:
            lib, stats = load_backup_payload(fp)
        except Exception as e:
            log_event("backup", "restore", "invalid", f"{name}: {e}", logging.WARNING)
            return self.send_json({"ok": False, "error": f"备份不可用，未执行恢复：{e}"}, 400)
        safety = snapshot_before_restore("恢复")
        if not safety:
            return self.send_json({"ok": False,
                                   "error": "未能创建恢复前安全快照，已取消恢复（当前档案未改动）"}, 500)
        try:
            write_library(lib)
        except Exception as e:
            log_event("backup", "restore", "write-fail", f"{type(e).__name__}: {e}", logging.ERROR)
            return self.send_json({"ok": False, "error": f"写入失败，当前档案未改动：{e}"}, 500)
        # 回读校验：恢复后档案必须能正常解析，否则回滚
        try:
            with open(LIB_PATH, "r", encoding="utf-8") as f:
                reloaded = json.load(f)
            check_library(reloaded)
        except Exception as e:
            try:
                with open(safety, "rb") as f:
                    atomic_write_bytes(LIB_PATH, f.read())
                log_event("backup", "restore", "rolled-back", f"{name}: {e}", logging.ERROR)
                tail = "，已回滚到恢复前状态"
            except Exception as e2:
                log_event("backup", "restore", "rollback-fail",
                          f"{e2}", logging.CRITICAL)
                tail = f"，回滚也失败，请手动使用 {os.path.basename(safety)}"
            return self.send_json({"ok": False, "error": f"恢复后校验失败{tail}"}, 500)
        log_event("backup", "restore", "ok", f"{name} works={stats['works']}")
        return self.send_json({"ok": True, "count": stats["works"], "series": stats["series"],
                               "safety": os.path.basename(safety)})

    def handle_backup_preview(self, body):
        """恢复前预览：校验备份、给出当前档案与备份的数量差异和风险提示。"""
        kind = body.get("kind") or "write"
        name = os.path.basename(str(body.get("name") or ""))
        fp = resolve_backup(kind, name)
        if not fp:
            return self.send_json({"ok": False, "error": "备份不存在"}, 404)
        try:
            lib, stats = load_backup_payload(fp)
        except Exception as e:
            return self.send_json({"ok": False, "valid": False,
                                   "error": f"这个备份不可用：{e}"}, 400)
        health = library_health()
        current = {"works": health.get("works", 0), "series": health.get("series", 0),
                   "state": health.get("state")}
        warnings = []
        if health.get("state") == "normal" and stats["works"] < current["works"]:
            warnings.append(f"这个备份比当前档案少 {current['works'] - stats['works']} 部作品，恢复会丢掉这些作品")
        if health.get("state") == "normal" and stats["series"] < current["series"]:
            warnings.append(f"系列会从 {current['series']} 个变成 {stats['series']} 个")
        if stats.get("duplicates"):
            warnings.append(f"备份里有 {stats['duplicates']} 条重复 ID，会保留第一条")
        return self.send_json({"ok": True, "valid": True, "name": name, "kind": kind,
                               "stats": stats, "current": current, "warnings": warnings})

    def handle_recover_new_start(self, body):
        """主档案损坏且没有可用备份时，经用户明确确认后另存损坏文件并新建空档案。"""
        if (body.get("confirm") or "") != "新建空档案":
            return self.send_json({"ok": False, "error": "需要明确确认"}, 400)
        health = library_health()
        if health.get("state") != "corrupt":
            return self.send_json({"ok": False, "error": "当前主档案可以正常读取，不需要新建"}, 400)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        corrupt_copy = os.path.join(DATA_DIR, f"library.corrupt-{stamp}.json")
        try:
            os.replace(LIB_PATH, corrupt_copy)
        except Exception as e:
            log_event("storage", "recover", "fail", f"{type(e).__name__}: {e}", logging.ERROR)
            return self.send_json({"ok": False, "error": f"无法移动损坏文件，操作已取消：{e}"}, 500)
        try:
            write_library(default_library())
        except Exception as e:
            try:
                os.replace(corrupt_copy, LIB_PATH)
            except Exception:
                pass
            return self.send_json({"ok": False, "error": f"新建空档案失败，已还原：{e}"}, 500)
        log_event("storage", "recover", "ok", f"损坏文件已保留为 {os.path.basename(corrupt_copy)}")
        return self.send_json({"ok": True, "corruptCopy": os.path.basename(corrupt_copy)})

    def handle_undo(self, body):
        """撤销最近一次写操作：回退到最近一份写前快照；快照会被移入 undo-used，连续撤销可继续往前退。"""
        snaps = write_snapshots()
        if not snaps:
            return self.send_json({"ok": False, "error": "没有可撤销的操作"}, 400)
        newest = os.path.join(BACKUP_DIR, snaps[-1])
        try:
            lib, stats = load_backup_payload(newest)
        except Exception as e:
            log_event("undo", "load", "invalid", f"{snaps[-1]}: {e}", logging.WARNING)
            return self.send_json({"ok": False, "error": f"上一份快照不可用：{e}"}, 400)
        safety = snapshot_before_restore("撤销")
        if not safety:
            return self.send_json({"ok": False, "error": "未能创建撤销前安全快照，已取消"}, 500)
        try:
            write_library(lib)
            with open(LIB_PATH, "r", encoding="utf-8") as f:
                check_library(json.load(f))
        except Exception as e:
            try:
                with open(safety, "rb") as f:
                    atomic_write_bytes(LIB_PATH, f.read())
            except Exception:
                pass
            return self.send_json({"ok": False, "error": f"撤销失败，已尽量还原：{e}"}, 500)
        try:
            os.makedirs(UNDO_USED_DIR, exist_ok=True)
            os.replace(newest, os.path.join(UNDO_USED_DIR, os.path.basename(newest)))
        except Exception:
            pass
        log_event("undo", "apply", "ok", f"{snaps[-1]} works={stats['works']}")
        return self.send_json({"ok": True, "works": stats["works"],
                               "remaining": len(write_snapshots())})


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
    corrupt_error = ""
    try:
        lib = load_library()
        ensure_daily_backup()
    except LibraryCorrupt as e:
        # 损坏时不写盘、不退出：起服务让界面显示恢复入口，所有写操作都会被拒绝。
        lib = None
        corrupt_error = f"{e.reason}：{e.detail}" if e.detail else e.reason
        log_event("startup", "load", "corrupt", corrupt_error, logging.ERROR)
    if _port_alive(PORT):
        print("=" * 52)
        print(f"  {PORT} 端口上已经有一个实例在跑，这次不再重复启动。")
        print(f"  已为你打开：http://127.0.0.1:{PORT}")
        print("  （Windows 允许多个进程绑同一端口，所以之前会出现两个实例。）")
        print("  如果刚同步过项目文件，请先关掉旧窗口再启动，否则页面显示的仍是旧版本。")
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
    print(f"  当前版本：{VERSION}（读取自 VERSION 文件）")
    if VERSION == VERSION_UNKNOWN:
        print("  ｜ 注意：没读到有效的版本号，界面会显示「版本未标注」")
        print("  ｜ 请检查根目录 VERSION：应为一行 1.2.3 这样的内容（允许前导 v）")
    print(f"  数据文件：{LIB_PATH}")
    print(f"  封面目录：{COVER_DIR}")
    print(f"  备份目录：{BACKUP_DIR}")
    print(f"  访问地址：http://127.0.0.1:{PORT}")
    if lib is None:
        print("  ｜ 主档案损坏，已停止写入保护原文件")
        print(f"  ｜ 原因：{corrupt_error}")
        print("  ｜ 请在网页里选择「从备份恢复」或确认后「新建空档案」")
    else:
        print(f"  作品数量：{len(lib['works'])}")
    print("  关闭这个窗口 = 停止服务，数据已写盘")
    log_event("startup", "serve", "ok", f"version={VERSION} port={PORT}")
    print("=" * 52)
    if not os.environ.get("GRDAG_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()



