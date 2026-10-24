"""OpenAI 兼容的大模型客户端（默认 DeepSeek），仅依赖标准库。

只负责「拆题」和「依据证据下结论」，不使用模型自带的联网能力：
证据必须来自元宝搜索，这样作品才满足「去掉元宝搜索就转不起来」。

配置（从 ``config`` 读取，不写入 ``os.environ``，不记录日志）：
    DEEPSEEK_API_KEY 或 LLM_API_KEY   密钥
    LLM_BASE_URL                      默认 https://api.deepseek.com
    LLM_MODEL                         默认 deepseek-flash
"""

import json
import re
from typing import Any, Dict, List, Optional

from . import http

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class LLMError(Exception):
    """模型调用失败或返回内容无法解析。"""


def resolve_settings(config: Dict[str, Any]) -> Dict[str, str]:
    key = config.get("LLM_API_KEY") or config.get("DEEPSEEK_API_KEY") or ""
    return {
        "api_key": key,
        "base_url": (config.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "model": config.get("LLM_MODEL") or DEFAULT_MODEL,
    }


def is_configured(config: Dict[str, Any]) -> bool:
    return bool(resolve_settings(config)["api_key"])


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> Dict[str, Any]:
    """从模型输出里取出 JSON 对象（容忍代码块围栏和前后多余文字）。"""
    cleaned = _FENCE_RE.sub("", (text or "").strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("模型没有返回 JSON")
        try:
            data = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型返回的 JSON 无法解析: {exc}")
    if not isinstance(data, dict):
        raise LLMError("模型返回的 JSON 不是对象")
    return data


def chat(
    config: Dict[str, Any],
    messages: List[Dict[str, str]],
    json_mode: bool = True,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> str:
    """调用 chat/completions，返回助手文本。"""
    settings = resolve_settings(config)
    if not settings["api_key"]:
        raise LLMError("未配置 DEEPSEEK_API_KEY（或 LLM_API_KEY），无法调用大模型")
    payload: Dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        # 关闭思考模式：DeepSeek 在思考模式下忽略 temperature，结果每次都会变。
        # 结论只依据证据，用 temperature 0 换稳定性。
        "thinking": {"type": "disabled"},
        "temperature": 0,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        data = http.post(
            f"{settings['base_url']}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {settings['api_key']}"},
            timeout=timeout,
            retries=2,
        )
    except http.HTTPError as exc:
        raise LLMError(f"大模型调用失败: {exc}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("大模型返回了无法识别的响应")
    return content or ""


def chat_json(
    config: Dict[str, Any],
    system: str,
    user: str,
    max_tokens: int = 2000,
    timeout: int = 60,
    attempts: int = 3,
) -> Dict[str, Any]:
    """要求模型输出 JSON；空内容或解析失败时重试，最终仍失败则抛 LLMError。

    提示词里必须出现 "json" 字样（DeepSeek JSON 模式的要求），调用方的 system
    提示词需包含期望的 JSON 结构示例。
    """
    last: Optional[Exception] = None
    for _ in range(max(1, attempts)):
        try:
            text = chat(
                config,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                json_mode=True,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return parse_json_object(text)
        except LLMError as exc:
            last = exc
    raise LLMError(str(last))
