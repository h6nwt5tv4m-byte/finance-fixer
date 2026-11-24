"""Verify the deployed BSB text and word timings as a single release."""
import hashlib
import json
import re
import unittest
from pathlib import Path

BIBLE = Path(__file__).resolve().parents[1] / "bible"
WORD = re.compile(r"\d+(?:,\d{3})*(?:st|nd|rd|th)?|[^\W\d_]+(?:[’'‐‑-][^\W\d_]+)*")


class ReadAlongDataTest(unittest.TestCase):
    def test_all_chapters_have_timings_for_the_exact_display_text(self):
        books = json.loads((BIBLE / "books.json").read_text())
        self.assertEqual(len(books), 66)
        self.assertEqual(sum(book["chapters"] for book in books), 1189)
        for order, book in enumerate(books, start=1):
            with self.subTest(book=book["id"]):
                self.assertRegex(book["haysPrefix"], rf"^BSB_{order:02d}_[A-Za-z0-9]+_$")
                source = (BIBLE / "bsb" / (book["id"] + ".json")).read_bytes()
                text = json.loads(source)
                timing = json.loads((BIBLE / "read-along" / "timings" / (book["id"] + ".json")).read_text())
                self.assertEqual(timing["textSha256"], hashlib.sha256(source).hexdigest())
                self.assertEqual(len(text), book["chapters"])
                self.assertEqual(len(timing["chapters"]), len(text))
                for chapter, (verses, record) in enumerate(zip(text, timing["chapters"]), start=1):
                    with self.subTest(chapter=chapter):
                        self.assertGreater(record["duration"], 0)
                        self.assertEqual(len(record["verses"]), len(verses))
                        last = 0
                        for verse, times in zip(verses, record["verses"]):
                            self.assertEqual(len(times), 2 * len(WORD.findall(verse)))
                            for start, end in zip(times[::2], times[1::2]):
                                self.assertIs(type(start), int)
                                self.assertIs(type(end), int)
                                self.assertLessEqual(last, start)
                                self.assertLess(start, end)
                                last = end
                        self.assertGreater(last, 0)
                        self.assertLessEqual(last, round(record["duration"] * 100))
