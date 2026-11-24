"""Initialize board data and take a private, consistent daily snapshot."""
from datetime import date
import os
from pathlib import Path
import sqlite3
import sys
import time
from storage import connect, expire, initialize, write

DATABASE = Path("/var/lib/finance-board/board.sqlite")

def backup(database, directory):
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    today=date.today()
    target=directory/f"{today}.sqlite"
    pending=directory/f".{today}.tmp"
    source=sqlite3.connect(f"file:{database}?mode=ro",uri=True)
    try:
        dest=sqlite3.connect(pending)
        try:
            source.backup(dest)
            dest.execute("PRAGMA secure_delete=ON")
            with dest:
                dest.execute("DELETE FROM sessions")
                dest.execute("DELETE FROM challenges")
            if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise RuntimeError("invalid snapshot")
        finally:
            dest.close()
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
