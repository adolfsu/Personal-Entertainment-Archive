"""Build and install versioned program-only update packages."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


GITHUB = "https://github.com/adolfsu/Personal-Entertainment-Archive"
CNB = "https://cnb.cool/adolfsu/Personal-Entertainment-Archive"
METADATA = "pea-update.json"
PACKAGE = "pea-update.zip"
FORMAT = 1
MAX_JSON = 32 * 1024
MAX_PACKAGE = 32 * 1024 * 1024
MAX_CONTENT = 64 * 1024 * 1024
REQUIRED = ("server.py", "update_release.py", "VERSION", "web")
DOCS = ("启动.bat", "README.md", "使用说明.md", "CHANGELOG.md", "发布说明.md")
MANAGED = REQUIRED + DOCS
WEB_FILE = re.compile(r"web/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_.-]+\.(?:js|css|html|json|svg|png|webp|jpg|ico|woff2)")
GITHUB_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
CNB_HOSTS = frozenset({"cnb.cool", "asset.cnb.cool", "api.cnb.cool"})
# 两个仓库的 Release 路径规则不同：GitHub 是 /releases，CNB 是 /-/releases。
# 发布源按顺序尝试：GitHub 为主，连不上或没有正式版时回退到 CNB 镜像。
SOURCES = (("GitHub", f"{GITHUB}/releases", GITHUB_HOSTS), ("CNB", f"{CNB}/-/releases", CNB_HOSTS))
DOWNLOAD_HOSTS = GITHUB_HOSTS


class UpdateError(Exception):
    pass


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}", value):
        raise UpdateError("版本号格式不正确")
    return tuple(int(part) for part in value.split("."))


def validate_release(value):
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        raise UpdateError("无法识别发布清单")
    version_key(value.get("version"))
    if (type(value.get("archiveSchema")) is not int or
            type(value.get("bytes")) is not int or not 0 < value["bytes"] <= MAX_PACKAGE or
            not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sha256", ""))) or
            not isinstance(value.get("notes", ""), str)):
        raise UpdateError("发布清单缺少有效的档案格式、大小或校验值")
    return {key: value.get(key, "") for key in ("format", "version", "archiveSchema", "bytes", "sha256", "notes")}


def is_safe_download(url, hosts=GITHUB_HOSTS):
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc.lower() in hosts


class ReleaseRedirect(HTTPRedirectHandler):
    def __init__(self, hosts=GITHUB_HOSTS):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_download(newurl, self.hosts):
            raise UpdateError("下载地址跳转到未授权的网站")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_release(url, hosts=GITHUB_HOSTS):
    if not is_safe_download(url, hosts):
        raise UpdateError("下载地址不属于官方仓库")
    return build_opener(ReleaseRedirect(hosts)).open(Request(url, headers={"User-Agent": "PEA-Updater"}), timeout=12)


def release_source(release):
    """下载包时沿用取清单时的那个源，避免两边版本不同导致校验失败。"""
    name = release.get("source")
    for source_name, base, hosts in SOURCES:
        if source_name == name:
            return base, hosts
    return GITHUB, GITHUB_HOSTS


def fetch_release():
    """读取发布清单：GitHub 优先，连不上或没有正式版时回退到 CNB 镜像。"""
    problems = []
    for name, base, hosts in SOURCES:
        try:
            with open_release(f"{base}/latest/download/{METADATA}", hosts) as response:
                raw = response.read(MAX_JSON + 1)
        except HTTPError as exc:
            if exc.code == 404:
                problems.append(f"{name} 暂无正式版")
            else:
                problems.append(f"{name} 返回 HTTP {exc.code}")
            continue
        except (OSError, URLError, UpdateError):
            problems.append(f"无法连接 {name}")
            continue
        try:
            if len(raw) > MAX_JSON:
                raise ValueError("oversized")
            release = validate_release(json.loads(raw))
        except (ValueError, UnicodeError):
            problems.append(f"{name} 上的发布清单无法读取")
            continue
        release["notes"] = release["notes"][:3000]
        release["source"] = name
        return release
    if all(text.endswith("暂无正式版") for text in problems):
        return None
    raise UpdateError("；".join(problems) + "，暂时无法检查更新")


def eligibility(release, current, schema):
    requested = version_key(release["version"])
    installed = version_key(current)
    if requested <= installed:
        return "current"
    if requested[0] != installed[0] or release["archiveSchema"] != schema:
        return "incompatible"
    return "available"


def allowed_file(name):
    if name in ("server.py", "update_release.py", "VERSION", *DOCS):
        return True
    if not WEB_FILE.fullmatch(name):
        return False
    return all(not part.startswith(".") and part.split(".")[0].lower() not in
               {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
               for part in name.split("/"))


def read_json(path):
    return json.loads(path.read_bytes())


def write_json(path, value):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def linked(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unpack_package(package, target, release):
    if package.stat().st_size != release["bytes"] or digest_file(package) != release["sha256"]:
        raise UpdateError("更新包大小或 SHA-256 不匹配")
    with zipfile.ZipFile(package) as bundle:
        entries = bundle.infolist()
        if len(entries) > 512 or sum(info.file_size for info in entries) > MAX_CONTENT:
            raise UpdateError("更新包解压大小或文件数量超出限制")
        seen = set()
        for info in entries:
            name = info.filename
            kind = stat.S_IFMT(info.external_attr >> 16)
            if (kind not in (0, stat.S_IFREG) or info.is_dir() or name.casefold() in seen or
                    (name != METADATA and not allowed_file(name))):
                raise UpdateError("更新包含有不允许的文件或重复路径")
            seen.add(name.casefold())
        if not {"server.py", "update_release.py", "version", "web/index.html", METADATA} <= seen:
            raise UpdateError("更新包缺少必要的程序文件")
        if bundle.getinfo(METADATA).file_size > MAX_JSON:
            raise UpdateError("包内发布清单太大")
        detail = json.loads(bundle.read(METADATA))
        if detail != {key: release[key] for key in ("format", "version", "archiveSchema")}:
            raise UpdateError("更新包标注的版本或档案格式与发布清单不一致")
        for info in entries:
            if info.filename == METADATA:
                continue
            dest = target / info.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, dest.open("xb") as output:
                shutil.copyfileobj(source, output)
    if (target / "VERSION").read_text(encoding="utf-8-sig").strip() != release["version"]:
        raise UpdateError("更新包里的 VERSION 与发布版本不一致")
    for name in ("server.py", "update_release.py"):
        compile((target / name).read_bytes(), name, "exec")


def download_package(release, path):
    base, hosts = release_source(release)
    url = f"{base}/download/v{release['version']}/{PACKAGE}"
    with open_release(url, hosts) as source, path.open("xb") as output:
        count = 0
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            count += len(chunk)
            if count > release["bytes"]:
                raise UpdateError("下载的更新包超过清单标注大小")
            output.write(chunk)


def state_dir(base):
    directory = base / ".pea-updates"
    if directory.is_symlink() or (directory.exists() and linked(directory)):
        raise UpdateError("更新工作目录不能是链接")
    return directory


def update_state(directory):
    try:
        return read_json(directory / "state.json")
    except (OSError, ValueError):
        return {}


def set_state(directory, job, phase, message):
    write_json(directory / "state.json", {"job": job, "phase": phase, "message": message})


def launch_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}


class Coordinator:
    def __init__(self, server, base, version, schema):
        self.server = server
        self.base = Path(base)
        self.version = version
        self.schema = schema
        self.lock = threading.Lock()
        self.ready = None

    def check(self, disk_version):
        if disk_version != self.version:
            raise UpdateError("磁盘版本与正在运行的版本不同，请先重启")
        release = fetch_release()
        result = {"current": self.version, "status": "unreleased"}
        if release:
            result.update(status=eligibility(release, self.version, self.schema), release=release)
        return result

    def start(self, expected, disk_version):
        if not isinstance(expected, dict):
            raise UpdateError("请先检查更新")
        root = state_dir(self.base)
        with self.lock:
            if self.ready is not None or update_state(root).get("phase") in ("downloading", "restarting") and getattr(self, "worker", None) is not None and self.worker.is_alive():
                raise UpdateError("已有更新正在处理")
            if disk_version != self.version:
                raise UpdateError("请先重启到磁盘版本")
            version_key(expected.get("version"))
            if not re.fullmatch(r"[a-f0-9]{64}", str(expected.get("sha256", ""))):
                raise UpdateError("请重新检查更新")
            root.mkdir(exist_ok=True)
            job = secrets.token_hex(8)
            set_state(root, job, "downloading", "正在下载并校验更新包…")
            self.worker = threading.Thread(target=self.prepare, args=(root, job, expected), daemon=True)
            self.worker.start()
        return job

    def prepare(self, root, job, expected):
        work = root / job
        try:
            release = fetch_release()
            if (not release or eligibility(release, self.version, self.schema) != "available" or
                    any(release[k] != expected[k] for k in ("version", "sha256"))):
                raise UpdateError("可用版本已变化，请重新检查")
            work.mkdir()
            package = work / PACKAGE
            download_package(release, package)
            unpack_package(package, work / "new", release)
            package.unlink()
            runner = work / "runner.py"
            shutil.copyfile(__file__, runner)
            write_json(work / "job.json", {"old": self.version, "new": release["version"],
                                           "port": self.server.server_address[1]})
            set_state(root, job, "restarting", "更新包已验证，正在重启…")
            with (work / "update.log").open("ab") as log:
                subprocess.Popen([sys.executable, "-B", str(runner), "apply"], cwd=self.base,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, **launch_options())
            self.ready = work / "stopped"
        except Exception as exc:
            message = str(exc) if isinstance(exc, UpdateError) else "下载或校验失败，未替换程序文件"
            set_state(root, job, "failed", message)
            return
        self.server.shutdown()


def wait_for_server(child, port, version, identity):
    url = f"http://127.0.0.1:{port}/api/update/health"
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 18
    while child.poll() is None and time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as response:
                if json.load(response) == {"version": version, "instance": identity}:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    return False


def start_program(base, work, version, port, job):
    env = dict(os.environ, GRDAG_BASE_DIR=str(base), GRDAG_PORT=str(port),
               GRDAG_NO_BROWSER="1", PEA_UPDATE_INSTANCE=job)
    with (work / "update.log").open("ab") as log:
        child = subprocess.Popen([sys.executable, "-B", str(base / "server.py")], cwd=base, env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, **launch_options())
    if wait_for_server(child, port, version, job):
        return
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    raise UpdateError("更新后的服务未通过启动检查")


def apply_update(work):
    root, base = work.parent, work.parent.parent
    job = work.name
    args = read_json(work / "job.json")
    deadline = time.monotonic() + 150
    while not (work / "stopped").is_file():
        if time.monotonic() >= deadline:
            set_state(root, job, "failed", "旧服务尚未停止，未替换程序文件")
            return
        time.sleep(0.2)
    backup = work / "previous"
    incoming = work / "new"
    saved, installed = [], []
    try:
        backup.mkdir()
        for name in MANAGED:
            src, dst = incoming / name, base / name
            if not src.exists():
                continue
            if dst.exists() or dst.is_symlink():
                if linked(dst):
                    raise UpdateError("程序路径是链接，不能自动替换")
                os.replace(dst, backup / name)
                saved.append(name)
            os.replace(src, dst)
            installed.append(name)
        start_program(base, work, args["new"], args["port"], job)
    except Exception as exc:
        print(f"Install failed: {exc}", flush=True)
        try:
            for name in reversed(installed):
                os.replace(base / name, incoming / name)
            for name in reversed(saved):
                os.replace(backup / name, base / name)
            start_program(base, work, args["old"], args["port"], job)
        except Exception as recovery:
            print(f"Rollback failed: {recovery}", flush=True)
            set_state(root, job, "failed", "自动回退未完成，请查看更新日志和上一版程序备份")
            return
        set_state(root, job, "rolled-back", "新版本未能启动，已恢复上一版")
        return
    set_state(root, job, "installed", f"已更新到 v{args['new']}")


def build_package(base, out, schema):
    version = (base / "VERSION").read_text(encoding="utf-8-sig").strip()
    version_key(version)
    manifest = {"format": FORMAT, "version": version, "archiveSchema": schema}
    out.mkdir(parents=True, exist_ok=True)
    package = out / PACKAGE
    files = [base / name for name in (*REQUIRED, *DOCS) if name != "web"]
    if linked(base / "web"):
        raise UpdateError("web 目录不能是链接")
    files.extend(sorted(path for path in (base / "web").rglob("*") if path.is_file()))
    with tempfile.TemporaryDirectory(dir=out) as temp:
        temp = Path(temp)
        candidate = temp / PACKAGE
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(METADATA, json.dumps(manifest))
            for path in files:
                name = path.relative_to(base).as_posix()
                if not allowed_file(name) or linked(path):
                    raise UpdateError(f"无法打包：{name}")
                archive.write(path, name)
        notes = (base / "CHANGELOG.md").read_text(encoding="utf-8-sig")
        sections = re.split(r"^## ", notes, flags=re.MULTILINE)
        current = next((text for text in sections[1:] if text.startswith(f"[{version}]")), "")
        release = dict(manifest, sha256=digest_file(candidate), bytes=candidate.stat().st_size,
                       notes=current.partition("\n")[2].strip()[:3000])
        unpack_package(candidate, temp / "verify", validate_release(release))
        write_json(temp / METADATA, release)
        os.replace(candidate, package)
        os.replace(temp / METADATA, out / METADATA)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--out", type=Path, required=True)
    commands.add_parser("apply")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    if args.command == "apply":
        apply_update(here)
    else:
        from server import LIB_VERSION
        print(build_package(here, args.out.resolve(), LIB_VERSION))


if __name__ == "__main__":
    main()
