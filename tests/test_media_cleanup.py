import json
import os
import time

import test_core as core


SCAN = "/api/media-cleanup"
STAGE = SCAN + "/stage"


class TestMediaCleanup(core.ServerCase):
    def media(self, kind, name, recent=False):
        core.server.ensure_dirs()
        path = os.path.join(core.server.DATA_DIR, kind, name)
        core.write_raw(path, name)
        if not recent:
            old = time.time() - 2 * core.server.MEDIA_GRACE_SECONDS
            os.utime(path, (old, old))
        return path

    def test_moves_only_unused_managed_media_and_preserves_original_bytes(self):
        cover, background, old_background, orphan_image = [c * 16 + ".jpg" for c in "abcd"]
        music, daily_music, orphan_audio, recent = [c * 64 + ".mp3" for c in "abcd"]
        use_cover = self.media("covers", cover)
        use_background = self.media("covers", background)
        protect_legacy = self.media("covers", old_background)
        protect_audio = self.media("audio", daily_music)
        use_audio = self.media("audio", music)
        unknown = self.media("covers", "personal.jpg")
        recent_audio = self.media("audio", recent, recent=True)
        source_image = self.media("covers", orphan_image)
        source_audio = self.media("audio", orphan_audio)
        lib = core.server.default_library()
        work = core.sample_work("work")
        work["cover"] = "covers/" + cover
        work["immersiveBackgroundUrls"] = ["/covers/" + background]
        lib["works"] = [work]
        lib["series"] = [{"id": "series", "name": "Series", "cover": "/covers/" + cover,
                         "bgm": {"src": "/audio/" + music}}]
        core.server.write_library(lib)
        snapshot = core.server.default_library()
        record = core.sample_work("snapshot")
        record["immersiveBackgroundUrl"] = "/covers/" + old_background
        snapshot["works"] = [record]
        core.write_raw(os.path.join(core.server.PRE_RESTORE_DIR, "old.json"), json.dumps(snapshot))
        snapshot["series"] = [{"id": "series", "bgm": {"src": "/audio/" + daily_music}}]
        core.write_raw(os.path.join(core.server.DAILY_BACKUP_DIR, "daily.json"), json.dumps(snapshot))

        archive_before = core.read_bytes(core.server.LIB_PATH)
        image_before, audio_before = map(core.read_bytes, (source_image, source_audio))
        status, result = core.http_json("GET", SCAN)
        self.assertEqual(status, 200, result)
        self.assertEqual({row["name"] for row in result["files"]}, {orphan_image, orphan_audio})
        self.assertEqual((result["backupOnly"], result["recent"]), (2, 1))
        self.assertFalse(os.path.exists(result["folder"]))
        self.assertTrue(os.path.exists(source_image))
        status, staged = core.http_json("POST", STAGE, {"token": result["token"]})
        self.assertEqual(status, 200, staged)
        self.assertEqual((staged["moved"], staged["bytes"], staged["skipped"]), (2, result["bytes"], []))
        self.assertEqual(os.path.dirname(staged["folder"]), core.server.MEDIA_STAGING_DIR)
        self.assertEqual(core.read_bytes(os.path.join(staged["folder"], "covers", orphan_image)), image_before)
        self.assertEqual(core.read_bytes(os.path.join(staged["folder"], "audio", orphan_audio)), audio_before)
        self.assertFalse(os.path.exists(source_image))
        self.assertFalse(os.path.exists(source_audio))
        self.assertTrue(all(os.path.isfile(path) for path in
                            (use_cover, use_background, protect_legacy, protect_audio, use_audio, unknown, recent_audio)))
        self.assertEqual(core.read_bytes(core.server.LIB_PATH), archive_before)

    def test_rechecks_references_and_refuses_unreadable_backups(self):
        name = "f" * 16 + ".jpg"
        path = self.media("covers", name)
        lib = core.server.default_library()
        core.server.write_library(lib)
        _, result = core.http_json("GET", SCAN)
        snapshot_path = os.path.join(core.server.BACKUP_DIR, "library_20000101_000000.json")
        work = core.sample_work("shared")
        work["cover"] = "/covers/" + name
        lib["works"] = [work]
        core.write_raw(snapshot_path, json.dumps(lib))
        status, _ = core.http_json("POST", STAGE, {"token": result["token"]})
        self.assertEqual(status, 409)
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(core.server.MEDIA_STAGING_DIR))

        core.write_raw(snapshot_path, "{unreadable")
        self.assertEqual(core.http_json("GET", SCAN)[0], 409)
        self.assertEqual(core.http_json("POST", STAGE, {"token": result["token"]})[0], 409)
        self.assertTrue(os.path.isfile(path))
