"""Initialize board data and take a private, consistent daily snapshot."""
from datetime import date
import fcntl
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import secrets
import shutil
import sys
import time
from storage import connect, expire, initialize, write

DATABASE = Path("/var/lib/finance-board/board.sqlite")

def backup(database, directory):
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (directory/".snapshot.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for item in directory.glob("????-??-??.sqlite"):
            if (date.today()-date.fromisoformat(item.stem)).days >= 7:
                item.unlink()
        work = directory / "restore-work"
        if work.is_dir() and not work.is_symlink():
            for item in work.iterdir():
                if (len(item.name)==10 and item.name.isascii() and item.name.isdigit()
                        and int(item.name)<=int(time.time())-86400 and not item.is_symlink() and item.is_dir()):
                    shutil.rmtree(item)
        save_snapshot(database,directory)

def save_snapshot(database,directory):
    today=date.today()
    target=directory/f"{today}.sqlite"
    pending=directory/".snapshot.pending"
    pending.unlink(missing_ok=True)
    source=sqlite3.connect(f"file:{database}?mode=ro",uri=True)
    try:
        # SQLite owns and unlinks this unnamed temporary database. Named backup files
        # only ever receive the sanitized snapshot, including after an interrupted run.
        with closing(sqlite3.connect("")) as clean:
            source.backup(clean)
            clean.execute("PRAGMA secure_delete=ON")
            with clean:
                clean.execute("DELETE FROM sessions")
                clean.execute("DELETE FROM challenges")
                clean.execute("UPDATE consultations SET restore_pending=1")
                clean.execute("INSERT OR REPLACE INTO settings VALUES ('consultation-restore-pending','1')")
                clean.execute("INSERT OR REPLACE INTO settings VALUES ('consultation-ticket-generation',?)",
                              (secrets.token_hex(16),))
            with closing(sqlite3.connect(pending)) as dest:
                clean.backup(dest)
                if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise RuntimeError("invalid snapshot")
        pending.chmod(0o600)
        pending.replace(target)
    finally:
        source.close()
        pending.unlink(missing_ok=True)

def reconcile_consultations(candidate, latest):
    """Activate private rows only in an offline restore copy, using the current erasure register."""
    candidate = Path(candidate).resolve(strict=True)
    if (candidate == DATABASE.resolve() or candidate.stat().st_nlink != 1
            or candidate.parent == Path("/var/lib/finance-board-backup")):
        raise ValueError("복구용 별도 작업 사본을 지정하세요.")
    with closing(connect(candidate)) as target, write(target):
        if not target.execute("SELECT 1 FROM settings WHERE name='consultation-restore-pending'").fetchone():
            raise ValueError("상담 복구 대기 상태의 사본만 처리할 수 있습니다.")
        if latest is None:
            target.execute("DELETE FROM consultations WHERE restore_pending=1")
        else:
            latest = Path(latest).resolve(strict=True)
            if candidate.samefile(latest):
                raise ValueError("검증된 최신 삭제 기록이 필요합니다.")
            with closing(sqlite3.connect(latest.as_uri()+"?mode=ro", uri=True)) as source:
                if source.execute("SELECT 1 FROM settings WHERE name='consultation-restore-pending'").fetchone():
                    raise ValueError("미검증 백업은 최신 삭제 기록으로 사용할 수 없습니다.")
                fingerprint = "SELECT value FROM settings WHERE name='identity-key'"
                key = target.execute(fingerprint).fetchone()
                if not key or source.execute(fingerprint).fetchone() != (key[0],):
                    raise ValueError("같은 설치의 최신 삭제 기록을 지정하세요.")
                erased = source.execute("SELECT id,erased FROM erased_consultations")
                target.executemany("INSERT OR REPLACE INTO erased_consultations(id,erased) VALUES (?,?)", erased)
            target.execute("DELETE FROM consultations WHERE id IN (SELECT id FROM erased_consultations)")
            target.execute("UPDATE consultations SET restore_pending=0 WHERE restore_pending=1")
        expire(target, int(time.time()))
        target.execute("DELETE FROM settings WHERE name='consultation-restore-pending'")


if __name__=="__main__":
    os.umask(0o077)
    if sys.argv[1]=="initialize":
        key=(Path(os.environ["CREDENTIALS_DIRECTORY"])/"identity-key").read_bytes()
        initialize(DATABASE,key)
    elif sys.argv[1]=="expire":
        db=connect(DATABASE)
        try:
            with write(db):
                expire(db,int(time.time()))
        finally:
            db.close()
    elif sys.argv[1]=="restore-consultations" and len(sys.argv)==4:
        reconcile_consultations(sys.argv[2], None if sys.argv[3]=="--discard" else sys.argv[3])
    elif sys.argv[1]=="backup":
        backup(DATABASE,Path("/var/lib/finance-board-backup"))
    else:
        raise SystemExit(2)
