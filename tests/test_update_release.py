import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import update_release as updater


class TestUpdateRelease(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        (self.base / "web").mkdir()
        (self.base / "web/index.html").write_text("old", encoding="ascii")
        for name in ("server.py", "update_release.py", *updater.DOCS):
            (self.base / name).write_text("# old", encoding="ascii")
        (self.base / "VERSION").write_text("1.9.0\n", encoding="ascii")
        for name in ("data", "backups", "runtime"):
            (self.base / name).mkdir()
            (self.base / name / "keep").write_bytes(name.encode())

    def test_release_package_contains_only_program_files(self):
        output = updater.build_package(self.base, self.base / "dist", 2)
        release = updater.validate_release(updater.read_json(output / updater.METADATA))
        with zipfile.ZipFile(output / updater.PACKAGE) as package:
            self.assertTrue(all(updater.allowed_file(name) or name == updater.METADATA for name in package.namelist()))
        self.assertEqual(updater.eligibility(release, "1.8.0", 2), "available")
        self.assertEqual(updater.eligibility(release, "1.9.0", 2), "current")
        self.assertEqual(updater.eligibility(release, "1.10.0", 2), "current")
        self.assertEqual(updater.eligibility(release, "1.8.0", 3), "incompatible")
        self.assertEqual(updater.eligibility(release, "0.8.0", 2), "incompatible")

    def test_integrity_and_path_whitelist_checked_before_extraction(self):
        package = self.base / updater.PACKAGE
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("data/library.json", "{}")
        release = dict(format=1, version="1.10.0", archiveSchema=2, bytes=package.stat().st_size, sha256="0" * 64)
        with self.assertRaisesRegex(updater.UpdateError, "SHA-256"):
            updater.unpack_package(package, self.base / "unpack", release)
        release["sha256"] = updater.digest_file(package)
        with self.assertRaises(updater.UpdateError):
            updater.unpack_package(package, self.base / "unpack", release)
        self.assertFalse((self.base / "unpack").exists())
        self.assertFalse(updater.is_safe_download("https://example.com/package"))

    def test_falls_back_to_cnb_mirror_when_github_unreachable(self):
        payload = json.dumps({"format": 1, "version": "1.10.1", "archiveSchema": 2,
                              "bytes": 10, "sha256": "a" * 64, "notes": "n"}).encode()
        opened = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self, _size):
                return payload

        def fake_open(url, hosts=updater.GITHUB_HOSTS):
            opened.append(url)
            if "github.com" in url:
                raise updater.URLError("blocked")
            return FakeResponse()

        with patch.object(updater, "open_release", side_effect=fake_open):
            release = updater.fetch_release()
        self.assertEqual(release["source"], "CNB")
        self.assertEqual(release["version"], "1.10.1")
        self.assertTrue(opened[0].startswith(updater.GITHUB))
        self.assertTrue(opened[1].startswith(updater.CNB))
        self.assertEqual(updater.release_source(release)[0], updater.CNB)
        self.assertFalse(updater.is_safe_download("https://cnb.cool.example.com/package", updater.CNB_HOSTS))

        def not_found(url, hosts=updater.GITHUB_HOSTS):
            raise updater.HTTPError(url, 404, "Not Found", None, None)

        with patch.object(updater, "open_release", side_effect=not_found):
            self.assertIsNone(updater.fetch_release())

    def test_failed_start_restores_program_and_preserves_data(self):
        work = self.base / ".pea-updates/fixture"
        new = work / "new"
        (new / "web").mkdir(parents=True)
        (new / "web/index.html").write_text("new", encoding="ascii")
        (new / "VERSION").write_text("1.10.0\n", encoding="ascii")
        (work / "stopped").touch()
        updater.write_json(work / "job.json", {"old": "1.9.0", "new": "1.10.0", "port": 12345})
        versions = []

        def start(base, _work, version, port, _job):
            self.assertEqual(port, 12345)
            self.assertEqual((base / "VERSION").read_text().strip(), version)
            versions.append(version)
            if version == "1.10.0":
                raise updater.UpdateError("test startup failure")

        with patch.object(updater, "start_program", side_effect=start):
            updater.apply_update(work)
        self.assertEqual(versions, ["1.10.0", "1.9.0"])
        self.assertEqual(updater.update_state(work.parent)["phase"], "rolled-back")
        self.assertEqual((self.base / "web/index.html").read_text(), "old")
        for name in ("data", "backups", "runtime"):
            self.assertEqual((self.base / name / "keep").read_bytes(), name.encode())
