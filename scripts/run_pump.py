#!/usr/bin/env python3
"""چرخهٔ ایجنت پامپ (هر ~۱۵ دقیقه در Actions): جمع‌آوری → تشخیص ≥۸٪/۱۵m → شباهت‌یابی → یادگیری → تلگرام → حافظه."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from phoenix.notify import Notifier, fmt_pump  # noqa: E402
from phoenix.org.memory import Memory  # noqa: E402
from phoenix.pump import agent  # noqa: E402


def main() -> int:
    memory = Memory()
    state = memory.data.setdefault("pump_state", {})
    events = memory.data.setdefault("pumps", [])
    memory.data.setdefault("notify_pump", {})
    if not isinstance(events, list):
        events = memory.data["pumps"] = []

    res = agent.run_cycle(state, events, memory.data.get("intel") or None)

    notifier = Notifier(memory.data["notify_pump"])
    for ev in res["new_events"]:
        if notifier.send(fmt_pump(ev), category="pump", dedupe_text=ev["id"]):
            ev["notified"] = True

    memory.save_only("pumps", "pump_state", "notify_pump")
    print(f"pump: منابع {res['sources_ok']} · جهان {state.get('universe')} · پامپ تازه {len(res['new_events'])} · "
          f"پیش‌پامپ {len(res['watch'])} · پیگیری تازه {res['new_followups']} · ۲۴h {res['events_24h']} · "
          f"تلگرام {notifier.sent_now} · مغز {state.get('brain')} · آستانه {state['params']['threshold_pct']}")
    for ev in res["new_events"]:
        print(json.dumps({k: ev.get(k) for k in ("symbol", "change_15m", "vol_spike", "mcap_tier", "attention_fa", "factors_fa", "pattern_fa")},
                         ensure_ascii=False))
    if res.get("review"):
        print("اختیار ۵٪:", res["review"]["decision_fa"], "—", res["review"]["reason_fa"])
    print("نظر ایجنت:", state.get("opinion_fa"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
