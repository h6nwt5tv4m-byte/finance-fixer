"""Private consultation intake and the office's follow-up queue."""
import secrets
import time

from flask import abort, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

from mail_protocol import address
from storage import CONSULTATION_RETENTION, reserve, write

TOPICS = ("기장·세무 신고", "세무 상담", "회계감사·검토", "기타 문의")
STATES = ("접수", "회신", "상담", "수임", "종결")
NOTICE = "2026-11-24"


def install(app, db, is_admin, network):

    @app.route("/consultation", methods=["GET", "POST"])
    def consultation_form():
        generation = db().execute("SELECT value FROM settings WHERE name='consultation-ticket-generation'").fetchone()
        forms = URLSafeTimedSerializer(app.secret_key, salt="consultation-form-" + NOTICE + (generation[0] if generation else ""))
        if request.method != "POST":
            return render_template("consultation_form.html", topics=TOPICS, values={},
                                   token=forms.dumps(secrets.token_hex(16)))
        values = request.form
        token = values.get("ticket", "")
        try:
            inquiry_id, issued = forms.loads(token, return_timestamp=True)
        except BadData:
            # A stale recovery generation needs a fresh consent and ticket.
            return render_template("consultation_form.html", topics=TOPICS, values=values,
                                   token=forms.dumps(secrets.token_hex(16)), renew=True,
                                   error="신청 화면을 갱신했습니다. 내용을 확인하고 다시 접수해 주세요."), 400
        topic = values.get("topic", "")
        note = values.get("note", "").replace("\r\n", "\n").replace("\r", "\n").strip()
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
            if conn.execute("SELECT 1 FROM erased_consultations WHERE id=?", (inquiry_id,)).fetchone():
                abort(410, description="이미 삭제된 신청입니다. 새 상담은 홈페이지 문의에서 신청해 주세요.")
            existing = conn.execute("SELECT email,topic,note FROM consultations WHERE id=?", (inquiry_id,)).fetchone()
            if existing and tuple(existing) != (email, topic, note):
                return render_template("consultation_form.html", topics=TOPICS, values=values,
                                       token=forms.dumps(secrets.token_hex(16)), renew=True,
                                       error="이 신청서는 이미 접수되었습니다. 별도 상담이라면 다시 확인해 접수해 주세요."), 409
            if not existing:
                if not 0 <= now - int(issued.timestamp()) <= 86400:
                    return render_template("consultation_form.html", topics=TOPICS, values=values,
                                           token=forms.dumps(secrets.token_hex(16)), renew=True,
                                           error="신청서가 만료되었습니다. 내용을 확인하고 다시 접수해 주세요."), 400
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
        total = conn.execute("SELECT COUNT(*) FROM consultations WHERE restore_pending=0 AND created>?", (cutoff,)).fetchone()[0]
        last = max(1, (total + 19) // 20)
        page = min(last, max(1, request.args.get("page", 1, type=int)))
        rows = conn.execute("""SELECT id,topic,created,state,email FROM consultations WHERE restore_pending=0 AND created>?
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
                if not is_admin():
                    abort(404)
                cutoff = int(time.time()) - CONSULTATION_RETENTION
                row = conn.execute("SELECT state,revision FROM consultations WHERE id=? AND restore_pending=0 AND created>?",
                                   (inquiry_id, cutoff)).fetchone()
                if row is None:
                    abort(404)
                if state != row["state"]:
                    if int(revision) != row["revision"]:
                        abort(409, description="다른 화면에서 상태를 변경했습니다. 상담 관리에서 최신 상태를 확인해 주세요.")
                    conn.execute("UPDATE consultations SET state=?, revision=revision+1 WHERE id=?",
                                 (state, inquiry_id))
                    conn.execute("""INSERT INTO consultation_updates(inquiry,revision,state,changed)
                                    VALUES (?,?,?,?)""", (inquiry_id, row["revision"]+1, state, int(time.time())))
            flash("진행 상태를 저장했습니다.")
            return redirect(url_for("consultation_detail", inquiry_id=inquiry_id), code=303)
        row = conn.execute("SELECT * FROM consultations WHERE id=? AND restore_pending=0 AND created>?", (inquiry_id, cutoff)).fetchone()
        if row is None:
            abort(404)
        history = conn.execute("SELECT state,changed FROM consultation_updates WHERE inquiry=? ORDER BY revision",
                               (inquiry_id,)).fetchall()
        return render_template("consultation_detail.html", item=row, states=STATES, history=history)

    @app.post("/consultations/<inquiry_id>/delete")
    def consultation_delete(inquiry_id):
        if not is_admin():
            abort(404)
        if request.form.get("confirm") != "yes":
            abort(400)
        conn = db()
        with write(conn):
            if not is_admin():
                abort(404)
            now = int(time.time())
            deleted = conn.execute("DELETE FROM consultations WHERE id=? AND restore_pending=0 AND created>?",
                                   (inquiry_id, now-CONSULTATION_RETENTION))
            if deleted.rowcount != 1:
                abort(404)
            conn.execute("INSERT INTO erased_consultations(id,erased) VALUES (?,?)", (inquiry_id, now))
        flash("상담 신청과 진행 기록을 삭제했습니다.")
        return redirect(url_for("consultations"), code=303)
