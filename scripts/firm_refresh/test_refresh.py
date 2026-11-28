import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aggregate
import build
import filings
import pension
import workbook


class Response:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class RefreshTests(unittest.TestCase):
    def test_recent_amendment_to_older_year_cannot_replace_new_year(self):
        reports = [("2026.03","20260630000001"),("2025.03","20261127000001"),("2026.03","20261125000001")]
        entries = [dict(corp_code="12345678",corp_name="가회계법인",rm="",rcept_no=r,
                        report_nm="회계법인사업보고서 ("+m+")") for m,r in reports]
        with patch.object(filings,"dart_get",return_value=Response(dict(status="000",list=entries,total_page=1))):
            self.assertEqual(filings.latest(None,"test",dt.date(2025,1,1))["12345678"][1],reports[-1][1])

    def test_missing_nps_month(self):
        periods = ["2025-12"] + [f"2026-{n:02}" for n in range(1,13) if n!=5]
        with tempfile.TemporaryDirectory() as tmp, patch.object(pension,"catalog",return_value=[(m.replace("-","")+"23","pk") for m in sorted(periods, reverse=True)]), \
             patch.object(pension,"get_release",side_effect=[{"month":m} for m in sorted(periods, reverse=True)]):
            with self.assertRaisesRegex(ValueError,"누락"):
                pension.collect(Path(tmp))

    def test_distinguishes_no_record_from_zero_and_uses_alias(self):
        months = [{"month":"2026-10","data":[["2026-10","회계법인예서 지점","123456","1","서울 강남구", "", "2020", "4","0","0"]]}]
        docs = {code:(name,"20261111000001",{"revenue":1}) for code,name in
                [("01898642","회계법인예서"),("01010101","나회계법인")]}
        firms = aggregate.aggregate(months,{"1":"리드넘버회계법인","2":"나회계법인"},docs)
        bycode = {f.code:f.record() for f in firms}
        self.assertEqual(bycode["01898642"]["months"],1)
        self.assertEqual(bycode["01898642"]["name"],"리드넘버회계법인")
        self.assertEqual(bycode["01010101"]["months"],0)
        self.assertIsNone(workbook.ratio(bycode["01010101"]))
        self.assertIsNone(workbook.ratio(dict(months=12,personMonths=0,lost=0)))

    def test_previous_public_filing_cannot_disappear_or_regress(self):
        published = [dict(code="12345678",name="예시",end="2026-03-31",receipt="20260610000002")]
        for current in [{}, {"12345678":("2025-03","20261111000001","예시")}, {"12345678":("2026-03","20260610000001","예시")}]:
            with self.assertRaises(ValueError):
                build.validate_filings(published,current)

    def test_old_reference_month_published_again_does_not_displace_recent_month(self):
        months = ["2026-10","2026-09","2026-08","2026-07","2026-06","2026-05",
                  "2026-04","2026-03","2026-02","2026-01","2025-12","2025-11"]
        extract = ["20261127","20261123","20261023","20260923","20260823","20260723","20260623",
                   "20260523","20260423","20260323","20260223","20260123","20251223"]
        data = [dict(month=m,rows=590000) for m in ["2025-10",*months]]
        with tempfile.TemporaryDirectory() as tmp, patch.object(pension,"catalog",return_value=[(d,"pk") for d in extract]), \
             patch.object(pension,"get_release",side_effect=data):
            self.assertEqual([r["month"] for r in pension.collect(Path(tmp))],list(reversed(months)))

    def test_region_stops_before_roads_and_towns(self):
        self.assertEqual(aggregate.public_region("세종특별자치시 조치원읍 원리"),"세종특별자치시")
        self.assertEqual(aggregate.public_region("경기도 성남시 분당구 판교로"),"경기도 성남시 분당구")
        self.assertEqual(aggregate.public_region("서울특별시 강남구 테헤란로"),"서울특별시 강남구")

    def test_fund_with_same_prefix_is_separate(self):
        row = ["2026-10","테스트회계법인사내근로복지기금","123456","1","서울 강남구","","","10","0","0"]
        firms = aggregate.aggregate([{"month":"2026-10","data":[row]}],{},{"12345678":("테스트회계법인","receipt",{})})
        self.assertEqual(firms[0].record()["months"],0)

    def test_fiscal_columns_and_mixed_display_precision(self):
        def document(income, segments, first_unit="원", second_unit="원"):
            def section(title, unit, name, values):
                label = "과목" if name == "영업수익" else "구분"
                return (f"<TITLE>{title}</TITLE> (단위: {unit})"
                        f"<TR><TH>{label}</TH><TH>전기</TH><TH>당기</TH></TR>"
                        f"<TR><TD>{name}</TD><TD>100</TD><TD>{values}</TD></TR>")
            return ("사업연도 2025년 4월 1일 2026년 3월 31일 " +
                    section("나.손익계산서",first_unit,"영업수익",income) +
                    section("3.사업부문별매출액",second_unit,"합계",segments))
        self.assertEqual(filings.parse(document(200,200),"2026-03")["revenue"],200)
        self.assertEqual(filings.parse(document(2000,1,"천원","백만원"),"2026-03")["revenue"],2000000)
        with self.assertRaisesRegex(ValueError,"불일치"):
            filings.parse(document(200,201),"2026-03")

    def test_registry_identity_survives_new_name_and_missing_listing(self):
        prior = [("옛회계법인","제 1 호","00000001"),("과거회계법인","제 2 호",None)]
        current = {"제 1 호":"새회계법인"}
        docs = {"00000001":("새회계법인","receipt",{})}
        rows = [["2026-10",n,"123456","1","서울 강남구","741202","","4","0","0"]
                for n in ("옛회계법인","새회계법인 컨설팅본부","새회계법인(노동조합)","과거회계법인")]
        firms = aggregate.aggregate([{"month":"2026-10","data":rows}],current,docs,prior)
        new = next(f for f in firms if f.code)
        self.assertEqual((new.record()["aliases"],new.record()["personMonths"]),(["옛회계법인"],8))
        self.assertTrue(next(f for f in firms if f.number=="제 2 호").historical)
        again = aggregate.aggregate([{"month":"2026-10","data":rows}],current,docs,
                                    [("새회계법인","제 1 호","00000001")],[new.record()])
        self.assertEqual(again[0].record()["personMonths"],8)

    def test_official_withdrawal_allows_exact_prior_receipt_to_leave(self):
        old = dict(code="12345678",name="예시",end="2026-03-31",receipt="20260610000002")
        build.validate_filings([old],{}, {(old["code"],old["receipt"])})
        with self.assertRaises(ValueError):
            build.validate_filings([old],{}, {(old["code"],"20250610000002")})

    def test_bad_cached_month_is_fetched_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            releases = [dict(date=f"2026{n:02}20") for n in range(1,13)]
            for row in releases:
                (directory/(row["date"]+".json")).touch()
            with self.assertRaisesRegex(ValueError,"급감"):
                pension.check_coverage(directory,releases,[400001]+[590000]*11,.95,"급감")
            self.assertEqual(len(list(directory.iterdir())),11)
            self.assertFalse((directory/(releases[0]["date"]+".json")).exists())

    def test_publication_with_zero_annual_rates(self):
        firm = aggregate.Firm("테스트회계법인","12345678",receipt="20260701000001",
                              accounts=dict(start="2025-04-01",end="2026-03-31",revenue=100))
        releases = [dict(month=f"2026-{n:02}",date=f"2026{n:02}28",rows=600000,sha256="abc")
                    for n in range(1,13)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"summary.xlsx"
            workbook.write(path,[firm],releases)
            build.validate_book(path,[firm.record()],releases)
        template = (Path(__file__).resolve().parents[2]/"accounting-firms/index.html").read_text()
        self.assertIn("<!--data:median-->미산출",build.render_page(template,"a"*16,releases,[firm.record()]))

    def test_period_ordinals_and_identity_before_first_filing(self):
        self.assertEqual(list(filings.current_columns([(["과 목","제8기","제10기","제9기"],[""]*4)])),[2])
        docs = {"12345678":("새회계법인","receipt",{})}
        prior = [("옛회계법인","제 1 호",None)]
        rows = [["2026-10",n,"123456","1","서울 강남구","741202","","4","0","0"]
                for n in ("옛회계법인","새회계법인 컨설팅본부(강남)")]
        result = aggregate.aggregate([{"month":"2026-10","data":rows}],{"제 1 호":"새회계법인"},docs,prior)[0]
        self.assertEqual((result.name,result.record()["personMonths"]),("새회계법인",8))
        absent = aggregate.aggregate([],{},docs,[("옛회계법인","제 1 호","12345678")])[0]
        self.assertEqual((absent.name,absent.aliases),("새회계법인",("옛회계법인",)))

    def test_broad_source_loss_against_last_public_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            releases = [dict(date=f"2026{n:02}28",month=f"2026-{n:02}") for n in range(1,13)]
            prior = {r["month"]:590000 for r in releases}
            with self.assertRaisesRegex(ValueError,"급감"):
                pension.check_coverage(Path(tmp),releases,[490000]*7+[590000]*5,.95,"급감",prior)
        with self.assertRaises(ValueError):
            pension.month_index("0000-10")

    def test_ongoing_pages_run_that_fails_is_retried(self):
        import schedule
        with patch.object(schedule,"verify_publication",side_effect=[schedule.PublicationMismatch(),
                          schedule.PublicationMismatch(),None]),patch.object(schedule,"repair_pages",side_effect=[False,True]) as repair:
            schedule.ensure_published(Path("."))
            self.assertEqual(repair.call_count,2)
