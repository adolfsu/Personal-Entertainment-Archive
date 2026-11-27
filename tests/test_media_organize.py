import base64
import io
import json
from pathlib import Path
import time
import os
from unittest.mock import patch
import zipfile

import test_core as core
from test_audio import MP3, request


class TestMediaOrganize(core.ServerCase):
    def organize(self):
        status, result = core.http_json("POST", "/api/media-organize", {"organize": True})
        self.assertEqual(status, 200, result)
        return result

    def test_moves_bound_files_and_keeps_old_urls_and_backups(self):
        server = core.server
        server.ensure_dirs()
        cover_name = "1" * 16 + ".jpg"
        background_name = "background_" + "2" * 64 + ".png"
        cover_path = Path(server.COVER_DIR, cover_name)
        cover_path.write_bytes(b"cover")
        Path(server.COVER_DIR, background_name).write_bytes(b"background")
        _, raw, _ = request("POST", "/api/audio", MP3, {"Content-Type": "audio/mpeg"})
        bgm = json.loads(raw)["bgm"]
        audio_name = bgm["src"].rsplit("/", 1)[1]
        book = core.sample_work("book")
        book.update(cover="covers/" + cover_name, bgm=bgm,
                    immersiveBackgroundUrl="/covers/" + background_name)
        game = dict(core.sample_work("game"), category="game", bgm=bgm)
        lib = server.default_library()
        lib["works"] = [book, game]
        server.write_library(lib)
        legacy_snapshot = server.snapshot_library(30)
        before = Path(server.LIB_PATH).read_bytes()

        moved = self.organize()
        self.assertEqual((moved["covers"], moved["audio"], moved["missing"], moved["skipped"]), (2, 1, [], []))
        self.assertEqual(Path(server.LIB_PATH).read_bytes(), before)
        self.assertFalse(cover_path.exists())
        self.assertTrue(Path(server.COVER_DIR, "book", cover_name).is_file())
        self.assertTrue(Path(server.AUDIO_DIR, "shared", audio_name).is_file())
        self.assertEqual((self.organize()["covers"], self.organize()["audio"]), (0, 0))
        self.assertEqual(core.http("GET", "/covers/" + cover_name), (200, b"cover"))
        self.assertEqual(core.http("GET", "/covers/" + background_name), (200, b"background"))
        self.assertEqual(request("GET", bgm["src"], headers={"Range": "bytes=3-8"})[:2], (206, MP3[3:9]))
        self.assertEqual(request("HEAD", bgm["src"])[0], 200)

        with zipfile.ZipFile(moved["backup"]) as backup:
            self.assertEqual(backup.read("library.json"), before)
            self.assertEqual(backup.read("audio/" + audio_name), MP3)
        status, exported = core.http("GET", "/api/export?covers=1")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            self.assertEqual(archive.read("covers/" + background_name), b"background")
            self.assertEqual(archive.read("audio/" + audio_name), MP3)
        Path(server.AUDIO_DIR, "shared", audio_name).unlink()
        status, result = core.http_json("POST", "/api/import", {
            "mode": "replace", "zip": base64.b64encode(exported).decode("ascii"),
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["audio"], 1)
        self.assertTrue(Path(server.AUDIO_DIR, "shared", audio_name).is_file())
        status, result = core.http_json("POST", "/api/backups/restore", {
            "kind": "write", "name": os.path.basename(legacy_snapshot), "confirm": "恢复",
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(core.http("GET", "/covers/" + cover_name), (200, b"cover"))

    def test_future_binding_and_cleanup_keep_snapshot_only_files(self):
        server = core.server
        server.load_library()
        self.assertIsNone(self.organize()["backup"])
        name = "a" * 16 + ".jpg"
        core.write_raw(os.path.join(server.COVER_DIR, name), "poster")
        status, result = core.http_json("POST", "/api/works", {
            "category": "novel", "draft": {"title": "Novel", "cover": "covers/" + name},
        })
        self.assertEqual(status, 200, result)
        work = result["work"]
        saved = Path(server.COVER_DIR, "novel", name)
        self.assertTrue(saved.is_file())
        self.assertEqual(work["cover"], "covers/" + name)
        self.assertEqual(core.http_json("DELETE", "/api/works/" + work["id"])[0], 200)
        orphan = Path(server.COVER_DIR, "novel", "b" * 16 + ".jpg")
        orphan.write_bytes(b"unused")
        old = time.time() - 2 * server.MEDIA_GRACE_SECONDS
        os.utime(orphan, (old, old))
        status, scanned = core.http_json("GET", "/api/media-cleanup")
        self.assertEqual(status, 200, scanned)
        self.assertEqual(scanned["backupOnly"], 1)
        self.assertEqual([(f["bucket"], f["name"]) for f in scanned["files"]], [("novel", orphan.name)])
        status, staged = core.http_json("POST", "/api/media-cleanup/stage", {"token": scanned["token"]})
        self.assertEqual(status, 200, staged)
        self.assertTrue(saved.is_file())
        self.assertFalse(orphan.exists())
        self.assertTrue(Path(staged["folder"], "covers", "novel", orphan.name).is_file())

    def test_failed_backup_leaves_assets_and_automatic_organization_disabled(self):
        server = core.server
        server.ensure_dirs()
        source = Path(server.COVER_DIR, "poster.jpg")
        source.write_bytes(b"cover")
        lib = server.default_library()
        lib["works"] = [dict(core.sample_work("book"), cover="covers/poster.jpg")]
        server.write_library(lib)
        with patch.object(server, "backup_media_layout", side_effect=OSError("disk full")):
            status, _ = core.http_json("POST", "/api/media-organize", {"organize": True})
        self.assertEqual(status, 500)
        self.assertTrue(source.is_file())
        self.assertFalse(Path(server.MEDIA_LAYOUT_PATH).exists())
