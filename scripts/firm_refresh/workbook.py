"""Build the six public worksheets from the same rows used by the directory."""
from collections import Counter
from datetime import datetime
from statistics import median

import xlsxwriter

from filings import REGISTRY
from pension import SOURCE

NOTES = {"00260213":"구 상호 대성삼경회계법인", "01898642":"사업보고서에 구 회계법인 예서 병기",
         "01812554":"DART 기업정보의 펍스케일과 동일 법인", "01210710":"사업보고서 및 국민연금 사업장 기록 대조"}

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def ratio(row):
    if row["months"] == 12 and row["personMonths"]:
        return row["lost"] * 12 / row["personMonths"]
    return None


def write(path, entities, releases):
    first, last = releases[0]["month"], releases[-1]["month"]
    months = [r["month"] for r in releases]
    filers = [f for f in entities if f.code]
    rows = [f.record() for f in filers]
    complete = [r for r in rows if ratio(r) is not None]
    with xlsxwriter.Workbook(path, {"strings_to_urls": False, "strings_to_formulas": False}) as book:
        book.set_properties({"title":"회계법인의 매출과 국민연금 가입 변동", "created":datetime(2000,1,1)})
        head = book.add_format({"bold":True,"bg_color":"#21535A","font_color":"white","text_wrap":True})
        pct = book.add_format({"num_format":"0.0%"})
        avg = book.add_format({"num_format":"#,##0.0"})
        integer = book.add_format({"num_format":"#,##0"})
        title = book.add_format({"bold":True,"font_size":17,"font_color":"#21535A"})

        def table(name, labels, widths):
            ws = book.add_worksheet(name)
            ws.write_row(0, 0, labels, head)
            ws.freeze_panes(1, 1)
            ws.set_row(0, 32)
            for col, width in enumerate(widths):
                ws.set_column(col, col, width)
            return ws

        def finish(ws, count, last_col):
            ws.autofilter(0, 0, count, last_col)

        summary = book.add_worksheet("요약")
        summary.set_column("A:H", 19)
        summary.merge_range("A1:H2", "회계법인의 매출과 국민연금 가입 변동", title)
        summary.merge_range("A3:H3", f"국민연금 {first} ~ {last} · 법인별 최신 결산 공시")
        summary.write_row("A5", ["연간 비율 산출 법인","법인별 중앙값","가입자 가중 비율","월평균 가입자","신규취득 건수","상실 건수"], head)
        summary.write("A6", len(complete))
        summary.write("B6", median(ratio(r) for r in complete) if complete else None, pct)
        population = sum(r["personMonths"] for r in complete) / 12
        losses = sum(r["lost"] for r in complete)
        summary.write("C6", losses / population if population else None, pct)
        summary.write("D6", population, avg)
        summary.write_row("E6", [sum(r["gained"] for r in complete), losses], integer)
        summary.merge_range("A8:H8", "실제 퇴사 여부는 확인할 수 없습니다. 국민연금 상실에는 납부예외가 포함됩니다.")
        summary.write_row("A12", ["연간 상실 비율", "법인 수", "법인 구성비"], head)
        bounds = [0, .1, .2, .3, .5, 1, float("inf")]
        for i, (lo,hi) in enumerate(zip(bounds,bounds[1:]),12):
            count = sum(lo <= ratio(r) < hi for r in complete)
            label = f"{lo:.0%} 이상" if hi == float("inf") else f"{lo:.0%} 이상 ~ {hi:.0%} 미만"
            summary.write_row(i,0,[label,count])
            summary.write(i,2,count / len(complete) if complete else None,pct)
        chart = book.add_chart({"type":"bar"})
        chart.add_series({"name":"법인 수","categories":["요약",12,0,17,0],"values":["요약",12,1,17,1]})
        chart.set_title({"name":"연간 상실 비율 분포"})
        chart.set_legend({"none":True})
        summary.insert_chart("D11", chart)

        annual = table("법인별", ["회계법인","관측 상태","관측 개월","관측월 평균 가입자","신규취득 합계(건)","상실 합계(건)",
                "연간 상실 비율",last+" 가입자","최근월 사업장 행 수","12개월 사업장 행 수","공시·명칭 메모",
                "매출액(원)","매출 사업연도 시작","매출 사업연도 종료","매출 공시 원문"],
                [31,16,12,18,18,18,18,18,18,18,28,22,21,21,18])
        monthly = table("법인별 월자료", ["회계법인","자료 기준월","공개자료 상태","가입자 수","신규취득(건)","상실(건)","사업장 행 수"],
                        [31,15,17,17,17,17,17])
        sites = table("사업장 월자료", ["회계법인","자료 기준월","공개 사업장 지역","사업자번호 앞 6자리","연금 적용일","가입자 수","신규취득(건)","상실(건)","사업장 상태"],
                      [31,15,24,20,17,15,15,15,15])
        registry = table("명부 대조", ["회계법인","한공회 등록번호","DART 고유번호","집계 상태","자료 관측월 수","명칭 대조 메모","최신 결산 사업보고서"],
                         [31,17,17,20,18,30,21])
        site_count, month_count, filer_count = 0, 0, 0
        matched = Counter()
        for index, firm in enumerate(entities,1):
            row = firm.record()
            n = row["months"]
            status = "12개월 확인" if n == 12 else ("일부 월 확인" if n else "기간 내 자료 없음")
            registry.write_row(index,0,[firm.name,firm.number,firm.code,status,n])
            notes = [NOTES[firm.code]] if firm.code in NOTES else []
            if firm.aliases:
                notes.append("종전 명칭: " + ", ".join(firm.aliases))
            if firm.historical:
                notes.append("과거 명부 등록, 현재 명부 미확인")
            if notes:
                registry.write(index,5," · ".join(notes))
            if firm.receipt:
                registry.write_url(index,6,DART+firm.receipt,string="DART 원문")
                filer_count += 1
                recent = firm.monthly.get(last)
                annual.write_row(filer_count,0,[firm.name,status,n])
                if notes:
                    annual.write(filer_count,10," · ".join(notes))
                if n:
                    annual.write(filer_count,3,row["personMonths"]/n,avg)
                    annual.write_row(filer_count,4,[row["gained"],row["lost"]],integer)
                if ratio(row) is not None:
                    ix = filer_count + 1
                    annual.write_formula(filer_count,6,f"=F{ix}/D{ix}",pct,ratio(row))
                if recent:
                    annual.write_row(filer_count,7,[recent[0],recent[3]],integer)
                annual.write(filer_count,9,len(firm.sites))
                annual.write(filer_count,11,row["revenue"],integer)
                annual.write_row(filer_count,12,[row["start"],row["end"]])
                annual.write_url(filer_count,14,DART+firm.receipt,string="DART 원문")
            # Registry-only firms may have public pension data before their first filing.
            if not firm.receipt and not n:
                continue
            for month in months:
                month_count += 1
                data = firm.monthly.get(month)
                monthly.write_row(month_count,0,[firm.name,month,"자료 있음" if data else "자료 없음"])
                if data:
                    monthly.write_row(month_count,3,data,integer)
            for site in sorted(firm.sites):
                site_count += 1
                matched[site[0]] += 1
                sites.write_row(site_count,0,[firm.name,*site])
        finish(annual,filer_count,14)
        finish(monthly,month_count,6)
        finish(sites,site_count,8)
        finish(registry,len(entities),6)

        method = book.add_worksheet("산식과 출처")
        method.set_column("A:A",26)
        method.set_column("B:D",23)
        method.set_column("E:E",70)
        method.merge_range("A1:E2","집계 기준과 출처",title)
        notes = [
            ("분석 기간", f"{first} ~ {last}, 각 CSV 행의 자료생성년월 기준 최근 연속 12개월"),
            ("대상", "2025년 이후 DART 회계법인사업보고서 제출 법인을 표시하고 한공회 법인 명부와 대조합니다."),
            ("매출", "법인별 최신 결산의 당기 영업수익. 동일 결산은 최신 정정 공시를 적용하고 사업부문별 합계와 대조합니다."),
            ("사업장 연결", "공개 상호·과거 명칭 및 본점·분사무소 이름으로 합산합니다. 공개 기준 미달·별도 명칭 사업장은 누락될 수 있습니다."),
            ("평균과 누계", "관측된 달의 가입자 평균과 취득·상실 건수 합계입니다. 미관측 월은 공란입니다."),
            ("연간 상실 비율", "12개월 모두 관측되고 평균 가입자가 양수인 경우에만 연간 상실 건수 ÷ 월평균 가입자 수로 산출합니다."),
            ("해석", "상실에는 납부예외가, 신규취득에는 납부재개가 포함됩니다. 한 사람의 반복 변동이 여러 건으로 잡힐 수 있습니다."),
            ("중앙값과 가중 비율", "연간 비율 산출 대상 법인들의 중앙값과, 같은 집단의 상실 합계 ÷ 월평균 가입자 합계를 표시합니다."),
            ("사업장 월자료", "사업자번호 앞 6자리와 시·군·구까지만 표시합니다. 번호 앞부분은 서로 겹칠 수 있습니다.")]
        for i,(label,detail) in enumerate(notes,3):
            method.write(i,0,label,head)
            method.merge_range(i,1,i,4,detail)
        for i,(label,link) in enumerate([("국민연금공단",SOURCE),("DART 공시검색","https://dart.fss.or.kr"),("한국공인회계사회",REGISTRY)],14):
            method.write_url(i,0,link,string=label)
        method.write_row("A20",["원자료 추출일","행의 기준월","전국 원본 행 수","연결 행 수","전국 CSV의 SHA-256"],head)
        for i,item in enumerate(releases,20):
            method.write_row(i,0,[item["date"],item["month"],item["rows"],matched[item["month"]],item["sha256"]])
