from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup


class ArticleIdentityError(RuntimeError):
    pass


@dataclass
class ArticleIdentity:
    book_id: str
    title: str = ""
    account_name: str = ""
    cover: str = ""
    intro: str = ""
    update_time: int = 0


def _decode_biz(value: str) -> str:
    value = unquote(value).strip()
    value += "=" * ((4 - len(value) % 4) % 4)
    try:
        result = base64.b64decode(value, validate=False).decode().strip()
    except Exception as exc:
        raise ArticleIdentityError("公众号链接中的 __biz 无法解析") from exc
    if not result.isdigit():
        raise ArticleIdentityError("公众号链接中的 __biz 不是有效编号")
    return result


def _query_biz(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return str((query.get("__biz") or query.get("biz") or [""])[0]).strip()


def _js_clean(value: str) -> str:
    return html.unescape(value).replace(r"\/", "/").replace(r"\x26", "&").replace(r"\u0026", "&")


def resolve_article_identity(url: str, timeout: float = 20.0) -> ArticleIdentity:
    url = str(url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != "mp.weixin.qq.com":
        raise ArticleIdentityError("请粘贴 mp.weixin.qq.com 的公众号文章链接")
    if not parsed.path.startswith("/s"):
        raise ArticleIdentityError("当前链接不是标准公众号文章链接")

    direct = _query_biz(url)
    if direct:
        _decode_biz(direct)  # Validate the query identity; still read official profile metadata.

    response = requests.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 MicroMessenger/8.0", "Accept-Language": "zh-CN,zh;q=0.9"},
    )
    if response.status_code == 429:
        raise ArticleIdentityError("微信文章访问过于频繁，请稍后重试")
    response.raise_for_status()
    source = response.text
    if any(x in source for x in ("当前环境异常", "完成验证后即可继续访问", "访问过于频繁")):
        raise ArticleIdentityError("微信文章要求人工验证，请稍后重试")

    candidates = [direct, _query_biz(response.url)]
    for pattern in (
        r"(?:window\.)?biz\s*=\s*['\"]([^'\"]+)['\"]",
        r"var\s+biz\s*=\s*['\"]([^'\"]+)['\"]",
        r"__biz\s*=\s*['\"]([^'\"]+)['\"]",
    ):
        match = re.search(pattern, source, re.I)
        if match:
            candidates.append(_js_clean(match.group(1)))
    for match in re.finditer(r"https?://mp\.weixin\.qq\.com/s\?[^\"'<>\s]+", source, re.I):
        candidates.append(_query_biz(_js_clean(match.group(0))))

    bid = ""
    for candidate in candidates:
        if not candidate:
            continue
        try:
            bid = _decode_biz(candidate)
            break
        except ArticleIdentityError:
            pass
    if not bid:
        raise ArticleIdentityError("文章页面中没有识别到公众号编号；请换一篇该公众号的普通图文")

    soup = BeautifulSoup(source, "html.parser")
    def meta(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return str(tag.get("content") or "").strip() if tag else ""

    title = meta("og:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    # Article author and article cover are not the public account profile.
    account = ""
    node = soup.select_one("#js_name, #js_wx_follow_nickname, .profile_nickname")
    if node:
        account = node.get_text(" ", strip=True)
    if not account:
        for pattern in (
            r"\bvar\s+nickname\s*=\s*(?:htmlDecode\()?['\"]([^'\"]+)['\"]",
            r"\bnick_name\s*:\s*['\"]([^'\"]+)['\"]",
        ):
            match = re.search(pattern, source)
            if match:
                account = _js_clean(match.group(1)).strip()
                break
    cover = ""
    for pattern in (
        r"\bvar\s+round_head_img\s*=\s*['\"]([^'\"]+)['\"]",
        r"\bround_head_img\s*:\s*['\"]([^'\"]+)['\"]",
    ):
        match = re.search(pattern, source)
        if match:
            candidate = _js_clean(match.group(1))
            parsed_cover = urlparse(candidate)
            if parsed_cover.scheme in {"http", "https"} and (parsed_cover.hostname or "").lower().endswith((".qpic.cn", ".qlogo.cn")):
                cover = candidate.replace("http://", "https://", 1)
                break
    if not account:
        raise ArticleIdentityError("未识别到正式公众号名称，请换一篇该账号的普通图文；不会使用文章作者代替")
    timestamp = 0
    match = re.search(r"(?:oriCreateTime|publish_time|ct)\s*[:=]\s*['\"]?(\d{10})", source)
    if match:
        timestamp = int(match.group(1))
    return ArticleIdentity(
        book_id=f"MP_WXS_{bid}", title=title, account_name=account,
        cover=cover, intro="", update_time=timestamp,
    )

