#!/usr/bin/env python3
"""چرخهٔ عیب‌یابی (هر ۱۵ دقیقه): سلامت → تشخیص → ترمیم → هشدار + فرمان‌های تلگرام."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from phoenix import watchdog  # noqa: E402
from phoenix.notify import Notifier, fmt_incident  # noqa: E402
from phoenix.org.memory import Memory  # noqa: E402


def _commands(memory: Memory, health: dict) -> dict:
    def status(_: list[str]) -> str:
        c = memory.data.get("counters", {})
        checks = "\n".join(f"{'✅' if k['ok'] else '⚠️'} {k['fa']}: {k['value']}" for k in health.get("checks", []))
        return (f"<b>وضعیت سازمان ققنوس</b>\n{checks}\n"
                f"سیگنال‌ها: {c.get('signals', 0)} · بسته: {c.get('closed', 0)} (TP {c.get('tp', 0)} / SL {c.get('sl', 0)})\n"
                f"معاملات باز: {len(memory.open_decisions())} · رخداد باز: {len(health.get('open_incidents', []))}")

    def signals(_: list[str]) -> str:
        od = memory.open_decisions()
        if not od:
            return "معاملهٔ بازی نیست."
        return "\n".join(f"<code>{d['id']}</code> {d['symbol']} {d['direction']} ورود {d['entry']} استاپ {d['stop']}" for d in od)

    def close(args: list[str]) -> str:
        if len(args) < 2:
            return "فرمت: /close ID TP|SL [R]"
        pend = memory.data["notify_watchdog"].setdefault("pending_closes", [])
        spec = ":".join([args[0], args[1].upper()] + ([args[2]] if len(args) > 2 else []))
        if spec not in pend:
            pend.append(spec)
        return f"ثبت شد؛ در چرخهٔ بعدی اسکن اعمال و ریشه‌یابی می‌شود: <code>{spec}</code>"

    def help_(_: list[str]) -> str:
        return "/status · /signals · /close ID TP|SL [R] · /help"

    return {"/status": status, "/signals": signals, "/close": close, "/help": help_, "/start": help_}


def main() -> int:
    memory = Memory()
    memory.data.setdefault("notify_watchdog", {})
    gh = watchdog.GitHub(None, None)
    health = watchdog.run(gh, memory.data, os.environ.get("PHOENIX_PAGES_URL") or None)

    # فرمان‌های /close که اسکن قبلاً اعمال کرده (تصمیم دیگر باز نیست) از صف حذف می‌شوند
    open_ids = {d["id"] for d in memory.open_decisions()}
    nw = memory.data["notify_watchdog"]
    nw["pending_closes"] = [s for s in nw.get("pending_closes", []) if s.split(":")[0] in open_ids]

    notifier = Notifier(memory.data["notify_watchdog"])
    for inc in health["new_incidents"]:
        if inc["severity"] in ("medium", "high"):
            notifier.send(fmt_incident(inc), category="incident", dedupe_text=inc["id"])
    handled = notifier.poll_commands(_commands(memory, health))

    memory.data["health"] = {k: v for k, v in health.items() if k != "new_incidents"}
    memory.save_only("incidents", "notify_watchdog", "health")
    print(json.dumps({"checks": [(c["fa"], c["ok"], c["value"]) for c in health["checks"]],
                      "problems": [p["kind"] for p in health["problems"]],
                      "new_incidents": [(i["kind"], i["cause"], i["action"]) for i in health["new_incidents"]],
                      "open_incidents": len(health["open_incidents"]), "telegram_sent": notifier.sent_now,
                      "commands_handled": handled, "brain": health.get("brain")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
