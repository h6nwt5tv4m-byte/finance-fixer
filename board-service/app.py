from contextlib import contextmanager
from datetime import datetime
import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import secrets
import time
from threading import BoundedSemaphore
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from column_source import remember as remember_public_column
from consultation import install as install_consultation
from mail_protocol import DeliveryUncertain, address, deliver, mailbox_limit
from photos import FORM_MEMORY, MAX_FILES, REQUEST_LIMIT, PHOTO_STORAGE, PhotoBudget, Rejected, chosen, convert, gif_poster, reserve_budget
from public_views import install as install_public_views
from site_account import install as install_site_account, return_page
from storage import VISIBLE, connect, expire, reserve, write

ORIGIN = "https://board.finance-fixer.net"
PAGE_SIZE = 12
AUTH_COOKIE = "__Host-board-auth"

class FormProblem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message

def create_app(key, database, admins, send_code=deliver, *, identity_key=None):
    if not key or identity_key == b"":
        raise ValueError("Board credentials must be nonempty.")
    identity_secret = key if identity_key is None else identity_key
    app = Flask(__name__)
    app.config.update(SECRET_KEY=key, MAX_CONTENT_LENGTH=48000, MAX_FORM_MEMORY_SIZE=48000,
                      SESSION_COOKIE_NAME="__Host-board",SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",
                      TRUSTED_HOSTS=["board.finance-fixer.net"])
    def stamp():
        return int(time.time())

    def digest(kind, value):
        secret=identity_secret if kind in {"mail-limit","ip","consultation-ip"} else key
        return hmac.new(secret,(kind+"\0"+value).encode(),"sha256").hexdigest()

    def owner_id(email):
        local,domain=email.split("@")
        if domain in {"gmail.com","googlemail.com"}:
            email=mailbox_limit(email)
        return hmac.new(identity_secret,("email\0"+email).encode(),"sha256").hexdigest()

    admin_ids = {owner_id(address(x.strip())) for x in admins if x.strip()}
    def editor(uid):
        return uid in admin_ids

    def db():
        if "db" not in g:
            g.db = connect(database)
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        if "db" in g:
            g.db.close()

    def login_token():
        return request.cookies.get(AUTH_COOKIE) or session.get("token","")

    def viewer():
        token = login_token()
        if not token:
            return ""
        row = db().execute("""SELECT owner FROM sessions WHERE id=? AND expires>?
                            AND NOT EXISTS (SELECT 1 FROM blocked WHERE blocked.owner=sessions.owner)""",
                           (digest("session",token),stamp())).fetchone()
        return row["owner"] if row else ""

    def args(uid):
        return dict(uid=uid,admin=int(editor(uid)))

    def reset_login_session():
        # A guest consultation draft can survive a separate tab signing in or out.
        consultation_token = session.get("consultation_csrf")
        session.clear()
        if consultation_token:
            session["consultation_csrf"] = consultation_token

    def current_form_token():
        if viewer():
            return digest("form-csrf",login_token())
        return session.get("csrf","")

    def csrf():
        token=current_form_token()
        if token:
            return token
        session["csrf"]=secrets.token_urlsafe(24)
        return session["csrf"]

    def consultation_csrf():
        if not session.get("consultation_csrf"):
            session["consultation_csrf"] = secrets.token_urlsafe(24)
        return session["consultation_csrf"]

    @app.before_request
    def check_request():
        if request.method=="POST" and request.endpoint=="compose":
            # Only the post form accepts photos, and only from a signed-in writer on this site:
            # these checks read headers and cookies, never the request body.
            if request.headers.get("Origin") != ORIGIN:
                abort(403,description="화면을 새로 열고 다시 시도해 주세요.")
            if not viewer():
                abort(403,description="이메일 인증을 먼저 해 주세요.")
            request.max_content_length=REQUEST_LIMIT
            request.max_form_memory_size=FORM_MEMORY
        if request.method=="POST":
            supplied=request.form.get("csrf","")
            expected = session.get("consultation_csrf","") if request.endpoint=="consultation_form" else current_form_token()
            if request.headers.get("Origin") != ORIGIN:
                abort(403,description="화면을 새로 열고 다시 시도해 주세요.")
            if not supplied.isascii() or not expected or not hmac.compare_digest(expected,supplied):
                if request.endpoint == "consultation_form":
                    return app.view_functions["consultation_form"](renew_csrf=True)
                abort(403,description="화면을 새로 열고 다시 시도해 주세요.")

    install_public_views(app, db)
    install_site_account(app, db, viewer, lambda uid: label(uid), digest, lambda: digest("bookmark-form", login_token()))

    @app.after_request
    def privacy(response):
        response.headers.update({
            "Cache-Control":"private, no-store, max-age=0, no-transform",
            "CDN-Cache-Control":"no-store", "Cloudflare-CDN-Cache-Control":"no-store",
            "Content-Security-Policy":"default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; script-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
            "X-Content-Type-Options":"nosniff","Referrer-Policy":"same-origin",
            "X-Robots-Tag":"noindex, nofollow","X-Frame-Options":"DENY"})
        # Only a successful static font may be reused by the same browser.
        if request.endpoint == "static" and response.status_code in (200, 206, 304) and response.mimetype == "font/woff2":
            response.headers["Cache-Control"] = "private, max-age=86400, no-transform"
        return response

    def network(scope="ip"):
        try:
            ip = ipaddress.ip_address(request.headers.get("CF-Connecting-IP",""))
        except ValueError:
            abort(503,description="접속 정보를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.")
        subnet=ipaddress.ip_network(f"{ip}/64" if ip.version==6 else f"{ip}/32",strict=False)
        return digest(scope,str(subnet))

    install_consultation(app, db, lambda: editor(viewer()), lambda: network("consultation-ip"))

    def label(owner):
        if editor(owner) or owner=="editorial":
            return "재무해결사 운영자"
        return "참여자 "+owner[:8].upper()

    @app.template_filter("day")
    def day(value):
        return datetime.fromtimestamp(value,ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")

    @app.context_processor
    def context():
        uid=viewer()
        return dict(uid=uid,admin=editor(uid),label=label,csrf=csrf,consultation_csrf=consultation_csrf)

    @app.errorhandler(HTTPException)
    def problem(error):
        messages={400:"입력 내용을 확인해 주세요.",403:"이 작업을 할 권한이 없습니다.",
                  404:"글이 없거나 열람할 수 없습니다.",413:"입력한 글이 너무 깁니다.",
                  429:"등록 한도에 도달했습니다. 잠시 뒤 다시 시도해 주세요."}
        detail=error.description if error.description and not error.description.isascii() else messages.get(error.code,"다시 시도해 주세요.")
        if error.code == 413 and request.endpoint == "compose":
            detail="사진 용량이 너무 큽니다. 사진은 한 장에 5MB, 3장까지 올릴 수 있습니다."
        if request.endpoint == "book_audio" and error.code == 416:
            return error.get_response()
        back = return_page(request.form.get("return_to")) if error.code != 413 and request.endpoint in {"confirm", "request_code"} else None
        return render_template("error.html", detail=detail, back=back),error.code

    def move(name,**kwargs):
        return redirect(url_for(name,**kwargs),code=303)

    def pinned_post():
        # Deleting the post by any path removes the notice row (ON DELETE CASCADE).
        row=db().execute("SELECT post FROM pinned WHERE slot=1").fetchone()
        return row[0] if row else ""

    def find_post(pid,uid):
        row=db().execute(f"SELECT p.* FROM posts p WHERE p.id=:id AND {VISIBLE}",dict(id=pid,**args(uid))).fetchone()
        if not row:
            abort(404)
        return row

    @app.get("/")
    def index():
        uid=viewer()
        mine=request.args.get("view")=="mine"
        if mine and not uid:
            return move("login")
        page=request.args.get("page",1,type=int)
        params=dict(args(uid),pinned=pinned_post())
        columns="""p.*, (SELECT COUNT(*) FROM comments c WHERE c.post=p.id AND (c.hidden=0 OR :admin)) AS replies,
                   (SELECT COUNT(*) FROM images i WHERE i.post=p.id) AS photos"""
        pinned=None
        if not mine:
            # A hidden notice leaves the slot empty for everyone, editors included.
            pinned=db().execute(f"SELECT {columns} FROM posts p WHERE p.id=:pinned AND p.private=0 AND p.hidden=0 AND {VISIBLE}",params).fetchone()
        params["shown"]=pinned["id"] if pinned else ""
        # The notice is listed once, above page 1, instead of in its chronological place.
        filters=VISIBLE+(" AND p.owner=:uid" if mine else " AND p.id!=:shown")
        count=db().execute("SELECT COUNT(*) FROM posts p WHERE "+filters,params).fetchone()[0]
        last=max(1,(count+PAGE_SIZE-1)//PAGE_SIZE)
        page=min(max(page,1),last)
        rows=db().execute(f"""SELECT {columns} FROM posts p WHERE {filters}
                            ORDER BY p.created DESC,p.source_date DESC,p.id DESC LIMIT :limit OFFSET :offset""",
                            dict(params,limit=PAGE_SIZE,offset=(page-1)*PAGE_SIZE)).fetchall()
        g.public_board_page = not mine
        return render_template("index.html",posts=rows,count=count+bool(pinned),mine=mine,page=page,last=last,
                               pinned=pinned if page==1 else None)

    @app.get("/login")
    def login():
        back = return_page(request.args.get("return_to"))
        if back and viewer():
            return redirect(back, code=303)
        return render_template("login.html", pending=bool(session.get("challenge")), back=back)

    @app.get("/account")
    def account():
        back = return_page(request.args.get("return_to")) or "https://finance-fixer.net/"
        if not viewer():
            return move("login", return_to=back)
        return render_template("account.html", back=back)

    @app.get("/account/continue")
    def continue_site():
        back = return_page(request.args.get("return_to"))
        if not back:
            return move("index")
        # The OTP form posts only to this host. Subsequent navigation is a new document.
        return render_template("continue.html", back=back)

    # Bound SMTP waits per worker so normal reads always have threads available.
    mail_slot=BoundedSemaphore(1)

    @app.post("/login/request")
    def request_code():
        if not mail_slot.acquire(blocking=False):
            abort(503,description="다른 인증 메일을 보내고 있습니다. 잠시 후 다시 요청해 주세요.")
        try:
            return issue_code()
        finally:
            mail_slot.release()

    def issue_code():
        try:
            email=address(request.form.get("email","").strip())
        except (UnicodeError,ValueError):
            abort(400,description="이메일 주소를 확인해 주세요.")
        owner=owner_id(email)
        mail_bucket=digest("mail-limit",mailbox_limit(email))
        ip=network()
        now=stamp()
        with write(db()):
            expire(db(),now)
            if not reserve(db(),"mail",[(mail_bucket,60,1),(mail_bucket,86400,6),(ip,3600,10),(ip,86400,36),("*",3600,40),("*",86400,180)],now):
                abort(429,description="인증번호 요청이 많습니다. 1분 뒤 다시 시도해 주세요. 일일 한도를 넘으면 다음 날 다시 이용할 수 있습니다.")
            previous=session.get("challenge","")
            prior=db().execute("SELECT * FROM challenges WHERE id=? AND owner=? AND expires>? AND tries>0",
                               (previous,owner,now)).fetchone()
            # In the same browser, resending a live challenge sends the same number
            # without extending its lifetime or replenishing the allowed attempts.
            challenge=previous if prior else secrets.token_urlsafe(24)
            code=f"{int(digest('mail-code',challenge),16)%1000000:06d}"
            proof=digest("otp",challenge+code)
            if prior and not hmac.compare_digest(prior["proof"],proof):
                # A challenge issued by a previous app version cannot be reconstructed.
                prior=None
                challenge=secrets.token_urlsafe(24)
                code=f"{int(digest('mail-code',challenge),16)%1000000:06d}"
                proof=digest("otp",challenge+code)
            if not prior:
                if previous:
                    db().execute("DELETE FROM challenges WHERE id=?",(previous,))
                    session.pop("challenge",None)
                db().execute("INSERT INTO challenges VALUES (?,?,?,?,5)",(challenge,owner,proof,now+600))
            blocked=db().execute("SELECT 1 FROM blocked WHERE owner=?",(owner,)).fetchone()
        try:
            if not blocked:
                send_code(email,code)
        except DeliveryUncertain:
            session["challenge"]=challenge
            flash("발송 확인이 지연되고 있습니다. 메일이 도착했다면 번호를 입력해 주세요.")
            return move("login", return_to=return_page(request.form.get("return_to")))
        except OSError:
            if not prior:
                db().execute("DELETE FROM challenges WHERE id=?",(challenge,))
            abort(503,description="인증 메일을 보내지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        session["challenge"]=challenge
        flash("인증번호를 보냈습니다. 번호는 최초 발급 후 10분 동안 유효합니다.")
        return move("login", return_to=return_page(request.form.get("return_to")))

    @app.post("/login/confirm")
    def confirm():
        challenge=session.get("challenge","")
        code=request.form.get("code","").strip()
        now=stamp()
        ip=network()
        token=secrets.token_urlsafe(32)
        success=False
        with write(db()):
            if not reserve(db(),"attempt",[(ip,600,40),("*",600,1200)],now):
                abort(429)
            row=db().execute("SELECT * FROM challenges WHERE id=? AND tries>0 AND expires>?",(challenge,now)).fetchone()
            if row:
                db().execute("UPDATE challenges SET tries=tries-1 WHERE id=?",(challenge,))
                if len(code)==6 and code.isascii() and hmac.compare_digest(row["proof"],digest("otp",challenge+code)):
                    db().execute("DELETE FROM challenges WHERE id=?",(challenge,))
                    owner=row["owner"]
                    if not db().execute("SELECT 1 FROM blocked WHERE owner=?",(owner,)).fetchone():
                        db().execute("DELETE FROM sessions WHERE id=?",(digest("session",login_token()),))
                        lifetime = 43200 if editor(owner) else 604800
                        db().execute("INSERT INTO sessions VALUES (?,?,?)",(digest("session",token),owner,now+lifetime))
                        success=True
        if not success:
            abort(400,description="인증번호가 만료되었거나 일치하지 않습니다. 번호를 확인하거나 다시 요청해 주세요.")
        reset_login_session()
        flash("이메일 인증이 완료되었습니다.")
        back = return_page(request.form.get("return_to"))
        response = move("continue_site", return_to=back) if back else move("index")
        response.set_cookie(AUTH_COOKIE,token,max_age=lifetime,secure=True,httponly=True,samesite="Lax",path="/")
        return response

    @app.post("/logout")
    def logout():
        db().execute("DELETE FROM sessions WHERE id=?",(digest("session",login_token()),))
        db().execute("DELETE FROM challenges WHERE id=?",(session.get("challenge",""),))
        reset_login_session()
        back = return_page(request.form.get("return_to"))
        if back and back.startswith(("https://finance-fixer.net/bookworm/", "https://www.finance-fixer.net/bookworm/")):
            back = "https://finance-fixer.net/bookworm/"
        response = move("continue_site", return_to=back) if back else move("index")
        response.delete_cookie(AUTH_COOKIE,secure=True,httponly=True,samesite="Lax",path="/")
        return response

    @contextmanager
    def authenticated_write():
        with write(db()):
            uid=viewer()
            if not uid:
                abort(403,description="이메일 인증을 먼저 해 주세요.")
            yield uid

    def quota(uid):
        ip=network()
        if not reserve(db(),"write",[(uid,30,1),(uid,86400,20),(ip,600,18),(ip,86400,90),("*",86400,1000)],stamp()):
            abort(429,description="글과 댓글은 30초에 한 번, 계정마다 24시간에 20개까지 쓸 수 있습니다. 접속망의 한도도 적용됩니다.")

    # Decoding photos is CPU and memory heavy; one at a time per worker.
    photo_slot=BoundedSemaphore(1)

    @app.route("/write",methods=["GET","POST"])
    def compose():
        if request.method!="POST":
            # GET and Flask's automatic HEAD only show the form; nothing below runs without the POST checks.
            return render_template("write.html") if viewer() else move("login")
        files=chosen(request.files.getlist("images"))
        def form_error(status,message):
            if files:
                message+=" 사진은 다시 골라 주세요."
            return render_template("write.html",error=message),status
        if files:
            # Every submission that carried photos counts, including ones rejected below.
            with authenticated_write() as uid:
                allowed=reserve(db(),"photo-try",[(uid,600,20),(network(),600,60)],stamp())
            if not allowed:
                return form_error(429,"사진 올리기를 너무 자주 시도했습니다. 10분 뒤 다시 시도해 주세요.")
        title=request.form.get("title","").strip()
        body=request.form.get("body","").replace("\r\n","\n").strip()
        visibility=request.form.get("visibility","")
        if not (1<=len(title)<=100 and 1<=len(body)<=4000 and visibility in ("public","private")):
            return form_error(400,"제목은 1~100자, 본문은 1~4,000자로 작성하고 공개 범위를 선택해 주세요.")
        if len(files)>MAX_FILES:
            return form_error(400,f"사진은 {MAX_FILES}장까지 올릴 수 있습니다.")
        photos=[]
        if files:
            # A short wait only: waiting requests hold a server thread that page views also need.
            if not photo_slot.acquire(timeout=5):
                return form_error(503,"다른 사진을 처리하고 있습니다. 잠시 후 다시 등록해 주세요.")
            try:
                for item in files:
                    photos.append(convert(item.stream))
            except Rejected as problem:
                return form_error(400,str(problem))
            finally:
                photo_slot.release()
        pid=secrets.token_hex(12)
        try:
            with authenticated_write() as uid:
                quota(uid)
                now=stamp()
                try:
                    reserve_budget(db(),uid,[len(data) for data,_,_ in photos],now,PHOTO_STORAGE)
                except PhotoBudget as exc:
                    raise FormProblem(exc.status,str(exc)) from exc
                db().execute("INSERT INTO posts(id,owner,title,body,private,created) VALUES (?,?,?,?,?,?)",
                             (pid,uid,title,body,int(visibility=="private"),now))
                db().executemany("INSERT INTO images(id,post,seq,width,height,size,created,data) VALUES (?,?,?,?,?,?,?,?)",
                                 [(secrets.token_hex(16),pid,seq,width,height,len(data),now,data)
                                  for seq,(data,width,height) in enumerate(photos,1)])
                if visibility == "public" and editor(uid):
                    remember_public_column(db(), title, body)
        except FormProblem as problem:
            return form_error(problem.status,problem.message)
        return move("post",pid=pid)

    @app.get("/i/<iid>")
    def photo(iid):
        uid=viewer()
        # The same visibility rule as the post: private posts for the writer and editors, hidden ones for editors.
        row=db().execute(f"SELECT i.data,COALESCE(f.mime,'image/jpeg') AS mime FROM images i JOIN posts p ON p.id=i.post LEFT JOIN column_figures f ON f.image=i.id WHERE i.id=:iid AND {VISIBLE}",
                         dict(iid=iid,**args(uid))).fetchone()
        if not row:
            abort(404)
        if row["mime"] == "image/gif" and request.args.get("still") == "1":
            return Response(gif_poster(row["data"]), mimetype="image/jpeg",headers={"Content-Disposition":"inline"})
        return Response(row["data"],mimetype=row["mime"],headers={"Content-Disposition":"inline"})

    @app.get("/p/<pid>")
    def post(pid):
        uid=viewer()
        item=find_post(pid,uid)
        replies=db().execute("""SELECT * FROM comments WHERE post=? AND (hidden=0 OR ?)
                              ORDER BY created,rowid""",(pid,editor(uid))).fetchall()
        blocked={r[0] for r in db().execute("SELECT owner FROM blocked")} if editor(uid) else set()
        photos=db().execute("SELECT i.id,i.width,i.height,f.body_offset,f.label,f.mime FROM images i LEFT JOIN column_figures f ON f.image=i.id WHERE i.post=? ORDER BY i.seq",(pid,)).fetchall()
        g.public_board_page = not (item["private"] or item["hidden"])
        return render_template("post.html",p=item,replies=replies,blocked=blocked,photos=photos,
                               pinned=pinned_post()==pid)

    @app.post("/p/<pid>/reply")
    def reply(pid):
        with authenticated_write() as uid:
            item=find_post(pid,uid)
            if item["hidden"]:
                abort(404)
            body=request.form.get("body","").replace("\r\n","\n").strip()
            if not (1<=len(body)<=1200):
                abort(400,description="댓글은 1~1,200자로 작성해 주세요.")
            quota(uid)
            db().execute("INSERT INTO comments(id,post,owner,body,created) VALUES (?,?,?,?,?)",
                         (secrets.token_hex(12),pid,uid,body,stamp()))
        return move("post",pid=pid)

    @app.post("/p/<pid>/manage")
    def manage(pid):
        action=request.form.get("action","")
        cid=request.form.get("comment","")
        with authenticated_write() as uid:
            item=find_post(pid,uid)
            table="posts"
            target=pid
            if cid:
                item=db().execute("SELECT * FROM comments WHERE id=? AND post=? AND (hidden=0 OR ?)",(cid,pid,editor(uid))).fetchone()
                if not item:
                    abort(404)
                table="comments"
                target=cid
            if action=="delete" and (uid==item["owner"] or editor(uid)):
                if not cid and not item["private"] and (editor(item["owner"]) or item["owner"] == "editorial"):
                    remember_public_column(db(), item["title"], item["body"] + " " + (item["source_url"] or ""))
                db().execute(f"DELETE FROM {table} WHERE id=?",(target,))
                return move("post",pid=pid) if cid else move("index")
            if not editor(uid):
                abort(403)
            if action=="pin" and not cid:
                if item["private"] or item["hidden"]:
                    # Readers could not see it, and the current notice would disappear for them.
                    abort(400,description="비밀글이나 숨긴 글은 공지로 고정할 수 없습니다.")
                # One notice at a time: pinning another post replaces the previous one.
                db().execute("INSERT OR REPLACE INTO pinned VALUES (1,?)",(pid,))
            elif action=="unpin" and not cid:
                # Only this post: an old page must not release a notice pinned since.
                db().execute("DELETE FROM pinned WHERE post=?",(pid,))
            elif action in ("hide","show"):
                db().execute(f"UPDATE {table} SET hidden=? WHERE id=?",(action=="hide",target))
            elif action in ("block","unblock") and item["owner"]!="editorial" and not editor(item["owner"]):
                if action=="block":
                    db().execute("INSERT OR IGNORE INTO blocked VALUES (?)",(item["owner"],))
                    db().execute("DELETE FROM sessions WHERE owner=?",(item["owner"],))
                    db().execute("DELETE FROM challenges WHERE owner=?",(item["owner"],))
                else:
                    db().execute("DELETE FROM blocked WHERE owner=?",(item["owner"],))
            else:
                abort(400)
        return move("post",pid=pid)

    @app.route("/account/hidden",methods=["GET","POST"])
    def hidden_items():
        if request.method=="POST":
            with authenticated_write() as uid:
                item_id=request.form.get("id","")
                if request.form.get("kind")=="comment":
                    removed=db().execute("""DELETE FROM comments WHERE id=:id AND owner=:uid
                        AND EXISTS(SELECT 1 FROM posts p WHERE p.id=comments.post
                        AND (p.private=0 OR p.owner=:uid OR :admin) AND (comments.hidden=1 OR p.hidden=1))""",
                        dict(id=item_id,**args(uid)))
                else:
                    removed=db().execute("DELETE FROM posts WHERE id=? AND owner=? AND hidden=1",(item_id,uid))
                if not removed.rowcount:
                    abort(404)
            return move("hidden_items")
        uid=viewer()
        if not uid:
            return move("login")
        items=db().execute("""SELECT id,title AS heading,body AS text,'post' AS kind,created FROM posts WHERE owner=:uid AND hidden=1
            UNION ALL SELECT c.id, CASE WHEN p.owner=:uid OR (p.private=0 AND p.hidden=0)
                           THEN p.title ELSE '숨김 처리된 원글' END,
                           c.body,'comment',c.created FROM comments c JOIN posts p ON p.id=c.post
                    WHERE c.owner=:uid AND (p.private=0 OR p.owner=:uid OR :admin)
                    AND (c.hidden=1 OR p.hidden=1) ORDER BY created DESC""",args(uid)).fetchall()
        return render_template("hidden.html",items=items)

    @app.route("/moderation",methods=["GET","POST"])
    def moderation():
        if request.method=="POST":
            with authenticated_write() as uid:
                if not editor(uid):
                    abort(404)
                db().execute("DELETE FROM blocked WHERE owner=?",(request.form.get("owner",""),))
            return move("moderation")
        if not editor(viewer()):
            abort(404)
        accounts=db().execute("SELECT owner FROM blocked ORDER BY owner").fetchall()
        return render_template("moderation.html",accounts=accounts)

    return app

def production():
    keyfile=Path(os.environ["CREDENTIALS_DIRECTORY"])/"board-key"
    identity_key=(keyfile.parent/"identity-key").read_bytes()
    return create_app(keyfile.read_bytes(),"/var/lib/finance-board/board.sqlite",
                      os.environ["BOARD_ADMINS"].split(","),identity_key=identity_key)
