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
        form=self.get(c,"/consultation" if url == "/consultation" else "/login").get_data(as_text=True)
        if url == "/consultation":
            form = form.split('action="/consultation"',1)[1]
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

    def test_public_view_scope_and_daily_report(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from unittest.mock import patch
        from public_views import HOME, report
        fixed = datetime(2026,11,24,23,59,59,tzinfo=ZoneInfo("Asia/Seoul"))
        mock_clock = patch("public_views.datetime")
        clock = mock_clock.start()
        self.addCleanup(mock_clock.stop)
        clock.now.return_value = fixed
        date = fixed.date()
        owner = self.account("reader@example.com")
        private = self.create(owner,"private")
        public = re.search(r'href="(/p/[0-9a-f]+)"', self.get(self.guest,"/").get_data(as_text=True))[1]
        browser = {"Accept":"text/html"}
        self.assertTrue(all(row["today"] is None for row in report(self.path,date)["rows"]))
        for path in ("/?view=mine",private,"/consultation","/account","/login"):
            owner.get(path,base_url=ORIGIN,headers=browser)
        self.guest.head("/",base_url=ORIGIN,headers=browser)
        self.guest.get("/",base_url=ORIGIN,headers=dict(browser,Purpose="prefetch"))
        self.assertIsNone(report(self.path,date)["rows"][1]["today"])
        for path in ("/",public):
            response = self.guest.get(path,base_url=ORIGIN,headers=browser)
            self.assertNotIn(b"/metrics/view/board.gif",response.data)
        self.assertEqual(report(self.path,date)["rows"][1]["today"],2)
        for source in ("bible","columns"):
            path = "/metrics/view/"+source+".gif"
            headers = {"Origin":HOME}
            self.assertEqual(self.guest.head(path,base_url=ORIGIN,headers=headers).status_code,200)
            self.assertEqual(self.get(self.guest,path).status_code,403)
            self.assertEqual(self.guest.get(path,base_url=ORIGIN,headers={"Origin":"https://example.org"}).status_code,403)
            response = self.guest.get(path,base_url=ORIGIN,headers=headers)
            self.assertEqual(response.mimetype,"image/gif")
            self.assertNotIn("Set-Cookie",response.headers)
            self.assertIn("no-store",response.headers["Cache-Control"])
            if source != "board":
                www = "https://www.finance-fixer.net"
                pre = self.guest.head(path,base_url=ORIGIN,headers={"Origin":www})
                self.assertEqual(pre.headers["Access-Control-Allow-Origin"],www)
            self.assertEqual(self.guest.get(path+"?q=test",base_url=ORIGIN,headers=headers).status_code,404)
        r = report(self.path,date)
        expected = {"bible":1, "board":2, "columns":1}
        self.assertEqual(r["rows"],[{"source":s,"start":date.isoformat(),"today":n,"yesterday":None} for s,n in expected.items()])
        self.assertTrue(all(row["today"]==0 and row["yesterday"]==expected[row["source"]]
                            for row in report(self.path,date+timedelta(days=1))["rows"]))
        clock.now.return_value = fixed + timedelta(seconds=1)
        self.guest.get("/",base_url=ORIGIN,headers=browser)
        next_day = report(self.path,date+timedelta(days=1))["rows"][1]
        self.assertEqual((next_day["today"], next_day["yesterday"]), (1,2))

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
        rejected = put(b, t)
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json, {"scope": state(b).json["scope"]})
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

    def test_bookmark_orders_choices_from_two_devices(self):
        reader = self.account("devices@example.com")
        url = "/site/bookworm/holmes"
        headers = {"Origin": "https://finance-fixer.net"}
        state = reader.get(url, base_url=ORIGIN, headers=headers).json
        headers["X-Bookworm-CSRF"] = state["csrf"]
        first = state["server_us"] - 10000
        def put(scene, ms, revision, chosen):
            return reader.put(url, base_url=ORIGIN, headers=headers,
                              json=dict(chapter=1, scene=scene, ms=ms, revision=revision, chosen_at=chosen))

        self.assertEqual(put(1, 10000, 0, first).json["bookmark"]["revision"], 1)
        self.assertEqual(put(1, 10000, 1, first + 1).json["bookmark"]["revision"], 2)
        self.assertEqual(put(1, 10000, 1, first + 1).json["bookmark"]["revision"], 2)
        self.assertEqual(put(1, 25345, 1, first).status_code, 409)
        self.assertEqual(put(1, 12125, 2, first + 1).json["bookmark"]["ms"], 12125)
        self.assertEqual(put(3, 0, 3, first + 3).json["bookmark"]["revision"], 4)
        self.assertEqual(put(2, 0, 3, first + 2).status_code, 409)
        self.assertEqual(put(2, 0, 4, first + 2).status_code, 409)
        self.assertEqual(put(2, 0, 3, first + 4).status_code, 409)
        self.assertEqual(put(2, 0, 4, first + 4).json["bookmark"]["scene"], 2)

        def claim(marker, stamp, base, ms=0, explicit=True):
            return reader.put(url, base_url=ORIGIN, headers=headers, json=dict(
                chapter=1, scene=2, ms=ms, revision=base, chosen_at=stamp, choice_id=marker, claim=explicit))
        self.assertEqual(claim("reader-b", first+6, 3).json["bookmark"]["revision"], 6)
        self.assertEqual(claim("reader-a", first+6, 3).status_code, 409)
        self.assertEqual(claim("reader-b", first+6, 3).json["bookmark"]["revision"], 6)
        self.assertEqual(claim("reader-a", first+6, 6, 25000, False).status_code, 409)
        self.assertEqual(claim("reader-b", first+6, 6, 12125, False).json["bookmark"]["ms"], 12125)

    def test_book_positions_remain_separate(self):
        reader = self.account("reader@example.com")
        origin = {"Origin": "https://finance-fixer.net"}
        def position(book):
            return reader.get("/site/bookworm/" + book, base_url=ORIGIN, headers=origin)
        token = position("oz").json["csrf"]
        def save(book, chapter, scene, ms, revision=0):
            return reader.put("/site/bookworm/" + book, base_url=ORIGIN,
                              headers={**origin, "X-Bookworm-CSRF": token},
                              json=dict(chapter=chapter, scene=scene, ms=ms, revision=revision))
        self.assertEqual(save("oz", 24, 1, 1000).status_code, 200)
        self.assertIsNone(position("holmes").json["bookmark"])
        self.assertEqual(save("holmes", 12, 29, 7200).status_code, 200)
        self.assertEqual(position("oz").json["bookmark"]["ms"], 1000)
        self.assertEqual(save("holmes", 12, 30, 7200, 1).status_code, 400)
        self.assertEqual(save("holmes", 13, 1, 0, 1).status_code, 400)
        self.assertEqual(save("oz", 12, 29, 0, 1).status_code, 400)
        self.assertEqual(save("holmes", 1, 1, 0).status_code, 409)
        self.assertEqual(position("holmes").json["bookmark"]["revision"], 1)
        self.assertEqual(position("unknown").status_code, 404)

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
        self.assertIn("first+reply@example.com", response.get_data(as_text=True))
        self.assertNotIn("mailto:first", response.get_data(as_text=True))
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

    def test_consultation_restore_respects_later_deletions(self):
        from maintenance import reconcile_consultations
        import shutil
        initialize(self.path, b"test-installation")
        guest = self.guest
        first, second = self.consultation_data(guest, note="erase"), self.consultation_data(guest, note="keep")
        for form in [first, second]:
            self.assertEqual(self.send(guest, "/consultation", form).status_code, 303)
        with closing(connect(self.path)) as db:
            gone, keep = [row["id"] for row in db.execute("SELECT id FROM consultations ORDER BY note")]
        admin = self.account("admin@example.com")
        self.send(admin, "/consultations/"+keep, {"state":"상담","revision":"0"})
        directory=Path(self.tmp.name)/"copies"
        backup(self.path,directory)
        snapshot=next(directory.glob("*.sqlite"))
        safe=Path(self.tmp.name)/"restore.sqlite"
        discard=Path(self.tmp.name)/"no-ledger.sqlite"
        shutil.copyfile(snapshot,safe)
        shutil.copyfile(snapshot,discard)
        self.assertEqual(self.send(admin, "/consultations/"+gone+"/delete", {"confirm":"yes","revision":"0"}).status_code, 303)
        self.assertEqual(self.send(guest, "/consultation", first).status_code, 410)
        with closing(connect(safe)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM consultations WHERE restore_pending=0").fetchone()[0],0)
        with self.assertRaises(RuntimeError):
            initialize(safe, b"test-installation")
        reconcile_consultations(safe,self.path)
        reconcile_consultations(discard,None)
        older = Path(self.tmp.name)/"older.sqlite"
        shutil.copyfile(snapshot,older)
        reconcile_consultations(older,discard)
        with closing(connect(older)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM consultations").fetchone()[0],0)
        with closing(connect(safe)) as db:
            self.assertEqual([r[0] for r in db.execute("SELECT id FROM consultations WHERE restore_pending=0")],[keep])
            self.assertEqual(db.execute("SELECT state FROM consultation_updates WHERE inquiry=?",(keep,)).fetchone()[0],"상담")
        with closing(connect(discard)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM consultations").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM consultation_updates").fetchone()[0],0)

    def test_consultation_draft_survives_login_lifecycle(self):
        guest=self.guest
        data=self.consultation_data(guest)
        page=self.get(guest,"/consultation").get_data(as_text=True)
        data["csrf"]=re.search(r'name="csrf" value="([^"]+)"',page)[1]
        self.send(guest,"/login/request",{"email":"reader@example.com"})
        self.send(guest,"/login/confirm",{"code":self.sent["reader@example.com"]})
        form = self.get(guest,"/consultation").get_data(as_text=True).split('action="/logout"',1)[1]
        logout_csrf = re.search(r'name="csrf" value="([^"]+)"',form)[1]
        logout = guest.post("/logout",base_url=ORIGIN,headers={"Origin":ORIGIN},data={"csrf":logout_csrf})
        self.assertEqual(logout.status_code,303)
        response=guest.post("/consultation",base_url=ORIGIN,headers={"Origin":ORIGIN,"CF-Connecting-IP":"192.0.2.1"},data=data)
        self.assertEqual(response.status_code,303)

    # --- photo attachments and pinned notice (2026-11-26) ---
    def photo_bytes(self, fmt="JPEG", size=(400, 300), metadata=False, noise=False, orientation=None):
        import io, os
        from PIL import Image, ImageCms
        mode = "RGBA" if fmt in ("PNG", "WEBP") else "RGB"
        image = Image.frombytes(mode, size, os.urandom(size[0]*size[1]*len(mode))) if noise else Image.new(mode, size, (200, 30, 30) + ((128,) if mode == "RGBA" else ()))
        options = {}
        exif = Image.Exif()
        if metadata:
            exif[0x010F] = "SecretMaker"
            exif[0x0110] = "SecretModel"
            exif[0x8825] = {1: "N", 2: (37.0, 33.0, 1.0), 3: "E", 4: (127.0, 0.0, 1.0)}
            options.update(comment=b"secret-comment-location", icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
            if fmt == "JPEG":
                options["xmp"] = b'<x:xmpmeta xmlns:x="adobe:ns:meta/">secret-xmp</x:xmpmeta>'
        if orientation:
            exif[0x0112] = orientation
        if len(exif):
            options["exif"] = exif
        out = io.BytesIO()
        image.save(out, fmt, **options)
        return out.getvalue()

    def upload(self, c, files, title="사진 글", visibility="public", **extra):
        import io
        return self.send(c, "/write", dict(title=title, body="사진 본문", visibility=visibility,
                                           images=[(io.BytesIO(data), name) for name, data in files], **extra))

    def fresh_quota(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM events WHERE kind IN ('write','photo-try')")

    def photo_ids(self, html):
        return re.findall(r'<img src="/i/([0-9a-f]+)"', html)

    def test_photo_upload_shows_and_reencodes(self):
        from PIL import Image
        import io
        a = self.account("a@example.com")
        noisy = self.photo_bytes("PNG", size=(600, 500), noise=True)
        self.assertGreater(len(noisy), 600_000)
        response = self.upload(a, [("a.jpg", self.photo_bytes(size=(4032, 3024))), ("b.png", noisy), ("c.webp", self.photo_bytes("WEBP"))])
        self.assertEqual(response.status_code, 303)
        html = self.get(self.guest, response.location).get_data(as_text=True)
        ids = self.photo_ids(html)
        self.assertEqual(len(ids), 3)
        self.assertIn(f'<a href="/i/{ids[0]}">', html)
        self.assertIn("사진 3", self.get(a, "/?view=mine").get_data(as_text=True))
        first = self.get(self.guest, "/i/" + ids[0])
        self.assertEqual((first.status_code, first.mimetype), (200, "image/jpeg"))
        self.assertIn("no-store", first.headers["Cache-Control"])
        self.assertEqual(first.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(max(Image.open(io.BytesIO(first.data)).size), 2000)
        for iid in ids[1:]:
            self.assertEqual(Image.open(io.BytesIO(self.get(self.guest, "/i/" + iid).data)).format, "JPEG")
        # The photo is not a counted page view.
        from datetime import date
        from public_views import report
        before = report(self.path, date.today())["rows"][1]["today"]
        self.get(self.guest, "/i/" + ids[0])
        self.assertEqual(report(self.path, date.today())["rows"][1]["today"], before)

    def test_photo_metadata_and_orientation(self):
        from PIL import Image
        import io
        a = self.account("a@example.com")
        response = self.upload(a, [("gps.jpg", self.photo_bytes(metadata=True)), ("png.png", self.photo_bytes("PNG", metadata=True)),
                                   ("turn.jpg", self.photo_bytes(size=(300, 100), orientation=6))])
        self.assertEqual(response.status_code, 303)
        ids = self.photo_ids(self.get(a, response.location).get_data(as_text=True))
        for iid in ids:
            data = self.get(a, "/i/" + iid).data
            image = Image.open(io.BytesIO(data))
            self.assertEqual(len(image.getexif()), 0)
            for key in ("exif", "icc_profile", "comment", "xmp", "XML:com.adobe.xmp"):
                self.assertNotIn(key, image.info)
            for marker in (b"Exif", b"secret", b"SecretMaker", b"adobe:ns:meta", b"ICC_PROFILE"):
                self.assertNotIn(marker, data)
        self.assertEqual(Image.open(io.BytesIO(self.get(a, "/i/" + ids[2]).data)).size, (100, 300))

    def test_photo_rejections_keep_text_and_store_nothing(self):
        a = self.account("a@example.com")
        jpg = self.photo_bytes()
        cases = [
            ([("1.jpg", jpg)] * 4, "3장까지"),
            ([("big.jpg", jpg + b"\0" * (5 * 1024 * 1024))], "5MB"),
            ([("fake.jpg", b"not an image at all")], "JPG·PNG·WebP"),
            ([("photo.heic", b"\0\0\0\x18ftypheic\0\0\0\0mif1heic")], "HEIC"),
            ([("anim.gif", __import__("base64").b64decode("R0lGODlhAQABAAAAACw="))], "JPG·PNG·WebP"),
        ]
        for files, reason in cases:
            response = self.upload(a, files, title="보존될 제목")
            html = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 400, reason)
            self.assertIn(reason, html)
            self.assertIn("사진은 다시 골라 주세요", html)
            self.assertIn('value="보존될 제목"', html)
            self.assertIn("사진 본문", html)
        too_large = self.upload(a, [("x.jpg", jpg + b"\0" * (25 * 1024 * 1024))])
        self.assertEqual(too_large.status_code, 413)
        self.assertIn("5MB, 3장까지", too_large.get_data(as_text=True))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM images").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM posts WHERE title='보존될 제목'").fetchone()[0], 0)
        # Rejections do not use up the writing quota.
        self.assertEqual(self.upload(a, [("ok.jpg", jpg)]).status_code, 303)
        # Text-only posts and other forms keep their old behavior and limits.
        self.fresh_quota()
        self.assertEqual(self.create(a, "public")[:3], "/p/")
        self.assertEqual(self.send(a, "/login/request", {"email": "x" * 60000}).status_code, 413)

    def test_upload_body_not_read_without_login_or_origin(self):
        import io
        from unittest.mock import patch
        a = self.account("a@example.com")
        form = self.get(self.guest, "/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf" value="([^"]+)"', form)[1]
        with patch("app.convert") as convert:
            guest = self.guest.post("/write", base_url=ORIGIN, headers={"Origin": ORIGIN, "CF-Connecting-IP": "192.0.2.1"},
                                    data=dict(csrf=csrf, title="t", body="b", visibility="public", images=[(io.BytesIO(self.photo_bytes()), "a.jpg")]))
            self.assertEqual(guest.status_code, 403)
            foreign = a.post("/write", base_url=ORIGIN, headers={"Origin": "https://example.org", "CF-Connecting-IP": "192.0.2.1"},
                             data=dict(title="t", body="b", visibility="public", images=[(io.BytesIO(self.photo_bytes()), "a.jpg")]))
            self.assertEqual(foreign.status_code, 403)
            convert.assert_not_called()

    def test_private_hidden_and_deleted_photos(self):
        a = self.account("a@example.com")
        b = self.account("b@example.com")
        op = self.account("admin@example.com")
        private = self.upload(a, [("p.jpg", self.photo_bytes())], visibility="private").location
        [secret] = self.photo_ids(self.get(a, private).get_data(as_text=True))
        for reader, status in ((a, 200), (op, 200), (b, 404), (self.guest, 404)):
            self.assertEqual(self.get(reader, "/i/" + secret).status_code, status)
        self.fresh_quota()
        public = self.upload(a, [("q.jpg", self.photo_bytes())]).location
        [shown] = self.photo_ids(self.get(self.guest, public).get_data(as_text=True))
        self.assertEqual(self.send(op, public + "/manage", {"action": "hide"}).status_code, 303)
        self.assertEqual(self.get(self.guest, "/i/" + shown).status_code, 404)
        self.assertEqual(self.get(a, "/i/" + shown).status_code, 404)
        self.assertEqual(self.get(op, "/i/" + shown).status_code, 200)
        self.assertEqual(self.send(op, public + "/manage", {"action": "delete"}).status_code, 303)
        self.assertEqual(self.send(a, private + "/manage", {"action": "delete"}).status_code, 303)
        for iid in (secret, shown):
            self.assertEqual(self.get(op, "/i/" + iid).status_code, 404)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM images").fetchone()[0], 0)
            # Deleting posts does not hand back the daily photo allowance.
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='photo' AND bucket!='*'").fetchone()[0], 2)

    def test_photo_daily_limits_roll_back_the_post(self):
        import time
        from unittest.mock import patch
        a = self.account("a@example.com")
        owner = None
        with closing(sqlite3.connect(self.path)) as db, db:
            owner = db.execute("SELECT owner FROM sessions").fetchone()[0]
            db.executemany("INSERT INTO events VALUES ('photo',?,?)", [(owner, int(time.time()))] * 14)
        over = self.upload(a, [("1.jpg", self.photo_bytes()), ("2.jpg", self.photo_bytes())], title="한도 초과")
        self.assertEqual(over.status_code, 429)
        self.assertIn("사진 수를 넘었습니다", over.get_data(as_text=True))
        self.assertEqual(self.upload(a, [("1.jpg", self.photo_bytes())]).status_code, 303)
        self.fresh_quota()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM events WHERE kind='photo'")
        with patch("app.PHOTO_STORAGE", 10):
            full = self.upload(a, [("1.jpg", self.photo_bytes())], title="공간 부족")
        self.assertEqual(full.status_code, 503)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM posts WHERE title IN ('한도 초과','공간 부족')").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM images").fetchone()[0], 1)

    def test_pinned_notice(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            # Opening posts are stamped at setup; move them back so new posts sort first.
            db.execute("UPDATE posts SET created=created-86400")
        a = self.account("a@example.com")
        op = self.account("admin@example.com")
        first = self.create(op, "public")
        self.fresh_quota()
        second = self.send(op, "/write", dict(title="두 번째 공지", body="본문", visibility="public")).location
        self.fresh_quota()
        private = self.create(a, "private")
        self.assertEqual(self.send(a, first + "/manage", {"action": "pin"}).status_code, 403)
        self.assertNotIn("맨 위 공지로 고정", self.get(a, first).get_data(as_text=True))
        self.assertEqual(self.send(op, private + "/manage", {"action": "pin"}).status_code, 400)
        self.assertNotIn("맨 위 공지로 고정", self.get(op, private).get_data(as_text=True))
        self.assertEqual(self.send(op, first + "/manage", {"action": "pin"}).status_code, 303)
        listing = self.get(self.guest, "/").get_data(as_text=True)
        self.assertEqual(listing.count(f'href="{first}"'), 1)
        self.assertLess(listing.index("공지"), listing.index(f'href="{second}"'))
        self.assertLess(listing.index(f'href="{first}"'), listing.index(f'href="{second}"'))
        self.assertIn("공지 고정 해제", self.get(op, first).get_data(as_text=True))
        # One notice at a time; a stale unpin of the old notice keeps the new one.
        self.assertEqual(self.send(op, second + "/manage", {"action": "pin"}).status_code, 303)
        self.assertEqual(self.send(op, first + "/manage", {"action": "unpin"}).status_code, 303)
        listing = self.get(self.guest, "/").get_data(as_text=True)
        self.assertLess(listing.index(f'href="{second}"'), listing.index(f'href="{first}"'))
        self.assertIn("notice-tag", listing)
        self.assertNotIn("notice-tag", self.get(a, "/?view=mine").get_data(as_text=True))
        # Hidden notice: readers see an empty slot, the post is not listed elsewhere either.
        self.send(op, second + "/manage", {"action": "hide"})
        self.assertNotIn(f'href="{second}"', self.get(self.guest, "/").get_data(as_text=True))
        editor_list = self.get(op, "/").get_data(as_text=True)
        self.assertIn(f'href="{second}"', editor_list)
        self.assertNotIn("notice-tag", editor_list)
        self.send(op, second + "/manage", {"action": "delete"})
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM pinned").fetchone()[0], 0)
        self.assertNotIn("notice-tag", self.get(self.guest, "/").get_data(as_text=True))
        # The notice is not repeated on later pages.
        self.send(op, first + "/manage", {"action": "pin"})
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany("INSERT INTO posts(id,owner,title,body,private,created) VALUES (?,?,?,?,0,?)",
                           [(f"{i:024x}", "editorial", f"채움 {i}", "본문", i) for i in range(30)])
        self.assertNotIn("notice-tag", self.get(self.guest, "/?page=2").get_data(as_text=True))

    def converted(self, data):
        import io
        from PIL import Image
        from photos import convert
        out, width, height = convert(io.BytesIO(data))
        return Image.open(io.BytesIO(out)), out

    def test_phone_and_unusual_image_formats(self):
        import io
        from PIL import Image, ImageCms
        from photos import Rejected
        # HEIC straight from a phone, with location and camera tags.
        exif = Image.Exif(); exif[0x010F] = "SecretMaker"; exif[0x8825] = {1: "N", 2: (37.0, 33.0, 1.0)}
        buffer = io.BytesIO(); Image.new("RGB", (640, 480), (200, 30, 30)).save(buffer, "HEIF", exif=exif, quality=80)
        image, raw = self.converted(buffer.getvalue())
        self.assertEqual((image.format, image.size), ("JPEG", (640, 480)))
        self.assertNotIn(b"SecretMaker", raw); self.assertEqual(len(image.getexif()), 0)
        # 16-bit grayscale keeps its shades instead of turning white.
        gray = Image.new("I;16", (30, 10)); [gray.paste(Image.new("I;16", (10, 10), v), (i * 10, 0)) for i, v in enumerate((8192, 32768, 57344))]
        buffer = io.BytesIO(); gray.save(buffer, "PNG")
        image, _ = self.converted(buffer.getvalue())
        shades = [image.getpixel((i * 10 + 5, 5))[0] for i in range(3)]
        self.assertTrue(shades[0] < shades[1] < shades[2] < 250, shades)
        # A color-keyed transparent RGB PNG shows white where it was transparent.
        keyed = Image.new("RGB", (20, 20), (16, 148, 80)); buffer = io.BytesIO(); keyed.save(buffer, "PNG", transparency=(16, 148, 80))
        image, _ = self.converted(buffer.getvalue())
        self.assertGreater(min(image.getpixel((10, 10))), 245)
        # Multi-picture JPEG (MPO) is a JPEG for limits and decoding.
        first = Image.new("RGB", (4800, 3600), (90, 120, 150)); buffer = io.BytesIO()
        first.save(buffer, "MPO", save_all=True, append_images=[Image.new("RGB", (320, 240))])
        self.assertEqual(Image.open(io.BytesIO(buffer.getvalue())).format, "MPO")
        self.assertEqual(self.converted(buffer.getvalue())[0].size, (2000, 1500))
        # Wide panoramas are reduced while decoding and come out with a 2000px long edge.
        buffer = io.BytesIO(); Image.new("RGB", (8000, 3000), (90, 120, 150)).save(buffer, "JPEG")
        self.assertEqual(self.converted(buffer.getvalue())[0].size, (2000, 750))
        # Over 50MP: the message is about resolution, not file type.
        buffer = io.BytesIO(); Image.new("RGB", (7200, 7000)).save(buffer, "JPEG")
        with self.assertRaisesRegex(Rejected, "해상도"):
            self.converted(buffer.getvalue())
        # A palette PNG with a color profile is converted like the same RGB picture.
        linear = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        rgb = Image.new("RGB", (8, 8), (128, 64, 32))
        outputs = []
        from unittest.mock import patch
        for picture in (rgb, rgb.convert("P", palette=Image.Palette.ADAPTIVE)):
            buffer = io.BytesIO(); picture.save(buffer, "PNG", icc_profile=linear)
            with patch("photos.ImageCms.profileToProfile", wraps=ImageCms.profileToProfile) as transform:
                outputs.append(self.converted(buffer.getvalue())[0].getpixel((4, 4)))
            self.assertEqual(transform.call_count, 1, picture.mode)
        self.assertTrue(all(abs(a - b) <= 6 for a, b in zip(*outputs)), outputs)

    def test_photo_attempts_rejected_posts_and_head(self):
        import io
        a = self.account("a@example.com")
        op = self.account("admin@example.com")
        self.upload(a, [("1.jpg", self.photo_bytes())] * 4)
        self.upload(a, [("1.jpg", self.photo_bytes())], title="")
        with closing(sqlite3.connect(self.path)) as db, db:
            tries = db.execute("SELECT count(*) FROM events WHERE kind='photo-try'").fetchone()[0]
        self.assertEqual(tries, 4)  # two submissions, account and network buckets
        with closing(sqlite3.connect(self.path)) as db, db:
            owner = db.execute("SELECT owner FROM sessions").fetchall()
            db.executemany("INSERT INTO events VALUES ('photo-try',?,strftime('%s','now'))", [(o[0],) for o in owner for _ in range(20)])
        limited = self.upload(a, [("1.jpg", self.photo_bytes())], title="이어 쓸 제목")
        self.assertEqual(limited.status_code, 429)
        self.assertIn('value="이어 쓸 제목"', limited.get_data(as_text=True))
        head = a.open("/write", method="HEAD", base_url=ORIGIN, headers={"Origin": ORIGIN, "CF-Connecting-IP": "192.0.2.1"},
                      data=dict(title="t", body="b", visibility="public", images=[(io.BytesIO(self.photo_bytes()), "a.jpg")]))
        self.assertEqual(head.status_code, 200)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM posts WHERE owner!='editorial'").fetchone()[0], 0)
        # A hidden post cannot replace the notice readers see.
        notice = self.create(op, "public")
        self.fresh_quota()
        hidden = self.send(op, "/write", dict(title="숨길 글", body="본문", visibility="public")).location
        self.send(op, notice + "/manage", {"action": "pin"})
        self.send(op, hidden + "/manage", {"action": "hide"})
        self.assertNotIn("맨 위 공지로 고정", self.get(op, hidden).get_data(as_text=True))
        self.assertEqual(self.send(op, hidden + "/manage", {"action": "pin"}).status_code, 400)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT post FROM pinned").fetchone()[0], notice.rsplit("/", 1)[1])

    @staticmethod
    def gray_icc(gamma=1.0):
        """A minimal ICC v2 gray profile (linear when gamma is 1.0) for color-conversion tests."""
        import struct
        def fixed(v): return struct.pack(">i", round(v * 65536))
        def pad(b): return b + b"\0" * (-len(b) % 4)
        text = b"Linear gray test"
        tags = [(b"desc", pad(b"desc\0\0\0\0" + struct.pack(">I", len(text) + 1) + text + b"\0" + b"\0" * 8 + b"\0" * 3 + b"\0" * 67)),
                (b"wtpt", b"XYZ \0\0\0\0" + fixed(0.9642) + fixed(1.0) + fixed(0.8249)),
                (b"kTRC", pad(b"curv\0\0\0\0" + struct.pack(">IH", 1, round(gamma * 256)))),
                (b"cprt", pad(b"text\0\0\0\0" + b"test\0"))]
        offset = 128 + 4 + 12 * len(tags); table = b""; body = b""
        for sig, data in tags:
            table += sig + struct.pack(">II", offset + len(body), len(data)); body += data
        size = offset + len(body)
        header = (struct.pack(">I", size) + b"\0" * 4 + struct.pack(">I", 0x02100000) + b"mntrGRAYXYZ " + b"\0" * 12 + b"acsp"
                  + b"\0" * 24 + struct.pack(">I", 0) + fixed(0.9642) + fixed(1.0) + fixed(0.8249) + b"\0" * 48)
        assert len(header) == 128
        return header + struct.pack(">I", len(tags)) + table + body

    def test_png_color_edge_cases(self):
        import io
        from PIL import Image, ImageCms
        icc = self.gray_icc()
        self.assertEqual(ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile.xcolor_space.strip(), "GRAY")
        # Gray with and without an opaque alpha channel convert the same way through the gray profile.
        outputs = []
        for picture in (Image.new("L", (8, 8), 128), Image.new("LA", (8, 8), (128, 255))):
            buffer = io.BytesIO(); picture.save(buffer, "PNG", icc_profile=icc)
            outputs.append(self.converted(buffer.getvalue())[0].getpixel((4, 4))[0])
        self.assertTrue(outputs[0] > 170 and abs(outputs[0] - outputs[1]) <= 3, outputs)
        # PNG gamma 1.0 without ICC is shown gamma-corrected, as browsers do.
        raw = io.BytesIO(); Image.new("RGB", (8, 8), (128, 128, 128)).save(raw, "PNG")
        data = raw.getvalue(); import struct, zlib
        chunk = b"gAMA" + struct.pack(">I", 100000)
        data = data[:33] + struct.pack(">I", 4) + chunk + struct.pack(">I", zlib.crc32(chunk)) + data[33:]
        self.assertAlmostEqual(Image.open(io.BytesIO(data)).info["gamma"], 1.0)
        self.assertGreater(self.converted(data)[0].getpixel((4, 4))[0], 175)
        # A 16-bit gray PNG whose transparent key is an original 16-bit value shows white there.
        gray = Image.new("I;16", (20, 10)); gray.paste(Image.new("I;16", (10, 10), 32768), (0, 0)); gray.paste(Image.new("I;16", (10, 10), 8192), (10, 0))
        buffer = io.BytesIO(); gray.save(buffer, "PNG", transparency=32768)
        image = self.converted(buffer.getvalue())[0]
        self.assertGreater(min(image.getpixel((4, 5))), 245)
        self.assertLess(image.getpixel((15, 5))[0], 60)

    def test_heic_primary_image_and_linear_png_shadows(self):
        import io, struct, zlib
        import pillow_heif
        from PIL import Image
        heif = pillow_heif.HeifFile()
        heif.add_from_pillow(Image.new("RGB", (64, 32), (220, 20, 20)))
        heif.add_from_pillow(Image.new("RGB", (32, 64), (20, 20, 220)))
        buffer = io.BytesIO(); heif.save(buffer, primary_index=1, quality=90)
        image = self.converted(buffer.getvalue())[0]
        self.assertEqual(image.size, (32, 64))
        red, green, blue = image.getpixel((16, 32))
        self.assertGreater(blue, red + 100)
        def linear_png(level):
            raw = io.BytesIO(); Image.new("L", (16, 16), level).save(raw, "PNG"); data = raw.getvalue()
            chunk = b"gAMA" + struct.pack(">I", 100000)
            return data[:33] + struct.pack(">I", 4) + chunk + struct.pack(">I", zlib.crc32(chunk)) + data[33:]
        for level, expected in ((1, 13), (2, 22), (4, 34), (128, 188)):
            self.assertLessEqual(abs(self.converted(linear_png(level))[0].getpixel((8, 8))[0] - expected), 2, level)


if __name__=="__main__":
    unittest.main()
