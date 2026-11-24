"""Private consultation intake and the office's follow-up queue."""
import secrets
import time
from urllib.parse import quote

from flask import abort, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

from mail_protocol import address
from storage import CONSULTATION_RETENTION, reserve, write

TOPICS = ("기장·세무 신고", "세무 상담", "회계감사·검토", "기타 문의")
STATES = ("접수", "회신", "상담", "수임", "종결")
NOTICE = "2026-11-24"


def install(app, db, is_admin, network):
    forms = URLSafeTimedSerializer(app.secret_key, salt="consultation-form-" + NOTICE)

    @app.route("/consultation", methods=["GET", "POST"])
    def consultation_form():
        if request.method == "GET":
            return render_template("consultation_form.html", topics=TOPICS, values={},
                                   token=forms.dumps(secrets.token_hex(16)))
        values = request.form
        token = values.get("ticket", "")
        try:
            inquiry_id = forms.loads(token, max_age=86400)
        except BadData:
            # Keep the draft, but require a fresh confirmation on an expired form.
            return render_template("consultation_form.html", topics=TOPICS, values=values,
                                   token=forms.dumps(secrets.token_hex(16)), renew=True,
                                   error="신청 화면을 갱신했습니다. 내용을 확인하고 다시 접수해 주세요."), 400
        topic = values.get("topic", "")
        note = values.get("note", "").strip()
        error = None
        try:
            email = address(values.get("email", "").strip())
        except (UnicodeError, ValueError):
            error = "회신받을 이메일 주소를 확인해 주세요."
        if not error and topic not in TOPICS:
            error = "상담 주제를 선택해 주세요."
        if not error and (len(note) > 1000 or "\x00" in note):
            error = "상담 내용은 일반 텍스트로 1,000자 이내로 작성해 주세요."
        if not error and values.get("consent") != "yes":
            error = "접수하려면 개인정보 수집·이용에 동의해 주세요."
        if error:
            return render_template("consultation_form.html", topics=TOPICS, values=values,
                                   token=token, error=error), 400

        now = int(time.time())
        conn = db()
        with write(conn):
            existing = conn.execute("SELECT email,topic,note FROM consultations WHERE id=?", (inquiry_id,)).fetchone()
            if existing and tuple(existing) != (email, topic, note):
                return render_template("consultation_form.html", topics=TOPICS, values=values,
                                       token=forms.dumps(secrets.token_hex(16)), renew=True,
                                       error="이 신청서는 이미 접수되었습니다. 별도 상담이라면 다시 확인해 접수해 주세요."), 409
            if not existing:
                if not reserve(conn, "consultation", [(network(), 3600, 10)], now):
                    abort(429, description="잠시 후 다시 신청하거나 홈페이지의 전화·이메일로 문의해 주세요.")
                conn.execute("""INSERT INTO consultations(id,email,topic,note,created,notice)
                                VALUES (?,?,?,?,?,?)""", (inquiry_id, email, topic, note, now, NOTICE))
        session["consultation_received"] = True
        return redirect(url_for("consultation_received"), code=303)

    @app.get("/consultation/received")
    def consultation_received():
        if not session.get("consultation_received"):
            return redirect(url_for("consultation_form"))
        return render_template("consultation_received.html")

    @app.get("/consultations")
    def consultations():
        if not is_admin():
            abort(404)
        cutoff = int(time.time()) - CONSULTATION_RETENTION
        conn = db()
        total = conn.execute("SELECT COUNT(*) FROM consultations WHERE created>?", (cutoff,)).fetchone()[0]
        last = max(1, (total + 19) // 20)
        page = min(last, max(1, request.args.get("page", 1, type=int)))
        rows = conn.execute("""SELECT id,topic,created,state,email FROM consultations WHERE created>?
                               ORDER BY created DESC,id DESC LIMIT 20 OFFSET ?""",
                            (cutoff, (page - 1) * 20)).fetchall()
        return render_template("consultations.html", rows=rows, page=page, last=last, total=total)

    @app.route("/consultations/<inquiry_id>", methods=["GET", "POST"])
    def consultation_detail(inquiry_id):
        if not is_admin():
            abort(404)
        conn = db()
        cutoff = int(time.time()) - CONSULTATION_RETENTION
        if request.method == "POST":
            state = request.form.get("state")
            revision = request.form.get("revision", "")
            if state not in STATES or not revision.isascii() or not revision.isdigit() or len(revision) > 15:
                abort(400)
            with write(conn):
                row = conn.execute("SELECT state,revision FROM consultations WHERE id=? AND created>?",
                                   (inquiry_id, cutoff)).fetchone()
                if row is None:
                    abort(404)
                if state != row["state"]:
                    if int(revision) != row["revision"]:
                        abort(409, description="다른 화면에서 상태를 변경했습니다. 상담 관리에서 최신 상태를 확인해 주세요.")
                    conn.execute("UPDATE consultations SET state=?, revision=revision+1 WHERE id=?",
                                 (state, inquiry_id))
            flash("진행 상태를 저장했습니다.")
            return redirect(url_for("consultation_detail", inquiry_id=inquiry_id), code=303)
        row = conn.execute("SELECT * FROM consultations WHERE id=? AND created>?", (inquiry_id, cutoff)).fetchone()
        if row is None:
            abort(404)
        local, domain = row["email"].rsplit("@", 1)
        return render_template("consultation_detail.html", item=row, states=STATES,
                               mailto="mailto:" + quote(local, safe="") + "@" + domain)
