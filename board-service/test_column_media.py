import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
import requests

import column_feed as feed
import column_media as media
from storage import connect, initialize


def gif():
    frames = [Image.new("RGB", (5, 6), color) for color in ("red", "blue")]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=[80, 120], comment=b"private", loop=0)
    return buf.getvalue()


def article(contents):
    return '<meta property="og:title" content="제목"><div class="se-main-container">' + contents + '</div>'


def para(text):
    return '<div class="se-component se-text"><p class="se-text-paragraph">' + text + '</p></div>'


def picture(url):
    return '<div class="se-component se-image"><img class="se-image-resource" src="' + url + '"></div>'


class ColumnMediaTest(unittest.TestCase):
    url = "https://mblogthumb-phinf.pstatic.net/x/photo.gif"

    def test_placement_limit_and_unsupported_origins(self):
        first = para("첫 문단") + picture(self.url) + picture("https://example.org/image") + para("다음 문단")
        items = []
        body = feed.board_body(article(first + para("끝" * 3990) + picture(self.url + "?3")), "제목", figures=items)
        self.assertEqual([(i.offset, i.source) for i in items], [(len("첫 문단"), self.url)])
        self.assertEqual(body[:4], "첫 문단")
        self.assertIn("관련 자료 보기", body)
        self.assertFalse(media.hosted("https://mblogthumb-phinf.pstatic.net.example.org/x"))

    def test_normal_cdn_image_uses_displayed_url_and_gif_has_fallback(self):
        for ext in ("png", "gif"):
            original = f"https://mblogthumb-phinf.pstatic.net/path/figure.{ext}"
            shown = original + "?type=w800"
            html = f"""<div class="se-component se-image"><a data-linkdata='{{"src":"{original}"}}'>
                <img class="se-image-resource" data-lazy-src="{shown}"></a></div>"""
            figures = []
            feed.board_body(article(html + para("설명")), "제목", figures=figures)
            fig = figures[0]
            self.assertEqual((fig.source, fig.alternatives), (shown, (original,)) if ext == "png" else (original, (shown,)))
            if ext == "gif":
                with patch.object(media, "download", side_effect=[media.Rejected("원본 없음"), gif()]):
                    self.assertEqual(media.prepare(figures)[0][1][-1], "image/gif")

    def test_mobile_gif_video_reads_the_animated_image(self):
        fallback = self.url + "?type=w800"
        video = f"""<div class="se-component se-image"><a data-linkdata='{{"src":"{self.url}"}}'>
            <video class="_gifmp4" src="https://mblogvideo-phinf.pstatic.net/movie.mp4"
             poster="{self.url}?type=w80_blur" data-gif-url="{fallback}" loop></video></a></div>"""
        figures = []
        body = feed.board_body(article(video), "제목", figures=figures)
        self.assertIn("사진", body)
        self.assertEqual([(f.offset, f.source, f.alternatives) for f in figures], [(0, self.url, (fallback,))])
        with patch.object(media, "download", side_effect=[media.Rejected("없음"), gif()]):
            self.assertEqual(media.prepare(figures)[0][1][-1], "image/gif")

    def test_mobile_gif_ignores_video_and_poster_and_tries_animated_fallback(self):
        display = self.url + "?type=w800"
        poster = self.url + "?type=w80_blur"
        video = self.url.replace("photo.gif", "clip.mp4")
        first = io.BytesIO()
        Image.new("RGB", (12, 16)).save(first, "JPEG")
        def markup(original, fallback):
            return article(f"""<div class="se-component se-image"><a data-linkdata='{{"src":"{original}"}}'>
                <video class="_gifmp4" src="{video}" poster="{poster}" data-gif-url="{fallback}"></video></a></div>""")
        for bad in (video, poster):
            with self.assertRaises(ValueError):
                feed.board_body(markup(bad, "https://example.org/foreign.gif"), "제목", figures=[])
        figures = []
        feed.board_body(markup(self.url, display), "제목", figures=figures)
        with patch.object(media, "download", side_effect=[first.getvalue(), gif()]) as download:
            self.assertEqual(media.prepare(figures)[0][1][-1], "image/gif")
            self.assertEqual([c.args[0] for c in download.call_args_list], [self.url, display])
        with patch.object(media, "download", side_effect=[first.getvalue(), gif()]):
            assets = media.prepare([media.Figure(0, self.url, "사진"), *figures])
            self.assertEqual([asset[-1] for _, asset in assets], ["image/jpeg", "image/gif"])

    def test_gif_only_article_can_retry_a_flattened_download(self):
        flat = io.BytesIO()
        Image.new("RGB", (12, 16)).save(flat, "GIF")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db"
            initialize(path)
            db = connect(path)
            args = (db, "11", "움직이는 그림", feed.IMAGE_ONLY, "2026-11-28", 89000,
                    [media.Figure(0, self.url, "그림", animated=True)])
            with patch.object(media, "download", return_value=flat.getvalue()), self.assertRaises(ValueError):
                feed.publish(*args)
            with patch.object(media, "download", return_value=flat.getvalue()), self.assertRaises(ValueError):
                feed.publish(db, "11", "그림", "설명이 있는 GIF", *args[4:])
            self.assertFalse(db.execute("SELECT 1 FROM seeded WHERE key='public-blog:11'").fetchone())
            with patch.object(media, "download", return_value=gif()):
                self.assertTrue(feed.publish(*args))
            self.assertEqual(db.execute("SELECT mime FROM column_figures").fetchone()[0], "image/gif")
            db.close()

    def test_display_src_survives_unavailable_lazy_url(self):
        lazy, src = self.url + "?w1200", self.url + "?w800"
        block = f'<div class="se-component se-image"><img class="se-image-resource" data-lazy-src="{lazy}" src="{src}"></div>'
        figures = []
        feed.board_body(article(block), "제목", figures=figures)
        for error in (media.Rejected("없음"), requests.Timeout()):
            with patch.object(media, "download", side_effect=[error, gif()]) as get:
                self.assertEqual(len(media.prepare(figures)), 1)
                self.assertEqual([call.args[0] for call in get.call_args_list], [lazy, src])

    def test_one_pixel_placeholder_uses_viewer_original(self):
        blank = io.BytesIO()
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(blank, "GIF")
        original = self.url + "?large"
        f = media.Figure(3, self.url, "원본", alternatives=(original,))
        with patch.object(media, "download", side_effect=[blank.getvalue(), gif()]):
            self.assertEqual(media.prepare([f])[0][1][1:3], (5, 6))
        with patch.object(media, "download", return_value=blank.getvalue()):
            self.assertEqual(media.prepare([f]), [])

    def test_deduplicate_the_usable_url(self):
        def fetch(url):
            if "missing" in url:
                raise media.Rejected("없음")
            return gif()
        def figure(primary, alternate):
            return media.Figure(0, self.url + primary, "그림", alternatives=(self.url + alternate,))
        with patch.object(media, "download", side_effect=fetch):
            shared = [figure("missing1", "front"), figure("missing2", "front"), figure("back", "back")]
            self.assertEqual([f for f, _ in media.prepare(shared)], [shared[0], shared[2]])
            limited = [figure("missing", "a"), figure("a", "a"), figure("b", "b"), figure("c", "c")]
            self.assertEqual([f for f, _ in media.prepare(limited)], [limited[0], limited[2], limited[3]])
            separate = [figure("missing", "front"), figure("missing", "back")]
            self.assertEqual([f for f, _ in media.prepare(separate)], separate)

    def test_redirect_and_viewer_only_group(self):
        for target, accepted in ((self.url + "?display", True), ("https://outside.example/i", False)):
            redirect = MagicMock(status_code=302, headers={"Location": target})
            ok = MagicMock(status_code=200)
            ok.iter_content.return_value = [b"image"]
            for response in (redirect, ok):
                response.__enter__.return_value = response
            with patch.object(media.requests, "get", side_effect=[redirect, ok]) as get:
                if accepted:
                    self.assertEqual(media.download(self.url), b"image")
                else:
                    with self.assertRaises(media.Rejected):
                        media.download(self.url)
                self.assertEqual(get.call_count, 2 if accepted else 1)
        html = f"""<div class="se-component se-imageGroup"><a data-linkdata='{{"src":"{self.url}"}}'>
            <img class="se-image-resource" src="data:image/gif,placeholder" alt="고지서 앞면"></a>
            <img class="se-image-resource" src="{self.url}?back" alt="고지서 뒷면">
            <div class="se-caption">고지서 비교</div></div>"""
        figures = []
        feed.board_body(article(html), "제목", figures=figures)
        self.assertEqual([f.label for f in figures], ["고지서 앞면", "고지서 뒷면"])

    def test_original_frame_delays(self):
        buf = io.BytesIO()
        frames = [Image.new("RGB", (3, 3), color) for color in ("red", "blue")]
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=[20, 15000])
        with Image.open(io.BytesIO(media.clean_gif(buf.getvalue())[0])) as im:
            self.assertEqual(im.info["duration"], 20)
            im.seek(1)
            self.assertEqual(im.info["duration"], 15000)

    def test_animation_and_priority(self):
        a = media.Figure(0, self.url + "?thumb", "표지", 3)
        b = media.Figure(7, self.url, "첫 그림")
        c = media.Figure(7, self.url + "?two", "둘째 그림")
        f = media.rounding_example(["의견 | 건수 | 비율", "부적정 | 7건 | 0.0%"], 15)
        self.assertIn("7건", media.rounding_example(["의견 | 건수 | 비율","부적정 | 7 | 0.0%"],15).label)
        self.assertIsNone(media.rounding_example(["의견 | 건수 | 비율","부적정 | 0건 | 0.0%"],15))
        with patch.object(media, "download", return_value=gif()):
            assets = media.prepare([a, b, c, f, b])
        self.assertEqual([fig for fig, asset in assets], [b,c,f])
        data, w, h, mime = assets[0][1]
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual((w, h, mime, im.n_frames), (5, 6, "image/gif", 2))
            self.assertNotIn("comment", im.info)
            self.assertEqual(im.info.get("loop"), 0)
        with patch.object(media, "download", side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout):
                media.prepare([b])

    def test_kept_table_at_excerpt_boundary_retains_its_figure(self):
        table = ('<div class="se-component se-table"><table><tr><th>의견</th><th>건수</th><th>비율</th></tr>'
                 '<tr><td>부적정</td><td>7 건</td><td>0.0%</td></tr></table></div>')
        figures = []
        body = feed.board_body(article(para("가"*3750) + table + para("나"*500) + picture(self.url)),
                               "제목", figures=figures)
        self.assertEqual([f.source for f in figures], [media.ROUNDING])
        self.assertTrue(body[:figures[0].offset].endswith("0.0%"))

    def test_photo_after_last_kept_paragraph_stays(self):
        figures = []
        feed.board_body(article(para("가"*3750) + picture(self.url) + para("나"*1000)),
                        "제목", figures=figures)
        self.assertEqual([f.offset for f in figures], [3750])

    def test_daily_photo_quota_retries_with_media(self):
        with tempfile.TemporaryDirectory() as d, patch.object(media, "download", return_value=gif()):
            path = Path(d)/"db"
            initialize(path)
            db = connect(path)
            db.executemany("INSERT INTO events VALUES('photo','editorial',?)", [(81000,)] * 15)
            db.execute("INSERT INTO settings VALUES('column-pending:18','[]')")
            f = media.Figure(2, self.url, "그림")
            with self.assertRaises(feed.PhotoBudget):
                feed.publish(db, "18", "제목", "본문", "2026-11-28", 89000, [f])
            self.assertTrue(db.execute("SELECT 1 FROM settings WHERE name='column-pending:18'").fetchone())
            self.assertTrue(feed.publish(db, "18", "제목", "본문", "2026-11-28", 190000, [f]))
            self.assertEqual(db.execute("SELECT count(*) FROM column_figures").fetchone()[0], 1)
            db.close()

    def test_media_and_dedup_commit_together(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"db"
            initialize(path)
            db = connect(path)
            f = media.Figure(0, self.url, "그림")
            self.enterContext(patch.object(media, "download", return_value=gif()))
            with patch.object(feed,"reserve_budget",side_effect=ValueError):
                with self.assertRaises(ValueError):
                    feed.publish(db, "9", "글", "본문", "2026-11-28", 1000, [f])
            self.assertFalse(db.execute("select 1 from seeded where key='public-blog:9'").fetchone())
            self.assertTrue(feed.publish(db, "9", "글", "본문", "2026-11-28", 1000, [f]))
            with patch.object(media, "prepare", side_effect=AssertionError("중복 글의 이미지 다운로드")):
                self.assertFalse(feed.publish(db, "9", "글", "본문", "2026-11-28", 1001, [f]))
                db.execute("INSERT INTO seeded(key) VALUES(?)", (feed.manual_key("10", "수동"),))
                self.assertFalse(feed.publish(db, "10", "수동", "본문", "2026-11-28", 1001, [f]))
            self.assertEqual(db.execute("select count(*) from column_figures").fetchone()[0], 1)
            db.execute("delete from posts where source_url=?", (feed.BLOG+"9",))
            self.assertFalse(db.execute("select 1 from column_figures").fetchone())
            db.close()
