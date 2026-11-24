import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from server import Budget, Gateway, NoRedirect, Server, UpstreamError, UpstreamLimited


class GatewayTests(unittest.TestCase):
    def test_attribution_failure_does_not_fetch_or_return_passage(self):
        gateway = Gateway("test-key")
        for metadata in ({}, {"copyright": " "}, {"promotional_content":"Marketing only"}, {"copyright":"", "promotional_content":"Marketing only"}):
            with patch.object(gateway, "fetch", return_value=metadata) as fetch:
                with self.assertRaises(UpstreamError):
                    gateway.chapter("MRK", 1)
                self.assertEqual(fetch.call_count, 1)

    def test_passage_identity_and_content_are_checked(self):
        gateway = Gateway("test-key")
        for passage in ({"id": "GEN.1", "content": "example"}, {"id": "MRK.1", "content": ""}):
            with patch.object(gateway, "fetch", side_effect=[{"copyright": "Publisher notice"}, passage]):
                with self.assertRaises(UpstreamError):
                    gateway.chapter("MRK", 1)

    def test_redirect_is_never_followed(self):
        request = urllib.request.Request("https://api.youversion.com/v1/bibles/111", headers={"X-YVP-App-Key":"test-key"})
        self.assertIsNone(NoRedirect().redirect_request(request, None, 302, "redirect", {}, "https://other.invalid/"))

    def test_upstream_key_echo_is_not_returned(self):
        gateway = Gateway("test-key")
        class Response(io.BytesIO):
            status = 200
        with patch.object(gateway.opener, "open", return_value=Response(b'{"message":"test-key"}')):
            with self.assertRaises(UpstreamError):
                gateway.fetch("/v1/bibles/111")

    def test_budget_limits_expire_and_global_budget_is_separate(self):
        now = [0]
        budget = Budget(lambda:now[0])
        for _ in range(12):
            self.assertTrue(budget.take("client",1))
        self.assertFalse(budget.take("client",2))
        self.assertTrue(budget.take("other",2))
        now[0] = 61
        self.assertTrue(budget.take("client",2))
        self.assertNotIn("other",budget.clients)
        for n in range(29):
            self.assertTrue(budget.take(str(n),2))
        self.assertFalse(budget.take("last",2))
        now[0] = 122
        budget.day_count = 10000
        self.assertFalse(budget.take("new",1))

    def test_client_table_has_a_bound(self):
        budget = Budget()
        for n in range(1024):
            self.assertTrue(budget.take(str(n),0))
        self.assertFalse(budget.take("overflow",0))
        self.assertEqual(len(budget.daily_clients),0)

    def test_full_minute_budget_of_one_reader_preserves_other_readers(self):
        budget=Budget()
        for _ in range(6):self.assertTrue(budget.take('reader',2))
        self.assertFalse(budget.take('reader',2))
        self.assertTrue(budget.take('another-reader',2))

    def test_free_font_clients_cannot_fill_daily_table(self):
        now=[0];budget=Budget(lambda:now[0])
        for n in range(4096):
            now[0]=(n//1024)*61
            self.assertTrue(budget.take(str(n),0))
        now[0]+=61
        self.assertEqual(len(budget.daily_clients),0)
        self.assertTrue(budget.take('new-reader',2))

    def test_daily_table_eviction_keeps_new_readers_working(self):
        now=[0];budget=Budget(lambda:now[0])
        for n in range(4096):
            now[0]=n*21
            self.assertTrue(budget.take(str(n),1))
        now[0]+=61
        self.assertTrue(budget.take('new-reader',2))
        self.assertEqual(len(budget.daily_clients),4096)
        self.assertNotIn('0',budget.daily_clients)

    def test_daily_client_budget_does_not_block_other_readers(self):
        now=[0];budget=Budget(lambda:now[0])
        for n in range(120):
            now[0]=n*210
            self.assertTrue(budget.take("reader",2))
        now[0]+=61
        self.assertFalse(budget.take("reader",2))
        self.assertTrue(budget.take("another-reader",2))
        now[0]=86401
        self.assertTrue(budget.take("reader",2))

    def test_hourly_caps_preserve_other_readers_and_expire(self):
        now=[0];budget=Budget(lambda:now[0])
        for n in range(18):
            now[0]=n*11
            self.assertTrue(budget.take('reader',2))
        now[0]+=61
        self.assertFalse(budget.take('reader',2))
        self.assertTrue(budget.take('other',2))
        now[0]=3601
        self.assertTrue(budget.take('reader',2))
        self.assertLessEqual(sum(map(len,budget.client_hours.values())),180)

    def test_global_hourly_cap_is_below_reported_provider_allowance(self):
        now=[0];budget=Budget(lambda:now[0])
        for n in range(90):
            now[0]=n*3
            self.assertTrue(budget.take(str(n),2))
        now[0]+=61
        self.assertFalse(budget.take('new-reader',2))
        now[0]=3601
        self.assertTrue(budget.take('new-reader',2))

    def test_incomplete_upstream_read_becomes_safe_error(self):
        import http.client
        gateway=Gateway("test-key")
        with patch.object(gateway.opener,"open",side_effect=http.client.IncompleteRead(b"test-key")):
            with self.assertRaises(UpstreamError):gateway.fetch('/v1/bibles/111')

    def test_font_cache_is_only_css_and_expires(self):
        gateway=Gateway("test-key")
        with patch.object(gateway,"fetch",return_value=b'/* sample CSS */') as fetch:
            self.assertEqual(gateway.fonts(),gateway.fonts());self.assertEqual(fetch.call_count,1)
            gateway.font_cached_at-=901;gateway.fonts();self.assertEqual(fetch.call_count,2)

    def test_provider_retry_after_stops_further_calls(self):
        import time
        gateway=Gateway('test-key')
        error=urllib.error.HTTPError('https://api.youversion.com',429,'limited',{'Retry-After':'300'},None)
        with patch.object(gateway.opener,'open',side_effect=error) as fetch:
            with self.assertRaises(UpstreamLimited):gateway.fetch('/v1/bibles/111')
            self.assertGreater(gateway.blocked_until-time.monotonic(),295)
            with self.assertRaises(UpstreamLimited):gateway.fetch('/v1/bibles/111')
            self.assertEqual(fetch.call_count,1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.gateway=Gateway("unpublished-test-secret")
        self.gateway.fetch=lambda path, **kwargs: {"copyright":"Publisher notice"} if path=="/v1/bibles/111" else {"id":"MRK.1","content":"<div>Original sample sentence.</div>"}
        self.server=Server(("127.0.0.1",0),self.gateway,development=False)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.worker.join()

    def get(self,path,headers=None):
        request=urllib.request.Request(self.base+path,headers=headers or {})
        try: response=urllib.request.urlopen(request,timeout=2)
        except urllib.error.HTTPError as error: response=error
        with response:return response.status,response.headers,response.read()

    def test_public_player_only_serves_three_files_without_fetching_scripture(self):
        with patch.object(self.gateway, "fetch") as fetch:
            for name, mime in [("lumo.html", "text/html"), ("lumo.js", "text/javascript"), ("lumo.css", "text/css")]:
                status, headers, body = self.get("/player/" + name)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), mime)
                self.assertTrue(body)
            self.assertEqual(self.get("/player/server.py")[0], 404)
            fetch.assert_not_called()

    def headers(self,ip="203.0.113.1"):
        return {"Origin":"https://finance-fixer.net","CF-Connecting-IP":ip}

    def test_success_has_no_key_or_cache(self):
        status,headers,body=self.get('/chapter?book=MRK&chapter=1',self.headers())
        self.assertEqual(status,200);self.assertEqual(json.loads(body)["id"],"MRK.1")
        self.assertIn("no-store",headers["Cache-Control"])
        self.assertEqual(headers["Access-Control-Allow-Origin"],"https://finance-fixer.net")
        self.assertNotIn(self.gateway.key.encode(),body)

    def test_direct_or_wrong_origin_request_is_denied(self):
        for headers in ({},{"Origin":"https://finance-fixer.net"},{"Origin":"https://wrong.invalid","CF-Connecting-IP":"203.0.113.1"},{"Origin":"https://finance-fixer.net","X-Forwarded-For":"203.0.113.1"},self.headers('203.0.113.1, 203.0.113.2')):
            self.assertEqual(self.get('/chapter?book=MRK&chapter=1',headers)[0],403)

    def test_validation_never_fetches_arbitrary_path_or_extra_chapters(self):
        with patch.object(self.gateway,"fetch") as fetch:
            for path in ['/chapter?book=MRK&chapter=0','/chapter?book=MRK&chapter=17','/chapter?book=XXX&chapter=1','/chapter?book=MRK&chapter=1&chapter=2','/chapter?book=MRK&chapter=1&key=anything','/chapter?book=MRK&chapter=1-2','/chapter?book=MRK&chapter=%D9%A1','/fonts.css?url=https://other.invalid']:
                self.assertEqual(self.get(path,self.headers())[0],400,path)
            self.assertEqual(self.get('/v1/licenses',self.headers())[0],404)
            self.assertEqual(self.get('/bible-service/server.py',self.headers())[0],404)
            fetch.assert_not_called()

    def test_disabled_and_upstream_errors_do_not_leak(self):
        self.gateway.enabled=False
        self.assertEqual(self.get('/chapter?book=MRK&chapter=1',self.headers())[0],503)
        self.gateway.enabled=True
        with patch.object(self.gateway,"fetch",side_effect=UpstreamError("unpublished-test-secret")):
            status,headers,body=self.get('/chapter?book=MRK&chapter=1',self.headers())
            self.assertEqual(status,502);self.assertNotIn(b"unpublished",body)

    def test_ipv6_subnets_share_a_48_bucket_without_exhausting_global(self):
        for n in range(6):
            self.assertEqual(self.get('/chapter?book=MRK&chapter=1',self.headers(f'2001:db8:1:1::{n+1:x}'))[0],200)
        self.assertEqual(self.get('/chapter?book=MRK&chapter=1',self.headers('2001:db8:1:1::ffff'))[0],429)
        self.assertEqual(self.get('/chapter?book=MRK&chapter=1',self.headers('2001:db8:1:2::1'))[0],429)
        self.assertEqual(self.get('/chapter?book=MRK&chapter=1',self.headers('2001:db8:2:1::1'))[0],200)

    def test_cached_fonts_still_work_during_provider_cooldown(self):
        import time
        self.gateway.font_cache=b'/* sample CSS */'
        self.gateway.font_cached_at=time.monotonic()
        self.gateway.blocked_until=time.monotonic()+300
        with patch.object(self.gateway,'fetch') as fetch:
            self.assertEqual(self.get('/fonts.css',self.headers())[0],200)
            self.assertEqual(self.get('/chapter?book=MRK&chapter=1',self.headers())[0],429)
            fetch.assert_not_called()

    def test_head_does_not_spend_upstream_budget(self):
        req=urllib.request.Request(self.base+'/chapter?book=MRK&chapter=1',headers=self.headers(),method='HEAD')
        with patch.object(self.gateway,'fetch') as fetch:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
            self.assertEqual(error.exception.code,405);fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
