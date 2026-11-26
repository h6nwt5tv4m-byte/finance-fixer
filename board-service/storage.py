"""Board persistence. All authorization decisions use the same visibility predicates."""
from contextlib import contextmanager
import hashlib
import json
import secrets
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parent
VISIBLE = "((p.hidden=0 OR :admin) AND (p.private=0 OR p.owner=:uid OR :admin))"
CONSULTATION_RETENTION = 90 * 86400
SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 private INTEGER NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL,
 source_date TEXT, source_url TEXT);
CREATE INDEX IF NOT EXISTS posts_order ON posts(created DESC);
CREATE TABLE IF NOT EXISTS comments(
 id TEXT PRIMARY KEY, post TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 owner TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL, hidden INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS replies ON comments(post,created);
CREATE TABLE IF NOT EXISTS images(
 id TEXT PRIMARY KEY, post TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 seq INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, size INTEGER NOT NULL,
 created INTEGER NOT NULL, data BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS images_post ON images(post,seq);
CREATE TABLE IF NOT EXISTS pinned(
 slot INTEGER PRIMARY KEY CHECK(slot=1), post TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS seeded(key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS challenges(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, proof TEXT NOT NULL, expires INTEGER NOT NULL, tries INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(kind TEXT, bucket TEXT, at INTEGER);
CREATE INDEX IF NOT EXISTS event_idx ON events(kind,bucket,at);
CREATE TABLE IF NOT EXISTS reading_bookmarks(
 owner TEXT NOT NULL, book TEXT NOT NULL, chapter INTEGER NOT NULL, scene INTEGER NOT NULL,
 ms INTEGER NOT NULL, revision INTEGER NOT NULL, chosen_at INTEGER NOT NULL DEFAULT 0, choice_id TEXT NOT NULL DEFAULT '', PRIMARY KEY(owner,book));
CREATE TABLE IF NOT EXISTS consultations(
 id TEXT PRIMARY KEY, email TEXT NOT NULL, topic TEXT NOT NULL, note TEXT NOT NULL,
 created INTEGER NOT NULL, notice TEXT NOT NULL, state TEXT NOT NULL DEFAULT '접수',
 revision INTEGER NOT NULL DEFAULT 0, restore_pending INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS consultation_updates(
 inquiry TEXT NOT NULL REFERENCES consultations(id) ON DELETE CASCADE, revision INTEGER NOT NULL,
 state TEXT NOT NULL, changed INTEGER NOT NULL, PRIMARY KEY(inquiry,revision));
CREATE TABLE IF NOT EXISTS erased_consultations(id TEXT PRIMARY KEY, erased INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS consultation_sources(week TEXT NOT NULL, source TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(week,source));
CREATE INDEX IF NOT EXISTS consultations_created ON consultations(created,id);
CREATE TABLE IF NOT EXISTS blocked(owner TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS public_view_counts(
 day TEXT NOT NULL, source TEXT NOT NULL, views INTEGER NOT NULL, PRIMARY KEY(day,source));
CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT NOT NULL);
"""

def connect(path):
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA secure_delete=ON")
    return db

@contextmanager
def write(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise

def initialize(path, identity_key=None):
    if identity_key == b"":
        raise ValueError("Missing board identity credential.")
    db = connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        items = json.loads((ROOT / "seed.json").read_text())
        with write(db):
            if db.execute("SELECT 1 FROM settings WHERE name='consultation-restore-pending'").fetchone():
                raise RuntimeError("먼저 별도 복구 사본에 maintenance.py restore-consultations를 실행하세요.")
            if "chosen_at" not in {row["name"] for row in db.execute("PRAGMA table_info(reading_bookmarks)")}:
                db.execute("ALTER TABLE reading_bookmarks ADD COLUMN chosen_at INTEGER NOT NULL DEFAULT 0")
            if "choice_id" not in {row["name"] for row in db.execute("PRAGMA table_info(reading_bookmarks)")}:
                db.execute("ALTER TABLE reading_bookmarks ADD COLUMN choice_id TEXT NOT NULL DEFAULT ''")
            if "restore_pending" not in {row["name"] for row in db.execute("PRAGMA table_info(consultations)")}:
                db.execute("ALTER TABLE consultations ADD COLUMN restore_pending INTEGER NOT NULL DEFAULT 0")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('consultation-ledger-id',?)", (secrets.token_hex(16),))
            if identity_key is not None:
                fingerprint=hashlib.sha256(identity_key).hexdigest()
                stored=db.execute("SELECT value FROM settings WHERE name='identity-key'").fetchone()
                if stored is None:
                    # The board launched with key fingerprints. Only initialize pristine/seed-only data.
                    has_owners=db.execute("""SELECT EXISTS(SELECT 1 FROM posts WHERE owner!='editorial')
                        OR EXISTS(SELECT 1 FROM comments) OR EXISTS(SELECT 1 FROM blocked)
                        OR EXISTS(SELECT 1 FROM sessions) OR EXISTS(SELECT 1 FROM challenges) OR EXISTS(SELECT 1 FROM reading_bookmarks)
                        OR EXISTS(SELECT 1 FROM consultations)""").fetchone()[0]
                    if has_owners:
                        raise RuntimeError("Unversioned user data requires recovery from a verified source.")
                    db.execute("INSERT INTO settings VALUES ('identity-key',?)",(fingerprint,))
                elif stored[0]!=fingerprint:
                    raise RuntimeError("Restore the matching board identity key before starting.")
            for i, item in enumerate(items, start=1):
                key = f"opening-{i:02}"
                if db.execute("INSERT OR IGNORE INTO seeded VALUES (?)", (key,)).rowcount:
                    pid = hashlib.sha256(key.encode()).hexdigest()[:24]
                    db.execute("""INSERT INTO posts(id,owner,title,body,private,created,source_date,source_url)
                                  VALUES (?,'editorial',?,?,0,?,?,?)""", (pid,item["title"],item["body"],
                               int(time.time()),item["source_date"],item["source_url"]))
            # The October archive entry referred to the contact link predating the video section.
            if db.execute("INSERT OR IGNORE INTO settings VALUES ('correction-video-contact','done')").rowcount:
                video=next(item for item in items if item["title"]=="글보다 영상이 편한 날에는")
                db.execute("""UPDATE posts SET body=?,source_url=? WHERE owner='editorial'
                              AND title=? AND source_url='https://finance-fixer.net/#videos'""",
                           (video["body"],video["source_url"],video["title"]))
            if db.execute("INSERT OR IGNORE INTO settings VALUES ('correction-audit-plan-amount','done')").rowcount:
                audit=items[0]
                db.execute("""UPDATE posts SET body=? WHERE id=? AND owner='editorial' AND title=?""",
                           (audit["body"],hashlib.sha256(b"opening-01").hexdigest()[:24],audit["title"]))
    finally:
        db.close()

def expire(db, now):
    db.execute("DELETE FROM settings WHERE name='consultation-discard-through' AND CAST(value AS INTEGER)<=?",
               (now-CONSULTATION_RETENTION,))
    db.execute("DELETE FROM erased_consultations WHERE erased<=?", (now-CONSULTATION_RETENTION,))
    db.execute("DELETE FROM consultations WHERE created<=?", (now-CONSULTATION_RETENTION,))
    db.execute("DELETE FROM events WHERE at<=?", (now-86400,))
    db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
    db.execute("DELETE FROM challenges WHERE expires<=? OR tries<=0", (now,))

def reserve(db, kind, limits, now):
    """Called under a write lock. One event per distinct bucket."""
    for bucket, seconds, count in limits:
        recent = db.execute("SELECT COUNT(*) FROM events WHERE kind=? AND bucket=? AND at>?",
                            (kind, bucket, now-seconds)).fetchone()[0]
        if recent >= count:
            return False
    db.executemany("INSERT INTO events VALUES (?,?,?)",
                   [(kind,bucket,now) for bucket in dict.fromkeys(row[0] for row in limits)])
    return True
