"""Fixed-format email verification protocol shared by the site and its mail service."""
import re
import socket

ADDRESS = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
def address(value):
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("주소 형식을 확인해 주세요.")
    local, domain = value.split("@")
    domain = domain.encode("idna").decode("ascii").lower()
    if len(local)>64 or len(local)+1+len(domain)>254 or not ADDRESS.fullmatch(local) or "." not in domain or not all(LABEL.fullmatch(x) for x in domain.split(".")):
        raise ValueError("주소 형식을 확인해 주세요.")
    # These mailbox providers and the office Workspace treat letter case alike.
    if domain in {"gmail.com","googlemail.com","icloud.com","me.com","mac.com","finance-fixer.net"}:
        local=local.lower()
    return local+"@"+domain

def mailbox_limit(email):
    """Group obvious delivery aliases only for throttling, never for access to posts."""
    local, domain = email.split("@")
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.lower().partition("+")[0].replace(".", "")
        domain = "gmail.com"
    elif domain in {"icloud.com","me.com","mac.com","finance-fixer.net"}:
        local=local.lower().partition("+")[0]
    return local+"@"+domain

def deliver(email, code):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(17)
        sock.connect("/run/finance-board-mail.sock")
        sock.sendall(f"{email}\n{code}\n".encode("ascii"))
        sock.shutdown(socket.SHUT_WR)
        if sock.makefile("rb").readline(12) != b"OK\n":
            raise OSError("verification delivery unavailable")
