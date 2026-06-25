from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
from urllib.request import Request
import unittest

from baidu_pan_sync.baidu_share import BaiduShareClient, parse_cookie_header


class FakeResponse:
    def __init__(self, body: dict[str, object] | str, set_cookies: list[str] | None = None) -> None:
        self.body = body
        self.headers = FakeHeaders(set_cookies or [])

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.body, str):
            return self.body.encode("utf-8")
        return json.dumps(self.body).encode("utf-8")


class FakeHeaders:
    def __init__(self, set_cookies: list[str]) -> None:
        self.set_cookies = set_cookies

    def get_all(self, name: str, default: list[str] | None = None) -> list[str] | None:
        if name.lower() == "set-cookie":
            return self.set_cookies
        return default


class RecordingOpener:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: int) -> FakeResponse:
        del timeout
        self.requests.append(request)
        parsed = urlparse(request.full_url)
        query = parse_qs(parsed.query)
        if parsed.path.startswith("/s/"):
            return FakeResponse('window.yunData = {"loginstate":1,"bdstoken":"token","share_uk":"uk","shareid":"sid"});')
        if parsed.path == "/share/verify":
            return FakeResponse({"errno": 0, "randsk": "sekey"}, ["BDCLND=sekey; Path=/; Domain=.baidu.com"])
        if parsed.path == "/share/list" and query.get("root") == ["1"]:
            return FakeResponse(
                {
                    "errno": 0,
                    "list": [
                        {
                            "path": "/daily/a.csv",
                            "isdir": 0,
                            "size": 10,
                            "server_mtime": 1782144000,
                            "md5": "abc",
                            "fs_id": 1001,
                        },
                        {
                            "path": "/daily/nested",
                            "server_filename": "nested",
                            "isdir": 1,
                            "fs_id": 1002,
                        },
                    ],
                }
            )
        if parsed.path == "/share/list" and query.get("dir") == ["/daily/nested"]:
            return FakeResponse(
                {
                    "errno": 0,
                    "list": [
                        {
                            "path": "/daily/nested/b.csv",
                            "isdir": 0,
                            "size": 20,
                            "server_mtime": 1782144300,
                            "md5": "def",
                            "fs_id": 1003,
                        }
                    ],
                }
            )
        if parsed.path == "/share/transfer":
            return FakeResponse({"errno": 0, "info": [{"path": "/auto-sync/source_a/a.csv"}]})
        raise AssertionError(f"unexpected request: {request.full_url}")


class RetryVerifyOpener(RecordingOpener):
    def open(self, request: Request, timeout: int) -> FakeResponse:
        parsed = urlparse(request.full_url)
        if parsed.path == "/share/verify" and len([r for r in self.requests if urlparse(r.full_url).path == "/share/verify"]) == 0:
            self.requests.append(request)
            return FakeResponse({"errno": 9019, "errmsg": "params error"})
        return super().open(request, timeout)


class Always9019VerifyOpener(RecordingOpener):
    def open(self, request: Request, timeout: int) -> FakeResponse:
        parsed = urlparse(request.full_url)
        if parsed.path == "/share/verify":
            self.requests.append(request)
            return FakeResponse({"errno": 9019, "errmsg": "params error"})
        return super().open(request, timeout)


class ExistingSeKeyOpener(RecordingOpener):
    def open(self, request: Request, timeout: int) -> FakeResponse:
        parsed = urlparse(request.full_url)
        if parsed.path == "/share/verify":
            raise AssertionError("verify should be skipped when BDCLND is already present")
        return super().open(request, timeout)


class ExpiredSeKeyOpener(RecordingOpener):
    def open(self, request: Request, timeout: int) -> FakeResponse:
        self.requests.append(request)
        parsed = urlparse(request.full_url)
        query = parse_qs(parsed.query)
        if parsed.path.startswith("/s/"):
            return FakeResponse('window.yunData = {"loginstate":1,"bdstoken":"token","share_uk":"uk","shareid":"sid"});')
        if parsed.path == "/share/list" and len([r for r in self.requests if urlparse(r.full_url).path == "/share/list"]) == 1:
            return FakeResponse({"errno": -9, "list": []})
        if parsed.path == "/share/verify":
            return FakeResponse({"errno": 0}, ["BDCLND=fresh; Path=/; Domain=.baidu.com"])
        if parsed.path == "/share/list" and query.get("root") == ["1"]:
            return FakeResponse(
                {
                    "errno": 0,
                    "list": [
                        {
                            "path": "/daily/a.csv",
                            "isdir": 0,
                            "size": 10,
                            "server_mtime": 1782144000,
                            "md5": "abc",
                            "fs_id": 1001,
                        }
                    ],
                }
            )
        raise AssertionError(f"unexpected request: {request.full_url}")


class BaiduShareClientTests(unittest.TestCase):
    def test_list_share_verifies_passcode_and_recursively_returns_files(self):
        opener = RecordingOpener()
        client = BaiduShareClient("BDUSS=redacted; STOKEN=redacted", opener=opener)

        listing = client.list_share("https://pan.baidu.com/s/1source", "h12i")

        self.assertEqual([item["path"] for item in listing], ["/daily/a.csv", "/daily/nested/b.csv"])
        verify_request = opener.requests[1]
        self.assertEqual(urlparse(verify_request.full_url).path, "/share/verify")
        verify_query = parse_qs(urlparse(verify_request.full_url).query)
        self.assertEqual(verify_query["time"][0].isdigit(), True)
        self.assertIn("Mozilla/5.0", verify_request.headers["User-agent"])
        self.assertEqual(verify_request.headers["Referer"], "https://pan.baidu.com/s/1source?pwd=h12i")
        self.assertEqual(verify_request.headers["Content-type"], "application/x-www-form-urlencoded; charset=UTF-8")
        self.assertEqual(parse_qs((verify_request.data or b"").decode("utf-8"))["pwd"], ["h12i"])
        self.assertIn("BDCLND=sekey", opener.requests[2].headers["Cookie"])
        directory_queries = [
            parse_qs(urlparse(request.full_url).query)
            for request in opener.requests
            if urlparse(request.full_url).path == "/share/list" and "dir=" in urlparse(request.full_url).query
        ]
        self.assertEqual(directory_queries[0]["dir"], ["/daily/nested"])

    def test_list_share_reuses_existing_bdclnd_cookie_without_verify(self):
        opener = ExistingSeKeyOpener()
        client = BaiduShareClient("BDUSS=redacted; STOKEN=redacted; BDCLND=sekey", opener=opener)

        listing = client.list_share("https://pan.baidu.com/s/1source", "h12i")

        self.assertEqual([item["path"] for item in listing], ["/daily/a.csv", "/daily/nested/b.csv"])
        request_paths = [urlparse(request.full_url).path for request in opener.requests]
        self.assertNotIn("/share/verify", request_paths)
        list_request = next(request for request in opener.requests if urlparse(request.full_url).path == "/share/list")
        list_query = parse_qs(urlparse(list_request.full_url).query)
        self.assertEqual(list_query["sekey"], ["sekey"])

    def test_list_share_refreshes_bdclnd_when_existing_sekey_is_invalid_for_share(self):
        opener = ExpiredSeKeyOpener()
        client = BaiduShareClient("BDUSS=redacted; STOKEN=redacted; BDCLND=stale", opener=opener)

        listing = client.list_share("https://pan.baidu.com/s/1source", "h12i")

        self.assertEqual([item["path"] for item in listing], ["/daily/a.csv"])
        list_requests = [request for request in opener.requests if urlparse(request.full_url).path == "/share/list"]
        retry_query = parse_qs(urlparse(list_requests[-1].full_url).query)
        self.assertEqual(retry_query["sekey"], ["fresh"])
        self.assertIn("BDCLND=fresh", list_requests[-1].headers["Cookie"])

    def test_explicit_sekeys_disable_global_bdclnd_fallback(self):
        opener = RecordingOpener()
        client = BaiduShareClient("BDUSS=redacted; STOKEN=redacted; BDCLND=global", opener=opener, sekeys={})

        client.list_share("https://pan.baidu.com/s/1source", "h12i")

        verify_requests = [request for request in opener.requests if urlparse(request.full_url).path == "/share/verify"]
        self.assertEqual(len(verify_requests), 1)

    def test_transfer_files_posts_only_selected_fs_ids_to_remote_transfer_root(self):
        opener = RecordingOpener()
        client = BaiduShareClient("BDUSS=redacted; STOKEN=redacted", opener=opener)
        client.list_share("https://pan.baidu.com/s/1source", "h12i")

        client.transfer_files(
            "https://pan.baidu.com/s/1source",
            "h12i",
            ["1001", "1003"],
            "/auto-sync/source_a",
        )

        transfer_request = opener.requests[-1]
        self.assertEqual(urlparse(transfer_request.full_url).path, "/share/transfer")
        body = parse_qs((transfer_request.data or b"").decode("utf-8"))
        self.assertEqual(body["fsidlist"], ["[1001,1003]"])
        self.assertEqual(body["path"], ["/auto-sync/source_a"])
        self.assertEqual(transfer_request.headers["Referer"], "https://pan.baidu.com/s/1source")

    def test_list_share_retries_verify_with_surl_parameters_when_legacy_verify_gets_9019(self):
        opener = RetryVerifyOpener()
        client = BaiduShareClient("BDUSS=redacted; STOKEN=redacted; BAIDUID=abc123", opener=opener)

        listing = client.list_share("https://pan.baidu.com/s/1source", "h12i")

        verify_requests = [request for request in opener.requests if urlparse(request.full_url).path == "/share/verify"]
        retry_query = parse_qs(urlparse(verify_requests[1].full_url).query)
        self.assertEqual([item["path"] for item in listing], ["/daily/a.csv", "/daily/nested/b.csv"])
        self.assertEqual(retry_query["surl"], ["source"])
        self.assertEqual(retry_query["channel"], ["chunlei"])
        self.assertEqual(retry_query["web"], ["1"])
        self.assertEqual(retry_query["app_id"], ["250528"])
        self.assertEqual(retry_query["bdstoken"], ["token"])
        self.assertEqual(retry_query["logid"], ["YWJjMTIz"])
        self.assertEqual(retry_query["clienttype"], ["0"])

    def test_verify_9019_error_reports_safe_diagnostics_without_cookie_values(self):
        opener = Always9019VerifyOpener()
        client = BaiduShareClient("BDUSS=secret; STOKEN=secret", opener=opener)

        with self.assertRaisesRegex(RuntimeError, "legacy,surl"):
            client.list_share("https://pan.baidu.com/s/1source", "h12i")

        message = str(client.last_verify_error)
        self.assertIn("shareid_present=True", message)
        self.assertIn("share_uk_present=True", message)
        self.assertIn("bdstoken_present=True", message)
        self.assertIn("bdclnd_present=False", message)
        self.assertNotIn("secret", message)

    def test_parse_cookie_header_ignores_utf8_bom(self):
        cookies = parse_cookie_header("\ufeffBDUSS=redacted; STOKEN=redacted")

        self.assertEqual(cookies["BDUSS"], "redacted")
        self.assertNotIn("\ufeffBDUSS", cookies)


if __name__ == "__main__":
    unittest.main()
