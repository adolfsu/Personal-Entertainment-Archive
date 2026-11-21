"""沉浸背景多图与全局播放偏好，使用 test_core 的隔离档案。"""
import json
import test_core as core


class TestBackgrounds(core.ServerCase):
    def create_work(self, **fields):
        status, data = core.http_json('POST', '/api/works', {'category': 'book', 'draft': {'title': '背景测试', **fields}})
        self.assertEqual(status, 200, data)
        return data['work']

    def test_legacy_background_and_multiple_background_edit(self):
        work = self.create_work(immersiveBackgroundUrl='https://example.com/old.jpg')
        self.assertEqual(work['immersiveBackgroundUrls'], ['https://example.com/old.jpg'])
        url = '/api/works/' + work['id']
        images = ['https://example.com/2.jpg', 'https://example.com/1.jpg']
        status, data = core.http_json('PATCH', url, {'immersiveBackgroundUrls': images + images})
        self.assertEqual(status, 200, data)
        self.assertEqual(data['work']['immersiveBackgroundUrls'], images)
        core.http_json('PATCH', url, {'title': '仅修改标题'})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(data['works'][0]['immersiveBackgroundUrls'], images)
        _, raw = core.http('GET', '/api/export')
        exported = json.loads(raw)
        self.assertEqual(exported['works'][0]['immersiveBackgroundUrls'], images)
        core.http_json('PATCH', url, {'immersiveBackgroundUrls': []})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertNotIn('immersiveBackgroundUrls', data['works'][0])
        self.assertNotIn('immersiveBackgroundUrl', data['works'][0])
        core.http_json('POST', '/api/undo', {})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(data['works'][0]['immersiveBackgroundUrls'], images)

    def test_invalid_list_rejected_without_altering_work(self):
        work = self.create_work(immersiveBackgroundUrls=['https://example.com/a.jpg'])
        before = core.read_bytes(core.server.LIB_PATH)
        for invalid in ['https://example.com/a.jpg', ['javascript:alert(1)'], ['https://example.com/%s' % i for i in range(21)]]:
            status, data = core.http_json('PATCH', '/api/works/'+work['id'], {'immersiveBackgroundUrls': invalid})
            self.assertEqual(status, 400, data)
            self.assertEqual(core.read_bytes(core.server.LIB_PATH), before)

    def test_global_slideshow_settings_persist_and_invalid_values_do_not_write(self):
        status, data = core.http_json('POST', '/api/settings', {'immersive_background_interval': 8, 'immersive_background_order': 'random'})
        self.assertEqual(status, 200, data)
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(data['settings']['immersive_background_interval'], 8)
        self.assertEqual(data['settings']['immersive_background_order'], 'random')
        before = core.read_bytes(core.server.LIB_PATH)
        for invalid in [{'immersive_background_interval': 0}, {'immersive_background_interval': 301}, {'immersive_background_order': 'invalid'}]:
            status, data = core.http_json('POST', '/api/settings', invalid)
            self.assertEqual(status, 400, data)
            self.assertEqual(core.read_bytes(core.server.LIB_PATH), before)
