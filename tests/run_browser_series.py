"""阶段 4 隔离浏览器验收；全部素材和档案在临时目录生成。"""
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='grdag-series-ui-') as temporary:
    base = Path(temporary)
    os.environ['GRDAG_BASE_DIR'] = temporary
    os.environ['GRDAG_SKIP_PROXY_DETECT'] = '1'
    sys.path.insert(0, str(ROOT))
    shutil.copytree(ROOT / 'web', base / 'web')
    shutil.copyfile(Path(__file__).with_name('series-browser.html'), base / 'web/series-browser.html')
    shutil.copyfile(ROOT / 'VERSION', base / 'VERSION')
    import server
    server.ensure_dirs()
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    origin = 'http://127.0.0.1:' + str(httpd.server_port)
    colors = [('#567380', '#dcc89e'), ('#786350', '#e6bd8c'), ('#405e59', '#c6d6a5')]
    urls = []
    for i, (color, moon) in enumerate(colors):
        name = 'series-scene-%s.svg' % i
        (base / 'web' / name).write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><defs><linearGradient id="g" x2="0" y2="1"><stop stop-color="{color}"/><stop offset="1" stop-color="#15262d"/></linearGradient></defs><rect width="1920" height="1080" fill="url(#g)"/><circle cx="1430" cy="290" r="145" fill="{moon}"/><path d="M0 800L300 450L700 790L1000 430L1500 800L1800 430L1920 600V1080H0" fill="#243c43"/><path d="M0 940L500 710L900 970L1500 730L1920 900V1080H0" fill="#13272e"/></svg>''', encoding='utf-8')
        urls.append(origin + '/static/' + name)
    lib = server.default_library()
    lib['settings'].update({'immersive_background_interval': 5, 'immersive_background_order': 'ordered'})
    for sid, name, summary in [('mixed', '山海之间', '穿过群山与海岸，收藏同一世界的不同回声。\n从文字到影像，再到亲手探索的旅程。'), ('books', '纸上的远行', '翻开一页，走进另一片天地。\n小说、漫画与出版书，共同构成一座安静的书房。'), ('empty', '等待第一件收藏', ''), ('broken', '失效背景回退', '用于验证图片加载失败后的柔和背景。')]:
        series = server.normalize_series({'name':name,'summary':summary})
        series['id'] = sid
        if sid == 'mixed': series['rating'] = 9.0
        lib['series'].append(series)
    categories = ['anime', 'game', 'manga', 'book', 'novel']
    titles = ['山海之间 · 动画', '山海之间 · 游戏', '山海之间 · 漫画', '山海之间 · 原著', '山海之间 · 长篇', '海风来信', '山间余音', '归途', '远方的灯塔', '潮汐笔记', '雨后的森林', '最后一页']
    for i, title in enumerate(titles + ['远行：山川', '远行：城市', '远行：归乡', '回退测试']):
        sid = 'mixed' if i < 12 else 'books' if i < 15 else 'broken'
        color, moon = colors[i % 3]
        poster = 'series-poster-%s.svg' % i
        (base / 'data/covers' / poster).write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="{color}"/><circle cx="260" cy="190" r="90" fill="{moon}"/><path d="M0 430L150 220L400 480V600H0" fill="#20333b"/><text x="32" y="495" fill="#f4ead5" font-family="serif" font-size="30">山 海 典 藏</text><text x="32" y="540" fill="#d0d5d0" font-size="16">VOL. {i+1:02}</text></svg>''', encoding='utf-8')
        work = server.normalize_work({'title':title, 'category':categories[i % 5] if i < 12 else ('book' if i != 13 else 'manga'), 'year':str(2010 + i), 'cover':'covers/' + poster,
            'summary':'一段有关远方、记忆与归途的旅程。', 'immersiveBackgroundUrls':urls[:2] if i == 0 else urls[2:] if i == 1 else [origin + '/static/missing.svg'] if sid == 'broken' else []})
        work['id'] = 'work-%s' % i
        work['seriesLinks'] = [{'id':sid,'role':'main'}]
        if i % 3 == 0:
            work['rating'] = 8.5
            work['experiences'] = [{'id':'exp','date':'2026-11-01','status':'completed','content':'已完成，留下这段旅程。'}]
        lib['works'].append(work)
    lib['series'][-1]['cover'] = 'covers/missing.jpg'
    server.write_library(lib)
    print(origin + '/static/series-browser.html', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
