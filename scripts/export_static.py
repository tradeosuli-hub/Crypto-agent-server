#!/usr/bin/env python3
"""
چرخهٔ اسکن + سازمان → خروجی استاتیک برای GitHub Pages (آیپد، بدون سرور، بدون هزینه).

می‌نویسد (site/data/):
  latest.json    آخرین اسکن + رأی شورا روی هر ارز
  org.json       تابلوی سازمان، تصمیم‌ها، تجربه‌ها، ممیزی‌ها
  history.json   خلاصهٔ چرخه‌های اخیر
  signals.json   دفترچهٔ سیگنال‌های نهایی
  intel.json     خبر/رویداد/سوشال (از ایجنت اطلاعات، فقط کپی)
  health.json    سلامت + رخدادهای عیب‌یابی (از واچ‌داگ، فقط کپی)

حافظهٔ دائمی: PHOENIX_MEMORY_DIR (در Actions از شاخهٔ phoenix-memory بازیابی/ذخیره می‌شود).
این Workflow فقط فایل‌های سازمان و notify_scan را می‌نویسد.
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

from phoenix.market_data import klines  # noqa: E402
from phoenix.notify import Notifier, fmt_decision, fmt_learned  # noqa: E402
from phoenix.org.memory import Memory  # noqa: E402
from phoenix.org.office import run_org_cycle  # noqa: E402
from phoenix.org.outcomes import manual_close  # noqa: E402
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


def _apply_pending_closes(memory: Memory) -> list[dict[str, Any]]:
    """فرمان‌های /close که واچ‌داگ از تلگرام گرفته (و ورودی دستی Workflow) — این‌جا اعمال و ریشه‌یابی می‌شوند."""
    specs: list[str] = list((memory.data.get("notify_watchdog") or {}).get("pending_closes") or [])
    manual = os.environ.get("PHOENIX_CLOSE", "").strip()
    if manual:
        specs.append(manual)
    learned = []
    for spec in specs:
        parts = spec.split(":")
        if len(parts) < 2:
            continue
        exp = manual_close(memory, parts[0].strip(), parts[1].strip(),
                           float(parts[2]) if len(parts) > 2 and parts[2].strip() else None)
        if exp:
            exp["via"] = "telegram" if spec != manual else "workflow_input"
            learned.append(exp)
    return learned


def main() -> int:
    top = _env_int("PHOENIX_TOP", 30)
    workers = _env_int("PHOENIX_WORKERS", 4)
    symbols_env = os.environ.get("PHOENIX_SYMBOLS", "").strip()
    symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()] or None

    panel = PhoenixPanel(symbols=symbols, top_n=None if symbols else top, workers=workers)
    print(f"ققنوس · چرخهٔ اسکن + سازمان · {len(panel.symbols)} ارز · متد {SPEC['version']}")
    summary = panel.run_cycle()
    light = compact_summary(summary) or {}
    now = datetime.now(timezone.utc).isoformat()
    light["generated_at"] = now
    light["source"] = "github_actions"
    light["gates"] = gates()
    light["note_fa"] = "تولیدشده توسط GitHub Actions — بدون سرور، بدون هزینه. بدون SETUP روی ۱۵دقیقه سیگنالی نیست."

    os.makedirs(SITE_DATA, exist_ok=True)

    history = _load_previous("history.json") or []
    if not isinstance(history, list):
        history = []
    history.append({
        "ts": now, "scanned": light.get("symbols_scanned"), "setups": light.get("setups"), "watches": light.get("watches"),
        "flats": light.get("flats"), "blinds": light.get("blinds"), "dominance": (light.get("dominance") or {}).get("bias"),
    })
    history = history[-HISTORY_KEEP:]

    # ---- سازمان ----
    memory = Memory()
    memory.data.setdefault("notify_scan", {})
    learned_manual = _apply_pending_closes(memory)
    org = run_org_cycle(summary.get("results") or [], memory, fetch_klines=klines)
    org["learned_now"] = learned_manual + org["learned_now"]
    memory.save()

    ledger = _load_previous("signals.json") or []
    if not isinstance(ledger, list):
        ledger = []
    seen = {s.get("id") for s in ledger}
    new_decisions = [d for d in org["new_decisions"] if d and d.get("id") not in seen]
    for d in new_decisions:
        ledger.append({**d, "first_seen": now})
    ledger = ledger[-SIGNALS_KEEP:]

    notifier = Notifier(memory.data["notify_scan"])
    for d in new_decisions:
        notifier.send(fmt_decision(d), category="signal", dedupe_text=d["id"])
    for exp in org["learned_now"]:
        notifier.send(fmt_learned(exp), category="learned", dedupe_text=str(exp.get("decision_id")) + str(exp.get("outcome")))
    memory.save_only("notify_scan")

    light["telegram_sent"] = notifier.sent_now
    light["new_signals"] = len(new_decisions)
    light["org"] = {
        "signals": len(org["signals"]),
        "vetoes": sum(1 for r in org["rows"] if r.get("final") in ("VETO", "HOLD")),
        "open_decisions": len(memory.open_decisions()),
        "learned_now": len(org["learned_now"]),
        "counters": memory.data["counters"],
    }
    council = {r["symbol"]: r for r in org["rows"]}
    for r in light.get("results") or []:
        c = council.get(r.get("symbol"))
        if c:
            r["council"] = {k: c.get(k) for k in ("final", "direction", "strength", "confidence", "vetoes", "gate_fa", "regime", "decision_id", "votes")}

    # کپی خروجی ایجنت‌های دیگر برای تب‌ها (فقط خواندن)
    intel = memory.data.get("intel") or {}
    health = {**(memory.data.get("health") or {}), "incidents": (memory.data.get("incidents") or [])[-60:]}
    light["intel_updated_at"] = intel.get("updated_at")
    light["market"] = intel.get("market")

    outputs = (("latest.json", light), ("history.json", history), ("signals.json", ledger), ("org.json", org),
               ("intel.json", intel), ("health.json", health))
    for name, payload in outputs:
        with open(os.path.join(SITE_DATA, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str)

    print(
        f"SETUP {light.get('setups')} · WATCH {light.get('watches')} · FLAT {light.get('flats')} · BLIND {light.get('blinds')} · "
        f"SIGNAL سازمان {len(org['signals'])} · وتو/نگه‌دار {light['org']['vetoes']} · تصمیم باز {light['org']['open_decisions']} · "
        f"تجربهٔ تازه {len(org['learned_now'])} · تلگرام {notifier.sent_now} · اطلاعات {intel.get('updated_at') or 'ندارد'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
