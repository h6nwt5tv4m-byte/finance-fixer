"""Daily publisher for the existing GitHub Pages site. Run from the dedicated mini."""
import fcntl
import hashlib
import os
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import requests

STATE = Path.home() / ".local/share/accounting-firms-refresh"
ORIGIN = "https://github.com/h6nwt5tv4m-byte/finance-fixer.git"
BASE_URL = "https://finance-fixer.net/accounting-firms/"
FILES = ["accounting-firms/" + name for name in ("index.html", "firms.json", "accounting-firms.xlsx")]


def git(directory, *args):
    return subprocess.check_output(["git","-C",str(directory),*map(str,args)],text=True).strip()


def publication_files(site):
    page = (site / FILES[0]).read_text()
    version = re.search(r'data-version="([0-9a-f]{16})"', page)
    if not version:
        raise ValueError("공개 버전 표식 누락")
    snapshot = "accounting-firms/snapshots/" + version[1] + "/"
    return FILES + [snapshot + name for name in ("firms.json","accounting-firms.xlsx")]


class PublicationMismatch(RuntimeError):
    pass


def verify_publication(site):
    expected = {}
    for name in [*publication_files(site), "accounting-firms/firms.js"]:
        file = site / name
        route = file.relative_to(site / "accounting-firms").as_posix()
        expected["" if route == "index.html" else route] = hashlib.sha256(file.read_bytes()).digest()
    for attempt in range(20):
        try:
            matches = []
            for path, sha in expected.items():
                response = requests.get(BASE_URL+path, params={"release":sha.hex()[:16],"check":attempt},
                                        timeout=(10,25))
                matches.append(response.ok and hashlib.sha256(response.content).digest() == sha)
            if all(matches):
                return
        except requests.RequestException:
            pass
        if attempt < 19:
            time.sleep(10)
    raise PublicationMismatch("운영 HTML·표·엑셀 버전 불일치")


def repair_pages(checkout):
    # Only redeploy the still-current homepage head; never send a new commit as a retry.
    head = git(checkout,"rev-parse","HEAD")
    remote = git(checkout,"ls-remote",ORIGIN,"refs/heads/main").split()[0]
    if head != remote:
        raise RuntimeError("원격 main이 갱신되어 다음 회차에서 다시 검증합니다")
    api = ["gh","api"]
    repo = "repos/h6nwt5tv4m-byte/finance-fixer"
    runs = json.loads(subprocess.check_output(api+[repo+"/actions/runs?head_sha="+head+"&event=dynamic&per_page=100"]))
    pages = next((r for r in runs["workflow_runs"] if r["path"] == "dynamic/pages/pages-build-deployment"), None)
    if pages and pages["status"] != "completed":
        return False
    if pages and pages["conclusion"] in ("failure","cancelled","timed_out","action_required"):
        subprocess.run(api+["-X","POST",repo+f"/actions/runs/{pages['id']}/rerun"],check=True)
    else:
        subprocess.run(api+["-X","POST",repo+"/pages/builds"],check=True)
    return True


def ensure_published(checkout):
    try:
        verify_publication(checkout)
        return
    except PublicationMismatch:
        started = repair_pages(checkout)
    try:
        verify_publication(checkout)
    except PublicationMismatch:
        if started or not repair_pages(checkout):
            raise
        verify_publication(checkout)


def update():
    repo = STATE / "repository.git"
    if not repo.exists():
        subprocess.run(["git","init","--bare",str(repo)],check=True)
    git(repo,"fetch","--depth=1",ORIGIN,"+refs/heads/main:refs/remotes/origin/main")
    base = git(repo,"rev-parse","refs/remotes/origin/main")
    with tempfile.TemporaryDirectory(dir=STATE) as tmp:
        checkout = Path(tmp) / "site"
        git(repo,"worktree","add","--detach",checkout,base)
        try:
            ensure_published(checkout)
            env = os.environ.copy()
            env["DART_API_KEY"] = (STATE/"dart.key").read_text().strip()
            cmd = [sys.executable,str(checkout/"scripts/firm_refresh/build.py"),
                   "--site",str(checkout/"accounting-firms"),"--cache",str(STATE/"cache")]
            subprocess.run(cmd,env=env,check=True)
            git(checkout,"add","--",*publication_files(checkout))
            changed = git(checkout,"diff","--cached","--name-only")
            if changed:
                git(checkout,"-c","user.name=재무해결사 자료 갱신","-c","user.email=accounting-firms@users.noreply.github.com",
                    "commit","-m","회계법인 최신 국민연금·공시 매출 반영")
                # Reject upstream races. The next run computes from the new main, never force pushes.
                git(checkout,"-c","credential.helper=","-c","credential.helper=!/opt/homebrew/bin/gh auth git-credential",
                    "push",ORIGIN,"HEAD:refs/heads/main")
                ensure_published(checkout)
            print(time.strftime("%F %T"), "공개 확인", "갱신" if changed else "변동 없음",
                  git(checkout,"rev-parse","--short","HEAD"),flush=True)
        finally:
            git(repo,"worktree","remove","--force",checkout)


if __name__ == "__main__":
    os.umask(0o077)
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (STATE/"running.lock").open("a") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("이미 갱신 실행 중")
        update()
