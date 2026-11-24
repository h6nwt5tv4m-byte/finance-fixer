"""systemd Accept=yes handler. Only the board UID may send fixed verification messages."""
from email.message import EmailMessage
from email.policy import SMTP
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
    sender=address(mail["from"])
    msg = EmailMessage()
    msg["From"] = "재무해결사 자유게시판 <"+sender+">"
    msg["To"] = recipient
    msg["Subject"] = "재무해결사 자유게시판 이메일 인증번호"
    msg.set_content(f"게시판 로그인 인증번호는 {code} 입니다. 최초 발급 후 10분 안에 요청한 화면에 입력하세요.\n직접 요청하지 않으셨다면 이 메일을 무시하세요.",cte="base64")
    smtp=smtplib.SMTP_SSL(mail["host"],int(mail["port"]),timeout=8,context=ssl.create_default_context())
    try:
        smtp.login(mail["user"],mail["password"])
        submit(smtp,msg,sender,recipient)
    finally:
        smtp.close()

class ReplyLines:
    """Keep smtplib's reply parser, but require complete CRLF lines after submission."""
    def __init__(self,stream):
        self.stream=stream

    def readline(self,limit):
        line=self.stream.readline(limit)
        if not line.endswith(b"\r\n"):
            raise DeliveryUncertain("incomplete SMTP reply line")
        return line

    def close(self):
        self.stream.close()

def submit(smtp,msg,sender,recipient):
    # A refusal or disconnect before the server invites the message body is definite.
    for operation,expected in ((lambda:smtp.mail(sender),(250,)),(lambda:smtp.rcpt(recipient),(250,251)),
                               (lambda:smtp.docmd("DATA"),(354,))):
        status,note=operation()
        if status not in expected:
            raise smtplib.SMTPResponseException(status,note)
    # The fixed RFC 5322 message starts with From. Protect subsequent dot-leading lines.
    payload=msg.as_bytes(policy=SMTP).replace(b"\r\n.",b"\r\n..")
    if not payload.endswith(b"\r\n"):
        payload+=b"\r\n"
    try:
        smtp.send(payload+b".\r\n")
        stream=smtp.file
        smtp.file=ReplyLines(stream)
        try:
            status,note=smtp.getreply()
        finally:
            smtp.file=stream
    except OSError as exc:
        raise DeliveryUncertain("SMTP acknowledgement unavailable") from exc
    if 400<=status<600:
        raise smtplib.SMTPDataError(status,note)
    if status!=250:
        raise DeliveryUncertain("incomplete SMTP acknowledgement")

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
