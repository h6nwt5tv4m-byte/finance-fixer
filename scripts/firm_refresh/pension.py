"""Read the official NPS monthly business-site CSV releases."""
import csv
import hashlib
import json
import time
import io
import re
from statistics import median
from tempfile import TemporaryFile

import requests
from lxml import html

PORTAL = "https://www.data.go.kr"
SOURCE = PORTAL + "/data/15083277/fileData.do"
TITLE = "국민연금공단_국민연금 가입 사업장 내역_"
COLUMNS = ("자료생성년월", "사업장명", "사업자등록번호", "사업장가입상태코드", "사업장도로명상세주소",
           "사업장업종코드", "적용일자", "가입자수", "신규취득자수", "상실가입자수")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def month_index(month):
    year, number = map(int, month.split("-"))
    require(1 <= number <= 12, "잘못된 기준월 " + month)
    return year * 12 + number


def catalog(session):
    response = session.get(SOURCE, timeout=25)
    response.raise_for_status()
    page = html.fromstring(response.text)
    latest = page.xpath('string(//meta[@property="og:title"]/@content)')
    require(re.fullmatch(re.escape(TITLE) + r"\d{8}", latest), "국민연금 최신 자료 제목 확인 필요")
    pk = page.get_element_by_id("publicDataDetailPk").get("value")
    path = "/tcs/dss/selectHistAndCsvData.do"
    response = session.post(PORTAL + path, data={"publicDataPk": "15083277", "publicDataDetailPk": pk,
                                               "url": path}, timeout=25)
    response.raise_for_status()
    history = html.fromstring(response.text)
    releases = {}
    for item in history.xpath('//a[@data-public-pk]'):
        title = item.text_content().strip()
        if re.fullmatch(re.escape(TITLE) + r"\d{8}", title):
            releases[title[-8:]] = item.get("data-public-pk")
    releases[latest[-8:]] = pk
    require(len(releases) >= 12, "국민연금 이력 부족")
    return sorted(releases.items(), reverse=True)


def extract(source, date, pk, digest):
    head = source.readline()
    try:
        head.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "cp949"
    source.seek(0)
    with io.TextIOWrapper(source, encoding=encoding, newline="") as text:
        reader = csv.reader(text)
        header = [re.sub(r"\s", "", h) for h in next(reader)]
        indices = [next(i for i, h in enumerate(header) if h.startswith(prefix)) for prefix in COLUMNS]
        rows, months, total = [], set(), 0
        for row in reader:
            if not row:
                continue
            require(len(row) == len(header), "잘린 국민연금 원자료 " + date)
            total += 1
            months.add(row[indices[0]])
            name = re.sub(r"\s", "", row[indices[1]])
            if row[indices[5]].startswith("7412") or "회계" in name or "어카운팅" in name:
                rows.append([row[i] for i in indices])
    require(len(months) == 1 and total > 400000 and rows, "국민연금 행 수 또는 기준월 오류 " + date)
    return dict(date=date, pk=pk, rows=total, month=months.pop(), sha256=digest, data=rows)


def get_release(session, cache, date, pk, max_age):
    # Check the published attachment identity even when yesterday's filtered rows are cached.
    params = {"publicDataPk": "15083277", "publicDataDetailPk": pk, "atchFileId": "",
              "fileDetailSn": "1", "publicDataTyCode": "PR0051"}
    response = session.post(PORTAL + "/tcs/dss/selectFileDataDownload.do", data=params, timeout=25)
    response.raise_for_status()
    meta = response.json()
    require(meta.get("status") and meta.get("atchFileId"), "국민연금 첨부 조회 실패 " + date)
    attachment = {key: meta[key] for key in ("atchFileId", "fileDetailSn")}
    cachefile = cache / (date + ".json")
    if cachefile.exists():
        saved = json.loads(cachefile.read_text())
        if saved.get("pk") == pk and saved.get("attachment") == attachment and time.time() - cachefile.stat().st_mtime < max_age:
            return saved
    check = session.post(PORTAL + "/cmm/cmm/check-limit.json", data=attachment, timeout=25)
    check.raise_for_status()
    require(check.json().get("needCaptcha") is False, "국민연금 다운로드 한도 확인 필요")
    params = dict(attachment, dataNm=TITLE + date)
    with TemporaryFile() as tmp, session.get(PORTAL + "/cmm/cmm/fileDownload.do", params=params,
                                              stream=True, timeout=(20, 120)) as response:
        response.raise_for_status()
        digest = hashlib.sha256()
        for chunk in response.iter_content(512 * 1024):
            digest.update(chunk)
            tmp.write(chunk)
        if response.headers.get("Content-Length") and not response.headers.get("Content-Encoding"):
            require(tmp.tell() == int(response.headers["Content-Length"]), "국민연금 다운로드 중단 " + date)
        tmp.seek(0)
        result = extract(tmp, date, pk, digest.hexdigest())
    result["attachment"] = attachment
    pending = cachefile.with_suffix(".tmp")
    pending.write_text(json.dumps(result, ensure_ascii=False))
    pending.replace(cachefile)
    print(date, result["month"], result["rows"], flush=True)
    return result


def check_coverage(cache, releases, counts, fraction, error):
    minimum = max(1, median(counts) * fraction)
    suspect = [r for r, count in zip(releases, counts) if count < minimum]
    for release in suspect:
        (cache / (release["date"] + ".json")).unlink(missing_ok=True)
    require(not suspect, error)


def collect(cache):
    cache.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers["Referer"] = SOURCE
        selected = {}
        latest = 0
        for date, pk in catalog(session):
            item = get_release(session, cache, date, pk, (1 if not selected else 12) * 86400)
            month = item["month"]
            require(re.fullmatch(r"\d{4}-\d{2}", month), "국민연금 기준월 형식 변경")
            index = month_index(month)
            extracted = month_index(date[:4] + "-" + date[4:6])
            require(index <= extracted, "추출일 이후의 국민연금 기준월")
            latest = max(latest, index)
            selected.setdefault(index, item)  # latest extraction for each reference month
            if extracted <= latest and all(i in selected for i in range(latest-11, latest+1)):
                break
            if extracted < latest-11:
                break
    require(latest and all(i in selected for i in range(latest-11, latest+1)),
            "최근 12개월 중 누락된 국민연금 원자료가 있습니다")
    result = [selected[i] for i in range(latest-11, latest+1)]
    # Portal metadata lists CSV row count as 1. Check nationwide coverage against adjacent months.
    check_coverage(cache, result, [x["rows"] for x in result], .95, "전국 사업장 행 수 급감: 원천 파일 확인 필요")
    return result
