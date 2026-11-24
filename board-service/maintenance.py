"""Initialize board data and take a private, consistent daily snapshot."""
from datetime import date
import fcntl
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import time
from storage import connect, expire, initialize, write

DATABASE = Path("/var/lib/finance-board/board.sqlite")

def backup(database, directory):
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (directory/".snapshot.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
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
            with closing(sqlite3.connect(pending)) as dest:
                clean.backup(dest)
                if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise RuntimeError("invalid snapshot")
        pending.chmod(0o600)
        pending.replace(target)
    finally:
        source.close()
        pending.unlink(missing_ok=True)
    for item in directory.glob("????-??-??.sqlite"):
        if (today-date.fromisoformat(item.stem)).days>=7:
            item.unlink()

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
    elif sys.argv[1]=="backup":
        backup(DATABASE,Path("/var/lib/finance-board-backup"))
    else:
        raise SystemExit(2)
