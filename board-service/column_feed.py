"""Publish the author's new, public columns from the FinanceFixer blog: apartment columns, and since 2026-11-26 every business-category post."""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import secrets
import column_media
from photos import PhotoBudget, reserve_budget
import json
import re
import time
from column_source import blog_ids, manual_key, title_key
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from maintenance import DATABASE
from storage import connect, reserve, write


FEED = "https://rss.blog.naver.com/financefixer.xml"
BLOG = "https://blog.naver.com/financefixer/"
HOUSING = re.compile(r"아파트|공동주택|입주자대표|입대의|관리사무소|우리\s?단지|K-?apt", re.I)
MANAGEMENT = re.compile(r"관리비|관리수수료|장기수선|장충금|수선유지비|승강기유지비|시설유지비|공동전기료|외부감사|회계감사|감사인(?!사)|감사의견|감사보고서|감사보수")
SPECIFIC = re.compile(r"장기수선충당금|장충금|승강기유지비|수선유지비|공용관리비|개별사용료|위탁관리수수료|시설유지비|관리비[ ]?(고지서|회계감사비|잡비)")
OTHER_BUILDINGS = re.compile(r"상가|상업용|오피스텔|사무실|매장|기숙사")
KST = timezone(timedelta(hours=9))
# 2026-11-26 22:44 owner decision: every new post in a business category goes to the board, automatic or hand-written.
# Earlier posts are not backfilled; hobby posts never go.
BUSINESS = {"관리비·생활정보", "회계감사·외부감사", "보조금·정산", "세금·신고", "경제"}
WIDE_SINCE = datetime(2026, 11, 26, 22, 0, tzinfo=KST)
PACE = 31   # seconds between two inserts in one run; the board allows one editorial post per 30 seconds
IMAGE_ONLY = "사진으로 구성한 칼럼입니다. 아래 ‘관련 자료 보기’에서 사진과 함께 읽어 보세요."


def matches_topic(category, title, tags, published=None):
    if apartment_topic(category, title, tags):
        return True
    return category in BUSINESS and published is not None and published >= WIDE_SINCE


def apartment_topic(category, title, tags):
    if category not in {"관리비·생활정보", "회계감사·외부감사"}:
        return False
    # A comparison can cover apartments and shops. A shop-only article is outside this series.
    terms = re.sub(r"\s+", "", title + " " + tags)
    if OTHER_BUILDINGS.search(title + " " + tags) and not re.search(r"아파트|공동주택", terms):
        return False
    if HOUSING.search(terms) and MANAGEMENT.search(terms):
        return True
    return category == "관리비·생활정보" and bool(SPECIFIC.search(terms))


def public_items(xml, since, now, excluded=None):
    root = ElementTree.fromstring(xml)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Expected an RSS channel")
    items = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        category = item.findtext("category")
        match = re.fullmatch(re.escape(BLOG) + r"([0-9]+)(?:\?[^#]*)?", item.findtext("link", ""))
        if not match or item.findtext("author") != "financefixer":
            continue
        try:
            date_text = item.findtext("pubDate", "").strip()
            if not re.search(r"(?:[+-](?:[01]\d|2[0-3])[0-5]\d|GMT|UTC)\Z", date_text, re.I):
                raise ValueError("Malformed time zone")
            published = parsedate_to_datetime(date_text)
            if published.tzinfo is None:
                raise ValueError("Date has no time zone")
        except (TypeError, ValueError, OverflowError):
            published = None   # judged by the apartment rule alone, as before
        if not matches_topic(category, title, item.findtext("tag", ""), published):
            if excluded is not None:
                excluded.add(match[1])
            continue
        if not 0 < len(title) <= 100:
            continue
        if published is None:
            print("Ignoring invalid RSS date for", match[1], flush=True)
            continue
        if since <= published <= now:
            items.append((published, match[1], title))
    return sorted(items)


def text_of(node):
    return node.get_text("", strip=False).replace("\u200b", "").strip()


def board_body(html, title, url=None, figures=None):
    doc = BeautifulSoup(html, "html.parser")
    meta = doc.select_one('meta[property="og:title"]')
    source = doc.select_one('meta[property="og:url"]')
    if url and (not source or source.get("content") != url):
        raise ValueError("Unexpected public source")
    main = doc.select_one(".se-main-container")
    if not meta or meta.get("content") != title or not main:
        raise ValueError("Public title or article body unavailable")
    for deleted in main.select('del, strike, s, .se-strikethrough, [style*="line-through"]'):
        if deleted.parent is not None:
            deleted.replace_with("(취소된 표기 " + text_of(deleted) + ")")
    for br in main.select("br"):
        br.replace_with("\n")
    sections = []
    candidates = []
    length = 0
    for block in main.select(".se-component"):
        is_table = "se-table" in block.get("class", [])
        if {"se-image", "se-imageGroup"} & set(block.get("class", [])):
            candidates.extend(column_media.source_figures(block, length))
        if is_table:
            if block.select_one('[rowspan]:not([rowspan="1"]), [colspan]:not([colspan="1"])'):
                sections.append("이 표는 셀이 병합되어 있습니다. 아래 ‘관련 자료 보기’에서 원본 표를 확인해 주세요.")
                length = len("\n\n".join(sections))
                continue
            lines = [" | ".join(" ".join(text_of(cell).split()) for cell in row.find_all(["th", "td"], recursive=False))
                     for row in block.select("tr")]
        else:
            lines = [text_of(p) for p in block.select(".se-text-paragraph")]
        table_rows = lines if is_table else []
        if is_table:
            lines = ["\n".join(lines)]
        sections.extend(line for line in lines if line.strip())
        length = len("\n\n".join(sections))
        if figures is not None and table_rows:
            example = column_media.rounding_example(table_rows, length)
            if example:
                candidates.append(example)
    if not sections:
        if candidates or main.select_one(".se-image img, .se-image-resource"):
            if figures is not None:
                figures.extend(candidates)
            return IMAGE_ONLY
        raise ValueError("No public article paragraphs")
    body = "\n\n".join(sections)
    if len(body) > 4000:
        # Preserve the board limit and keep whole paragraphs and tables.
        end = "\n\n사진·표를 포함한 전문은 아래 ‘관련 자료 보기’에서 읽을 수 있습니다."
        if len(sections[0]) + len(end) > 4000:
            return title + end
        kept = []
        for part in sections:
            if len("\n\n".join([*kept, part])) + len(end) > 4000:
                break
            kept.append(part)
        body = "\n\n".join(kept)
        if figures is not None:
            figures.extend(f for f in candidates if f.offset <= len(body))
        return body + end
    if figures is not None:
        figures.extend(candidates)
    return body


def manual_duplicate(db, url, title):
    log_no = url.rsplit("/", 1)[1]
    candidates = db.execute("""SELECT id, owner, body, hidden, source_url, title FROM posts WHERE private=0
                               AND (instr(body,?)>0 OR instr(source_url,?)>0)""", (log_no, log_no)).fetchall()
    for pid, owner, body, hidden, source_url, prior_title in candidates:
        if title_key(title) != title_key(prior_title) or log_no not in blog_ids(body + " " + (source_url or "")):
            continue
        if hidden:
            return True
        if owner == "editorial":
            return True
        page = BeautifulSoup(fetch("https://board.finance-fixer.net/p/" + pid).decode("utf-8"), "html.parser")
        author = page.select_one("article .byline span")
        if author and author.get_text(strip=True) == "재무해결사 운영자":
            return True
    return False


def publish(db, log_no, title, body, source_day, now, figures=()):
    if not 0 < len(title) <= 100:
        raise ValueError("Title exceeds board limits")
    url = BLOG + log_no
    key = "public-blog:" + log_no
    pid = hashlib.sha256(key.encode()).hexdigest()[:24]
    existing = manual_duplicate(db, url, title)
    assets = ()
    if figures and not existing and not db.execute("SELECT 1 FROM seeded WHERE key IN (?,?)",
                                                   (key, manual_key(log_no, title))).fetchone():
        # Naver can publish the poster before it serves the animation. Retry through the
        # following local day, then use the existing fallback to the public original.
        retry_until = datetime.fromisoformat(source_day).replace(tzinfo=KST) + timedelta(days=2)
        assets = column_media.prepare(figures, retry_flattened=now < retry_until.timestamp())
    with write(db):
        db.execute("DELETE FROM settings WHERE name=?", ("column-pending:" + log_no,))
        if not db.execute("INSERT OR IGNORE INTO seeded(key) VALUES(?)", (key,)).rowcount:
            return False
        if db.execute("SELECT 1 FROM seeded WHERE key=?", (manual_key(log_no, title),)).fetchone():
            return False
        if existing or db.execute("SELECT 1 FROM posts WHERE owner='editorial' AND source_url=?", (url,)).fetchone():
            return False
        if not reserve(db, "write", [("editorial", 30, 1), ("editorial", 86400, 20), ("*", 86400, 1000)], now):
            raise ValueError("Board rate limit; retry on next run")
        db.execute("""INSERT INTO posts(id,owner,title,body,private,created,source_date,source_url)
                      VALUES(?,'editorial',?,?,0,?,?,?)""", (pid, title, body, now, source_day, url))
        if assets:
            try:
                reserve_budget(db, "editorial", [len(asset[0]) for _, asset in assets], now)
            except PhotoBudget as exc:
                if exc.status == 429:
                    raise  # The rolling daily quota recovers; retry with the figures.
                # The normal board limits apply. Keep the scheduled text and its public original.
                print(f"Column {log_no}: image budget {exc.status}; publishing text with source link", flush=True)
                assets = ()
        for seq, (figure, (data, width, height, mime)) in enumerate(assets, 1):
            iid = secrets.token_hex(16)
            db.execute("INSERT INTO images(id,post,seq,width,height,size,created,data) VALUES(?,?,?,?,?,?,?,?)",
                       (iid,pid,seq,width,height,len(data),now,data))
            db.execute("INSERT INTO column_figures(image,body_offset,label,mime) VALUES(?,?,?,?)",
                       (iid,figure.offset,figure.label,mime))
    return True


def fetch(url):
    response = requests.get(url, timeout=(8, 20))
    response.raise_for_status()
    return response.content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=datetime.fromisoformat, required=True)
    since = parser.parse_args().since
    if since.tzinfo is None:
        parser.error("--since requires an explicit UTC offset")
    failed = []
    excluded = set()
    try:
        items = public_items(fetch(FEED), since, datetime.now(timezone.utc), excluded)
    except (requests.RequestException, ElementTree.ParseError, ValueError, LookupError) as exc:
        # Already observed posts can still be completed while RSS is unavailable.
        print("RSS unavailable:", type(exc).__name__, flush=True)
        items, failed = [], ["RSS"]
    with closing(connect(DATABASE)) as db:
        with write(db):
            db.executemany("DELETE FROM settings WHERE name=?",
                           [("column-pending:" + log_no,) for log_no in excluded])
            for published, log_no, title in items:
                if not db.execute("SELECT 1 FROM seeded WHERE key=?", ("public-blog:" + log_no,)).fetchone():
                    db.execute("""INSERT INTO settings(name,value) VALUES(?,?)
                                  ON CONFLICT(name) DO UPDATE SET value=excluded.value""",
                               ("column-pending:" + log_no,
                                json.dumps([published.astimezone(KST).isoformat(), title], ensure_ascii=False)))
        queue = db.execute("SELECT name,value FROM settings WHERE name GLOB 'column-pending:*' ORDER BY value").fetchall()
        last = None
        for key, value in queue:
            log_no = key.removeprefix("column-pending:")
            published, title = json.loads(value)
            try:
                html = fetch("https://m.blog.naver.com/financefixer/" + log_no)
                figures = []
                body = board_body(html.decode("utf-8"), title, BLOG + log_no, figures)
                if last is not None and time.monotonic() - last < PACE:   # two posts in one run: wait out the board's 30-second limit
                    time.sleep(PACE - (time.monotonic() - last))
                inserted = publish(db, log_no, title, body, published[:10], int(time.time()), figures)
                if inserted:
                    last = time.monotonic()
                    print("Published", BLOG + log_no, flush=True)
            except (requests.RequestException, ValueError) as exc:
                failed.append(log_no)
                print(log_no, type(exc).__name__, str(exc), flush=True)
    if failed:
        raise SystemExit("Pending blog posts: " + ", ".join(failed))
    print("Checked", len(items), "eligible public posts")


if __name__ == "__main__":
    main()
