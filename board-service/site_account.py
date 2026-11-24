"""Use the board's host-only session for first-party site pages and book bookmarks."""
import hmac
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import abort, jsonify, request, send_from_directory

from storage import write

HOME = {"https://finance-fixer.net", "https://www.finance-fixer.net"}
TOOLS = {f"https://{name}.finance-fixer.net" for name in
         ("aptfee", "bench", "econ", "gamsain", "jiwon", "jobs", "sangkwon")}
SITE = HOME | TOOLS
OZ_SCENES = (6, 6, 6, 5, 7, 5, 6, 7, 5, 7, 13, 13, 4, 7, 10, 3, 4, 4, 4, 5, 3, 3, 4, 1)


PUBLISHED_OZ_CHAPTERS = 4


def return_page(value):
    if not value or len(value) > 2048 or "\\" in value or any(ord(c) < 32 for c in value):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if f"{url.scheme}://{url.netloc}" not in SITE or url.path.startswith("//"):
        return None
    # Public tools may put searches in their query strings. Retain only the reading intent.
    query = "?read=1" if url.query == "read=1" and url.path.startswith("/bookworm/") else ""
    home = f"{url.scheme}://{url.netloc}" in HOME
    if home and url.path == "/public-audit/":
        values = parse_qs(url.query)
        kept = {key: values[key][0] for key, pattern in (("year", r"[0-9]{4}"), ("id", r"[A-Z]-[A-Z0-9]{1,24}"))
                if key in values and re.fullmatch(pattern, values[key][0])}
        query = "?" + urlencode(kept) if kept else ""
    scene = url.path.startswith("/bookworm/") and re.fullmatch(r"scene-\d{1,2}", url.fragment)
    section = url.path == "/" and url.fragment in {"services", "method", "people", "tools", "contact", "videos", "db"}
    fragment = "#" + url.fragment if home and (scene or section) else ""
    return f"https://{url.netloc}{url.path or '/'}{query}{fragment}"


def install(app, db, viewer, label, digest, token):
    app.config.setdefault("BOOKWORM_MEDIA", "/opt/finance-board/media/bookworm")

    @app.after_request
    def site_headers(response):
        if request.endpoint in {"site_session", "book_position"}:
            origin = request.headers.get("Origin", "")
            allowed = HOME if request.endpoint == "book_position" else SITE
            response.vary.add("Origin")
            response.vary.add("Cookie")
            if origin in allowed:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                if request.method == "OPTIONS":
                    response.headers["Access-Control-Allow-Methods"] = "GET, PUT" if allowed == HOME else "GET"
                    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Bookworm-CSRF"
        if request.endpoint == "book_audio" and response.status_code in (200, 206, 304):
            for name in ("Cache-Control", "CDN-Cache-Control", "Cloudflare-CDN-Cache-Control"):
                response.headers[name] = "public, max-age=31536000, immutable, no-transform"
        return response

    @app.get("/site/session")
    def site_session():
        if request.headers.get("Origin") not in SITE:
            abort(403)
        uid = viewer()
        return jsonify(label=label(uid) if uid else None)

    @app.route("/site/bookworm/oz", methods=["GET", "PUT"])
    def book_position():
        if request.headers.get("Origin") not in HOME:
            abort(403)
        def result(uid):
            row = db().execute("SELECT chapter,scene,ms,revision FROM reading_bookmarks WHERE owner=? AND book='oz'", (uid,)).fetchone()
            return {"scope": digest("book-cache", uid)[:24], "csrf": token(),
                    "bookmark": dict(row) if row else None}

        if request.method in {"GET", "HEAD"}:
            uid = viewer()
            return jsonify(result(uid)) if uid else (jsonify(guest=True), 401)

        with write(db()):
            uid = viewer()
            if not uid:
                return jsonify(guest=True), 401
            csrf = request.headers.get("X-Bookworm-CSRF", "")
            if not csrf.isascii() or not hmac.compare_digest(csrf, token()):
                abort(403)
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or not all(type(data.get(k)) is int for k in ("chapter", "scene", "ms", "revision")):
                abort(400)
            ch, scene, ms, rev = (data[k] for k in ("chapter", "scene", "ms", "revision"))
            if not (1 <= ch <= PUBLISHED_OZ_CHAPTERS and 1 <= scene <= OZ_SCENES[ch-1] and 0 <= ms <= 86400000 and 0 <= rev < 2**53):
                abort(400)
            state = result(uid)
            old = state["bookmark"]
            if old and (old["chapter"], old["scene"], old["ms"]) == (ch, scene, ms):
                return jsonify(state)
            if (old["revision"] if old else 0) != rev:
                return jsonify(state), 409
            db().execute("""INSERT INTO reading_bookmarks(owner,book,chapter,scene,ms,revision)
                            VALUES (?,'oz',?,?,?,?) ON CONFLICT(owner,book) DO UPDATE SET
                            chapter=excluded.chapter,scene=excluded.scene,ms=excluded.ms,revision=excluded.revision""",
                         (uid, ch, scene, ms, rev+1))
            return jsonify(result(uid))

    @app.get("/bookworm-audio/<name>")
    def book_audio(name):
        if not re.fullmatch(r"oz-[0-9]{2}-[0-9]{2}-[0-9a-f]{12}\.mp3", name):
            abort(404)
        return send_from_directory(Path(app.config["BOOKWORM_MEDIA"]), name, mimetype="audio/mpeg", conditional=True)
