"""阶段 1 回归：沿用 test_core 的临时档案，不接触实际 data。"""
import json

import test_core as core


class TestPhase1Data(core.ServerCase):
    def create_members(self):
        _, s1 = core.http_json('POST', '/api/series', {'name': '系列一'})
        _, s2 = core.http_json('POST', '/api/series', {'name': '系列二'})
        _, work = core.http_json('POST', '/api/works', {'category': 'book', 'draft': {'title': '作品'}})
        wid = work['work']['id']
        for series in (s1, s2):
            status, data = core.http_json('POST', '/api/series/'+series['series']['id']+'/members', {'workIds': [wid]})
            self.assertEqual(status, 200, data)
        return wid, s1['series']['id']

    def test_bootstrap_aggregates_both_series_after_member_changes(self):
        wid, _ = self.create_members()
        core.http_json('POST', '/api/works/'+wid+'/rating', {'score': 8})
        core.http_json('POST', '/api/works/'+wid+'/experience', {'date': '2026-11-20', 'status': 'completed'})
        core.http_json('PATCH', '/api/works/'+wid, {'title': '新标题'})
        _, data = core.http_json('GET', '/api/bootstrap')
        for s in data['series']:
            self.assertEqual(s['avgRating'], 8)
            self.assertEqual(s['progress'], '1/1')
            self.assertEqual(s['members'][0]['title'], '新标题')
        core.http_json('DELETE', '/api/works/'+wid)
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertTrue(all(s['memberCount'] == 0 and s['avgRating'] is None for s in data['series']))

    def test_clear_series_fields_without_erasing_unsubmitted_fields(self):
        _, data = core.http_json('POST', '/api/series', {'name': '系列', 'originalTitle': 'Old', 'summary': '简介', 'note': '备注', 'tags': ['标签']})
        url = '/api/series/'+data['series']['id']
        status, data = core.http_json('PATCH', url, {'summary': '', 'tags': []})
        self.assertEqual(status, 200, data)
        self.assertEqual(data['series']['summary'], '')
        self.assertEqual(data['series']['tags'], [])
        self.assertEqual(data['series']['note'], '备注')
        _, data = core.http_json('PATCH', url, {'originalTitle': '', 'note': ''})
        self.assertEqual(data['series']['originalTitle'], '')
        self.assertEqual(data['series']['note'], '')
        core.http_json('POST', '/api/undo', {})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(data['series'][0]['note'], '备注')

    def test_import_replace_and_restore_keep_series_snapshot_complete(self):
        self.create_members()
        _, raw = core.http('GET', '/api/export')
        exported = json.loads(raw)
        status, _ = core.http_json('POST', '/api/import', {'mode': 'replace', 'data': {'version': 2, 'works': [], 'series': []}})
        self.assertEqual(status, 200)
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(data['series'], [])
        core.http_json('POST', '/api/import', {'mode': 'replace', 'data': exported})
        _, data = core.http_json('GET', '/api/bootstrap')
        self.assertEqual(len(data['series']), 2)
        self.assertTrue(all(s['memberCount'] == 1 for s in data['series']))
