"""
بات تلگرام سازمان — ارسال دسته‌بندی‌شده با ضدتکرار + دریافت فرمان‌های ساده.

فرمان‌ها (از آیپد، داخل تلگرام):
  /status                 وضعیت آخرین چرخه
  /signals                معاملات باز
  /close <ID> <TP|SL> [R] ثبت دستی نتیجه (ریشه‌یابی خودکار)
  /help
بدون TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID همه‌چیز بی‌صدا و بی‌خطا رد می‌شود.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Callable

import requests

API = "https://api.telegram.org/bot{token}/{method}"
SENT_KEEP = 2000


def _cfg() -> tuple[str | None, str | None]:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None, os.environ.get("TELEGRAM_CHAT_ID") or None


def enabled() -> bool:
    t, c = _cfg()
    return bool(t and c)


def _key(category: str, text: str) -> str:
    return category + ":" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Notifier:
    """ارسال با حافظهٔ ضدتکرار (sent_keys داخل حافظهٔ دائمی)."""

    def __init__(self, state: dict[str, Any] | None = None):
        self.state = state if state is not None else {}
        self.state.setdefault("sent_keys", [])
        self.state.setdefault("update_offset", 0)
        self.sent_now = 0

    def send(self, text: str, *, category: str = "general", dedupe_text: str | None = None) -> bool:
        token, chat = _cfg()
        if not token or not chat:
            return False
        key = _key(category, dedupe_text or text)
        if key in self.state["sent_keys"]:
            return False
        try:
            r = requests.post(
                API.format(token=token, method="sendMessage"),
                json={"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=20,
            )
            ok = bool(r.ok)
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            self.state["sent_keys"].append(key)
            self.state["sent_keys"] = self.state["sent_keys"][-SENT_KEEP:]
            self.sent_now += 1
        return ok

    def poll_commands(self, handlers: dict[str, Callable[[list[str]], str]]) -> int:
        """فرمان‌های تازه را می‌خواند و پاسخ می‌دهد. فقط از chat_id خودمان می‌پذیرد."""
        token, chat = _cfg()
        if not token or not chat:
            return 0
        try:
            r = requests.get(
                API.format(token=token, method="getUpdates"),
                params={"offset": int(self.state.get("update_offset", 0)) + 1, "timeout": 0, "allowed_updates": '["message"]'},
                timeout=20,
            )
            updates = r.json().get("result", []) if r.ok else []
        except Exception:  # noqa: BLE001
            return 0
        handled = 0
        for u in updates:
            self.state["update_offset"] = max(int(self.state.get("update_offset", 0)), int(u.get("update_id", 0)))
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != str(chat):
                continue
            text = (msg.get("text") or "").strip()
            if not text.startswith("/"):
                continue
            parts = text.split()
            cmd = parts[0].lower().split("@")[0]
            fn = handlers.get(cmd) or handlers.get("/help")
            if not fn:
                continue
            try:
                reply = fn(parts[1:])
            except Exception as exc:  # noqa: BLE001
                reply = f"خطا در اجرای فرمان: {exc}"
            try:
                requests.post(
                    API.format(token=token, method="sendMessage"),
                    json={"chat_id": chat, "text": reply[:4000], "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=20,
                )
            except Exception:  # noqa: BLE001
                pass
            handled += 1
        return handled


def fmt_decision(d: dict[str, Any]) -> str:
    targets = d.get("targets") or []
    tp1 = targets[0] if targets else None
    why = "\n".join(f"• {w}" for w in (d.get("why_fa") or [])[:4])
    votes = d.get("votes") or {}
    agree = [k for k, v in votes.items() if not v.get("silent") and v.get("direction") == d.get("direction")]
    return (
        f"<b>SIGNAL سازمان ققنوس</b> · {d.get('symbol')} · <b>{str(d.get('direction')).upper()}</b> @15m\n"
        f"شناسه: <code>{d.get('id')}</code> · رژیم: {d.get('regime')}\n"
        f"ورود: <code>{d.get('entry')}</code>\nاستاپ: <code>{d.get('stop')}</code>\n"
        f"تارگت۱: <code>{tp1}</code> · R:R={d.get('rr1')}\n"
        f"اهرم پیشنهادی: {d.get('leverage')} · اطمینان شورا: {d.get('confidence')}\n"
        f"موافق: {'، '.join(agree) or '—'}\n{why}\n"
        f"بستن دستی: <code>/close {d.get('id')} TP 1.5</code>"
    )


def fmt_learned(exp: dict[str, Any]) -> str:
    return f"<b>تجربهٔ تازه</b> · {exp.get('outcome')} ({exp.get('pnl_r')}R)\n{exp.get('lesson_fa')}"


def fmt_intel(item: dict[str, Any]) -> str:
    syms = "، ".join(item.get("symbols") or []) or "بازار"
    kind = item.get("kind_fa") or item.get("kind")
    return (
        f"<b>{kind}</b> · {syms} · اهمیت {item.get('importance')}/10\n"
        f"{item.get('title')}\n"
        f"{item.get('summary_fa') or ''}\n{item.get('url') or ''}"
    ).strip()


def fmt_incident(inc: dict[str, Any]) -> str:
    return (
        f"<b>عیب‌یابی</b> · {inc.get('severity', '').upper()} · {inc.get('kind_fa') or inc.get('kind')}\n"
        f"{inc.get('summary_fa')}\n"
        f"اقدام: {inc.get('action_fa') or '—'}\n"
        f"{inc.get('url') or ''}"
    ).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
