from contextlib import contextmanager
from datetime import datetime
import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import secrets
import time
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from mail_protocol import address, deliver, mailbox_limit
from storage import VISIBLE, connect, expire, reserve, write

ORIGIN = "https://board.finance-fixer.net"
PAGE_SIZE = 12

def create_app(key, database, admins, send_code=deliver, *, identity_key=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=key, MAX_CONTENT_LENGTH=48000, MAX_FORM_MEMORY_SIZE=48000,
                      SESSION_COOKIE_NAME="__Host-board",SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",
                      TRUSTED_HOSTS=["board.finance-fixer.net"])
    def stamp():
        return int(time.time())

    def digest(kind, value):
        return hmac.new(key,(kind+"\0"+value).encode(),"sha256").hexdigest()

    def owner_id(email):
        local,domain=email.split("@")
        if domain in {"gmail.com","googlemail.com"}:
            email=mailbox_limit(email)
        return hmac.new(identity_key or key,("email\0"+email).encode(),"sha256").hexdigest()

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

    def viewer():
        token = session.get("token")
        if not token:
            return ""
        row = db().execute("""SELECT owner FROM sessions WHERE id=? AND expires>?
                            AND NOT EXISTS (SELECT 1 FROM blocked WHERE blocked.owner=sessions.owner)""",
                           (digest("session",token),stamp())).fetchone()
        return row["owner"] if row else ""

    def args(uid):
        return dict(uid=uid,admin=int(editor(uid)))

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    @app.before_request
    def check_request():
        if request.method=="POST":
            supplied=request.form.get("csrf","")
            if request.headers.get("Origin")!=ORIGIN or not supplied.isascii() or not session.get("csrf") or not hmac.compare_digest(session["csrf"],supplied):
                abort(403,description="화면을 새로 열고 다시 시도해 주세요.")

    @app.after_request
    def privacy(response):
        response.headers.update({
            "Cache-Control":"private, no-store, max-age=0, no-transform",
            "CDN-Cache-Control":"no-store", "Cloudflare-CDN-Cache-Control":"no-store",
            "Content-Security-Policy":"default-src 'none'; style-src 'self'; img-src 'self'; script-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
            "X-Content-Type-Options":"nosniff","Referrer-Policy":"same-origin",
            "X-Robots-Tag":"noindex, nofollow","X-Frame-Options":"DENY"})
        return response

    def network():
        try:
            ip = ipaddress.ip_address(request.headers.get("CF-Connecting-IP",""))
        except ValueError:
            abort(503,description="접속 정보를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.")
        subnet=ipaddress.ip_network(f"{ip}/64" if ip.version==6 else f"{ip}/32",strict=False)
        return digest("ip",str(subnet))

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
        return dict(uid=uid,admin=editor(uid),label=label,csrf=csrf)

    @app.errorhandler(HTTPException)
    def problem(error):
        messages={400:"입력 내용을 확인해 주세요.",403:"이 작업을 할 권한이 없습니다.",
                  404:"글이 없거나 열람할 수 없습니다.",413:"입력한 글이 너무 깁니다.",
                  429:"등록 한도에 도달했습니다. 잠시 뒤 다시 시도해 주세요."}
        detail=error.description if error.description and not error.description.isascii() else messages.get(error.code,"다시 시도해 주세요.")
        return render_template("error.html",detail=detail),error.code

    def move(name,**kwargs):
        return redirect(url_for(name,**kwargs),code=303)

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
        filters=VISIBLE+(" AND p.owner=:uid" if mine else "")
        params=args(uid)
        count=db().execute("SELECT COUNT(*) FROM posts p WHERE "+filters,params).fetchone()[0]
        last=max(1,(count+PAGE_SIZE-1)//PAGE_SIZE)
        page=min(max(page,1),last)
        rows=db().execute(f"""SELECT p.*, (SELECT COUNT(*) FROM comments c WHERE c.post=p.id
                            AND (c.hidden=0 OR :admin)) AS replies FROM posts p WHERE {filters}
                            ORDER BY p.created DESC,p.source_date DESC,p.id DESC LIMIT :limit OFFSET :offset""",
                            dict(params,limit=PAGE_SIZE,offset=(page-1)*PAGE_SIZE)).fetchall()
        return render_template("index.html",posts=rows,count=count,mine=mine,page=page,last=last)

    @app.get("/login")
    def login():
        return render_template("login.html",pending=bool(session.get("challenge")))

    @app.post("/login/request")
    def request_code():
        try:
            email=address(request.form.get("email","").strip())
        except (UnicodeError,ValueError):
            abort(400,description="이메일 주소를 확인해 주세요.")
        owner=owner_id(email)
        mail_bucket=digest("mail-limit",mailbox_limit(email))
        ip=network()
        now=stamp()
        challenge=secrets.token_urlsafe(24)
        code=f"{secrets.randbelow(1000000):06}"
        with write(db()):
            expire(db(),now)
            if not reserve(db(),"mail",[(mail_bucket,60,1),(mail_bucket,86400,6),(ip,3600,10),(ip,86400,36),("*",3600,40),("*",86400,180)],now):
                abort(429,description="인증번호 요청이 많습니다. 1분 뒤 다시 시도해 주세요. 일일 한도를 넘으면 다음 날 다시 이용할 수 있습니다.")
            previous=session.get("challenge","")
            db().execute("INSERT INTO challenges VALUES (?,?,?,?,5)",(challenge,owner,digest("otp",challenge+code),now+600))
            blocked=db().execute("SELECT 1 FROM blocked WHERE owner=?",(owner,)).fetchone()
        try:
            if not blocked:
                send_code(email,code)
        except OSError:
            with write(db()):
                db().execute("DELETE FROM challenges WHERE id=?",(challenge,))
            abort(503,description="인증 메일을 보내지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        if previous:
            db().execute("DELETE FROM challenges WHERE id=?",(previous,))
        session["challenge"]=challenge
        flash("인증번호를 보냈습니다. 10분 안에 입력해 주세요.")
        return move("login")

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
                        db().execute("DELETE FROM sessions WHERE id=?",(digest("session",session.get("token","")),))
                        db().execute("INSERT INTO sessions VALUES (?,?,?)",(digest("session",token),owner,now+(43200 if editor(owner) else 604800)))
                        success=True
        if not success:
            abort(400,description="인증번호가 만료되었거나 일치하지 않습니다. 번호를 확인하거나 다시 요청해 주세요.")
        session.clear()
        session["token"]=token
        flash("이메일 인증이 완료되었습니다.")
        return move("index")

    @app.post("/logout")
    def logout():
        db().execute("DELETE FROM sessions WHERE id=?",(digest("session",session.get("token","")),))
        db().execute("DELETE FROM challenges WHERE id=?",(session.get("challenge",""),))
        session.clear()
        return move("index")

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

    @app.route("/write",methods=["GET","POST"])
    def compose():
        if request.method=="GET":
            return render_template("write.html") if viewer() else move("login")
        title=request.form.get("title","").strip()
        body=request.form.get("body","").replace("\r\n","\n").strip()
        visibility=request.form.get("visibility","")
        if not (1<=len(title)<=100 and 1<=len(body)<=4000 and visibility in ("public","private")):
            return render_template("write.html",error="제목은 1~100자, 본문은 1~4,000자로 작성하고 공개 범위를 선택해 주세요."),400
        pid=secrets.token_hex(12)
        with authenticated_write() as uid:
            quota(uid)
            db().execute("INSERT INTO posts(id,owner,title,body,private,created) VALUES (?,?,?,?,?,?)",
                         (pid,uid,title,body,int(visibility=="private"),stamp()))
        return move("post",pid=pid)

    @app.get("/p/<pid>")
    def post(pid):
        uid=viewer()
        item=find_post(pid,uid)
        replies=db().execute("""SELECT * FROM comments WHERE post=? AND (hidden=0 OR ?)
                              ORDER BY created,rowid""",(pid,editor(uid))).fetchall()
        blocked={r[0] for r in db().execute("SELECT owner FROM blocked")} if editor(uid) else set()
        return render_template("post.html",p=item,replies=replies,blocked=blocked)

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
                db().execute(f"DELETE FROM {table} WHERE id=?",(target,))
                return move("post",pid=pid) if cid else move("index")
            if not editor(uid):
                abort(403)
            if action in ("hide","show"):
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
