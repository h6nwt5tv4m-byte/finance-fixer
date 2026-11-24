"""systemd Accept=yes handler. Only the board UID may send fixed verification messages."""
from email.message import EmailMessage
import json
import os
from pathlib import Path
import pwd
import re
import smtplib
import socket
import sqlite3
import ssl
import struct
import time
from mail_protocol import DeliveryUncertain, address, mailbox_limit
from storage import write

def handle(sock):
    peer = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if peer[1] != pwd.getpwnam("finance-board").pw_uid:
        raise ValueError("peer")
    stream = sock.makefile("rb")
    recipient = address(stream.readline(260).removesuffix(b"\n").decode("ascii"))
    code = stream.readline(8).decode("ascii").removesuffix("\n")
    if not re.fullmatch("[0-9]{6}",code) or stream.read(1):
        raise ValueError("format")
    db = sqlite3.connect("/var/lib/finance-board-mail/quota.sqlite", isolation_level=None)
    now = int(time.time())
    cfgdir = Path(os.environ["CREDENTIALS_DIRECTORY"])
    import hmac
    dest = hmac.new((cfgdir/"mail-key").read_bytes(),mailbox_limit(recipient).encode(),"sha256").hexdigest()
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sent(dest TEXT, at INTEGER)")
        with write(db):
            db.execute("DELETE FROM sent WHERE at<=?", (now-86400,))
            if db.execute("SELECT COUNT(*) FROM sent").fetchone()[0]>=250 or db.execute("SELECT COUNT(*) FROM sent WHERE dest=?", (dest,)).fetchone()[0]>=8:
                raise ValueError("limit")
            db.execute("INSERT INTO sent VALUES (?,?)",(dest,now))
    finally:
        db.close()
    mail = json.loads((cfgdir/"smtp").read_text())
    if mail["security"] != "ssl":
        raise ValueError("SMTP transport")
    msg = EmailMessage()
    msg["From"] = "재무해결사 자유게시판 <"+address(mail["from"])+">"
    msg["To"] = recipient
    msg["Subject"] = "재무해결사 자유게시판 이메일 인증번호"
    msg.set_content(f"게시판 로그인 인증번호는 {code} 입니다. 10분 안에 요청한 화면에 입력하세요.\n직접 요청하지 않으셨다면 이 메일을 무시하세요.")
    smtp=smtplib.SMTP_SSL(mail["host"],int(mail["port"]),timeout=8,context=ssl.create_default_context())
    try:
        smtp.login(mail["user"],mail["password"])
        try:
            smtp.send_message(msg,from_addr=mail["from"],to_addrs=[recipient])
        except (smtplib.SMTPResponseException,smtplib.SMTPRecipientsRefused):
            raise
        except OSError as exc:
            raise DeliveryUncertain("SMTP acknowledgement unavailable") from exc
    finally:
        smtp.close()

if __name__ == "__main__":
    connection = socket.fromfd(0,socket.AF_UNIX,socket.SOCK_STREAM)
    connection.settimeout(4)
    try:
        handle(connection)
    except DeliveryUncertain:
        connection.sendall(b"UNKNOWN\n")
    except Exception:
        connection.sendall(b"FAILED\n")
    else:
        connection.sendall(b"OK\n")
