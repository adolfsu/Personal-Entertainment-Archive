"""系列可选背景的保存、校验和撤销，沿用隔离测试档案。"""
import json
import test_core as core


class TestSeriesBackgrounds(core.ServerCase):
    def test_series_backgrounds_persist_clear_export_and_undo(self):
        images = ['https://example.com/series.jpg', 'https://example.com/second.jpg']
        status, data = core.http_json('POST', '/api/series', {'name': '系列背景', 'immersiveBackgroundUrls': images + images})
        self.assertEqual(status, 200, data)
        sid = data['series']['id']
        self.assertEqual(data['series']['immersiveBackgroundUrls'], images)
        status, data = core.http_json('PATCH', '/api/series/' + sid, {'name': '改名'})
        self.assertEqual(status, 200, data)
        self.assertEqual(data['series']['immersiveBackgroundUrls'], images)
        _, raw = core.http('GET', '/api/export')
        self.assertEqual(json.loads(raw)['series'][0]['immersiveBackgroundUrls'], images)
        core.http_json('PATCH', '/api/series/' + sid, {'immersiveBackgroundUrls': []})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertNotIn('immersiveBackgroundUrls', data['series'][0])
        core.http_json('POST', '/api/undo', {})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(data['series'][0]['immersiveBackgroundUrls'], images)

    def test_invalid_series_backgrounds_do_not_change_library(self):
        _, data = core.http_json('POST', '/api/series', {'name': '保持原样'})
        sid = data['series']['id']
        before = core.read_bytes(core.server.LIB_PATH)
        for value in ['https://example.com/a', ['javascript:alert(1)'], ['https://example.com/%s' % i for i in range(21)]]:
            status, data = core.http_json('PATCH', '/api/series/' + sid, {'name': '不应保存', 'immersiveBackgroundUrls': value})
            self.assertEqual(status, 400, data)
            self.assertEqual(core.read_bytes(core.server.LIB_PATH), before)
