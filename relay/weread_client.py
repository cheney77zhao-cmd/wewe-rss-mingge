from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
import re
import secrets
import time
import threading
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit, parse_qs

import requests

WEREAD_BASE = "https://i.weread.qq.com"
WX_APPID = "wxab9b71ad2b90ff34"
WX_SCOPE = "snsapi_userinfo,snsapi_timeline,snsapi_friend"
VERSION_HEADERS = {
    "baseapi": "30", "appver": "2.1.2.10245900", "basever": "2.1.2.10245900",
    "osver": "11", "channelId": "900",
    "User-Agent": "WeRead/2.1.2 WRBrand/Onyx wr_eink Dalvik/2.1.0 (Linux; U; Android 11; BOOX Build/onyx)",
}


class WeReadError(RuntimeError): pass
class QRExpiredError(WeReadError): pass
class QRDeclinedError(WeReadError): pass
class AuthExpiredError(WeReadError): pass
class RiskControlError(WeReadError): pass
class ArticleValidationError(WeReadError): pass


def original_url_from_html(source: str) -> str:
    """Use article metadata only, never links in its body/recommendations."""
    class Metadata(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'meta' and attrs.get('property', '').lower() == 'og:url':
                self.urls.append(attrs.get('content', ''))
            if tag == 'link' and attrs.get('rel', '').lower() == 'canonical':
                self.urls.append(attrs.get('href', ''))

    parser = Metadata()
    parser.feed(source)
    candidates = parser.urls + re.findall(r'''\bvar\s+msg_link\s*=\s*["']([^"']+)["']''', source)
    for candidate in candidates:
        candidate = html.unescape(candidate).replace(r'\/', '/').replace(r'\x26', '&').replace(r'\u0026', '&').strip()
        try:
            url = urlsplit(candidate)
            if url.scheme != 'https' or url.hostname != 'mp.weixin.qq.com' or url.port or url.username or url.password:
                continue
        except ValueError:
            continue
        token = url.path[3:] if url.path.startswith('/s/') else ''
        if re.fullmatch(r'[A-Za-z0-9_-]{22}', token):
            return candidate
        query = parse_qs(url.query)
        if url.path == '/s' and all(query.get(k) for k in ('__biz', 'mid', 'idx', 'sn')):
            return candidate
    raise WeReadError('文章页面未提供可验证的微信原文链接，未生成替代链接')


def wechat_article_id(review_id: str) -> str:
    """Translate a WeRead review ID to WeWe's WeChat short-link ID.

    Only remove the anchored account prefix. Underscores, hyphens and tildes
    inside the article token belong to the URL and must remain untouched.
    """
    match = re.fullmatch(r"MP_WXS_[0-9]+_(.+)", review_id)
    return match.group(1) if match else review_id


@dataclass
class Credentials:
    vid: str
    accessToken: str
    refreshToken: str = ""
    deviceId: str = ""
    name: str = ""
    guestToken: str = ""
    syncKey: int = 0
    updatedAt: int = 0
    cookies: dict[str, str] = field(default_factory=dict)
    wrTicket: str = ""
    wrPa: str = ""

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Credentials":
        return cls(
            vid=str(value.get("vid") or ""), accessToken=str(value.get("accessToken") or ""),
            refreshToken=str(value.get("refreshToken") or ""), deviceId=str(value.get("deviceId") or ""),
            name=str(value.get("name") or ""), guestToken=str(value.get("guestToken") or ""),
            syncKey=int(value.get("syncKey") or 0), updatedAt=int(value.get("updatedAt") or 0),
            cookies=dict(value.get("cookies") or {}), wrTicket=str(value.get("wrTicket") or ""),
            wrPa=str(value.get("wrPa") or ""),
        )


@dataclass
class Article:
    article_id: str
    title: str
    pic_url: str
    publish_time: int


def _payload_error(payload: dict[str, Any]) -> tuple[int, str]:
    try: code = int(payload.get("errcode", payload.get("errCode", 0)) or 0)
    except (TypeError, ValueError): code = 0
    return code, str(payload.get("errmsg") or payload.get("errMsg") or "")


def _device_id() -> str:
    return "eink334691225" + str(secrets.randbits(63)).zfill(19)


class WeReadClient:
    def __init__(self, timeout: float = 25.0, min_interval: float = 3.0):
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self.session = requests.Session()
        self._last_request = 0.0
        self._request_lock = threading.Lock()

    def _json(self, response: requests.Response, label: str) -> dict[str, Any]:
        try: payload = response.json()
        except ValueError as exc: raise WeReadError(f"{label} 返回格式异常") from exc
        if not isinstance(payload, dict): raise WeReadError(f"{label} 返回格式异常")
        return payload

    def request_qr(self) -> tuple[str, str]:
        response = self.session.get(f"{WEREAD_BASE}/wxticket", params={"nonceStr": "weread"}, headers=VERSION_HEADERS, timeout=self.timeout)
        response.raise_for_status()
        ticket = self._json(response, "二维码 ticket")
        if not ticket.get("signature") or ticket.get("timeStamp") is None:
            code, message = _payload_error(ticket)
            raise WeReadError(f"二维码 ticket 获取失败: {code} {message}")
        response = self.session.get(
            "https://open.weixin.qq.com/connect/sdk/qrconnect",
            params={"appid": WX_APPID, "noncestr": "weread", "timestamp": str(ticket["timeStamp"]), "scope": WX_SCOPE, "signature": ticket["signature"]},
            headers={"User-Agent": VERSION_HEADERS["User-Agent"]}, timeout=self.timeout,
        )
        response.raise_for_status()
        payload = self._json(response, "微信二维码")
        uuid = str(payload.get("uuid") or "")
        if int(payload.get("errcode", -1)) != 0 or not uuid: raise WeReadError("微信二维码生成失败")
        return uuid, f"https://open.weixin.qq.com/connect/confirm?uuid={quote(uuid, safe='')}"

    def request_web_qr(self) -> tuple[str, str, dict[str, str]]:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        response = session.get(
            "https://weread.qq.com/r/weread-skills", allow_redirects=True,
            headers={**headers, "Accept": "text/html,application/xhtml+xml,*/*"}, timeout=self.timeout,
        )
        response.raise_for_status()
        response = session.get(
            "https://weread.qq.com/api/auth/getLoginUid",
            headers={**headers, "Accept": "application/json, text/plain, */*", "Referer": "https://weread.qq.com/r/weread-skills"},
            timeout=self.timeout,
        )
        response.raise_for_status(); payload = self._json(response, "网页版登录二维码")
        uid = str(payload.get("uid") or "")
        if not uid: raise WeReadError("微信读书没有返回网页版登录编号")
        return uid, f"https://weread.qq.com/web/confirm?uid={quote(uid, safe='')}", requests.utils.dict_from_cookiejar(session.cookies)

    def poll_web_qr(self, uid: str, cookies: dict[str, str]) -> tuple[str, Credentials | None, dict[str, str]]:
        session = requests.Session(); session.cookies.update(cookies)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*", "Referer": "https://weread.qq.com/r/weread-skills",
        }
        try:
            response = session.get(
                f"https://weread.qq.com/api/auth/getLoginInfo?uid={quote(uid, safe='')}&otp",
                headers=headers, timeout=min(self.timeout, 8),
            )
        except requests.Timeout:
            # The endpoint is a blocking poll. A transport timeout means the
            # QR is still waiting, not that the login failed.
            return "waiting", None, requests.utils.dict_from_cookiejar(session.cookies)
        response.raise_for_status(); payload = self._json(response, "网页版扫码状态")
        current_cookies = requests.utils.dict_from_cookiejar(session.cookies)
        if payload.get("succeed") is True:
            vid = str(payload.get("webLoginVid") or ""); access = str(payload.get("accessToken") or "")
            refresh = str(payload.get("refreshToken") or "")
            if not vid.isdigit() or not access: raise WeReadError("网页版扫码结果缺少账号凭证")
            current_cookies.update({"wr_vid": vid, "wr_skey": access, "wr_ql": "0"})
            if refresh: current_cookies["wr_rt"] = quote(refresh, safe="")
            name = ""
            try:
                user_response = session.get(
                    "https://weread.qq.com/api/userInfo", params={"userVid": vid},
                    headers={**headers, "Cookie": "; ".join(f"{k}={v}" for k, v in current_cookies.items()), "X-Vid": vid, "X-Skey": access},
                    timeout=self.timeout,
                )
                if user_response.ok:
                    user = self._json(user_response, "用户信息"); name = str(user.get("name") or "")
                    current_cookies.update(requests.utils.dict_from_cookiejar(session.cookies))
            except Exception:
                pass
            return "confirmed", Credentials(vid, access, refresh, name=name, updatedAt=int(time.time()), cookies=current_cookies), current_cookies
        logic = str(payload.get("logicCode") or "")
        if logic == "NEED_OTP": raise WeReadError("本次登录需要手机显示的四位验证码，原版界面暂不支持输入；请重新生成二维码再试")
        if logic in {"LOGIN_TIMEOUT", "OTP_EXPIRED"}: raise QRExpiredError("二维码已过期，请重新生成")
        if logic == "OTP_NOT_MATCH": raise WeReadError("登录验证码不正确，请重新生成二维码")
        return "waiting", None, current_cookies

    def poll_qr(self, uuid: str, last: int | None = None) -> tuple[str, str, int]:
        params: dict[str, Any] = {"f": "json", "uuid": uuid}
        if last is not None: params["last"] = str(last)
        response = self.session.get("https://long.open.weixin.qq.com/connect/l/qrconnect", params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=min(self.timeout, 25))
        response.raise_for_status()
        payload = self._json(response, "扫码状态")
        code = int(payload.get("wx_errcode", 0) or 0)
        if code == 405: return "confirmed", str(payload.get("wx_code") or ""), code
        if code == 404: return "scanned", "", code
        if code == 408: return "waiting", "", code
        if code == 402: raise QRExpiredError("二维码已过期，请重新生成")
        if code == 403: raise QRDeclinedError("已在微信中取消登录")
        raise WeReadError(f"未知扫码状态: {code}")

    def exchange_qr(self, wx_code: str) -> Credentials:
        device_id = _device_id(); timestamp = int(time.time() * 1000); random_value = secrets.randbelow(1000)
        signature = hashlib.sha256(f"{timestamp}{device_id}{random_value}".encode()).hexdigest()
        body = {"appFirstInstall": 1, "code": wx_code, "deviceId": device_id, "deviceName": "BOOX", "installId": "eink31" + "".join(str(secrets.randbelow(10)) for _ in range(26)), "isAutoLogout": 0, "isFromQrcode": 1, "random": random_value, "signature": signature, "timestamp": timestamp, "trackId": "", "deviceType": 3}
        headers = {**VERSION_HEADERS, "Content-Type": "application/json; charset=UTF-8"}
        response = self.session.post(f"{WEREAD_BASE}/login", headers=headers, data=json.dumps(body, separators=(",", ":")).encode(), timeout=self.timeout)
        payload = self._json(response, "扫码登录"); code, message = _payload_error(payload)
        if not response.ok or not payload.get("accessToken") or not payload.get("refreshToken"):
            raise WeReadError(f"微信读书登录失败: {code or response.status_code} {message}")
        user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        credentials = Credentials(str(payload.get("vid") or ""), str(payload["accessToken"]), str(payload["refreshToken"]), device_id, str(user.get("name") or ""), updatedAt=int(time.time()))
        if not credentials.vid.isdigit(): raise WeReadError("登录返回的账号编号无效")
        return credentials

    def refresh(self, credentials: Credentials) -> Credentials:
        if not credentials.refreshToken or not credentials.deviceId: raise AuthExpiredError("登录状态无法续期，请重新扫码")
        timestamp = int(time.time() * 1000); random_value = secrets.randbelow(1000) + 1
        signature = hashlib.sha256(f"{timestamp}{credentials.deviceId}{random_value}".encode()).hexdigest()
        body = {"deviceId": credentials.deviceId, "deviceName": "BOOX", "inBackground": 0, "kickType": 1, "random": random_value, "refCgi": "", "refreshToken": credentials.refreshToken, "signature": signature, "timestamp": timestamp, "trackId": "", "deviceType": 3}
        response = self.session.post(f"{WEREAD_BASE}/login", headers={**VERSION_HEADERS, "Content-Type": "application/json; charset=UTF-8"}, data=json.dumps(body, separators=(",", ":")).encode(), timeout=self.timeout)
        payload = self._json(response, "凭证续期"); code, message = _payload_error(payload)
        if not response.ok or not payload.get("accessToken"): raise AuthExpiredError(f"凭证续期失败: {code or response.status_code} {message}")
        if str(payload.get("vid") or credentials.vid) != credentials.vid: raise AuthExpiredError("续期账号不一致")
        return Credentials(
            credentials.vid, str(payload["accessToken"]),
            str(payload.get("refreshToken") or credentials.refreshToken), credentials.deviceId,
            credentials.name, credentials.guestToken, credentials.syncKey, int(time.time()),
            credentials.cookies, credentials.wrTicket, credentials.wrPa,
        )

    @staticmethod
    def _web_cookies(credentials: Credentials) -> dict[str, str]:
        cookies = dict(credentials.cookies)
        cookies.setdefault("wr_vid", credentials.vid)
        cookies.setdefault("wr_skey", credentials.accessToken)
        cookies.setdefault("wr_ql", "0")
        if credentials.refreshToken:
            cookies.setdefault("wr_rt", quote(credentials.refreshToken, safe=""))
        return cookies

    def renew_web(self, credentials: Credentials) -> Credentials:
        """Exchange the QR-login tokens for current Web cookies and WPA headers."""
        session = requests.Session()
        session.cookies.update(self._web_cookies(credentials))
        self._wait()
        response = session.post(
            "https://weread.qq.com/web/login/renewal",
            json={"rq": "%2Fweb%2Fbook%2Fread", "ql": False},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*", "Origin": "https://weread.qq.com",
                "Referer": "https://weread.qq.com/",
            },
            timeout=self.timeout,
        )
        if response.status_code == 429:
            raise RiskControlError("微信读书网页版续期请求过于频繁")
        payload = self._json(response, "网页版凭证续期")
        code, message = _payload_error(payload)
        if code in {-2041, -2010} or response.status_code == 403:
            raise ArticleValidationError(f"网页版续期验证未通过: {code or response.status_code}")
        if not response.ok or not (payload.get("succ") is True or payload.get("succ") == 1):
            code, message = _payload_error(payload)
            raise AuthExpiredError(f"网页版凭证续期失败: {code or response.status_code} {message}")
        credentials.cookies = requests.utils.dict_from_cookiejar(session.cookies)
        credentials.wrTicket = str(response.headers.get("x-wr-ticket") or credentials.wrTicket)
        credentials.wrPa = str(response.headers.get("x-wrpa-0") or credentials.wrPa)
        credentials.updatedAt = int(time.time())
        return credentials

    @staticmethod
    def _parse_articles(payload: dict[str, Any]) -> list[Article]:
        result: list[Article] = []
        entries = payload.get("data") or payload.get("reviews") or payload.get("articles") or payload.get("chapters") or []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict): continue
            review = entry.get("review") if isinstance(entry.get("review"), dict) else entry
            nested = review.get("subReviews") if isinstance(review.get("subReviews"), list) else None
            candidates = nested or [review]
            for item in candidates:
                item = item.get("review") if isinstance(item, dict) and isinstance(item.get("review"), dict) else item
                if not isinstance(item, dict): continue
                info = item.get("mpInfo") if isinstance(item.get("mpInfo"), dict) else {}
                article_id = str(item.get("reviewId") or ""); title = str(item.get("title") or info.get("title") or "")
                if article_id and title:
                    result.append(Article(wechat_article_id(article_id), title, str(info.get("pic_url") or info.get("picUrl") or ""), int(info.get("time") or item.get("createTime") or review.get("createTime") or 0)))
        result.sort(key=lambda item: item.publish_time, reverse=True)
        return result

    def web_articles(self, credentials: Credentials, book_id: str, page: int, count: int = 20) -> tuple[list[Article], Credentials]:
        if not book_id.startswith("MP_WXS_") or not book_id[7:].isdigit(): raise WeReadError("公众号编号无效")
        # A missing optional ticket alone is not evidence of an expired session.
        session = requests.Session(); session.cookies.update(self._web_cookies(credentials))
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*", "Referer": "https://weread.qq.com/",
            "x-wr-ticket": credentials.wrTicket,
        }
        if credentials.wrPa: headers["x-wrpa-0"] = credentials.wrPa
        self._wait()
        response = session.get(
            "https://weread.qq.com/web/mp/articles",
            params={"bookId": book_id, "offset": max(0, (page - 1) * count), "count": count},
            headers=headers, timeout=self.timeout,
        )
        if response.status_code == 401: raise AuthExpiredError("网页版登录状态已失效")
        if response.status_code == 403: raise ArticleValidationError("微信读书拒绝本次文章访问: 403")
        if response.status_code == 429: raise RiskControlError("微信读书网页版请求过于频繁")
        payload = self._json(response, "网页版文章列表"); code, message = _payload_error(payload)
        if code == -2012: raise AuthExpiredError(f"网页版登录状态已失效: {message}")
        if code in {-2041, -2010}: raise ArticleValidationError(f"微信读书文章验证未通过: {code}")
        if code: raise WeReadError(f"微信读书网页版接口错误 {code}: {message}")
        credentials.cookies = requests.utils.dict_from_cookiejar(session.cookies)
        credentials.wrTicket = str(response.headers.get("x-wr-ticket") or credentials.wrTicket)
        credentials.wrPa = str(response.headers.get("x-wrpa-0") or credentials.wrPa)
        return self._parse_articles(payload), credentials

    def web_article_url(self, credentials: Credentials, book_id: str, article_id: str, include_content: bool = False) -> tuple[str, Credentials]:
        if not re.fullmatch(r'MP_WXS_[0-9]+', book_id):
            raise WeReadError('公众号编号无效')
        if article_id.startswith('MP_WXS_'):
            if not article_id.startswith(book_id + '_'):
                raise WeReadError('文章与公众号不匹配')
            article_id = article_id[len(book_id) + 1:]
        if not re.fullmatch(r'WR[A-Za-z0-9_~-]{23,1024}', article_id):
            raise WeReadError('不是有效的微信读书文章标识')
        session = requests.Session()
        session.cookies.update(self._web_cookies(credentials))
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/json',
                   'Referer': 'https://weread.qq.com/', 'x-wr-ticket': credentials.wrTicket}
        if credentials.wrPa:
            headers['x-wrpa-0'] = credentials.wrPa
        self._wait()
        response = session.get('https://weread.qq.com/web/mp/content',
                               params={'reviewId': book_id + '_' + article_id},
                               headers=headers, timeout=self.timeout, allow_redirects=False)
        if response.status_code == 401: raise AuthExpiredError('网页版登录状态已失效')
        if response.status_code == 403: raise ArticleValidationError('微信读书拒绝本次原文解析: 403')
        if response.status_code == 429: raise RiskControlError('微信读书原文解析请求过于频繁')
        if response.status_code != 200: raise WeReadError(f'原文解析上游响应异常: {response.status_code}')
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            code, message = _payload_error(payload)
            if code == -2012: raise AuthExpiredError('网页版登录状态已失效')
            if code in {-2041, -2010}: raise ArticleValidationError(f'原文解析验证未通过: {code}')
            if code: raise WeReadError(f'原文解析接口错误: {code}')
            source = payload.get('html', '')
        else:
            source = response.text if payload is None else ''
        if not isinstance(source, str): raise WeReadError('原文解析响应格式异常')
        url = original_url_from_html(source)
        credentials.cookies = requests.utils.dict_from_cookiejar(session.cookies)
        credentials.wrTicket = str(response.headers.get('x-wr-ticket') or credentials.wrTicket)
        credentials.wrPa = str(response.headers.get('x-wrpa-0') or credentials.wrPa)
        return ({'url': url, 'html': source} if include_content else url), credentials

    def _wait(self) -> None:
        with self._request_lock:
            remaining = self.min_interval - (time.monotonic() - self._last_request)
            if remaining > 0: time.sleep(remaining)
            self._last_request = time.monotonic()

    def articles(self, credentials: Credentials, book_id: str, page: int, count: int = 20) -> list[Article]:
        if not book_id.startswith("MP_WXS_") or not book_id[7:].isdigit(): raise WeReadError("公众号编号无效")
        params: dict[str, Any] = {"bookId": book_id, "count": count}
        if page <= 1: params["synckey"] = 0
        else: params["offset"] = (page - 1) * count
        self._wait()
        response = self.session.get(f"{WEREAD_BASE}/mp/chapters", params=params, headers={**VERSION_HEADERS, "vid": credentials.vid, "accessToken": credentials.accessToken}, timeout=self.timeout)
        if response.status_code in {401, 403}: raise AuthExpiredError("登录状态已失效")
        if response.status_code == 429: raise RiskControlError("微信读书请求过于频繁")
        payload = self._json(response, "文章列表"); code, message = _payload_error(payload)
        if code == -2012: raise AuthExpiredError(f"登录状态已失效: {message}")
        if code in {-2041, -2010}: raise RiskControlError(f"微信读书风控 {code}: {message}")
        if code: raise WeReadError(f"微信读书接口错误 {code}: {message}")
        return self._parse_articles(payload)
