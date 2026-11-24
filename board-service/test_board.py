from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from app import ORIGIN, create_app
from maintenance import backup
from storage import connect, initialize

class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"board.sqlite"
        initialize(self.path)
        self.sent={}
        self.app=create_app(b"test-only",self.path,["admin@example.com"],self.sent.__setitem__)
        self.app.testing=True
        self.guest=self.app.test_client()

    def get(self,c,url):
        return c.get(url,base_url=ORIGIN)

    def send(self,c,url,data):
        form=self.get(c,"/login").get_data(as_text=True)
        csrf=re.search(r'name="csrf" value="([^"]+)"',form)[1]
        return c.post(url,base_url=ORIGIN,headers={"Origin":ORIGIN,"CF-Connecting-IP":"192.0.2.1"},
                      data=dict(csrf=csrf,**data))

    def account(self,email):
        c=self.app.test_client()
        self.assertEqual(self.send(c,"/login/request",{"email":email}).status_code,303)
        self.assertEqual(self.send(c,"/login/confirm",{"code":self.sent[email]}).status_code,303)
        return c

    def create(self,c,mode):
        result=self.send(c,"/write",dict(title="표시 확인",body="본문 확인",visibility=mode))
        self.assertEqual(result.status_code,303)
        return result.location

    def test_homepage_login_return_and_remember(self):
        back = "https://finance-fixer.net/bookworm/4/?read=1#scene-2"
        c = self.guest
        self.assertIn("return_to", self.get(c, "/account?return_to="+back).location)
        issued = self.send(c, "/login/request", {"email":"reader@example.com", "return_to":back})
        self.assertIn("return_to=", issued.location)
        result = self.send(c, "/login/confirm", {"code":self.sent["reader@example.com"], "return_to":back})
        self.assertTrue(result.location.startswith("/account/continue?"))
        self.assertIn(back, self.get(c,result.location).get_data(as_text=True))
        cookie = next(h for h in result.headers.getlist("Set-Cookie") if h.startswith("__Host-board-auth="))
        self.assertIn("Max-Age=604800", cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        out = self.send(c, "/logout", {"return_to":back})
        out_page = self.get(c,out.location).get_data(as_text=True)
        self.assertIn('href="https://finance-fixer.net/bookworm/"',out_page)
        self.assertNotIn(back,out_page)
        self.assertNotIn("other.example", self.get(c, "/account?return_to=https://other.example/").location)

    def test_bookmark_scope_and_concurrent_devices(self):
        origin = "https://finance-fixer.net"
        url = "/site/bookworm/oz"
        a = self.account("reader@example.com")
        b = self.account("second@example.com")
        def state(client, url=url, site=origin):
            return client.get(url, base_url=ORIGIN, headers={"Origin":site})
        def put(client, csrf, **args):
            return client.put(url, base_url=ORIGIN, headers={"Origin":origin,"X-Bookworm-CSRF":csrf},
                              json=dict(chapter=4, scene=1, ms=3456, revision=0, **args))
        self.assertEqual(state(self.guest).status_code, 401)
        for client in (a,b):
            res = state(client)
            self.assertEqual(res.headers["Access-Control-Allow-Origin"], origin)
            self.assertIn("no-store",res.headers["Cache-Control"])
            self.assertIsNone(res.json["bookmark"])
        t = state(a).json["csrf"]
        self.assertEqual(put(a, t).json["bookmark"]["ms"], 3456)
        self.assertEqual(put(a, t).json["bookmark"]["revision"], 1)
        self.assertIsNone(state(b).json["bookmark"])
        stale = a.put(url,base_url=ORIGIN,headers={"Origin":origin,"X-Bookworm-CSRF":t},
                      json=dict(chapter=1,scene=2,ms=10,revision=0))
        self.assertEqual(stale.status_code,409)
        self.assertEqual(stale.json["bookmark"]["chapter"],4)
        self.assertEqual(put(b,t).status_code,403)
        tool = "https://bench.finance-fixer.net"
        self.assertTrue(state(a,"/site/session",tool).json["label"])
        self.assertEqual(state(a,site=tool).status_code,403)
        self.assertNotIn("Access-Control-Allow-Origin",state(a,site=tool).headers)
        self.assertEqual(state(a,"/site/session","https://other.example").status_code,403)
        bad = a.put(url,base_url=ORIGIN,headers={"Origin":origin,"X-Bookworm-CSRF":t},
                    json=dict(chapter=4,scene=99,ms=0,revision=1))
        self.assertEqual(bad.status_code,400)
        self.assertEqual(state(a).json["bookmark"]["revision"],1)

    def test_public_narration_ranges(self):
        media = Path(self.tmp.name)/"audio"
        media.mkdir()
        self.app.config["BOOKWORM_MEDIA"] = media
        name = "oz-24-01-0123456789ab.mp3"
        (media/name).write_bytes(bytes(range(100)))
        res = self.guest.get("/bookworm-audio/"+name,base_url=ORIGIN,headers={"Range":"bytes=2-4"})
        self.addCleanup(res.close)
        self.assertEqual((res.status_code,res.data),(206,bytes([2,3,4])))
        self.assertIn("immutable",res.headers["Cache-Control"])
        self.assertNotIn("Set-Cookie",res.headers)
        bad = self.get(self.guest,"/bookworm-audio/missing.mp3")
        self.assertEqual(bad.status_code,404)
        self.assertIn("no-store",bad.headers["Cache-Control"])

    def test_private_and_comments(self):
        a=self.account("a@example.com")
        b=self.account("b@example.com")
        op=self.account("admin@example.com")
        url=self.create(a,"private")
        self.assertEqual(self.send(op,url+"/reply",{"body":"비밀 답글"}).status_code,303)
        for reader in (self.guest,b):
            self.assertEqual(self.get(reader,url).status_code,404)
            self.assertNotIn("표시 확인",self.get(reader,"/").get_data(as_text=True))
        self.assertEqual(self.send(b,url+"/reply",{"body":"다른 사용자"}).status_code,404)
        for reader in (a,op):
            self.assertIn("비밀 답글",self.get(reader,url).get_data(as_text=True))
        self.assertEqual(self.send(a,url+"/manage",{"action":"delete"}).status_code,303)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM comments").fetchone()[0],0)

    def test_moderation_and_quota(self):
        a=self.account("a@example.com")
        op=self.account("admin@example.com")
        url=self.create(a,"public")
        self.assertIn("표시 확인",self.get(self.guest,url).get_data(as_text=True))
        self.assertEqual(self.send(a,url+"/reply",{"body":"연속"}).status_code,429)
        self.assertEqual(self.send(a,url+"/manage",{"action":"hide"}).status_code,403)
        self.assertEqual(self.send(op,url+"/manage",{"action":"hide"}).status_code,303)
        self.assertEqual(self.get(self.guest,url).status_code,404)
        self.assertEqual(self.send(op,url+"/manage",{"action":"show"}).status_code,303)
        self.assertEqual(self.get(self.guest,url).status_code,200)
        self.assertEqual(self.send(op,url+"/manage",{"action":"block"}).status_code,303)
        self.assertEqual(self.get(a,"/write").status_code,303)
        self.assertEqual(self.send(a,url+"/reply",{"body":"차단 확인"}).status_code,403)

    def test_login_limits_binding_and_logout(self):
        c=self.app.test_client()
        self.send(c,"/login/request",{"email":"one@example.com"})
        code=self.sent["one@example.com"]
        self.assertEqual(self.send(self.guest,"/login/confirm",{"code":code}).status_code,400)
        self.assertEqual(self.send(c,"/login/request",{"email":"one@example.com"}).status_code,429)
        self.assertEqual(self.send(c,"/login/confirm",{"code":code}).status_code,303)
        self.assertEqual(self.send(c,"/login/confirm",{"code":code}).status_code,400)
        self.assertEqual(self.get(c,"/write").status_code,200)
        self.send(c,"/logout",{})
        self.assertEqual(self.get(c,"/write").status_code,303)
        self.assertEqual(self.guest.post("/login/request",base_url=ORIGIN,data={"email":"new@example.com"}).status_code,403)

    def test_email_case_and_failed_delivery(self):
        from mail_protocol import address, mailbox_limit
        self.assertEqual(mailbox_limit("first.last+tag@googlemail.com"),mailbox_limit("firstlast@gmail.com"))
        self.assertEqual(address("Writer@iCloud.com"),"writer@icloud.com")
        self.assertNotEqual(address("Writer@example.test"),address("writer@example.test"))
        self.assertNotEqual(mailbox_limit("team+one@example.test"),mailbox_limit("team+two@example.test"))
        self.assertEqual(mailbox_limit("Writer@example.test"),mailbox_limit("writer@example.test"))
        first=self.app.test_client()
        self.assertEqual(self.send(first,"/login/request",{"email":"Writer@icloud.com"}).status_code,303)
        self.assertEqual(self.send(self.guest,"/login/request",{"email":"writer@icloud.com"}).status_code,429)
        def down(email, code):
            raise OSError("test relay failed")
        app=create_app(b"test-only",self.path,[],down)
        self.assertEqual(self.send(app.test_client(),"/login/request",{"email":"down@example.test"}).status_code,503)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM challenges").fetchone()[0],1)

    def test_admin_removes_hidden_item(self):
        user=self.account("a@example.com")
        admin=self.account("admin@example.com")
        url=self.create(user,"private")
        self.send(admin,url+"/manage",{"action":"hide"})
        self.assertEqual(self.send(admin,url+"/manage",{"action":"delete"}).status_code,303)
        self.assertEqual(self.get(admin,url).status_code,404)

    def test_expired_or_exhausted_code(self):
        for email,expire_code in (("expired@example.com",True),("attempts@example.com",False)):
            c=self.app.test_client()
            self.send(c,"/login/request",{"email":email})
            if expire_code:
                with closing(sqlite3.connect(self.path)) as db, db: db.execute("UPDATE challenges SET expires=0")
            else:
                wrong="111111" if self.sent[email]!="111111" else "222222"
                for _ in range(5): self.assertEqual(self.send(c,"/login/confirm",{"code":wrong}).status_code,400)
            self.assertEqual(self.send(c,"/login/confirm",{"code":self.sent[email]}).status_code,400)

    def test_restore_identity_and_fresh_login(self):
        identity=b"persistent identity only"
        initialize(self.path,identity)
        self.app=create_app(b"session A",self.path,["admin@example.com"],self.sent.__setitem__,identity_key=identity)
        author=self.account("owner@example.com")
        url=self.create(author,"private")
        op=self.account("admin@example.com")
        self.assertEqual(self.send(op,url+"/reply",{"body":"복구용 비밀 댓글"}).status_code,303)
        self.send(self.guest,"/login/request",{"email":"pending@example.com"})
        dest=Path(self.tmp.name)/"restore"
        backup(self.path,dest)
        self.path=next(dest.glob("*.sqlite"))
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM challenges").fetchone()[0],0)
            db.execute("DELETE FROM events")
        with self.assertRaises(RuntimeError): initialize(self.path,b"wrong identity")
        initialize(self.path,identity)
        self.app=create_app(b"session B",self.path,["admin@example.com"],self.sent.__setitem__,identity_key=identity)
        response=self.get(self.account("owner@example.com"),url)
        self.assertIn("복구용 비밀 댓글",response.get_data(as_text=True))
        self.assertEqual(self.get(self.app.test_client(),url).status_code,404)

    def test_unblock_after_deletion_and_shared_gmail_owner(self):
        author=self.account("first.last+test@gmail.com")
        url=self.create(author,"private")
        with closing(connect(self.path)) as db: db.execute("DELETE FROM events")
        other=self.account("firstlast@gmail.com")
        self.assertEqual(self.get(other,url).status_code,200)
        op=self.account("admin@example.com")
        self.send(op,url+"/manage",{"action":"block"})
        self.send(op,url+"/manage",{"action":"delete"})
        self.assertEqual(self.get(other,"/moderation").status_code,404)
        body=self.get(op,"/moderation").get_data(as_text=True)
        value=re.search(r'name="owner" value="([^"]+)"',body)[1]
        self.assertEqual(self.send(op,"/moderation",{"owner":value}).status_code,303)
        self.assertIn("차단한 작성자가 없습니다",self.get(op,"/moderation").get_data(as_text=True))

    def test_failed_resend_retains_valid_code(self):
        codes=[]
        def mail(email,code):
            if codes: raise OSError("test delivery outage")
            codes.append(code)
        self.app=create_app(b"test-only",self.path,[],mail)
        c=self.app.test_client()
        self.send(c,"/login/request",{"email":"retry@example.com"})
        with closing(connect(self.path)) as db: db.execute("UPDATE events SET at=at-65")
        self.assertEqual(self.send(c,"/login/request",{"email":"retry@example.com"}).status_code,503)
        self.assertEqual(self.send(c,"/login/confirm",{"code":codes[0]}).status_code,303)

    def test_delivery_load_preserves_reads(self):
        from threading import Event,Thread
        started=Event()
        release=Event()
        def waiting(email,code):
            started.set()
            if not release.wait(3): raise OSError("mail timeout")
        self.app=create_app(b"test-only",self.path,[],waiting)
        first=self.app.test_client()
        results=[]
        t=Thread(target=lambda:results.append(self.send(first,"/login/request",{"email":"first@example.test"}).status_code))
        t.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertEqual(self.send(self.app.test_client(),"/login/request",{"email":"next@example.test"}).status_code,503)
            self.assertEqual(self.get(self.app.test_client(),"/").status_code,200)
        finally:
            release.set()
            t.join(3)
        self.assertEqual(results,[303])

    def test_existing_owner_needs_matching_key_and_nonempty_credentials(self):
        with self.assertRaises(ValueError): initialize(self.path,b"")
        with self.assertRaises(ValueError): create_app(b"valid",self.path,[],identity_key=b"")
        user=self.account("owner@example.com")
        with self.assertRaises(RuntimeError): initialize(self.path,b"unverified")
        self.create(user,"private")
        with self.assertRaises(RuntimeError): initialize(self.path,b"unverified")
        with closing(connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT value FROM settings WHERE name='identity-key'").fetchone())

    def test_mail_quota_survives_session_key_rotation(self):
        identity=b"stable key"
        self.app=create_app(b"left",self.path,[],self.sent.__setitem__,identity_key=identity)
        self.assertEqual(self.send(self.app.test_client(),"/login/request",{"email":"one@example.test"}).status_code,303)
        self.app=create_app(b"right",self.path,[],self.sent.__setitem__,identity_key=identity)
        self.assertEqual(self.send(self.app.test_client(),"/login/request",{"email":"one@example.test"}).status_code,429)

    def test_ambiguous_first_mail_and_hidden_self_removal(self):
        from mail_protocol import DeliveryUncertain
        def delayed(email,code):
            self.sent[email]=code
            raise DeliveryUncertain()
        self.app=create_app(b"test-only",self.path,["admin@example.com"],delayed)
        author=self.account("writer@example.com")
        admin=self.account("admin@example.com")
        url=self.create(author,"private")
        self.send(admin,url+"/manage",{"action":"hide"})
        self.assertIn("표시 확인",self.get(author,"/account/hidden").get_data(as_text=True))
        stranger=self.account("another@example.com")
        self.assertNotIn("표시 확인",self.get(stranger,"/account/hidden").get_data(as_text=True))
        data={"kind":"post","id":url.rsplit("/",1)[1]}
        self.assertEqual(self.send(stranger,"/account/hidden",data).status_code,404)
        self.assertEqual(self.send(author,"/account/hidden",data).status_code,303)
        self.assertEqual(self.get(admin,url).status_code,404)

    def test_concurrent_backups_publish_consistent_copy(self):
        from concurrent.futures import ThreadPoolExecutor
        dest=Path(self.tmp.name)/"overlap"
        with ThreadPoolExecutor(2) as jobs:
            list(jobs.map(lambda _:backup(self.path,dest),range(2)))
        with closing(connect(next(dest.glob("*.sqlite")))) as saved:
            self.assertEqual(saved.execute("SELECT COUNT(*) FROM posts").fetchone()[0],24)
            self.assertEqual(saved.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_mailbox_switch_when_delivery_acknowledgement_is_late(self):
        from mail_protocol import DeliveryUncertain
        codes={}
        def mail(email,code):
            codes[email]=code
            if len(codes)>1: raise DeliveryUncertain()
        self.app=create_app(b"test-only",self.path,[],mail)
        c=self.app.test_client()
        self.send(c,"/login/request",{"email":"first@example.test"})
        self.assertEqual(self.send(c,"/login/request",{"email":"second@example.test"}).status_code,303)
        self.assertEqual(self.send(c,"/login/confirm",{"code":codes["second@example.test"]}).status_code,303)

    def test_uncertain_resend_keeps_one_code_and_attempt_limit(self):
        from mail_protocol import DeliveryUncertain
        codes=[]
        def delayed(email,code):
            codes.append(code)
            raise DeliveryUncertain()
        self.app=create_app(b"test-only",self.path,[],delayed)
        c=self.app.test_client()
        self.send(c,"/login/request",{"email":"delay@example.com"})
        with closing(connect(self.path)) as db:
            db.execute("UPDATE events SET at=at-65")
            db.execute("UPDATE challenges SET tries=3")
            first=tuple(db.execute("SELECT id,expires,tries FROM challenges").fetchone())
        self.send(c,"/login/request",{"email":"delay@example.com"})
        self.assertEqual(codes[0],codes[1])
        with closing(connect(self.path)) as db:
            self.assertEqual(tuple(db.execute("SELECT id,expires,tries FROM challenges").fetchone()),first)
        self.assertEqual(self.send(c,"/login/confirm",{"code":codes[-1]}).status_code,303)

    def test_smtp_delivery_boundary(self):
        from email.message import EmailMessage
        from unittest.mock import Mock
        from mail_relay import submit
        from mail_protocol import DeliveryUncertain
        msg=EmailMessage();msg["From"]="from@example.test";msg.set_content("test")
        smtp=Mock()
        smtp.mail.return_value=(250,b"ok");smtp.rcpt.return_value=(250,b"ok")
        smtp.docmd.side_effect=ConnectionError()
        with self.assertRaises(ConnectionError): submit(smtp,msg,"from@example.test","to@example.test")
        smtp.send.assert_not_called()
        smtp.docmd.side_effect=None;smtp.docmd.return_value=(354,b"continue")
        smtp.getreply.side_effect=ConnectionError()
        with self.assertRaises(DeliveryUncertain): submit(smtp,msg,"from@example.test","to@example.test")
        smtp.getreply.side_effect=None; smtp.getreply.return_value=(25,b"")
        with self.assertRaises(DeliveryUncertain): submit(smtp,msg,"from@example.test","to@example.test")

    def test_former_moderator_has_no_comment_access_on_someone_elses_private_post(self):
        owner=self.account("owner@example.test")
        op=self.account("admin@example.com")
        url=self.create(owner,"private")
        self.send(op,url+"/reply",{"body":"운영자만 쓴 답변"})
        self.send(op,url+"/manage",{"action":"hide"})
        with closing(connect(self.path)) as db:
            cid=db.execute("SELECT id FROM comments").fetchone()[0]
            db.execute("DELETE FROM events")
        self.app=create_app(b"test-only",self.path,[],self.sent.__setitem__)
        former=self.account("admin@example.com")
        self.assertNotIn("운영자만 쓴 답변",self.get(former,"/account/hidden").get_data(as_text=True))
        self.assertEqual(self.send(former,"/account/hidden",{"kind":"comment","id":cid}).status_code,404)

    def test_late_browser_state_cannot_overwrite_login_cookie(self):
        c=self.app.test_client()
        self.send(c,"/login/request",{"email":"two-tabs@example.test"})
        code=self.sent["two-tabs@example.test"]
        from app import AUTH_COOKIE
        stale=c.get_cookie("__Host-board",domain="board.finance-fixer.net")
        self.send(c,"/login/confirm",{"code":code})
        self.assertIsNotNone(c.get_cookie(AUTH_COOKIE,domain="board.finance-fixer.net"))
        c.set_cookie("__Host-board",stale.value,domain="board.finance-fixer.net",secure=True)
        self.assertEqual(self.get(c,"/write").status_code,200)
        self.send(c,"/logout",{})
        self.assertEqual(self.get(c,"/write").status_code,303)

    def test_uncertain_when_final_smtp_line_has_no_terminator(self):
        import io,smtplib
        from email.message import EmailMessage
        from unittest.mock import Mock
        from mail_relay import submit
        from mail_protocol import DeliveryUncertain
        for raw in (b"250 queued",b"550 rejected",b"250Xdone\r\n",b"450-wait\r\n250 done\r\n"):
            smtp=smtplib.SMTP()
            smtp.file=io.BytesIO(raw)
            smtp.mail=Mock(return_value=(250,b"ok"));smtp.rcpt=Mock(return_value=(250,b"ok"))
            smtp.docmd=Mock(return_value=(354,b"go"));smtp.send=Mock()
            msg=EmailMessage();msg.set_content("test")
            with self.assertRaises(DeliveryUncertain): submit(smtp,msg,"a@example.test","b@example.test")
            smtp.close()

    def test_form_follows_current_authenticated_account(self):
        c=self.account("first@example.test")
        def form_token():
            return re.search(r'name="csrf" value="([^"]+)"',self.get(c,"/write").get_data(as_text=True))[1]
        old=form_token()
        c.delete_cookie("__Host-board",domain="board.finance-fixer.net")
        self.assertEqual(form_token(),old)
        self.send(c,"/login/request",{"email":"second@example.test"})
        self.send(c,"/login/confirm",{"code":self.sent["second@example.test"]})
        r=c.post("/write",base_url=ORIGIN,headers={"Origin":ORIGIN},data=dict(csrf=old,title="이전 작업",body="이전 작성자",visibility="public"))
        self.assertEqual(r.status_code,403)
        self.assertNotEqual(old,form_token())

    def test_expired_cookie_does_not_bind_anonymous_login_form(self):
        c=self.account("expired@example.test")
        with closing(connect(self.path)) as db:
            db.execute("UPDATE sessions SET expires=0")
        form=self.get(c,"/login").get_data(as_text=True)
        token=re.search(r'name="csrf" value="([^"]+)"',form)[1]
        c.delete_cookie("__Host-board-auth",domain="board.finance-fixer.net")
        reply=c.post("/login/request",base_url=ORIGIN,headers={"Origin":ORIGIN,"CF-Connecting-IP":"192.0.2.1"},
                     data={"email":"other@example.test","csrf":token})
        self.assertEqual(reply.status_code,303)

    def test_only_served_fonts_can_be_reused_by_the_browser(self):
        uri = "/static/fonts/gowun-batang-korean-400-normal.woff2"
        with self.get(self.guest, uri) as font:
            self.assertEqual(font.status_code, 200)
            self.assertEqual(font.mimetype, "font/woff2")
            self.assertTrue(font.cache_control.private)
            self.assertGreater(font.cache_control.max_age, 0)
            self.assertEqual(font.headers["CDN-Cache-Control"], "no-store")
        for path in ("/login", "/static/fonts/missing.woff2", "/p/missing.woff2"):
            with self.get(self.guest, path) as page:
                self.assertTrue(page.cache_control.no_store)
                self.assertIn("script-src 'none'", page.headers["Content-Security-Policy"])

    def test_seed_idempotence_and_restore(self):
        first=self.get(self.guest,"/")
        second=self.get(self.guest,"/?page=2")
        self.assertEqual(first.status_code,200)
        self.assertIn("no-store",first.headers["Cache-Control"])
        self.assertEqual(len(set(re.findall(r'href="(/p/[a-z0-9]+)"',(first.data+second.data).decode()))),24)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT source_date) FROM posts").fetchone()[0],15)
            db.execute("DELETE FROM posts WHERE id=(SELECT id FROM posts LIMIT 1)")
        initialize(self.path)
        directory=Path(self.tmp.name)/"backups"
        backup(self.path,directory)
        with closing(sqlite3.connect(next(directory.glob("*.sqlite")))) as copy:
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM posts").fetchone()[0],23)
            self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def consultation_data(self, c, **changes):
        html = self.get(c, "/consultation").get_data(as_text=True)
        ticket = re.search(r'name="ticket" value="([^"]+)"', html)[1]
        return dict(dict(ticket=ticket, email="first+reply@example.com", topic="세무 상담",
                         note="공개되지 않을 상담 내용", consent="yes"), **changes)

    def test_consultation_retries_and_validation(self):
        c = self.guest
        data = self.consultation_data(c)
        for fields in ({"email":"invalid"}, {"topic":"없는 주제"}, {"consent":""}, {"note":"가"*1001},
                       {"ticket":"expired-or-invalid"}):
            self.assertEqual(self.send(c, "/consultation", dict(data, **fields)).status_code, 400)
        self.assertEqual(self.get(c, "/consultation/received").status_code, 302)
        for _ in range(2):
            response = self.send(c, "/consultation", data)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.location, "/consultation/received")
        self.assertIn("신청이 접수되었습니다", self.get(c, response.location).get_data(as_text=True))
        self.assertEqual(self.send(c, "/consultation", dict(data, note="새 문의")).status_code, 409)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM consultations").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='consultation'").fetchone()[0], 1)
        self.assertFalse(self.sent)

    def test_consultation_is_private_and_status_updates_keep_latest(self):
        c = self.guest
        data = self.consultation_data(c, note="<em>private-note</em>")
        self.assertEqual(self.send(c, "/consultation", data).status_code, 303)
        with closing(connect(self.path)) as db:
            inquiry_id = db.execute("SELECT id FROM consultations").fetchone()[0]
        detail = "/consultations/" + inquiry_id
        member = self.account("reader@example.com")
        for client in (c, member):
            for path in ("/consultations", detail):
                self.assertEqual(self.get(client,path).status_code, 404)
            self.assertEqual(self.send(client, detail, {"state":"종결","revision":"0"}).status_code, 404)
            for path in ("/", "/?view=mine", "/consultation/received"):
                self.assertNotIn("private-note", self.get(client,path).get_data(as_text=True))
        admin = self.account("admin@example.com")
        response = self.get(admin, detail)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("&lt;em&gt;private-note&lt;/em&gt;", response.get_data(as_text=True))
        self.assertIn("mailto:first%2Breply@example.com", response.get_data(as_text=True))
        for revision, state in enumerate(("회신","상담","수임","종결")):
            self.assertEqual(self.send(admin, detail, {"state":state,"revision":str(revision)}).status_code, 303)
        self.assertEqual(self.send(admin, detail, {"state":"회신","revision":"0"}).status_code, 409)
        self.assertEqual(self.send(admin, detail, {"state":"종결","revision":"3"}).status_code, 303)
        self.assertIn("종결", self.get(admin, "/consultations").get_data(as_text=True))

    def test_consultation_expiry_and_quota(self):
        from storage import CONSULTATION_RETENTION, expire, write
        import time
        c = self.guest
        for i in range(11):
            result = self.send(c, "/consultation", self.consultation_data(c, note=str(i)))
            self.assertEqual(result.status_code, 303 if i < 10 else 429)
        admin = self.account("admin@example.com")
        now = int(time.time())
        with closing(connect(self.path)) as db:
            entry = db.execute("SELECT id FROM consultations LIMIT 1").fetchone()[0]
            db.execute("UPDATE consultations SET created=? WHERE id=?", (now-CONSULTATION_RETENTION,entry))
            self.assertEqual(self.get(admin, "/consultations/"+entry).status_code, 404)
            self.assertNotIn(entry, self.get(admin, "/consultations").get_data(as_text=True))
            with write(db):
                expire(db, now)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM consultations").fetchone()[0], 9)

if __name__=="__main__":
    unittest.main()
