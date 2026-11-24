"""Regenerate the static bookshelf and book tables of contents from catalog.json."""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "/bookworm/"
HOME = "https://finance-fixer.net"
RESUME = '<a data-resume-label hidden href="/bookworm/oz/">이어 읽기</a>'


def build():
    books = json.loads((ROOT / "catalog.json").read_text())
    reader = (ROOT / "1/index.html").read_text()
    header = reader[reader.index('<header class="top">'):reader.index('</header>')+9]
    styles = reader[reader.index('<link rel="icon"'):reader.index('<link rel="stylesheet" href="/bookworm/reader.css')]
    def page(path, title, contents, legacy=False):
        redirect = '<script src="/bookworm/legacy.js"></script>' if legacy else ''
        return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · 재무해결사</title><meta name="theme-color" content="#1c3b2e">
<link rel="canonical" href="{HOME}{path}">{redirect}
{styles}<link rel="stylesheet" href="/bookworm/library.css">
<script defer src="/nav.js"></script><script defer src="/bookworm/progress.js"></script><script defer src="/bookworm/resume.js?v=library"></script>
</head><body><div class="grain" aria-hidden="true"></div><a class="skip-link" href="#library">본문으로 건너뛰기</a>
{header}<main class="library" id="library">{contents}</main></body></html>
'''
    volumes = []
    for book in books:
        directory = ROOT / book['slug']
        directory.mkdir(exist_ok=True)
        base = URL + book['slug'] + '/'
        title, author, original = (escape(book[k]) for k in ('title','author','original'))
        cover = escape(base + book['cover'], quote=True)
        volumes.append(f'''<a class="volume" href="{base}"><span class="stand"><span class="jacket"><img src="{cover}" alt=""></span></span>
<span class="caption"><span class="volume-name">{title}</span><small>{author} · {book["year"]}</small></span></a>''')
        entries = ''.join(f'<li><a href="{escape(ch["path"], quote=True)}?read=1"><small>{i}장</small>{escape(ch["title"])}</a></li>'
                          for i, ch in enumerate(book['chapters'], 1))
        resume = RESUME if book['slug'] == 'oz' else ''
        detail = f'''<a href="/bookworm/">← 북웜 책장</a><div class="book-detail"><img src="{cover}" alt="">
<div><h1>{title}</h1><p class="original-title" lang="en">{original}</p><p class="book-author">{author} · {book["year"]}</p>{resume}</div>
<section class="chapter-list"><h2>목차</h2><ol class="toc-list">{entries}</ol></section></div>'''
        (directory / 'index.html').write_text(page(base, title + ' 목차', detail))
    shelves = ''.join('<div class="shelf">' + ''.join(volumes[i:i+2]) + '</div>' for i in range(0,len(volumes),2))
    (ROOT / 'index.html').write_text(page(URL, '북웜 고전 영어', f'''<div class="library-intro"><div><h1>북웜 책장</h1>
<p>책을 골라 영어 원문을 읽고 낭독을 들어보세요.</p></div>{RESUME}</div>{shelves}''', legacy=True))


if __name__ == '__main__':
    build()
