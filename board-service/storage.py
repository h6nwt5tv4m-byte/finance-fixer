"""Board persistence. All authorization decisions use the same visibility predicates."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parent
VISIBLE = "((p.hidden=0 OR :admin) AND (p.private=0 OR p.owner=:uid OR :admin))"
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
CREATE TABLE IF NOT EXISTS seeded(key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS challenges(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, proof TEXT NOT NULL, expires INTEGER NOT NULL, tries INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(kind TEXT, bucket TEXT, at INTEGER);
CREATE INDEX IF NOT EXISTS event_idx ON events(kind,bucket,at);
CREATE TABLE IF NOT EXISTS blocked(owner TEXT PRIMARY KEY);
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
    db = connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        items = json.loads((ROOT / "seed.json").read_text())
        with write(db):
            if identity_key is not None:
                fingerprint=hashlib.sha256(identity_key).hexdigest()
                db.execute("INSERT OR IGNORE INTO settings VALUES ('identity-key',?)",(fingerprint,))
                stored=db.execute("SELECT value FROM settings WHERE name='identity-key'").fetchone()[0]
                if stored!=fingerprint:
                    raise RuntimeError("Restore the matching board identity key before starting.")
            for i, item in enumerate(items, start=1):
                key = f"opening-{i:02}"
                if db.execute("INSERT OR IGNORE INTO seeded VALUES (?)", (key,)).rowcount:
                    pid = hashlib.sha256(key.encode()).hexdigest()[:24]
                    db.execute("""INSERT INTO posts(id,owner,title,body,private,created,source_date,source_url)
                                  VALUES (?,'editorial',?,?,0,?,?,?)""", (pid,item["title"],item["body"],
                               int(time.time()),item["source_date"],item["source_url"]))
    finally:
        db.close()

def expire(db, now):
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
