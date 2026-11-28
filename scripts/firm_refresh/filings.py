"""Select each firm's latest fiscal year and the latest effective filing for that year."""
import datetime as dt
import html
import io
import json
import re
import zipfile

import requests
from lxml import html as dom

from pension import require

API = "https://opendart.fss.or.kr/api/"
REGISTRY = "https://www.kicpa.or.kr/home/audtTaxAttrnGnrl/accCoReList.face"
START = dt.date(2025, 1, 1)  # First year covered by the published panel.
DATE = r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"


def dart_get(session, endpoint, params):
    # requests exceptions can contain the authenticated URL. Never propagate it into job logs.
    try:
        r = session.get(API + endpoint, params=params, timeout=(15, 45))
        r.raise_for_status()
        return r
    except requests.RequestException as exc:
        raise RuntimeError(f"DART {endpoint}: {type(exc).__name__}") from None


def latest(session, key, today, withdrawn=None):
    begin = START
    selected = {}
    while begin <= today:
        end = min(begin + dt.timedelta(days=88), today)
        params = dict(crtfc_key=key, bgn_de=begin.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"),
                      pblntf_detail_ty="F004", page_count=100, last_reprt_at="Y")
        page = 1
        while True:
            data = dart_get(session, "list.json", dict(params, page_no=page)).json()
            if data["status"] == "013" and page == 1:
                break
            require(data["status"] == "000" and data["list"], "DART 목록 조회 실패 " + data["status"])
            for item in data["list"]:
                match = re.search(r"회계법인사업보고서\s*\((\d{4})\.(\d{2})\)", item["report_nm"])
                require(match is not None, "확인할 DART 보고서 유형: " + item["report_nm"])
                code, receipt = item["corp_code"], item["rcept_no"]
                require(re.fullmatch(r"\d{8}", code) and re.fullmatch(r"\d{14}", receipt), "공시번호 오류")
                if "철" in item["rm"]:
                    if withdrawn is not None:
                        withdrawn.add((code, receipt))
                    continue
                end_month = "-".join(match.groups())
                entry = (end_month, receipt, item["corp_name"])
                if code not in selected or entry > selected[code]:
                    selected[code] = entry
            if page >= int(data["total_page"]):
                break
            page += 1
        begin = end + dt.timedelta(days=1)
    require(selected, "DART 공시 없음")
    return selected


def registry(session):
    r = session.get(REGISTRY, timeout=30)
    r.raise_for_status()
    page = dom.fromstring(r.content, parser=dom.HTMLParser(encoding="utf-8"))
    members = {}
    for cell in page.xpath('//td[input[@class="aciOffKname"]]'):
        name = cell.xpath('string(input[@class="aciOffKname"]/@value)').strip()
        no = cell.xpath('string(input[@class="aciNumber"]/@value)')
        require(name and no and no not in members, "한공회 등록명부 중복 또는 누락")
        members[no] = name
    require(len(members) >= 200, "한공회 명부가 일부만 반환됨")
    return members


def text(markup):
    return " ".join(html.unescape(re.sub("<[^>]*>", " ", markup)).split())


def table_rows(section):
    for row in re.findall(r"<TR\b[^>]*>(.*?)</TR>", section, re.I | re.S):
        cells = re.findall(r"<T(?:D|E|U|H)\b([^>]*)>(.*?)</T(?:D|E|U|H)>", row, re.I | re.S)
        yield [text(value) for _, value in cells], [attrs for attrs, _ in cells]


def dates(section):
    return [dt.date(int(y), int(m), int(d)).isoformat() for y, m, d in re.findall(DATE, section)[:2]]


def width(attrs):
    span = re.search(r'COLSPAN="(\d+)"', attrs, re.I)
    return int(span[1]) if span else 1


def current_columns(table):
    for labels, attrs in table:
        if not labels or labels[0].replace(" ", "") not in ("과목","구분"):
            continue
        possible = [i for i in range(1,len(labels)) if "당" in labels[i]]
        if len(possible) == 1:
            index = possible[0]
        else:
            semantic = [i for i, attr in enumerate(attrs) if 'ACODE="RVN_FY_TTL"' in attr]
            if len(semantic) == 1:
                index = semantic[0]
            else:
                numbered = [(int(n[1]), i) for i in possible
                            if (n := re.search(r"제\s*(\d+)", labels[i]))]
                require(numbered and len(numbered) == len(possible) and
                        len({n for n, _ in numbered}) == len(numbered), "공시 당기 머리글 판별 불가")
                index = max(numbered)[1]
        start = sum(width(a) for a in attrs[:index])
        return range(start, start + width(attrs[index]))
    raise ValueError("공시 당기 머리글 누락")


def parse(xml, end_month):
    amounts = {}
    statement_head = ""
    for section in re.split(r"(?=<TITLE\b)", xml):
        if "</TITLE>" not in section:
            continue
        heading, section = section.split("</TITLE>", 1)
        heading = text(heading).replace(" ", "")
        if heading not in ("나.손익계산서", "3.사업부문별매출액"):
            continue
        section = section.split("</SECTION-")[0]
        unit = re.search(r"단\s*위\s*[:：]\s*(백\s*만\s*원|천\s*원|원)", text(section))
        require(unit, "공시 금액 단위 확인 필요")
        factor = {"원": 1, "천원": 1000, "백만원": 1000000}[re.sub(r"\s", "", unit[1])]
        table = list(table_rows(section))
        is_income = heading == "나.손익계산서"
        if is_income:
            statement_head = " ".join(" ".join(row) for row, _ in table[:6])
        for row, attrs in table:
            if not row:
                continue
            label = row[0].replace(" ", "")
            if is_income:
                wanted = re.fullmatch(r"[ⅠI1.]*?(?:영업수익|매출액)(?:\((?:주석?[^)]*|매출액)\))*", label)
            else:
                wanted = label in ("합계", "총계")
            if wanted:
                columns = current_columns(table)
                pos = 0
                current = []
                for cell, attr in zip(row, attrs):
                    if pos in columns:
                        current.append(cell)
                    pos += width(attr)
                if not is_income:
                    current = current[:1]  # The next segment column is the share of sales.
                require(any(v.strip() for v in current), "공시 당기 금액 공란")
                values = {v.replace(" ", "").replace(",", "") for v in current if v.strip() not in ("", "-")}
                require(len(values) <= 1 and all(v.isdigit() for v in values), "공시 당기 금액 형식 확인 필요")
                amounts[heading] = (int(next(iter(values), "0")), factor)
                break
    require(len(amounts) == 2, "공시 매출 표 누락")
    income, income_unit = amounts["나.손익계산서"]
    # For each display, the original won amount lies in the union of its rounded
    # and truncated intervals. Both statements must admit a common won amount.
    ranges = [(max(0, n * unit - unit // 2), n * unit + unit - 1) for n, unit in amounts.values()]
    require(max(lo for lo,_ in ranges) <= min(hi for _,hi in ranges), "영업수익과 부문별 매출 불일치")

    cover = text(xml[:150000]).partition("사업연도")[2][:110]
    period = dates(cover)
    if len(period) != 2 or period[1][:7] != end_month:
        period = dates(statement_head)
    require(len(period) == 2 and period[1][:7] == end_month and period[0] <= period[1], "공시 사업연도 확인 필요")
    return dict(start=period[0], end=period[1], revenue=income * income_unit)


def financial(session, key, cache, receipt, end_month):
    file = cache / (receipt + ".xml")
    if not file.exists():
        response = dart_get(session, "document.xml", {"crtfc_key": key, "rcept_no": receipt})
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            xml = z.read(receipt + ".xml").decode("utf-8")
        value = parse(xml, end_month)
        pending = file.with_suffix(".tmp")
        pending.write_text(xml)
        pending.replace(file)
        return value
    return parse(file.read_text(), end_month)
