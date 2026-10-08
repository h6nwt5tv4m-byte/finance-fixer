#!/usr/bin/env python3
"""세금 FAQ 정적 페이지 생성 — faq/data/*.json → faq/index.html + faq/<id>.html.

답변 JSON은 faq-pipeline(answer.py)이 회계사DB 검색으로 만든다. 이 스크립트는 사람이 승인한 JSON(파일이 data/에
있으면 승인된 것)만 페이지로 바꾼다. 판단·추천 문구는 넣지 않고, 작성 기준일과 [미확인] 표시를 그대로 둔다.

사용: python3 faq/build_faq.py   (레포 루트에서)
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BASE = "https://finance-fixer.net/faq/"

HEAD = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} | 재무해결사 세금 FAQ</title>
  <meta name="description" content="{desc}" />
  <meta name="theme-color" content="#1c3b2e" />
  <link rel="icon" type="image/png" href="/favicon.png" />
  <link rel="canonical" href="{canonical}" />
  <meta property="og:title" content="{title}" />
  <meta property="og:description" content="{desc}" />
  <meta property="og:type" content="article" />
  <meta property="og:locale" content="ko_KR" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=IBM+Plex+Sans+KR:wght@300;400;500&display=swap" rel="stylesheet" />
  <style>
    :root {{ --paper:#f4f1ea; --paper-deep:#ece7dc; --ink:#1a1a17; --ink-soft:#4a4940; --ink-faint:#68645a; --green:#1c3b2e; --brass:#a8843f; --line:#d8d2c4; --warm:#9a3b26;
      --font-display:"Gowun Batang","Apple SD Gothic Neo",serif; --font-sans:"IBM Plex Sans KR","Apple SD Gothic Neo",system-ui,sans-serif; --measure:38rem; --gutter:clamp(1rem,5vw,3rem); }}
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:var(--font-sans); font-weight:300; font-size:1rem; line-height:1.8; color:var(--ink); background:var(--paper); -webkit-font-smoothing:antialiased; word-break:keep-all; overflow-wrap:anywhere; }}
    a {{ color:var(--green); text-decoration:none; border-bottom:1px solid transparent; }} a:hover {{ border-bottom-color:var(--brass); }}
    .wrap {{ max-width:var(--measure); margin:0 auto; padding:0 var(--gutter); }}
    .top {{ display:flex; align-items:baseline; justify-content:space-between; gap:1rem; padding:1.75rem 0; flex-wrap:wrap; }}
    .mark {{ font-family:var(--font-display); font-size:1.25rem; letter-spacing:.06em; color:var(--green); }} .mark small {{ font-family:var(--font-sans); font-size:.8125rem; letter-spacing:0; color:var(--ink-faint); margin-left:.6rem; }}
    .top nav {{ display:flex; gap:1.25rem; font-size:.875rem; color:var(--ink-soft); }} .top nav a {{ color:inherit; }}
    h1 {{ font-family:var(--font-display); font-weight:400; font-size:clamp(1.625rem,5vw,2.25rem); line-height:1.4; margin-top:1.5rem; }}
    h2 {{ font-family:var(--font-display); font-weight:400; font-size:1.25rem; color:var(--green); margin:2.5rem 0 .75rem; }}
    .muted {{ color:var(--ink-faint); font-size:.875rem; }} .crumb {{ font-size:.875rem; color:var(--ink-faint); }} .crumb a {{ color:inherit; }}
    .q {{ margin-top:1rem; padding:1rem 1.25rem; background:var(--paper-deep); border-radius:4px; color:var(--ink-soft); }}
    .answer p {{ margin:0 0 1.1rem; }} .answer .unverified {{ color:var(--warm); font-size:.8125rem; }}
    .refs {{ list-style:none; display:grid; gap:.4rem; font-size:.9375rem; }} .refs li span {{ color:var(--ink-faint); }}
    .caveats {{ padding-left:1.25rem; display:grid; gap:.4rem; }}
    .tag {{ display:inline-block; font-size:.75rem; padding:.05rem .5rem; background:var(--paper-deep); color:var(--ink-soft); border-radius:3px; margin-right:.3rem; }}
    .list {{ list-style:none; border-top:1px solid var(--line); }} .list li {{ padding:.9rem 0; border-bottom:1px solid var(--line); }} .list li a {{ color:var(--ink); font-size:1.0313rem; }} .list li a:hover {{ color:var(--green); }}
    .chips {{ display:flex; flex-wrap:wrap; gap:.5rem; margin:1rem 0 1.5rem; }} .chip {{ font-size:.8125rem; padding:.25rem .7rem; border:1px solid var(--line); border-radius:999px; color:var(--ink-soft); cursor:pointer; background:none; font-family:inherit; }} .chip.on {{ background:var(--green); border-color:var(--green); color:var(--paper); }}
    .note {{ margin-top:3rem; padding-top:1.5rem; border-top:1px solid var(--line); color:var(--ink-soft); font-size:.875rem; }}
    .foot {{ margin-top:3rem; padding:1.5rem 0 3rem; border-top:1px solid var(--line); display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; font-size:.8125rem; color:var(--ink-faint); }} .foot a {{ color:inherit; }}
    .search {{ width:100%; font:inherit; font-size:1rem; padding:.7rem .9rem; background:#fbf9f4; border:1px solid var(--line); border-radius:4px; color:var(--ink); margin-top:1.25rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="top">
      <a class="mark" href="/faq/">세금 FAQ<small>재무해결사</small></a>
      <nav><a href="/faq/">목록</a><a href="https://finance-fixer.net/">재무해결사 홈</a></nav>
    </header>
    <main>
"""
FOOT = """    </main>
    <footer class="foot"><span>© 2026 재무해결사</span><span>법령 원문 기준 · 자문 아님</span><span><a href="https://finance-fixer.net/">finance-fixer.net</a></span></footer>
  </div>
</body>
</html>
"""
DISCLAIMER = ("이 답은 질문 시점의 법령과 공개 자료를 기준으로 쓴 일반 정보이며, 개별 사실관계에 따라 결론이 달라집니다. "
              "[미확인] 표시는 조문으로 확정하지 못한 부분입니다. 세무 신고나 거래 결정에는 반드시 전문가 확인이 필요합니다. "
              "오류를 발견하시면 <a href=\"mailto:info@finance-fixer.net\">info@finance-fixer.net</a>으로 알려 주세요.")


def esc(s) -> str:
    return html.escape(str(s or ""))


def para(text: str) -> str:
    out = []
    for p in re.split(r"\n\s*\n", (text or "").strip()):
        p = esc(p.strip()).replace("\n", "<br />")
        p = p.replace("[미확인]", '<span class="unverified">[미확인]</span>')
        out.append(f"<p>{p}</p>")
    return "\n".join(out)


def slug(item: dict) -> str:
    return item["id"].lower()


def page(item: dict) -> str:
    title = item.get("title") or item.get("question", "")[:30]
    desc = (item.get("answer") or "").split("\n")[0][:150]
    body = [HEAD.format(title=esc(title), desc=esc(desc), canonical=BASE + slug(item) + ".html")]
    body.append(f'<div class="crumb"><a href="/faq/">세금 FAQ</a> › {esc(item.get("semok") or "")}</div>')
    body.append(f"<h1>{esc(title)}</h1>")
    body.append('<p class="muted">' + " ".join(f'<span class="tag">{esc(t)}</span>' for t in item.get("tags") or [])
                + f' 기준일 {esc(item.get("basis_date") or item.get("generated"))}'
                + (f' · 확신도 {esc(item["confidence"])}' if item.get("confidence") else "") + "</p>")
    body.append(f'<div class="q">{esc(item.get("question"))}</div>')
    body.append(f'<div class="answer" style="margin-top:1.5rem">{para(item.get("answer"))}</div>')
    if item.get("refs"):
        body.append("<h2>근거</h2><ul class=\"refs\">")
        for r in item["refs"]:
            body.append(f"<li>{esc(r.get('law'))} {esc(r.get('article'))} <span>{esc(r.get('note'))}</span></li>")
        body.append("</ul>")
    if item.get("caveats"):
        body.append("<h2>달라지는 경우</h2><ul class=\"caveats\">" + "".join(f"<li>{esc(c)}</li>" for c in item["caveats"]) + "</ul>")
    if item.get("n_asked"):
        body.append(f'<p class="muted" style="margin-top:2rem">같은 주제의 질문이 부동산 세금 오픈채팅에서 {int(item["n_asked"])}번 나왔습니다. 질문은 요지만 옮기고 질문자 정보는 담지 않습니다.</p>')
    body.append(f'<div class="note"><p>{DISCLAIMER}</p><p style="margin-top:.75rem">상담이 필요하시면 <a href="https://finance-fixer.net/#contact">재무해결사</a>로 연락 주세요.</p></div>')
    body.append(FOOT)
    return "\n".join(body)


def index(items: list[dict]) -> str:
    semoks = sorted({i.get("semok") or "기타" for i in items})
    body = [HEAD.format(title="세금 FAQ", desc="부동산 세금 오픈채팅에서 실제로 많이 나온 질문에 법령 원문을 찾아 답했습니다. 양도세·취득세·증여상속·임대사업자.", canonical=BASE)]
    body.append("<h1>자주 묻는 세금 질문,<br />조문을 찾아 답했습니다.</h1>")
    body.append(f'<p class="muted" style="margin-top:1rem">부동산 세금 오픈채팅에서 실제로 나온 질문 가운데 많이 묻는 것부터. 답은 회계사DB(법령·해석례)를 검색해 쓰고 근거 조문을 붙였습니다. {len(items)}건 · 갱신 {date.today().isoformat()}</p>')
    body.append('<input class="search" id="q" type="search" placeholder="질문 검색 (예: 일시적 2주택, 상생임대)" aria-label="검색" />')
    body.append('<div class="chips" id="chips"><button class="chip on" data-s="">전체</button>' + "".join(f'<button class="chip" data-s="{esc(s)}">{esc(s)}</button>' for s in semoks) + "</div>")
    body.append('<ul class="list" id="list">')
    for i in sorted(items, key=lambda x: (-(x.get("n_asked") or 0), x["id"])):
        body.append(f'<li data-s="{esc(i.get("semok") or "기타")}" data-t="{esc((i.get("title") or "") + " " + (i.get("question") or "") + " " + " ".join(i.get("tags") or []))}">'
                    f'<a href="/faq/{slug(i)}.html">{esc(i.get("title"))}</a><div class="muted">{esc(i.get("semok") or "")} · {esc(i.get("topic") or "")}</div></li>')
    body.append("</ul>")
    body.append(f'<div class="note"><p>{DISCLAIMER}</p></div>')
    body.append("""<script>
(() => { const q=document.getElementById('q'), chips=document.getElementById('chips'), items=[...document.querySelectorAll('#list li')]; let s='';
  const norm=t=>(t||'').toLowerCase().replace(/\\s+/g,'');
  const apply=()=>{ const k=norm(q.value); items.forEach(li=>{ li.style.display=((!s||li.dataset.s===s)&&(!k||norm(li.dataset.t).includes(k)))?'':'none'; }); };
  q.addEventListener('input',apply); chips.addEventListener('click',e=>{ const b=e.target.closest('.chip'); if(!b) return; s=b.dataset.s; chips.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c===b)); apply(); });
})();
</script>""")
    body.append(FOOT)
    return "\n".join(body)


def main() -> int:
    items = []
    for p in sorted(DATA.glob("*.json")):
        it = json.loads(p.read_text(encoding="utf-8"))
        if not it.get("answer") or not it.get("title"):
            continue
        items.append(it)
    for p in ROOT.glob("*.html"):
        p.unlink()
    for it in items:
        (ROOT / f"{slug(it)}.html").write_text(page(it), encoding="utf-8")
    (ROOT / "index.html").write_text(index(items), encoding="utf-8")
    print(f"faq pages: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
