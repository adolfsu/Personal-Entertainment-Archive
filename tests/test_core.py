# -*- coding: utf-8 -*-
"""核心数据安全测试：全部在临时目录里跑，绝不碰 data/library.json 真实档案。

运行：python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="grdag-test-")
REAL_DATA = os.path.join(ROOT, "data", "library.json")
assert os.path.abspath(TMP) != os.path.abspath(os.path.dirname(REAL_DATA)), "测试目录不能指向真实档案"

os.environ["GRDAG_BASE_DIR"] = TMP
os.environ["GRDAG_SKIP_PROXY_DETECT"] = "1"
os.environ["GRDAG_PORT"] = "0"
with open(os.path.join(TMP, "VERSION"), "w", encoding="utf-8") as f:
    f.write("9.9.9\n")
sys.path.insert(0, ROOT)
import server  # noqa: E402

BASE_URL = ""


def http(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_json(method, path, body=None):
    status, raw = http(method, path, body)
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, {}


def clean():
    for sub in ("data", "backups", "logs"):
        shutil.rmtree(os.path.join(TMP, sub), ignore_errors=True)
    server._proxy_cache["value"] = None
    server._proxy_cache["at"] = 0
    server._proxy_cache["source"] = ""


def write_raw(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def sample_work(wid, title="测试作品"):
    return {"id": wid, "title": title, "category": "book", "status": "completed",
            "rating": 8, "createdAt": "2026-01-01T00:00:00", "updatedAt": "2026-01-01T00:00:00"}


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global BASE_URL
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        BASE_URL = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        clean()


class TestStorage(ServerCase):
    def test_first_run_creates_library(self):
        lib = server.load_library()
        self.assertEqual(lib["works"], [])
        self.assertTrue(os.path.exists(server.LIB_PATH))

    def test_corrupt_file_is_never_overwritten(self):
        write_raw(server.LIB_PATH, '{"works": [broken')
        original = read_bytes(server.LIB_PATH)
        with self.assertRaises(server.LibraryCorrupt):
            server.load_library()
        self.assertEqual(read_bytes(server.LIB_PATH), original)
        self.assertEqual([f for f in os.listdir(server.DATA_DIR) if ".tmp" in f], [])

    def test_wrong_structure_is_corrupt(self):
        write_raw(server.LIB_PATH, json.dumps({"works": "not-a-list"}))
        with self.assertRaises(server.LibraryCorrupt):
            server.load_library()

    def test_missing_library_is_allowed_to_create(self):
        self.assertFalse(os.path.exists(server.LIB_PATH))
        lib = server.load_library()
        self.assertEqual(len(lib["works"]), 0)

    def test_atomic_write_leaves_no_tmp(self):
        server.write_library(server.default_library())
        self.assertEqual([f for f in os.listdir(server.DATA_DIR) if ".tmp" in f], [])
        with open(server.LIB_PATH, encoding="utf-8") as f:
            json.load(f)

    def test_newer_version_is_rejected(self):
        write_raw(server.LIB_PATH, json.dumps({"version": 99, "works": [], "series": []}))
        with self.assertRaises(server.LibraryCorrupt):
            server.load_library()


class TestDailyBackup(ServerCase):
    def test_one_per_day_and_retention(self):
        lib = server.default_library()
        lib["works"] = [sample_work("w_daily")]
        server.save_library(lib, snapshot=False)
        first = server.daily_backup_path()
        self.assertTrue(os.path.exists(first))
        server.ensure_daily_backup()
        self.assertEqual(len([f for f in os.listdir(server.DAILY_BACKUP_DIR)]), 1)
        # 造 20 份历史每日备份，清理后只保留最新 15 份
        for i in range(1, 21):
            write_raw(os.path.join(server.DAILY_BACKUP_DIR, f"library_2026-01-{i:02d}.json"), "{}")
        os.makedirs(server.PRE_RESTORE_DIR, exist_ok=True)
        keep_me = os.path.join(server.PRE_RESTORE_DIR, "恢复前_20260101_000000_000000.json")
        write_raw(keep_me, '{"works": []}')
        server.cleanup_daily()
        self.assertEqual(len(os.listdir(server.DAILY_BACKUP_DIR)), server.DAILY_KEEP)
        self.assertFalse(os.path.exists(os.path.join(server.DAILY_BACKUP_DIR, "library_2026-01-01.json")))
        self.assertTrue(os.path.exists(keep_me))

    def test_broken_library_does_not_create_daily_backup(self):
        write_raw(server.LIB_PATH, "not json")
        self.assertIsNone(server.ensure_daily_backup())
        self.assertFalse(os.path.exists(server.DAILY_BACKUP_DIR) and os.listdir(server.DAILY_BACKUP_DIR))


class TestBackupRestore(ServerCase):
    def _make_library(self, count):
        lib = server.default_library()
        lib["works"] = [sample_work(f"w{i}", f"作品{i}") for i in range(count)]
        server.save_library(lib, snapshot=False)
        return lib

    def test_preview_warns_about_rollback(self):
        self._make_library(3)
        backup = server.snapshot_library(30)
        self.assertTrue(backup)
        self._make_library(5)
        status, data = http_json("POST", "/api/backups/preview",
                                 {"kind": "write", "name": os.path.basename(backup)})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["stats"]["works"], 3)
        self.assertEqual(data["current"]["works"], 5)
        self.assertTrue(any("少 2 部" in w for w in data["warnings"]))

    def test_restore_requires_confirm_and_creates_safety(self):
        self._make_library(2)
        backup = server.snapshot_library(30)
        name = os.path.basename(backup)
        self._make_library(4)
        status, data = http_json("POST", "/api/backups/restore", {"kind": "write", "name": name})
        self.assertEqual(status, 400)
        self.assertEqual(len(server.load_library()["works"]), 4)
        status, data = http_json("POST", "/api/backups/restore",
                                 {"kind": "write", "name": name, "confirm": "恢复"})
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(server.load_library()["works"]), 2)
        self.assertEqual(len(os.listdir(server.PRE_RESTORE_DIR)), 1)

    def test_invalid_backup_does_not_touch_library(self):
        self._make_library(2)
        bad_dir = server.BACKUP_DIR
        write_raw(os.path.join(bad_dir, "library_20260101_000000.json"), "{oops")
        status, data = http_json("POST", "/api/backups/preview",
                                 {"kind": "write", "name": "library_20260101_000000.json"})
        self.assertEqual(status, 400)
        status, data = http_json("POST", "/api/backups/restore",
                                 {"kind": "write", "name": "library_20260101_000000.json", "confirm": "恢复"})
        self.assertEqual(status, 400)
        self.assertEqual(len(server.load_library()["works"]), 2)

    def test_path_traversal_is_rejected(self):
        self._make_library(1)
        status, data = http_json("POST", "/api/backups/preview",
                                 {"kind": "write", "name": "../data/library.json"})
        self.assertEqual(status, 404)


class TestCorruptMode(ServerCase):
    def test_bootstrap_reports_corrupt_and_writes_are_blocked(self):
        write_raw(server.LIB_PATH, "{broken")
        original = read_bytes(server.LIB_PATH)
        status, data = http_json("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(data["dataState"], "corrupt")
        self.assertEqual(data["works"], [])
        self.assertIn("corruptFile", data)
        status, data = http_json("POST", "/api/works", {"title": "不该写进去", "category": "book"})
        self.assertEqual(status, 409)
        self.assertEqual(read_bytes(server.LIB_PATH), original)

    def test_recover_new_start_keeps_corrupt_copy(self):
        write_raw(server.LIB_PATH, "{broken")
        original = read_bytes(server.LIB_PATH)
        status, data = http_json("POST", "/api/recover/new-start", {"confirm": "新建空档案"})
        self.assertEqual(status, 200)
        self.assertTrue(os.path.exists(os.path.join(server.DATA_DIR, data["corruptCopy"])))
        self.assertEqual(read_bytes(os.path.join(server.DATA_DIR, data["corruptCopy"])), original)
        self.assertEqual(len(server.load_library()["works"]), 0)

    def test_recover_requires_corrupt_state(self):
        server.load_library()
        status, data = http_json("POST", "/api/recover/new-start", {"confirm": "新建空档案"})
        self.assertEqual(status, 400)


class TestWorksApi(ServerCase):
    def test_crud_rating_and_experience(self):
        status, data = http_json("POST", "/api/works",
                                 {"title": "测试书", "category": "book", "rating": 8.3})
        self.assertEqual(status, 200, data)
        wid = data["work"]["id"]
        self.assertEqual(data["work"]["rating"], 8.5)

        status, data = http_json("POST", f"/api/works/{wid}/rating",
                                 {"score": 7, "reason": "看完了"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["work"]["rating"], 7)

        status, data = http_json("POST", f"/api/works/{wid}/experience",
                                 {"status": "completed", "content": "读完第一章"})
        self.assertEqual(status, 200, data)
        self.assertEqual(len(data["work"]["experiences"]), 1)

        status, data = http_json("PATCH", f"/api/works/{wid}", {"title": "改名了"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["work"]["title"], "改名了")

        status, data = http_json("DELETE", f"/api/works/{wid}")
        self.assertEqual(status, 200, data)
        self.assertEqual(len(server.load_library()["works"]), 0)

    def test_validation_error_is_clear(self):
        status, data = http_json("POST", "/api/works", {"title": "", "category": "book"})
        self.assertEqual(status, 400)
        self.assertIn("标题", data["error"])

    def test_export_and_import_roundtrip(self):
        http_json("POST", "/api/works", {"title": "导出测试", "category": "book"})
        status, raw = http("GET", "/api/export")
        self.assertEqual(status, 200)
        exported = json.loads(raw.decode("utf-8"))
        self.assertEqual(len(exported["works"]), 1)
        status, data = http_json("POST", "/api/import", {"data": raw.decode("utf-8"), "mode": "merge"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["count"], 1)
        lib_text = json.dumps({"works": [sample_work("w9", "导入测试")], "series": [],
                               "version": 2, "settings": {"proxy": "auto"}}, ensure_ascii=False)
        status, data = http_json("POST", "/api/import", {"data": lib_text, "mode": "merge"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["count"], 2)


class TestUndo(ServerCase):
    def test_undo_steps_back_one_write(self):
        server.load_library()
        lib = server.load_library()
        lib["works"] = [sample_work("a")]
        server.save_library(lib)
        lib = server.load_library()
        lib["works"].append(sample_work("b"))
        server.save_library(lib)
        self.assertEqual(len(server.load_library()["works"]), 2)

        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["works"], 1)
        self.assertEqual(len(server.load_library()["works"]), 1)

        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["works"], 0)

        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 400)

    def test_undo_disabled_state_reported(self):
        server.load_library()
        status, data = http_json("GET", "/api/bootstrap")
        self.assertFalse(data["undoAvailable"])

    def test_edit_save_creates_snapshot_and_undo_restores(self):
        """复现验收路径：编辑作品保存 → 顶栏撤销。"""
        status, data = http_json("POST", "/api/works", {"title": "原标题", "category": "book"})
        self.assertEqual(status, 200, data)
        wid = data["work"]["id"]
        status, data = http_json("PATCH", f"/api/works/{wid}", {"title": "修改后"})
        self.assertEqual(status, 200, data)
        snaps = server.write_snapshots()
        self.assertTrue(snaps, "编辑保存后必须留下写前快照")
        with open(os.path.join(server.BACKUP_DIR, snaps[-1]), encoding="utf-8") as f:
            pre = json.load(f)
        self.assertEqual(pre["works"][0]["title"], "原标题")
        status, data = http_json("GET", "/api/bootstrap")
        self.assertTrue(data["undoAvailable"], "编辑保存后 /api/bootstrap 应报告可撤销")
        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(server.load_library()["works"][0]["title"], "原标题")

    def test_consecutive_undo_after_multiple_edits(self):
        status, data = http_json("POST", "/api/works", {"title": "A", "category": "book"})
        wid = data["work"]["id"]
        http_json("PATCH", f"/api/works/{wid}", {"title": "B"})
        http_json("PATCH", f"/api/works/{wid}", {"title": "C"})
        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(server.load_library()["works"][0]["title"], "B")
        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(server.load_library()["works"][0]["title"], "A")
        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(len(server.load_library()["works"]), 0)

    def test_rating_change_is_undoable(self):
        status, data = http_json("POST", "/api/works", {"title": "评分测试", "category": "book", "rating": 8})
        wid = data["work"]["id"]
        status, data = http_json("POST", f"/api/works/{wid}/rating", {"score": 5, "reason": "改主意"})
        self.assertEqual(status, 200, data)
        status, data = http_json("POST", "/api/undo")
        self.assertEqual(status, 200, data)
        self.assertEqual(server.load_library()["works"][0]["rating"], 8)


class TestVersionAndLogs(ServerCase):
    def test_version_from_file(self):
        self.assertEqual(server.VERSION, "9.9.9")

    def test_version_bom_and_prefix(self):
        with open(server.VERSION_FILE, "wb") as f:
            f.write("\ufeffv1.2.3\n".encode("utf-8"))
        server._VERSION_CACHE.update({"mtime": None, "value": ""})
        self.assertEqual(server.read_version(), "1.2.3")

    def test_log_redacts_secrets(self):
        server.log_event("test", "login", "ok", "deepseek_key=sk-supersecret123456 token=abcdef123456")
        path = os.path.join(server.LOG_DIR, "app.log")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("sk-supersecret123456", text)
        self.assertNotIn("abcdef123456", text)
        self.assertIn("***", text)

    def test_log_write_failure_does_not_raise(self):
        try:
            server.log_event("test", "noop", "ok", "x" * 1000)
        except Exception as e:
            self.fail(f"日志写入不应抛异常：{e}")

    def test_web_import_unified_entry(self):
        server.load_library()
        status, data = http_json("POST", "/api/web-import",
                                 {"input": json.dumps({"title": "通用草稿", "tags": ["测试"]})})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["kind"], "json")
        self.assertEqual(data["draft"]["title"], "通用草稿")

        status, data = http_json("POST", "/api/web-import", {"input": "{不是 JSON"})
        self.assertEqual(status, 400)

        status, data = http_json("POST", "/api/web-import", {"input": "https://example.com/x"})
        self.assertEqual(status, 400)
        self.assertIn("暂不支持", data["error"])

    def test_tmdb_bookmark_json_still_works(self):
        """移除独立粘贴框后，TMDB 书签 JSON 仍走原有的校验/预览接口。"""
        payload = {"source": {"name": "tmdb", "type": "movie", "id": "123",
                              "url": "https://www.themoviedb.org/movie/123"},
                   "title": "测试电影", "year": "2024", "summary": "简介"}
        status, data = http_json("POST", "/api/tmdb/preview", {"json": json.dumps(payload)})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["ok"])
        self.assertEqual(data["draft"]["title"], "测试电影")

        status, data = http_json("POST", "/api/web-import", {"input": json.dumps(payload)})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["kind"], "json")
        self.assertEqual(data["draft"]["title"], "测试电影")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
