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
        first=self.app.test_client()
        self.assertEqual(self.send(first,"/login/request",{"email":"Writer@example.test"}).status_code,303)
        self.assertEqual(self.send(self.guest,"/login/request",{"email":"writer@example.test"}).status_code,429)
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

if __name__=="__main__":
    unittest.main()
