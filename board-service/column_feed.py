"""Publish the author's new, public apartment columns from the FinanceFixer blog."""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
import time
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from maintenance import DATABASE
from storage import connect, reserve, write


FEED = "https://rss.blog.naver.com/financefixer.xml"
BLOG = "https://blog.naver.com/financefixer/"
HOUSING = re.compile(r"아파트|공동주택|입주자대표|입대의|관리사무소|우리\s?단지|K-?apt", re.I)
MANAGEMENT = re.compile(r"관리비|관리수수료|장기수선|장충금|수선유지비|승강기유지비|시설유지비|공동전기료|외부감사|회계감사|감사인|감사의견|감사보고서|감사보수")
SPECIFIC = re.compile(r"장기수선충당금|장충금|승강기유지비|수선유지비|공용관리비|개별사용료|위탁관리수수료|시설유지비|관리비[ ]?(고지서|회계감사비|잡비)")
OTHER_BUILDINGS = re.compile(r"상가|상업용|오피스텔|사무실|매장|기숙사")
KST = timezone(timedelta(hours=9))


def matches_topic(category, title, tags):
    if category not in {"관리비·생활정보", "회계감사·외부감사"}:
        return False
    # A comparison can cover apartments and shops. A shop-only article is outside this series.
    terms = re.sub(r"\s+", "", title + " " + tags)
    if OTHER_BUILDINGS.search(terms) and not re.search(r"아파트|공동주택", terms):
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
        if not matches_topic(category, title, item.findtext("tag", "")):
            if excluded is not None:
                excluded.add(match[1])
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                raise ValueError("Date has no time zone")
        except (TypeError, ValueError, OverflowError):
            print("Ignoring invalid RSS date for", match[1], flush=True)
            continue
        if since <= published <= now:
            items.append((published, match[1], title))
    return sorted(items)


def text_of(node):
    return node.get_text("", strip=False).replace("\u200b", "").strip()


def board_body(html, title, url=None):
    doc = BeautifulSoup(html, "html.parser")
    meta = doc.select_one('meta[property="og:title"]')
    source = doc.select_one('meta[property="og:url"]')
    if url and (not source or source.get("content") != url):
        raise ValueError("Unexpected public source")
    main = doc.select_one(".se-main-container")
    if not meta or meta.get("content") != title or not main:
        raise ValueError("Public title or article body unavailable")
    for br in main.select("br"):
        br.replace_with("\n")
    sections = []
    for block in main.select(".se-component"):
        if "se-table" in block.get("class", []):
            if block.select_one('[rowspan]:not([rowspan="1"]), [colspan]:not([colspan="1"])'):
                sections.append("이 표는 셀이 병합되어 있습니다. 아래 ‘관련 자료 보기’에서 원본 표를 확인해 주세요.")
                continue
            lines = [" | ".join(" ".join(cell.stripped_strings) for cell in row.find_all(["th", "td"], recursive=False))
                     for row in block.select("tr")]
        else:
            lines = [text_of(p) for p in block.select(".se-text-paragraph")]
        if "se-table" in block.get("class", []):
            lines = ["\n".join(lines)]
        sections.extend(line for line in lines if line.strip())
    if not sections:
        if main.select_one(".se-image img, .se-image-resource"):
            return "사진으로 구성한 칼럼입니다. 아래 ‘관련 자료 보기’에서 사진과 함께 읽어 보세요."
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
        return "\n\n".join(kept) + end
    return body


def manual_duplicate(db, url, title):
    # Only the board itself can label a signed-in contributor as an operator.
    candidates = db.execute("""SELECT id, owner, body FROM posts WHERE title=? AND private=0 AND hidden=0
                               AND (source_url=? OR instr(body,?)>0)""", (title, url, url)).fetchall()
    for pid, owner, body in candidates:
        if url in body and not re.search(re.escape(url) + r"(?![0-9])", body):
            continue
        if owner == "editorial":
            return True
        page = BeautifulSoup(fetch("https://board.finance-fixer.net/p/" + pid).decode("utf-8"), "html.parser")
        author = page.select_one("article .byline span")
        if author and author.get_text(strip=True) == "재무해결사 운영자":
            return True
    return False


def publish(db, log_no, title, body, source_day, now):
    if not 0 < len(title) <= 100:
        raise ValueError("Title exceeds board limits")
    url = BLOG + log_no
    key = "public-blog:" + log_no
    pid = hashlib.sha256(key.encode()).hexdigest()[:24]
    existing = manual_duplicate(db, url, title)
    with write(db):
        db.execute("DELETE FROM settings WHERE name=?", ("column-pending:" + log_no,))
        if not db.execute("INSERT OR IGNORE INTO seeded(key) VALUES(?)", (key,)).rowcount:
            return False
        if existing or db.execute("SELECT 1 FROM posts WHERE owner='editorial' AND source_url=?", (url,)).fetchone():
            return False
        if not reserve(db, "write", [("editorial", 30, 1), ("editorial", 86400, 20), ("*", 86400, 1000)], now):
            raise ValueError("Board rate limit; retry on next run")
        db.execute("""INSERT INTO posts(id,owner,title,body,private,created,source_date,source_url)
                      VALUES(?,'editorial',?,?,0,?,?,?)""", (pid, title, body, now, source_day, url))
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
        for key, value in queue:
            log_no = key.removeprefix("column-pending:")
            published, title = json.loads(value)
            try:
                html = fetch("https://m.blog.naver.com/financefixer/" + log_no)
                body = board_body(html.decode("utf-8"), title, BLOG + log_no)
                inserted = publish(db, log_no, title, body, published[:10], int(time.time()))
                if inserted:
                    print("Published", BLOG + log_no, flush=True)
            except (requests.RequestException, ValueError) as exc:
                failed.append(log_no)
                print(log_no, type(exc).__name__, str(exc), flush=True)
    if failed:
        raise SystemExit("Pending blog posts: " + ", ".join(failed))
    print("Checked", len(items), "eligible public posts")


if __name__ == "__main__":
    main()
