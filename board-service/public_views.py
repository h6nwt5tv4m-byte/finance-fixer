"""First-party daily page views. The private report is read over SSH by the dashboard."""
from contextlib import closing
from datetime import date, datetime, timedelta
import json
import logging
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

from flask import Response, abort, g, request

HOME = "https://finance-fixer.net"
HOME_ORIGINS = (HOME, "https://www.finance-fixer.net")
KST = ZoneInfo("Asia/Seoul")
SOURCES = ("bible", "board", "columns")
PIXEL = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


def count(db, source):
    day = datetime.now(KST).date().isoformat()
    db().execute("""INSERT INTO public_view_counts(day, source, views)
                    VALUES (?, ?, 1)
                    ON CONFLICT(day,source) DO UPDATE SET views=views+1""", (day,source))


def install(app, db):
    @app.after_request
    def count_board_document(response):
        if not getattr(g, "public_board_page", False) or request.method != "GET" or response.status_code != 200:
            return response
        if request.headers.get("Sec-Fetch-Dest") not in (None, "document", "iframe"):
            return response
        if not request.headers.get("Sec-Fetch-Dest") and "text/html" not in request.headers.get("Accept", ""):
            return response
        purpose = request.headers.get("Sec-Purpose", "") + request.headers.get("Purpose", "")
        if "prefetch" not in purpose and "prerender" not in purpose:
            try:
                count(db, "board")
            except sqlite3.Error:
                logging.getLogger(__name__).warning("게시판 조회수 저장 실패")
        return response

    @app.get("/metrics/view/<source>.gif")
    def public_view(source):
        if source not in ("bible","columns") or request.query_string:
            abort(404)
        origin = request.headers.get("Origin")
        if origin not in HOME_ORIGINS or request.headers.get("Sec-Fetch-Dest", "image") != "image":
            abort(403)
        response = Response(PIXEL, mimetype="image/gif")
        response.headers["Access-Control-Allow-Origin"] = origin
        response.vary.add("Origin")
        if request.method == "GET":
            count(db, source)
        return response


def report(database, day):
    yesterday = (day - timedelta(days=1)).isoformat()
    today = day.isoformat()
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as conn:
        totals = {source:(start,n_today,n_yesterday) for source,start,n_today,n_yesterday in conn.execute(
            """SELECT source, MIN(day), SUM(CASE WHEN day=? THEN views ELSE 0 END),
                      SUM(CASE WHEN day=? THEN views ELSE 0 END)
               FROM public_view_counts GROUP BY source""", (today,yesterday))}
    rows = []
    for source in SOURCES:
        start, n_today, n_yesterday = totals.get(source,(None,0,0))
        rows.append({"source": source, "start": start,
                     "today": n_today if start and today >= start else None,
                     "yesterday": n_yesterday if start and yesterday >= start else None})
    return {"date": today, "rows": rows}


if __name__ == "__main__":
    print(json.dumps(report("/var/lib/finance-board/board.sqlite", date.fromisoformat(sys.argv[1]))))
