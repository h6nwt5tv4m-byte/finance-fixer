"""Figures in the author's public Naver article. Only same-site copies are served by the board."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import json
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from PIL import Image

from photos import MAX_FILES, MAX_UPLOAD, Rejected, convert


CDN = {"mblogthumb-phinf.pstatic.net", "postfiles.pstatic.net", "blogfiles.pstatic.net"}
ROUNDING = "rounded-share.gif"


class AnimationLimit(Rejected):
    """This source exceeds a fixed board limit, even when its preview is available."""


@dataclass(frozen=True)
class Figure:
    offset: int
    source: str
    label: str
    priority: int = 1
    alternatives: tuple[str, ...] = ()
    animated: bool = False


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
    for image in block.select("img.se-image-resource, video._gifmp4"):
        if image.name == "img" and image.find_parent("video"):
            continue
        # Mobile Naver plays GIFs as MP4. Its data-gif-url and image viewer still serve the GIF.
        animated = image.name == "video"
        keys = ("data-gif-url",) if animated else ("data-lazy-src", "src")
        urls = [value for key in keys
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
        if animated:
            urls = [u for u in urls if u not in (image.get("poster"), image.get("src"))
                    and not unquote(urlsplit(u).path).lower().endswith(".mp4")
                    and not any(t.startswith("mp4") or "blur" in t for t in
                                parse_qs(urlsplit(u).query).get("type", []))]
        if not urls:
            continue
        src, *alternatives = dict.fromkeys(urls)
        name = unquote(urlsplit(src).path.rsplit("/", 1)[-1]).lower()
        alt = (image.get("alt") or "").strip()
        label = alt or caption or "원문에 실린 자료 이미지"
        priority = 1 if animated or name.endswith(".gif") else 2
        if re.fullmatch(r"\d+_summary\.\w+", name):
            priority = 3
        elif re.fullmatch(r"\d+_thumb\.\w+", name):
            priority = 4
        figures.append(Figure(offset, src, label[:200], priority, tuple(alternatives), animated))
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
            raise AnimationLimit("GIF 해상도 초과")
        playback = {"loop": im.info["loop"]} if "loop" in im.info else {}
        frames, delays = [], []
        while True:
            try:
                im.seek(len(frames))
            except EOFError:
                break
            if len(frames) >= 96 or pixels * (len(frames) + 1) > 24_000_000:
                raise AnimationLimit("GIF 프레임 한도 초과")
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
        raise AnimationLimit("GIF 변환 용량 초과")
    if mime == "image/gif":
        out.seek(0)
        with Image.open(out) as result:
            animated = result.is_animated
        if not animated:
            out = BytesIO()
            frames[0].save(out, "JPEG", quality=82)
            mime = "image/jpeg"
    return out.getvalue(), *frames[0].size, mime


def prepare(figures, retry_flattened=False):
    assets = []
    stored_urls = {}
    unusable = set()
    limited = set()
    for order, fig in sorted(enumerate(figures), key=lambda pair: pair[1].priority):
        if fig.source in stored_urls and (not fig.animated or stored_urls[fig.source] == "image/gif"):
            continue
        if fig.source == ROUNDING:
            stored_urls[fig.source] = "image/gif"
            raw = (Path(__file__).resolve().parent / "column-assets" / ROUNDING).read_bytes()
            with Image.open(BytesIO(raw)) as im:
                asset = (raw, *im.size, "image/gif")
        else:
            transient = None
            flattened = False
            asset = None
            still = None
            sources = (fig.source, *fig.alternatives)
            prefer_gif = bool(fig.alternatives) and unquote(urlsplit(fig.source).path).lower().endswith(".gif")
            for url in sources:
                if url in stored_urls:
                    if fig.animated and stored_urls[url] != "image/gif":
                        flattened = True
                        continue
                    break
                if url in unusable or url in limited:
                    continue
                try:
                    raw = download(url)
                    if raw.startswith((b"GIF87a", b"GIF89a")):
                        candidate = clean_gif(raw)
                    else:
                        candidate = (*convert(BytesIO(raw)), "image/jpeg")
                    if candidate[1:3] == (1, 1):
                        raise Rejected("1픽셀 자리표시자")
                    if fig.animated and candidate[3] != "image/gif":
                        flattened = True
                        continue
                    if prefer_gif and candidate[3] != "image/gif":
                        if still is None:
                            still = (url, candidate)
                        continue
                    asset = candidate
                    stored_urls[url] = asset[3]
                    break
                except requests.RequestException as exc:
                    transient = exc
                except AnimationLimit:
                    limited.add(url)
                except (Rejected, ValueError, OSError, EOFError, Image.DecompressionBombError):
                    unusable.add(url)
            else:
                if still is not None:
                    url, asset = still
                    stored_urls[url] = asset[3]
                elif transient is not None:
                    raise transient
                elif flattened and retry_flattened and limited.isdisjoint(sources):
                    raise ValueError("원문 GIF가 정지 그림으로 응답하여 다음 회차에 다시 확인합니다.")
            if asset is None:
                continue
        assets.append((order, fig, asset))
        if len(assets) >= MAX_FILES:
            break
    return [(fig, asset) for _, fig, asset in sorted(assets, key=lambda item: item[0])]
