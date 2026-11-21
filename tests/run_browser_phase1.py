"""临时浏览器验收服务。运行后访问打印的网址；Ctrl+C 清理退出。"""
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent

with tempfile.TemporaryDirectory(prefix='grdag-phase1-ui-') as temporary:
    os.environ['GRDAG_BASE_DIR'] = temporary
    os.environ['GRDAG_SKIP_PROXY_DETECT'] = '1'
    sys.path.insert(0, str(ROOT))
    shutil.copytree(ROOT / 'web', Path(temporary) / 'web')
    shutil.copyfile(Path(__file__).with_name('phase1-browser.html'), Path(temporary) / 'web/phase1-browser.html')
    (Path(temporary) / 'VERSION').write_text((ROOT / 'VERSION').read_text(), encoding='utf-8')
    import server
    server.load_library()
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    print('http://127.0.0.1:'+str(httpd.server_port)+'/static/phase1-browser.html', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
