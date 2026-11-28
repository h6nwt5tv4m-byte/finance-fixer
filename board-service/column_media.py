"""Figures in the author's public Naver article. Only same-site copies are served by the board."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import json
import re
from urllib.parse import unquote, urljoin, urlsplit

import requests
from PIL import Image

from photos import MAX_FILES, MAX_UPLOAD, Rejected, convert


CDN = {"mblogthumb-phinf.pstatic.net", "postfiles.pstatic.net", "blogfiles.pstatic.net"}
ROUNDING = "rounded-share.gif"


@dataclass(frozen=True)
class Figure:
    offset: int
    source: str
    label: str
    priority: int = 1
    alternatives: tuple[str, ...] = ()


def hosted(url):
    try:
        p = urlsplit(url)
        return p.scheme == "https" and p.netloc in CDN and p.path.startswith("/") and not p.fragment
    except ValueError:
        return False


def source_figures(block, offset):
    figures = []
    caption = block.select_one(".se-caption")
    caption = caption.get_text(" ", strip=True) if caption else ""
    for image in block.select("img.se-image-resource"):
        urls = [value for key in ("data-lazy-src", "src")
                if (value := image.get(key)) and hosted(value)]
        original = ""
        viewer = image.find_parent("a", attrs={"data-linkdata": True})
        if viewer:
            try:
                url = json.loads(viewer["data-linkdata"]).get("src")
                if isinstance(url, str) and hosted(url):
                    original = url
            except (ValueError, AttributeError):
                pass
        # A resized display may flatten GIFs. For static photos the rendered size generally works best.
        if original:
            if urlsplit(original).path.lower().endswith(".gif"):
                urls.insert(0, original)
            else:
                urls.append(original)
        if not urls:
            continue
        src, *alternatives = dict.fromkeys(urls)
        name = unquote(urlsplit(src).path.rsplit("/", 1)[-1]).lower()
        alt = (image.get("alt") or "").strip()
        label = alt or caption or "원문에 실린 자료 이미지"
        priority = 1 if name.endswith(".gif") else 2
        if re.fullmatch(r"\d+_summary\.\w+", name):
            priority = 3
        elif re.fullmatch(r"\d+_thumb\.\w+", name):
            priority = 4
        figures.append(Figure(offset, src, label[:200], priority, tuple(alternatives)))
    return figures


def rounding_example(rows, offset):
    if not rows:
        return None
    headers = [s.strip() for s in rows[0].split("|")]
    if "건수" not in headers or "비율" not in headers:
        return None
    ni, pi = headers.index("건수"), headers.index("비율")
    for line in rows[1:]:
        cells = [s.strip() for s in line.split("|")]
        if len(cells) != len(headers) or cells[pi] != "0.0%":
            continue
        count = re.fullmatch(r"(\d+|\d{1,3}(?:,\d{3})+)(?:\s*건)?", cells[ni])
        if count and count[1].replace(",", "").lstrip("0"):
            return Figure(offset, ROUNDING, f"{cells[0]} {count[1]}건 · 표시 비율 {cells[pi]}. 반올림으로 건수가 가려지는 예시.", 0)
    return None


def download(url):
    for _ in range(4):
        if not hosted(url):
            break
        with requests.get(url, headers={"Referer": "https://m.blog.naver.com/financefixer"},
                          stream=True, allow_redirects=False, timeout=(5, 12)) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                url = urljoin(url, r.headers["Location"])
                continue
            if 300 <= r.status_code < 500 and r.status_code not in (408, 425, 429):
                raise Rejected("원문 그림을 열 수 없습니다.")
            r.raise_for_status()
            data = bytearray()
            for chunk in r.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_UPLOAD:
                    raise Rejected("원문 그림 용량 초과")
            return bytes(data)
    raise Rejected("원문 그림 주소를 확인할 수 없습니다.")


def clean_gif(raw):
    """Bound input and composed frame pixels; carry only image content and frame delays."""
    with Image.open(BytesIO(raw), formats=["GIF"]) as im:
        pixels = im.width * im.height
        if pixels > 4_000_000:
            raise Rejected("GIF 해상도 초과")
        playback = {"loop": im.info["loop"]} if "loop" in im.info else {}
        frames, delays = [], []
        while True:
            try:
                im.seek(len(frames))
            except EOFError:
                break
            if len(frames) >= 96 or pixels * (len(frames) + 1) > 24_000_000:
                raise Rejected("GIF 프레임 한도 초과")
            rgba = im.convert("RGBA")
            rgba.thumbnail((960, 960))
            frame = Image.new("RGB", rgba.size, "white")
            frame.paste(rgba, mask=rgba.getchannel("A"))
            frames.append(frame)
            delays.append(int(im.info.get("duration", 0)))
    out = BytesIO()
    if len(frames) == 1:
        frames[0].save(out, "JPEG", quality=82)
        mime = "image/jpeg"
    else:
        frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=delays, disposal=1, **playback)
        mime = "image/gif"
    if out.tell() > MAX_UPLOAD:
        raise Rejected("GIF 변환 용량 초과")
    return out.getvalue(), *frames[0].size, mime


def prepare(figures):
    assets = []
    stored_urls = set()
    unusable = set()
    for order, fig in sorted(enumerate(figures), key=lambda pair: pair[1].priority):
        if fig.source in stored_urls:
            continue
        if fig.source == ROUNDING:
            stored_urls.add(fig.source)
            raw = (Path(__file__).resolve().parent / "column-assets" / ROUNDING).read_bytes()
            with Image.open(BytesIO(raw)) as im:
                asset = (raw, *im.size, "image/gif")
        else:
            transient = None
            asset = None
            for url in (fig.source, *fig.alternatives):
                if url in stored_urls:
                    break
                if url in unusable:
                    continue
                try:
                    raw = download(url)
                    if raw.startswith((b"GIF87a", b"GIF89a")):
                        candidate = clean_gif(raw)
                    else:
                        candidate = (*convert(BytesIO(raw)), "image/jpeg")
                    if candidate[1:3] == (1, 1):
                        raise Rejected("1픽셀 자리표시자")
                    asset = candidate
                    stored_urls.add(url)
                    break
                except requests.RequestException as exc:
                    transient = exc
                except (Rejected, ValueError, OSError, EOFError, Image.DecompressionBombError):
                    unusable.add(url)
            else:
                if transient is not None:
                    raise transient
            if asset is None:
                continue
        assets.append((order, fig, asset))
        if len(assets) >= MAX_FILES:
            break
    return [(fig, asset) for _, fig, asset in sorted(assets, key=lambda item: item[0])]
