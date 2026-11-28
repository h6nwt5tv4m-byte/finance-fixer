"""Collect, validate, then render an isolated publication candidate."""
import argparse
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import median
import tempfile
import shutil
from zoneinfo import ZoneInfo

import openpyxl
import requests

import aggregate
import filings
import pension
import workbook
from pension import require


def render_page(source, version, releases, rows):
    values = [Decimal(r["lost"] * 1200) / Decimal(r["personMonths"]) for r in rows if workbook.ratio(r) is not None]
    first, last = releases[0]["month"], releases[-1]["month"]
    previous = re.search(r'data-period-end="([\d-]+)"', source)
    require(previous and last >= previous[1], "최신 월이 기존 공개본보다 과거입니다")
    metric = str(median(values).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if values else "미산출"
    source = re.sub(r'(<!--/data-->)<span(?: hidden)?>%</span>',r'\1' + ("<span>%</span>" if values else "<span hidden>%</span>"),source)
    labels = {"period": (first + " — " + last).replace("-", "."), "count": str(len(rows)),
              "median": metric, "full": str(len(values))}
    for label, value in labels.items():
        start = f"<!--data:{label}-->"
        source, n = re.subn(start + ".*?<!--/data-->", start + value + "<!--/data-->", source)
        require(n == 1, "화면 표시 위치 확인 필요: " + label)
    for pattern, replacement in [(r'data-version="[^"]+"',f'data-version="{version}"'),
                                  (r'data-period-end="[^"]+"',f'data-period-end="{last}"'),
                                  (r'href="(?:accounting-firms.xlsx\?v=[^"]+|snapshots/[a-f0-9]{16}/accounting-firms.xlsx)"', f'href="snapshots/{version}/accounting-firms.xlsx"' )]:
        source,n = re.subn(pattern, replacement, source)
        require(n == 1, "데이터 파일 연결 누락")
    return source


def validate_book(path, rows, releases):
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        require(set(book.sheetnames) == {"요약","법인별","법인별 월자료","사업장 월자료","명부 대조","산식과 출처"}, "엑셀 시트 누락")
        data = list(book["법인별"].values)[1:]
        require(len(data) == len(rows), "엑셀 법인 수 불일치")
        for r, cells in zip(rows, data):
            require((cells[0], cells[2], *cells[11:14]) == (r["name"],r["months"],r["revenue"],r["start"],r["end"]), "엑셀 법인 수치 불일치")
            require((cells[4],cells[5]) == ((r["gained"],r["lost"]) if r["months"] else (None,None)), "엑셀 변동 누계 오류")
            rate = workbook.ratio(r)
            require((rate is None and cells[6] is None) or
                    (rate is not None and cells[6] is not None and abs(rate-cells[6])<1e-10), "엑셀 비율 오류")
        evidence = list(book["산식과 출처"].values)[20:32]
        require([(r[1],r[4]) for r in evidence] == [(r["month"],r["sha256"]) for r in releases], "월자료 누락")
    finally:
        book.close()


def validate_filings(previous, selected, withdrawn=()):
    prior = [r for r in previous if "code" in r]
    require(len(selected) >= len(previous) - sum((r["code"],r["receipt"]) in withdrawn for r in prior), "기존 DART 대상 감소")
    for r in prior:
        if (r["code"],r["receipt"]) in withdrawn:
            continue
        current = selected.get(r["code"])
        require(current and current[:2] >= (r["end"][:7],r["receipt"]),
                f"{r['name']}의 공개 결산·정정이 과거로 돌아갑니다")


def build(site, cache, key):
    previous = json.loads((site/"firms.json").read_text())
    releases = pension.collect(cache / "nps")
    docs = cache / "dart"
    docs.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(ZoneInfo("Asia/Seoul")).date()
    with requests.Session() as session:
        withdrawn = set()
        selected = filings.latest(session, key, today, withdrawn)
        validate_filings(previous, selected, withdrawn)
        registry = filings.registry(session)
        reports = {}
        for code,(end,receipt,name) in sorted(selected.items()):
            try:
                accounts = filings.financial(session,key,docs,receipt,end)
            except (ValueError, KeyError, OSError) as exc:
                raise ValueError(f"{name} 공시 {receipt}: {exc}") from exc
            reports[code] = (name,receipt,accounts)
    old_book = openpyxl.load_workbook(site/"accounting-firms.xlsx", read_only=True, data_only=True)
    try:
        prior_members = [tuple(row[:3]) for row in list(old_book["명부 대조"].values)[1:]]
    finally:
        old_book.close()
    entities = aggregate.aggregate(releases,registry,reports,prior_members,previous)
    rows = [f.record() for f in entities if f.code]
    require(len({r["name"] for r in rows}) == len(rows), "공시 상호 중복")
    counts = [sum(f.monthly.get(item["month"], [0,0,0,0])[3] for f in entities if f.code) for item in releases]
    pension.check_coverage(cache / "nps", releases, counts, .8, "법인 연결 사업장 행 수 급감: 월자료 확인 필요")
    records = "[\n" + ",\n".join(json.dumps(r,ensure_ascii=False,separators=(",",":")) for r in rows) + "\n]\n"
    with tempfile.TemporaryDirectory(dir=site.parent) as temp:
        stage = Path(temp)
        (stage/"firms.json").write_text(records)
        workbook.write(stage/"accounting-firms.xlsx",entities,releases)
        validate_book(stage/"accounting-firms.xlsx",rows,releases)
        digest = hashlib.sha256(records.encode() + (stage/"accounting-firms.xlsx").read_bytes()).hexdigest()[:16]
        page = render_page((site/"index.html").read_text(),digest,releases,rows)
        (stage/"index.html").write_text(page)
        # The directory is intentionally permanent. An already-open page must retain its own download.
        snapshot = site/"snapshots"/digest
        snapshot.mkdir(parents=True, exist_ok=True)
        for name in ("firms.json", "accounting-firms.xlsx"):
            target = snapshot/name
            if target.exists():
                require(target.read_bytes() == (stage/name).read_bytes(), "이전 버전 파일 내용 불일치")
            else:
                shutil.copyfile(stage/name, target)
        for file in stage.iterdir():
            file.replace(site/file.name)
    print(f"{releases[0]['month']} ~ {releases[-1]['month']}, {len(rows)}곳, 버전 {digest}",flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site",type=Path,required=True)
    parser.add_argument("--cache",type=Path,required=True)
    args = parser.parse_args()
    build(args.site, args.cache, os.environ["DART_API_KEY"].strip())
