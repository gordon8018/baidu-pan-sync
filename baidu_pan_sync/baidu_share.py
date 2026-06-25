from __future__ import annotations

import base64
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, OpenerDirector, urlopen


PAN_APP_ID = "250528"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class UrlopenAdapter:
    def open(self, request: Request, timeout: int) -> Any:
        return urlopen(request, timeout=timeout)


class ShareSession:
    def __init__(
        self,
        url: str,
        passcode: str,
        feature: str,
        bdstoken: str,
        share_uk: str,
        shareid: str,
        sekey: str = "",
    ) -> None:
        self.url = url
        self.passcode = passcode
        self.feature = feature
        self.bdstoken = bdstoken
        self.share_uk = share_uk
        self.shareid = shareid
        self.sekey = sekey


class BaiduShareClient:
    def __init__(
        self,
        cookie: str,
        opener: OpenerDirector | UrlopenAdapter | None = None,
        sekeys: dict[str, str] | None = None,
    ) -> None:
        self.cookie = cookie.strip()
        self.cookie_parts = parse_cookie_header(self.cookie)
        self.opener = opener or UrlopenAdapter()
        self.sessions: dict[tuple[str, str], ShareSession] = {}
        self.use_explicit_sekeys = sekeys is not None
        self.sekeys = sekeys or {}
        self.last_verify_error: RuntimeError | None = None

    def list_share(self, url: str, passcode: str) -> list[dict[str, Any]]:
        session = self._ensure_session(url, passcode)
        return self._list_dir(session, None)

    def transfer_files(
        self,
        url: str,
        passcode: str,
        fs_ids: list[str],
        remote_transfer_root: str,
    ) -> None:
        if not fs_ids:
            return
        session = self._ensure_session(url, passcode)
        api_url = self._api_url(
            "/share/transfer",
            {
                "app_id": PAN_APP_ID,
                "channel": "chunlei",
                "clienttype": "0",
                "web": "1",
                "shareid": session.shareid,
                "from": session.share_uk,
                "bdstoken": session.bdstoken,
            },
        )
        data = {
            "fsidlist": "[" + ",".join(str(fs_id) for fs_id in fs_ids) + "]",
            "path": remote_transfer_root,
        }
        response = self._request_json(api_url, data=data, referer=f"https://pan.baidu.com/s/{session.feature}")
        errno = int(response.get("errno", 0))
        if errno != 0:
            raise RuntimeError(f"Baidu share transfer failed with errno {errno}: {response}")

    def _ensure_session(self, url: str, passcode: str) -> ShareSession:
        key = (url, passcode)
        if key in self.sessions:
            return self.sessions[key]

        feature = feature_from_share_url(url)
        first_tokens = self._access_share_page(feature, first=True)
        existing_sekey = self.sekeys.get(feature, "") if self.use_explicit_sekeys else self.sekeys.get(feature, self.sekey())
        if existing_sekey:
            session = ShareSession(
                url=url,
                passcode=passcode,
                feature=feature,
                bdstoken=first_tokens["bdstoken"],
                share_uk=first_tokens["share_uk"],
                shareid=first_tokens["shareid"],
                sekey=existing_sekey,
            )
            self.sessions[key] = session
            return session

        verify_response = self._verify_share(url, feature, passcode, first_tokens)
        errno = int(verify_response.get("errno", 0))
        if errno == 9019:
            verify_response = self._verify_share_with_surl(url, feature, passcode, first_tokens)
            errno = int(verify_response.get("errno", 0))
        if errno != 0:
            self.last_verify_error = RuntimeError(
                "Baidu share verify failed "
                f"with errno {errno}; methods=legacy,surl; "
                f"shareid_present={bool(first_tokens.get('shareid'))}; "
                f"share_uk_present={bool(first_tokens.get('share_uk'))}; "
                f"bdstoken_present={bool(first_tokens.get('bdstoken'))}; "
                f"bdclnd_present={bool(self.sekey())}; "
                f"referer_has_pwd={bool(passcode)}; "
                f"response={safe_response(verify_response)}"
            )
            raise self.last_verify_error

        tokens = self._access_share_page(feature, first=False)
        session = ShareSession(
            url=url,
            passcode=passcode,
            feature=feature,
            bdstoken=tokens["bdstoken"],
            share_uk=tokens["share_uk"],
            shareid=tokens["shareid"],
            sekey=self.sekey(),
        )
        self.sessions[key] = session
        return session

    def _refresh_session_sekey(self, session: ShareSession) -> None:
        verify_response = self._verify_share_with_surl(
            session.url,
            session.feature,
            session.passcode,
            {
                "bdstoken": session.bdstoken,
                "share_uk": session.share_uk,
                "shareid": session.shareid,
            },
        )
        errno = int(verify_response.get("errno", 0))
        if errno != 0:
            raise RuntimeError(
                f"Baidu share verify failed while refreshing sekey with errno {errno}: {safe_response(verify_response)}"
            )
        session.sekey = self.sekey()
        self.sekeys[session.feature] = session.sekey

    def _verify_share(
        self,
        url: str,
        feature: str,
        passcode: str,
        tokens: dict[str, str],
    ) -> dict[str, Any]:
        del feature
        verify_url = self._api_url(
            "/share/verify",
            {
                "shareid": tokens["shareid"],
                "time": str(int(time.time() * 1000)),
                "uk": tokens["share_uk"],
                "clienttype": "1",
            },
        )
        return self._request_json(
            verify_url,
            data={
                "pwd": passcode,
                "vcode": "null",
                "vcode_str": "null",
                "bdstoken": tokens["bdstoken"],
            },
            referer=share_referer(url, passcode),
        )

    def _verify_share_with_surl(
        self,
        url: str,
        feature: str,
        passcode: str,
        tokens: dict[str, str],
    ) -> dict[str, Any]:
        verify_url = self._api_url(
            "/share/verify",
            self.frontend_ajax_params(
                {
                    "surl": feature[1:],
                    "t": str(int(time.time() * 1000)),
                },
                tokens["bdstoken"],
            ),
        )
        return self._request_json(
            verify_url,
            data={
                "pwd": passcode,
                "vcode": "",
                "vcode_str": "",
            },
            referer=share_referer(url, passcode),
        )

    def _access_share_page(self, feature: str, first: bool) -> dict[str, str]:
        referer = "https://pan.baidu.com/disk/home" if first else f"https://pan.baidu.com/share/init?surl={feature[1:]}"
        request = self._request(
            f"https://pan.baidu.com/s/{feature}",
            headers={"Referer": referer},
        )
        with self.opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            self._remember_response_cookies(response)
        match = re.search(r"(\{.+?loginstate.+?\})\);", body)
        if match is None:
            raise RuntimeError("Baidu share page did not expose login token data")
        data = json.loads(match.group(1))
        return {
            "bdstoken": str(data["bdstoken"]),
            "share_uk": str(data["share_uk"]),
            "shareid": str(data["shareid"]),
        }

    def _list_dir(self, session: ShareSession, directory: str | None, allow_refresh: bool = True) -> list[dict[str, Any]]:
        params = {
            "app_id": PAN_APP_ID,
            "channel": "chunlei",
            "clienttype": "0",
            "web": "1",
            "bdstoken": session.bdstoken,
            "shorturl": session.feature[1:],
        }
        sekey = session.sekey
        if sekey:
            params["is_from_web"] = "1"
            params["sekey"] = sekey
            params["uk"] = session.share_uk
            params["shareid"] = session.shareid
        if directory is None:
            params["root"] = "1"
        else:
            params["dir"] = directory
        response = self._request_json(self._api_url("/share/list", params), sekey=sekey)
        errno = int(response.get("errno", 0))
        if errno == -9 and sekey and allow_refresh:
            self._refresh_session_sekey(session)
            return self._list_dir(session, directory, allow_refresh=False)
        if errno != 0:
            raise RuntimeError(f"Baidu share list failed with errno {errno}: {response}")

        files: list[dict[str, Any]] = []
        for item in response.get("list", []):
            if int(item.get("isdir", 0)):
                files.extend(self._list_dir(session, str(item["path"])))
            else:
                files.append(item)
        return files

    def _request_json(
        self,
        url: str,
        data: dict[str, str] | None = None,
        referer: str | None = None,
        sekey: str | None = None,
    ) -> dict[str, Any]:
        request = self._request(url, data=data, headers={"Referer": referer} if referer else None, sekey=sekey)
        with self.opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            self._remember_response_cookies(response)
            return json.loads(body)

    def _request(
        self,
        url: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str | None] | None = None,
        sekey: str | None = None,
    ) -> Request:
        body = None
        request_headers = {"Cookie": self._cookie_header(sekey=sekey), "User-Agent": BROWSER_USER_AGENT}
        if headers:
            for key, value in headers.items():
                if value is not None:
                    request_headers[key] = value
        if data is not None:
            body = urlencode(data).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            request_headers["X-Requested-With"] = "XMLHttpRequest"
            request_headers["Origin"] = "https://pan.baidu.com"
        return Request(url, data=body, headers=request_headers)

    def _api_url(self, path: str, params: dict[str, str]) -> str:
        return f"https://pan.baidu.com{path}?{urlencode(params)}"

    def frontend_ajax_params(self, params: dict[str, str], bdstoken: str) -> dict[str, str]:
        ajax_params = {
            "channel": "chunlei",
            "web": "1",
            "app_id": PAN_APP_ID,
            "bdstoken": bdstoken,
            "clienttype": "0",
        }
        logid = self.logid()
        if logid:
            ajax_params["logid"] = logid
        return {**params, **ajax_params}

    def logid(self) -> str:
        baiduid = self.cookie_parts.get("BAIDUID") or self.cookie_parts.get("BAIDUID_BFESS")
        if not baiduid:
            return ""
        return base64.b64encode(baiduid.encode("utf-8")).decode("ascii")

    def sekey(self) -> str:
        return self.cookie_parts.get("BDCLND", "")

    def _remember_response_cookies(self, response: Any) -> None:
        headers = getattr(response, "headers", None)
        if headers is None or not hasattr(headers, "get_all"):
            return
        for cookie_line in headers.get_all("Set-Cookie", []) or []:
            cookie_pair = cookie_line.split(";", 1)[0].strip()
            if "=" not in cookie_pair:
                continue
            name, value = cookie_pair.split("=", 1)
            self.cookie_parts[name] = value

    def _cookie_header(self, sekey: str | None = None) -> str:
        cookie_parts = dict(self.cookie_parts)
        if sekey is not None:
            cookie_parts["BDCLND"] = sekey
        return "; ".join(f"{name}={value}" for name, value in cookie_parts.items())


def feature_from_share_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if parsed.path.rstrip("/").endswith("/share/init"):
        surl = query.get("surl", [""])[0]
        return surl if surl.startswith("1") else f"1{surl}"
    feature = parsed.path.rstrip("/").split("/")[-1]
    if not feature.startswith("1"):
        raise ValueError(f"unsupported Baidu share URL: {url}")
    return feature


def parse_cookie_header(cookie: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in cookie.lstrip("\ufeff").split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        if name:
            parts[name] = value
    return parts


def share_referer(url: str, passcode: str) -> str:
    if not passcode:
        return url
    separator = "&" if "?" in url else "?"
    if "pwd=" in url:
        return url
    return f"{url}{separator}pwd={passcode}"


def safe_response(response: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in response.items()
        if key.lower() not in {"bduss", "stoken", "cookie", "randsk"}
    }
