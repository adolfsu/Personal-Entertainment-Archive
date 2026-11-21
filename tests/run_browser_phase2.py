"""阶段 2 浏览器测试：仅使用临时合成档案和本地测试封面。"""
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent

with tempfile.TemporaryDirectory(prefix='grdag-phase2-ui-') as temporary:
    base = Path(temporary)
    os.environ['GRDAG_BASE_DIR'] = temporary
    os.environ['GRDAG_SKIP_PROXY_DETECT'] = '1'
    sys.path.insert(0, str(ROOT))
    shutil.copytree(ROOT / 'web', base / 'web')
    for name in ('phase2-browser.html', 'phase1-browser.html'):
        shutil.copyfile(Path(__file__).with_name(name), base / 'web' / name)
    (base / 'VERSION').write_text((ROOT / 'VERSION').read_text(), encoding='utf-8')
    import server
    server.ensure_dirs()
    for index, (title, color, accent) in enumerate([
        ('ORBIT', '#17294a', '#b8d6ee'), ('VOYAGER', '#423c42', '#e3b994'), ('LETTERS', '#45665e', '#eeddbb'),
    ]):
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" viewBox="0 0 600 900">
        <defs><linearGradient id="g" x2="0.8" y2="1"><stop stop-color="{color}"/><stop offset="1" stop-color="#101822"/></linearGradient></defs>
        <rect width="600" height="900" fill="url(#g)"/><circle cx="350" cy="350" r="180" fill="{accent}" opacity=".6"/>
        <ellipse cx="300" cy="400" rx="270" ry="65" fill="none" stroke="{accent}" opacity=".65" transform="rotate(-25 300 400)"/>
        <path d="M0 740L140 620L310 710L470 570L600 650V900H0" fill="{color}"/>
        <text x="45" y="100" fill="{accent}" font-family="serif" font-size="48" letter-spacing="9">{title}</text>
        <text x="45" y="825" fill="{accent}" font-family="sans-serif" font-size="16" letter-spacing="5">PERSONAL COLLECTION / {index+1:02d}</text></svg>'''
        (base / 'data/covers' / f'fixture-{index}.svg').write_text(svg, encoding='utf-8')
    library = server.default_library()
    titles = ['星际漫游', '星际漫游：重返群星', '星际漫游：无声轨道', '远山书简',
              '一个很长的作品名称：穿越群山与海洋之后仍然记得的那段漫长旅程', '风之旅人', '夏日列车', '归途']
    categories = ['movie', 'game', 'anime', 'book', 'novel', 'game', 'anime', 'shortdrama']
    covers = ['fixture-0.svg', 'fixture-1.svg', 'missing.jpg', 'fixture-2.svg', '', '', 'fixture-0.svg', 'missing.jpg']
    for i, (title, cat, cover) in enumerate(zip(titles, categories, covers)):
        work = server.normalize_work({'category': cat, 'title': title, 'year': str(2024-i%4),
            'cover': 'covers/'+cover if cover else '', 'summary': '仅供阶段 2 浏览器验收使用的合成资料。'})
        work['id'] = f'fixture-{i}'
        work['rating'] = [8.5, 9, None, 8, None, 8.5, 0, None][i]
        work['createdAt'] = f'2026-11-{20-i:02d}T12:00:00'
        work['experiences'] = [{'id': f'exp-{i}', 'date': '2026-11-20', 'status': ['completed','active','planned','completed','paused','completed','dropped','planned'][i], 'content': '测试经历', 'createdAt': '2026-11-20T12:00:00'}]
        if i < 3: work['seriesLinks'] = [{'id': 'fixture-series', 'role': 'main', 'required': True}]
        library['works'].append(work)
    series = server.normalize_series({'name': '星际漫游典藏', 'summary': '电影、游戏与动画组成的跨媒介收藏。', 'cover': 'covers/missing-representative.jpg'})
    series['id'] = 'fixture-series'
    empty = server.normalize_series({'name': '尚待启程的收藏盒'})
    empty['id'] = 'fixture-empty'
    library['series'] = [series, empty]
    server.write_library(library)
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    url = 'http://127.0.0.1:'+str(httpd.server_port)
    print(url+'/static/phase2-browser.html', flush=True)
    print('Preview: '+url, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
