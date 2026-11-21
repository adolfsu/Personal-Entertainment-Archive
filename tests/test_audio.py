"""BGM 资源、绑定、撤销与迁移，全部使用临时档案。"""
import base64
import hashlib
import io
import json
import os
import zipfile
import urllib.request
import urllib.error
import test_core as core

MP3 = (b'\xff\xfb\x90\x64' + b'\x00' * 413) * 100


def request(method, path, raw=None, headers=None):
    req = urllib.request.Request(core.BASE_URL + path, data=raw, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


class TestAudio(core.ServerCase):
    def upload(self):
        status, raw, _ = request('POST', '/api/audio', MP3, {'Content-Type':'audio/mpeg','X-Audio-Name':'Test%20BGM'})
        self.assertEqual(status, 200, raw)
        return json.loads(raw)['bgm']

    def test_upload_deduplicates_and_streams_ranges_and_head(self):
        music = self.upload()
        self.assertEqual(music, self.upload())
        self.assertEqual(len(os.listdir(core.server.AUDIO_DIR)), 1)
        self.assertEqual(music['src'], '/audio/' + hashlib.sha256(MP3).hexdigest() + '.mp3')
        for byte_range, expected in [('bytes=3-12',MP3[3:13]),('bytes=-10',MP3[-10:]),('bytes=100-',MP3[100:])]:
            status, raw, headers = request('GET', music['src'], headers={'Range':byte_range})
            self.assertEqual(status, 206)
            self.assertEqual(raw, expected)
            self.assertEqual(headers['Content-Type'], 'audio/mpeg')
        status, raw, headers = request('HEAD', music['src'])
        self.assertEqual(status, 200)
        self.assertEqual(raw, b'')
        self.assertEqual(int(headers['Content-Length']),len(MP3))
        self.assertEqual(request('GET',music['src'],headers={'Range':'bytes=999999-1000000'})[0],416)
        self.assertEqual(request('GET','/audio/../../server.py')[0],404)

    def test_upload_rejects_invalid_audio_and_corrupt_library(self):
        self.assertEqual(request('POST','/api/audio',b'not mp3')[0],400)
        self.assertEqual(request('POST','/api/audio',b'')[0],413)
        core.write_raw(core.server.LIB_PATH,'broken')
        self.assertEqual(request('POST','/api/audio',MP3)[0],409)
        self.assertEqual(core.read_bytes(core.server.LIB_PATH),b'broken')

    def test_work_and_series_bgm_save_unbind_and_undo_keep_audio(self):
        music = self.upload()
        status, data = core.http_json('POST','/api/works',{'category':'book','draft':{'title':'测试音乐','bgm':music}})
        self.assertEqual(status,200,data)
        wid = data['work']['id']
        _, series = core.http_json('POST','/api/series',{'name':'音乐系列','bgm':music})
        self.assertEqual(series['series']['bgm'],music)
        core.http_json('PATCH','/api/works/'+wid,{'title':'改名'})
        core.http_json('PATCH','/api/works/'+wid,{'bgm':None})
        _, data = core.http_json('GET','/api/bootstrap')
        self.assertNotIn('bgm', data['works'][0])
        self.assertEqual(request('GET',music['src'])[0],200)
        core.http_json('POST','/api/undo',{})
        _, data = core.http_json('GET','/api/bootstrap')
        self.assertEqual(data['works'][0]['bgm'],music)

    def test_invalid_bgm_is_rejected_without_mutation(self):
        _, data = core.http_json('POST','/api/series',{'name':'音乐'})
        path = '/api/series/'+data['series']['id']
        before=core.read_bytes(core.server.LIB_PATH)
        for music in ['bad',{'src':'javascript:alert(1)'},{'src':'file:///x.mp3'},{'src':'http://example.com/a.mp3'}, {'src':'/audio/../library.json'}, {'src':'https://user:pass@example.com/a'}]:
            self.assertEqual(core.http_json('PATCH',path,{'bgm':music})[0],400)
            self.assertEqual(core.read_bytes(core.server.LIB_PATH),before)
        status, data=core.http_json('PATCH',path,{'bgm':{'src':'https://example.com/a.mp3','title':'曲名'}})
        self.assertEqual(status,200,data)

    def test_zip_restores_audio_and_json_contains_only_binding(self):
        music=self.upload()
        core.http_json('POST','/api/works',{'category':'book','draft':{'title':'音乐','bgm':music}})
        _, raw=core.http('GET','/api/export')
        self.assertEqual(json.loads(raw)['works'][0]['bgm'],music)
        _, raw=core.http('GET','/api/export?covers=1')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.read(music['src'].lstrip('/')),MP3)
        os.remove(os.path.join(core.server.AUDIO_DIR,music['src'].split('/')[-1]))
        status,data=core.http_json('POST','/api/import',{'mode':'replace','zip':base64.b64encode(raw).decode()})
        self.assertEqual(status,200,data)
        self.assertEqual(data['audio'],1)
        self.assertEqual(request('GET',music['src'])[1],MP3)

    def test_tampered_zip_audio_does_not_replace_archive(self):
        music=self.upload()
        before=core.read_bytes(core.server.LIB_PATH)
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as archive:
            archive.writestr('library.json',json.dumps({'works':[],'series':[]}))
            archive.writestr(music['src'].lstrip('/'),b'fake')
        status,data=core.http_json('POST','/api/import',{'mode':'replace','zip':base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(status,400,data)
        self.assertEqual(core.read_bytes(core.server.LIB_PATH),before)
