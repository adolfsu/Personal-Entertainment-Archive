"""隔离验收：链接添加、拖动排序、离线读取；原图源可通过临时标记关闭。"""
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent.parent


def scene_png(top, sun):
    width, height = 1920, 1080
    rows = []
    for y in range(height):
        rgb = tuple(round(channel * (1 - y / height * .65)) for channel in top)
        row = bytearray(bytes(rgb) * width)
        if abs(y - 330) < 145:
            half = int(math.sqrt(145 ** 2 - (y - 330) ** 2))
            row[(1370 - half) * 3:(1370 + half) * 3] = bytes(sun) * (2 * half)
        if y > 750:
            row[:] = bytes((18 + y // 180, 37 + y // 160, 43 + y // 140)) * width
        rows.append(b'\x00' + row)
    def chunk(kind, payload):
        return struct.pack('>I',len(payload)) + kind + payload + struct.pack('>I',zlib.crc32(kind + payload) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))
            + chunk(b'IDAT',zlib.compress(b''.join(rows))) + chunk(b'IEND',b''))


with tempfile.TemporaryDirectory(prefix='grdag-background-editor-') as folder:
    base = Path(folder)
    os.environ['GRDAG_BASE_DIR'] = folder
    os.environ['GRDAG_SKIP_PROXY_DETECT'] = '1'
    sys.path.insert(0,str(ROOT))
    shutil.copytree(ROOT / 'web',base / 'web')
    shutil.copyfile(ROOT / 'VERSION',base / 'VERSION')
    flag = base / 'source-enabled.txt'
    flag.write_text('on',encoding='utf-8')
    pictures = {f'/scene-{index + 1}.png':scene_png(top,sun) for index,(top,sun) in enumerate([
        ((54,90,120),(214,197,168)),((133,78,61),(239,200,133)),((47,101,92),(181,221,199))])}
    class Source(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            raw = pictures.get(self.path) if flag.read_text(encoding='utf-8').strip() == 'on' else None
            self.send_response(200 if raw else 503)
            self.send_header('Content-Type','image/png' if raw else 'text/plain')
            self.send_header('Content-Length',str(len(raw or b'unavailable')))
            self.end_headers()
            self.wfile.write(raw or b'unavailable')
    source = ThreadingHTTPServer(('127.0.0.1',0),Source)
    threading.Thread(target=source.serve_forever,daemon=True).start()
    remote = f'http://127.0.0.1:{source.server_port}'
    import server
    server.ensure_dirs()
    (base / 'data/covers/poster.png').write_bytes(pictures['/scene-1.png'])
    lib = server.default_library()
    work = server.normalize_work({'title':'山海之间','category':'book','cover':'covers/poster.png',
        'summary':'仅供沉浸图片管理验收使用的合成档案。','immersiveBackgroundUrls':[remote + '/scene-1.png']})
    work['id'] = 'fixture-work'
    work['experiences'] = [{'id':'fixture-exp','date':'2026-11-21','status':'active','content':'继续阅读','createdAt':'2026-11-21T12:00:00'}]
    work['seriesLinks'] = [{'id':'fixture-series','role':'main','required':True}]
    lib['works'] = [work]
    series = server.normalize_series({'name':'山海旅程','summary':'用于验证系列图片管理。'})
    series['id'] = 'fixture-series'
    lib['series'] = [series]
    server.write_library(lib)
    httpd = server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    print(json.dumps({'preview':f'http://127.0.0.1:{httpd.server_port}','images':[remote + path for path in pictures],
                      'sourceFlag':str(flag),'temporaryData':str(base / 'data')},ensure_ascii=False),flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        source.shutdown()
        source.server_close()
