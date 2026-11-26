"""Board column feed scope (2026-11-26 owner decision: business-category posts, no backfill, no hobby posts)."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import column_feed as cf

ITEM = """<item><title>{t}</title><link>https://blog.naver.com/financefixer/{n}?fromRss=true</link>
<author>financefixer</author><category>{c}</category><tag>{g}</tag><pubDate>{d}</pubDate></item>"""


def rss(*items):
    return ("<rss><channel>" + "".join(ITEM.format(t=t, n=n, c=c, g=g, d=d) for t, n, c, g, d in items) + "</channel></rss>").encode()


class FeedScopeTest(unittest.TestCase):
    SINCE = datetime(2026, 11, 24, 18, 45, tzinfo=cf.KST)
    NOW = datetime(2026, 11, 27, 8, 20, tzinfo=cf.KST)

    def items(self, *rows):
        excluded = set()
        got = cf.public_items(rss(*rows), self.SINCE, self.NOW, excluded)
        return [n for _, n, _ in got], excluded

    def test_business_posts_after_cutoff_go_and_older_or_hobby_do_not(self):
        got, excluded = self.items(
            ("수출은 역대급인데 왜 돈이 안 돌까?", "1", "경제", "경제날씨", "Thu, 26 Nov 2026 22:38:30 +0900"),
            ("장기수선충당금 적립금 부족, 큰 수선 전에", "2", "관리비·생활정보", "장기수선충당금,아파트", "Thu, 26 Nov 2026 08:01:03 +0900"),
            ("감사반 외부감사, 법령상 자격과 자산 규모별 수임 비율", "3", "회계감사·외부감사", "외부감사", "Wed, 25 Nov 2026 08:01:01 +0900"),
            ("세금 신고 일정", "4", "세금·신고", "세금", "Fri, 27 Nov 2026 08:01:00 +0900"),
            ("엑스박스 초기화", "5", "취미·일상", "xbox", "Fri, 27 Nov 2026 07:00:00 +0900"),
            ("보조금 정산 서류", "6", "보조금·정산", "보조금", "Thu, 26 Nov 2026 21:59:59 +0900"),
            ("관리비 문서 날짜 깨짐", "7", "경제", "", "not a date"),
        )
        self.assertEqual(got, ["2", "1", "4"])                     # 아파트 글(옛 규칙), 경계 뒤 업무 글
        self.assertEqual(excluded, {"3", "5", "6", "7"})          # 경계 전 업무 글·취미 글·날짜 깨진 비아파트 글
        self.assertEqual(cf.WIDE_SINCE.isoformat(), "2026-11-26T22:00:00+09:00")

    def test_two_posts_in_one_run_wait_for_the_board_limit(self):
        published, slept = [], []
        clock = iter([100.0, 100.0, 105.0, 136.0])
        db = mock.MagicMock()
        db.execute.return_value.fetchall.return_value = [("column-pending:1", '["2026-11-26T22:38:30+09:00", "a"]'),
                                                          ("column-pending:2", '["2026-11-27T08:01:03+09:00", "b"]')]
        with mock.patch.object(cf, "public_items", return_value=[]), \
                mock.patch.object(cf, "fetch", return_value=b"<html></html>"), \
                mock.patch.object(cf, "board_body", return_value="body"), \
                mock.patch.object(cf, "publish", side_effect=lambda *a: published.append(a[1]) or True), \
                mock.patch.object(cf, "connect", return_value=db), \
                mock.patch.object(cf, "write", mock.MagicMock()), \
                mock.patch.object(cf.time, "sleep", side_effect=slept.append), \
                mock.patch.object(cf.time, "monotonic", side_effect=lambda: next(clock)), \
                mock.patch.object(sys, "argv", ["column_feed.py", "--since", "2026-11-24T18:45:00+09:00"]):
            cf.main()
        self.assertEqual(published, ["1", "2"])
        self.assertEqual(len(slept), 1)
        self.assertGreater(slept[0], 25)


if __name__ == "__main__":
    unittest.main()
