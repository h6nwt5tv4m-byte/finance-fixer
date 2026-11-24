"""Source identity for manual and scheduled apartment columns."""
import hashlib
import re
from urllib.parse import parse_qs, urlsplit


def blog_ids(text):
    result = set()
    for link in re.findall(r"https?://(?:m\.)?blog\.naver\.com/[^\s<>]+", text):
        parts = urlsplit(link.rstrip(".,)〉]"))
        match = re.fullmatch(r"/financefixer/(\d+)/?", parts.path)
        if match:
            result.add(match[1])
        elif parts.path == "/PostView.naver":
            query = parse_qs(parts.query)
            numbers = query.get("logNo", [])
            if query.get("blogId") == ["financefixer"] and len(numbers) == 1 and numbers[0].isdigit():
                result.add(numbers[0])
    return result


def title_key(title):
    return re.sub(r"^(?:\s*\[[^\]]{1,24}\]\s*)+", "", title).strip()


def manual_key(log_no, title):
    return "manual-blog:" + log_no + ":" + hashlib.sha256(title_key(title).encode()).hexdigest()


def remember(db, title, body):
    db.executemany("INSERT OR IGNORE INTO seeded(key) VALUES(?)",
                   [(manual_key(log_no, title),) for log_no in blog_ids(body)])
