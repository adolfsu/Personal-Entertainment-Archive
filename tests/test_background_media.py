"""本地沉浸原图：下载、绑定、迁移和损坏保护，全部使用隔离档案。"""
import base64
import hashlib
import io
import json
import os
import struct
import tempfile
import zipfile
import zlib
from unittest import mock
import test_core as core


def png(color=(43, 76, 102)):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    pixels = (b'\x00' + bytes(color) * 32) * 24
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 24, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


class TestLocalBackgroundMedia(core.ServerCase):
    def test_local_upload_validates_bytes_and_saves_deduplicated_original(self):
        raw = png((11, 90, 180))
        request = core.urllib.request.Request(core.BASE_URL + '/api/backgrounds/local', data=raw, method='POST', headers={'Content-Type':'application/octet-stream'})
        with core.urllib.request.urlopen(request, timeout=15) as response:
            status, result = response.status, json.loads(response.read())
        self.assertEqual(status, 200)
        url = result['image']['url']
        self.assertEqual(url, '/covers/background_' + hashlib.sha256(raw).hexdigest() + '.png')
        self.assertEqual(core.http('GET', url)[1], raw)
        self.assertEqual(len(os.listdir(core.server.COVER_DIR)), 1)

    def test_local_upload_rejects_invalid_and_oversized_files(self):
        for raw in [b'not an image']:
            request = core.urllib.request.Request(core.BASE_URL + '/api/backgrounds/local', data=raw, method='POST', headers={'Content-Type':'application/octet-stream'})
            status = None
            try:
                with core.urllib.request.urlopen(request, timeout=15) as response: status = response.status
            except core.urllib.error.HTTPError as error: status = error.code
            self.assertEqual(status, 400)
        self.assertEqual(os.listdir(core.server.COVER_DIR), [])

    def add(self, color=(43, 76, 102)):
        raw = png(color)
        with mock.patch.object(core.server, 'download_background_image', return_value=raw):
            status, data = core.http_json('POST', '/api/backgrounds', {'url': 'https://example.com/original.png'})
        self.assertEqual(status, 200, data)
        return data['image']['url'], raw

    def test_download_keeps_original_bytes_deduplicates_and_does_not_save_form(self):
        core.server.load_library()
        before = core.read_bytes(core.server.LIB_PATH)
        url, raw = self.add()
        again, _ = self.add()
        self.assertEqual(url, again)
        self.assertEqual(url, '/covers/background_' + hashlib.sha256(raw).hexdigest() + '.png')
        status, served = core.http('GET', url)
        self.assertEqual(status, 200)
        self.assertEqual(served, raw)
        self.assertEqual(len(os.listdir(core.server.COVER_DIR)), 1)
        self.assertEqual(core.read_bytes(core.server.LIB_PATH), before)

    def test_invalid_links_and_non_images_leave_no_resource_or_library_changes(self):
        core.server.load_library()
        before = core.read_bytes(core.server.LIB_PATH)
        with mock.patch.object(core.server, 'download_background_image', return_value=png()) as download:
            for url in ['', None, 'javascript:alert(1)', 'file:///etc/passwd', '/covers/image.png',
                        'https://user:pass@example.com/a.png', 'https://example.com/a b.png']:
                self.assertEqual(core.http_json('POST', '/api/backgrounds', {'url': url})[0], 400)
            download.assert_not_called()
        for raw in [b'', b'<html>not an image</html>']:
            with mock.patch.object(core.server, 'download_background_image', return_value=raw):
                self.assertEqual(core.http_json('POST', '/api/backgrounds', {'url':'https://example.com/a'})[0], 400)
        with mock.patch.object(core.server, 'BACKGROUND_IMAGE_LIMIT', 16):
            with mock.patch.object(core.server, 'download_background_image', return_value=png()):
                self.assertEqual(core.http_json('POST', '/api/backgrounds', {'url':'https://example.com/a'})[0], 400)
        self.assertEqual(os.listdir(core.server.COVER_DIR), [])
        self.assertEqual(core.read_bytes(core.server.LIB_PATH), before)

    def test_network_read_is_bounded_even_without_content_length(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {}
        response.read.return_value = b'x' * 17
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(core.server, 'BACKGROUND_IMAGE_LIMIT', 16), \
             mock.patch.object(core.server, 'resolve_proxy', return_value=None), \
             mock.patch.object(core.server, 'build_opener', return_value=opener):
            with self.assertRaises(ValueError):
                core.server.download_background_image('https://example.com/a.png')
        response.read.assert_called_once_with(17)

    def test_local_order_preserved_for_work_series_and_undo_without_redownload(self):
        first, _ = self.add()
        second, _ = self.add((120, 75, 42))
        for route, body, key in [('/api/works', {'category':'book','draft':{'title':'本地背景','immersiveBackgroundUrls':[first, second]}}, 'work'),
                                 ('/api/series', {'name':'本地系列','immersiveBackgroundUrls':[first, second]}, 'series')]:
            status, data = core.http_json('POST', route, body)
            self.assertEqual(status, 200, data)
            target = route + '/' + data[key]['id']
            with mock.patch.object(core.server, 'download_background_image') as download:
                status, data = core.http_json('PATCH', target, {'immersiveBackgroundUrls':[second, first]})
                self.assertEqual(status, 200, data)
                self.assertEqual(data[key]['immersiveBackgroundUrls'], [second, first])
                self.assertEqual(data[key]['immersiveBackgroundUrl'], second)
                download.assert_not_called()
            before = core.read_bytes(core.server.LIB_PATH)
            for bad in ['/covers/../secret.png', '/covers/%2e%2e.png', '/covers/a.png?x=1', '//evil.com/a.png']:
                self.assertEqual(core.http_json('PATCH', target, {'immersiveBackgroundUrls':[bad]})[0], 400)
                self.assertEqual(core.read_bytes(core.server.LIB_PATH), before)
            core.http_json('POST', '/api/undo', {})
            _, lib = core.http_json('GET', '/api/bootstrap')
            entity = next(item for item in lib['works' if key == 'work' else 'series'] if item['id'] == data[key]['id'])
            self.assertEqual(entity['immersiveBackgroundUrls'], [first, second])

    def test_complete_zip_restores_work_and_series_backgrounds_and_deduplicates_cover(self):
        first, first_raw = self.add()
        second, second_raw = self.add((120, 75, 42))
        core.http_json('POST', '/api/works', {'category':'book','draft':{'title':'作品','cover':first.lstrip('/'),'immersiveBackgroundUrls':[first]}})
        core.http_json('POST', '/api/series', {'name':'系列','immersiveBackgroundUrls':[second, first]})
        status, raw = core.http('GET', '/api/export?covers=1')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            for path, expected in [(first, first_raw), (second, second_raw)]:
                self.assertEqual(archive.read(path.lstrip('/')), expected)
                os.remove(os.path.join(core.server.COVER_DIR, path.rsplit('/', 1)[-1]))
        status, data = core.http_json('POST', '/api/import', {'mode':'replace','zip':base64.b64encode(raw).decode()})
        self.assertEqual(status, 200, data)
        self.assertEqual(core.http('GET', first)[1], first_raw)
        self.assertEqual(core.http('GET', second)[1], second_raw)
        _, lib = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(lib['series'][0]['immersiveBackgroundUrls'], [second, first])

    def test_clear_data_safety_backup_includes_background_originals(self):
        url, raw = self.add()
        core.http_json('POST', '/api/series', {'name':'系列','immersiveBackgroundUrls':[url]})
        with tempfile.TemporaryDirectory(dir=core.TMP) as folder:
            with mock.patch.object(core.server, 'SIBLING_BACKUP_DIR', folder):
                status, data = core.http_json('POST', '/api/clear-data', {'confirm':'清空全部'})
            self.assertEqual(status, 200, data)
            with zipfile.ZipFile(data['backup_path']) as archive:
                self.assertEqual(archive.read(url.lstrip('/')), raw)

    def test_corrupt_library_blocks_download_and_resource_writes(self):
        core.write_raw(core.server.LIB_PATH, 'broken')
        with mock.patch.object(core.server, 'download_background_image') as download:
            self.assertEqual(core.http_json('POST', '/api/backgrounds', {'url':'https://example.com/a.png'})[0], 409)
            download.assert_not_called()
        self.assertEqual(core.read_bytes(core.server.LIB_PATH), b'broken')

