#!/usr/bin/env python3
"""چرخهٔ ایجنت اطلاعات (هر ۳۰ دقیقه در Actions): خبر/رویداد/سوشال → intel.json → تلگرام برای مهم‌ها."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from phoenix.intel import agent  # noqa: E402
from phoenix.market_data import top_usdt_by_volume  # noqa: E402
from phoenix.notify import Notifier, fmt_intel  # noqa: E402
from phoenix.org.memory import Memory  # noqa: E402


def main() -> int:
    memory = Memory()
    memory.data.setdefault("intel", {})
    memory.data.setdefault("notify_intel", {})
    try:
        watched = top_usdt_by_volume(int(os.environ.get("PHOENIX_TOP", "30")))
    except Exception:  # noqa: BLE001
        watched = []
    known = {s[:-4] for s in watched} | {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "TON", "TRX",
                                         "LTC", "SUI", "APT", "NEAR", "ARB", "OP", "PEPE", "SHIB", "POL"}
    intel = agent.collect(known, set(watched), memory.data.get("intel") or None)

    # سوشال (فقط با Grok) — برای ۸ ارز برتر
    social = agent.social_pulse(watched[:8])
    if social:
        intel["social"] = {**(intel.get("social") or {}), **social}

    notifier = Notifier(memory.data["notify_intel"])
    for it in agent.important_unnotified(intel):
        if notifier.send(fmt_intel(it), category="intel", dedupe_text=it["id"]):
            it["notified"] = True

    memory.data["intel"] = intel
    memory.save_only("intel", "notify_intel")
    print(f"intel: {len(intel['items'])} آیتم · منابع {intel['sources_ok']} · ارزهای دارای رویداد {len(intel['symbols'])} · "
          f"سوشال {len(intel.get('social') or {})} · تلگرام {notifier.sent_now} · مغز {intel.get('brain')}")
    print(json.dumps({k: v for k, v in intel["market"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
