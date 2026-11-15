"""
«مغز» اختیاری ایجنت‌ها — یک مدل زبانی برای مواقع اضطراری و تحلیل متن.

اولویت: XAI_API_KEY (Grok، با جست‌وجوی زندهٔ X) → OPENAI_API_KEY → بدون مغز (fallback قاعده‌محور).
همهٔ فراخوانی‌ها محدود، با تایم‌اوت، و بدون استثنا به بیرون: اگر نشد، None برمی‌گردد.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

XAI_URL = "https://api.x.ai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4-fast")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def provider() -> str | None:
    if os.environ.get("XAI_API_KEY"):
        return "xai"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def available() -> bool:
    return provider() is not None


def _post(url: str, key: str, payload: dict[str, Any], timeout: float) -> str | None:
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json=payload, timeout=timeout)
        if not r.ok:
            return None
        data = r.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception:  # noqa: BLE001
        return None


def ask(system: str, user: str, *, json_mode: bool = False, live_x_search: bool = False,
        max_tokens: int = 900, timeout: float = 60.0) -> str | None:
    """یک پرسش کوتاه. live_x_search فقط با Grok معنی دارد (جست‌وجوی X و وب)."""
    p = provider()
    if p is None:
        return None
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if p == "xai":
        payload: dict[str, Any] = {"model": XAI_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
        if live_x_search:
            payload["search_parameters"] = {"mode": "on", "sources": [{"type": "x"}, {"type": "web"}], "max_search_results": 15,
                                            "return_citations": True}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return _post(XAI_URL, os.environ["XAI_API_KEY"], payload, timeout)
    payload = {"model": OPENAI_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return _post(OPENAI_URL, os.environ["OPENAI_API_KEY"], payload, timeout)


def ask_json(system: str, user: str, **kw: Any) -> dict[str, Any] | None:
    raw = ask(system, user, json_mode=True, **kw)
    if not raw:
        return None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        return json.loads(raw[start:end + 1]) if start >= 0 else None
    except Exception:  # noqa: BLE001
        return None
