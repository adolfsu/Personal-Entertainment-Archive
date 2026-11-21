"""沉浸工具栏与多背景轮播实测，所有档案和图片仅在临时目录生成。"""
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='grdag-background-ui-') as temporary:
    base = Path(temporary)
    os.environ['GRDAG_BASE_DIR'] = temporary
    os.environ['GRDAG_SKIP_PROXY_DETECT'] = '1'
    sys.path.insert(0, str(ROOT))
    shutil.copytree(ROOT / 'web', base / 'web')
    shutil.copyfile(Path(__file__).with_name('backgrounds-browser.html'), base / 'web/backgrounds-browser.html')
    (base / 'VERSION').write_text((ROOT / 'VERSION').read_text(), encoding='utf-8')
    import server
    server.ensure_dirs()
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    origin = 'http://127.0.0.1:' + str(httpd.server_port)
    urls = []
    for index, (color, sun) in enumerate([('#365a78', '#d6c5a8'), ('#795449', '#efc885'), ('#34495b', '#b5ddc7')]):
        name = 'background-%s.svg' % index
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
        <defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="{color}"/><stop offset="1" stop-color="#151e28"/></linearGradient></defs>
        <rect width="1920" height="1080" fill="url(#sky)"/><circle cx="1370" cy="330" r="150" fill="{sun}"/>
        <path d="M0 800L350 440L730 770L1040 530L1420 790L1800 400L1920 570V1080H0" fill="#243747" opacity=".8"/>
        <path d="M0 940L570 660L1050 960L1560 670L1920 900V1080H0" fill="#13242e"/>
        <text x="1320" y="1040" fill="{sun}" font-size="22" letter-spacing="8">SCENE {index + 1}</text></svg>'''
        (base / 'web' / name).write_text(svg, encoding='utf-8')
        urls.append(origin + '/static/' + name)
    (base / 'data/covers/poster.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#365a78"/><circle cx="240" cy="220" r="100" fill="#d6c5a8"/></svg>', encoding='utf-8')
    lib = server.default_library()
    lib['settings'].update({'immersive_background_interval': 5, 'immersive_background_order': 'ordered'})
    for index, title in enumerate(['山海之间', '无背景作品', '其它分类作品']):
        work = server.normalize_work({'title': title, 'category': 'book' if index != 2 else 'game', 'cover': 'covers/poster.svg',
                                      'summary': '越过群山，在光与风中收藏一段旅程。\n仅供多背景和布局验收使用的合成资料。',
                                      'immersiveBackgroundUrls': urls if index == 0 else []})
        work['id'] = 'fixture-%s' % index
        lib['works'].append(work)
    server.write_library(lib)
    print(origin + '/static/backgrounds-browser.html', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
