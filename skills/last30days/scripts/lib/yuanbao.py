"""元宝搜索（腾讯云联网搜索 API, wsa.SearchPro）数据源。

鉴权使用腾讯云 TC3-HMAC-SHA256 签名，仅依赖标准库，不需要安装腾讯云 SDK。
密钥从配置读取（TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY，
可选 TENCENTCLOUD_TOKEN），不会写入代码或日志。

返回的每条结果统一成与其他数据源一致的 dict，字段见 ``parse_pages``。
"""

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from . import dates, http, relevance

HOST = "wsa.tencentcloudapi.com"
SERVICE = "wsa"
ACTION = "SearchPro"
VERSION = "2025-05-08"
ENDPOINT = f"https://{HOST}/"
ALGORITHM = "TC3-HMAC-SHA256"
CONTENT_TYPE = "application/json; charset=utf-8"

_LIMIT_BY_DEPTH = {"quick": 10, "default": 20, "deep": 30}
_VALID_CNT = (10, 20, 30, 40, 50)


class YuanbaoError(Exception):
    """元宝搜索接口返回错误（含腾讯云错误码）。"""

    def __init__(self, code: str, message: str, request_id: str = ""):
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code
        self.message = message
        self.request_id = request_id


# ---------------------------------------------------------------------------
# TC3 签名
# ---------------------------------------------------------------------------

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign_request(
    secret_id: str,
    secret_key: str,
    payload: bytes,
    timestamp: int,
    host: str = HOST,
    service: str = SERVICE,
    action: str = ACTION,
    content_type: str = CONTENT_TYPE,
) -> str:
    """返回 ``Authorization`` 头的值（TC3-HMAC-SHA256）。"""
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    signed_headers = "content-type;host;x-tc-action"
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    canonical_request = "\n".join([
        "POST", "/", "", canonical_headers, signed_headers, _sha256_hex(payload),
    ])
    scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join([
        ALGORITHM, str(timestamp), scope, _sha256_hex(canonical_request.encode("utf-8")),
    ])
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"{ALGORITHM} Credential={secret_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


# ---------------------------------------------------------------------------
# 调用
# ---------------------------------------------------------------------------

def _post(payload: Dict[str, Any], secret_id: str, secret_key: str, token: Optional[str],
          timeout: int, retries: int) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = int(time.time())
    headers = {
        "Authorization": sign_request(secret_id, secret_key, body, ts),
        "Content-Type": CONTENT_TYPE,
        "Host": HOST,
        "X-TC-Action": ACTION,
        "X-TC-Timestamp": str(ts),
        "X-TC-Version": VERSION,
    }
    if token:
        headers["X-TC-Token"] = token
    data = http.request("POST", ENDPOINT, headers=headers, data=body, timeout=timeout, retries=retries)
    response = data.get("Response") if isinstance(data, dict) else None
    if not isinstance(response, dict):
        raise YuanbaoError("BadResponse", "元宝搜索返回了无法识别的响应")
    err = response.get("Error")
    if err:
        raise YuanbaoError(str(err.get("Code", "")), str(err.get("Message", "")), str(response.get("RequestId", "")))
    return response


def search_pro(
    query: str,
    secret_id: str,
    secret_key: str,
    token: Optional[str] = None,
    mode: Optional[int] = None,
    cnt: Optional[int] = None,
    site: Optional[str] = None,
    industry: Optional[str] = None,
    freshness: Optional[str] = None,
    timeout: int = 20,
    retries: int = 2,
) -> Dict[str, Any]:
    """调用 SearchPro，返回 ``Response`` 字典。

    极速版不支持 Mode / Cnt / Industry；遇到参数错误时自动退回只带 Query
    （和 Freshness、Site）重试，保证低版本账号也能出结果。
    """
    payload: Dict[str, Any] = {"Query": query}
    if mode is not None:
        payload["Mode"] = int(mode)
    if cnt is not None:
        payload["Cnt"] = int(cnt) if int(cnt) in _VALID_CNT else 10
    if site:
        payload["Site"] = site
    if industry:
        payload["Industry"] = industry
    if freshness:
        payload["Freshness"] = freshness
    try:
        return _post(payload, secret_id, secret_key, token, timeout, retries)
    except YuanbaoError as exc:
        extras = {"Mode", "Cnt", "Industry"} & set(payload)
        if exc.code.endswith("InvalidParameter") and extras:
            for key in extras:
                payload.pop(key)
            return _post(payload, secret_id, secret_key, token, timeout, retries)
        raise


# ---------------------------------------------------------------------------
# 结果解析
# ---------------------------------------------------------------------------

def normalize_date(value: Any) -> Optional[str]:
    """``2025/02/26 09:37:00`` / ``2025-02-26`` -> ``2025-02-26``。"""
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-")[:10]
    return text if dates.parse_date(text) else None


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def parse_pages(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 ``Pages``（每项是 JSON 字符串）解析成统一的结果字典。"""
    items: List[Dict[str, Any]] = []
    for raw in response.get("Pages") or []:
        try:
            page = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        if not isinstance(page, dict):
            continue
        url = str(page.get("url") or "").strip()
        title = str(page.get("title") or "").strip()
        if not url or not title:
            continue
        date_value = normalize_date(page.get("date"))
        snippet = str(page.get("passage") or page.get("content") or "").strip()
        authority = page.get("authority_level")
        items.append({
            "title": title,
            "snippet": snippet[:500],
            "url": url,
            "source_domain": str(page.get("site") or "").strip() or _domain(url),
            "date": date_value,
            "date_confidence": "high" if date_value else "low",
            "authority": authority if isinstance(authority, int) else None,
            "api_score": page.get("score") if isinstance(page.get("score"), (int, float)) else None,
            "source_tag": "元宝搜索",
            "source": "yuanbao-api",
        })
    return items


def _freshness(from_date: str, to_date: str) -> Optional[str]:
    try:
        span = (datetime.strptime(to_date, "%Y-%m-%d") - datetime.strptime(from_date, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None
    span += 1
    return f"d{min(max(span, 1), 30)}"


def search_yuanbao(
    topic: str,
    from_date: str,
    to_date: str,
    depth: str = "default",
    secret_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """研究管线里的元宝搜索源（与 baidu 等并列）。"""
    if not (secret_id and secret_key):
        raise http.HTTPError("未配置 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY，已跳过元宝搜索")
    limit = _LIMIT_BY_DEPTH.get(depth, 20)
    try:
        response = search_pro(
            topic, secret_id, secret_key, token=token, cnt=limit,
            freshness=_freshness(from_date, to_date),
        )
    except YuanbaoError as exc:
        sys.stderr.write(f"[元宝搜索] 调用失败: {exc}\n")
        raise http.HTTPError(f"元宝搜索调用失败: {exc}")
    items = parse_pages(response)
    for i, item in enumerate(items[:limit]):
        rel = relevance.token_overlap_relevance(topic, f"{item['title']} {item['snippet']}")
        item["relevance"] = rel
        item["why_relevant"] = f"元宝搜索：{item['title'][:50]}"
        item["id"] = f"YB{i + 1}"
    return items[:limit]
