#!/usr/bin/env python3
"""
خروجی استاتیک برای GitHub Pages (آیپد، بدون سرور، بدون هزینه).

یک چرخهٔ کامل ققنوس را اجرا می‌کند و سه فایل سبک می‌نویسد:
  site/data/latest.json   — آخرین اسکن (همان چیزی که داشبورد می‌خواند)
  site/data/history.json  — خلاصهٔ چرخه‌های اخیر (برای نوار روند)
  site/data/signals.json  — دفترچهٔ سیگنال‌های SETUP (بدون تکرار)

اگر PHOENIX_PAGES_URL ست شده باشد، history/signals قبلی از Pages دانلود و ادغام می‌شود
تا حافظه بین اجراهای Actions حفظ بماند. اگر TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID
ست باشند، سیگنال‌های تازه به تلگرام می‌روند.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from phoenix.panel import PhoenixPanel, compact_summary  # noqa: E402
from strategies.hamid_method import SPEC, gates  # noqa: E402

SITE_DATA = os.path.join(ROOT, "site", "data")
HISTORY_KEEP = 288  # ~۴۸ ساعت با چرخهٔ ۱۰ دقیقه
SIGNALS_KEEP = 300


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _load_previous(name: str) -> Any:
    """اول از Pages (حافظهٔ بین اجراها)، بعد از دیسک."""
    base = os.environ.get("PHOENIX_PAGES_URL", "").rstrip("/")
    if base:
        try:
            r = requests.get(f"{base}/data/{name}", timeout=15)
            if r.ok:
                return r.json()
        except Exception:  # noqa: BLE001
            pass
    path = os.path.join(SITE_DATA, name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return None
    return None


def _signal_key(sig: dict[str, Any]) -> str:
    g = sig.get("geometry") or {}
    return f"{sig.get('symbol')}|{sig.get('direction')}|{g.get('entry')}|{g.get('stop')}"


def _telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        return bool(r.ok)
    except Exception:  # noqa: BLE001
        return False


def _fmt_signal_fa(sig: dict[str, Any]) -> str:
    g = sig.get("geometry") or {}
    targets = g.get("targets") or []
    tp1 = targets[0] if targets else None
    why = "\n".join(f"• {w}" for w in (sig.get("why_fa") or [])[:4])
    return (
        f"<b>SETUP ققنوس</b> · {sig.get('symbol')} · <b>{str(sig.get('direction')).upper()}</b> @15m\n"
        f"ورود: <code>{g.get('entry')}</code>\n"
        f"استاپ: <code>{g.get('stop')}</code>\n"
        f"تارگت۱: <code>{tp1}</code> · R:R={g.get('rr1')}\n"
        f"اهرم پیشنهادی: {g.get('leverage')}\n{why}"
    )


def main() -> int:
    top = _env_int("PHOENIX_TOP", 30)
    workers = _env_int("PHOENIX_WORKERS", 4)
    symbols_env = os.environ.get("PHOENIX_SYMBOLS", "").strip()
    symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()] or None

    panel = PhoenixPanel(symbols=symbols, top_n=None if symbols else top, workers=workers)
    print(f"ققنوس · خروجی استاتیک · {len(panel.symbols)} ارز · متد {SPEC['version']}")
    summary = panel.run_cycle()
    light = compact_summary(summary) or {}
    now = datetime.now(timezone.utc).isoformat()
    light["generated_at"] = now
    light["source"] = "github_actions"
    light["gates"] = gates()
    light["note_fa"] = "تولیدشده توسط GitHub Actions — بدون سرور، بدون هزینه. بدون SETUP روی ۱۵دقیقه سیگنالی نیست."

    os.makedirs(SITE_DATA, exist_ok=True)

    # history
    history = _load_previous("history.json") or []
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "ts": now,
            "scanned": light.get("symbols_scanned"),
            "setups": light.get("setups"),
            "watches": light.get("watches"),
            "flats": light.get("flats"),
            "blinds": light.get("blinds"),
            "dominance": (light.get("dominance") or {}).get("bias"),
        }
    )
    history = history[-HISTORY_KEEP:]

    # signals ledger (dedupe)
    ledger = _load_previous("signals.json") or []
    if not isinstance(ledger, list):
        ledger = []
    seen = {_signal_key(s) for s in ledger}
    new_signals: list[dict[str, Any]] = []
    for sig in light.get("signals") or []:
        key = _signal_key(sig)
        if key in seen:
            continue
        entry = {**sig, "first_seen": now, "key": key}
        ledger.append(entry)
        new_signals.append(entry)
        seen.add(key)
    ledger = ledger[-SIGNALS_KEEP:]

    sent = 0
    for sig in new_signals:
        if _telegram(_fmt_signal_fa(sig)):
            sent += 1
    light["telegram_sent"] = sent
    light["new_signals"] = len(new_signals)

    for name, payload in (("latest.json", light), ("history.json", history), ("signals.json", ledger)):
        with open(os.path.join(SITE_DATA, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str)

    print(
        f"SETUP {light.get('setups')} · WATCH {light.get('watches')} · FLAT {light.get('flats')} · "
        f"BLIND {light.get('blinds')} · سیگنال تازه {len(new_signals)} · تلگرام {sent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
