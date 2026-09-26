"""پنل سیگنال‌دهی ققنوس — اسکن همهٔ ارزها با قوانین یکسان متد حمید v3."""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from phoenix.ghoghnoos import confirm, evaluate_symbol  # noqa: E402
from phoenix.market_data import (  # noqa: E402
    fetch_dominance_proxy,
    fetch_multi_tf,
    list_usdt_perpetuals,
    top_usdt_by_volume,
)

ARTIFACTS = os.environ.get("PHOENIX_ARTIFACTS", "/opt/cursor/artifacts")


class PhoenixPanel:
    """چرخهٔ پایش: ققنوس اول، بعد نگهبانان (اختیاری)، بعد حکم نهایی."""

    def __init__(
        self,
        symbols: list[str] | None = None,
        top_n: int | None = 40,
        workers: int = 4,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.top_n = top_n
        self.workers = workers
        self.on_result = on_result
        if symbols:
            self.symbols = symbols
        elif top_n:
            self.symbols = top_usdt_by_volume(top_n)
        else:
            self.symbols = list_usdt_perpetuals()

    def scan_one(self, symbol: str, dominance: dict[str, Any]) -> dict[str, Any]:
        try:
            frames = fetch_multi_tf(symbol, limit=400)
            result = evaluate_symbol(symbol, frames, dominance=dominance)
            # council stub: no extra guardians yet — qoghnoos is authority
            result["council"] = {
                "require_ghoghnoos_setup": True,
                "final": result["verdict"],
                "note_fa": "بدون SETUP ققنوس، SIGNAL صادر نمی‌شود",
            }
            if result["verdict"] == "SETUP":
                result["signal"] = {
                    "action": "SIGNAL",
                    "symbol": symbol,
                    "direction": result["direction"],
                    "tf": "15m",
                    "geometry": result.get("geometry"),
                    "why_fa": result.get("why_fa"),
                }
            else:
                result["signal"] = {
                    "action": "WATCH" if result["verdict"] == "WATCH" else result["verdict"],
                    "symbol": symbol,
                    "alarms": result.get("alarms"),
                    "note_fa": "برو ارز بعدی",
                }
            if self.on_result:
                self.on_result(result)
            return result
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "symbol": symbol,
                "verdict": "BLIND",
                "error": str(exc),
                "why_fa": [f"خطا در ارزیابی: {exc}"],
            }

    def run_cycle(self) -> dict[str, Any]:
        started = datetime.now(timezone.utc).isoformat()
        dominance = fetch_dominance_proxy()
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = {pool.submit(self.scan_one, s, dominance): s for s in self.symbols}
            for fut in as_completed(futs):
                results.append(fut.result())

        setups = [r for r in results if r.get("verdict") == "SETUP"]
        watches = [r for r in results if r.get("verdict") == "WATCH"]
        summary = {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "method": "hamid_method_v3",
            "applies_to": "all_symbols",
            "symbols_scanned": len(results),
            "setups": len(setups),
            "watches": len(watches),
            "dominance": dominance,
            "signals": [r["signal"] for r in setups if r.get("signal")],
            "watch_list": [
                {
                    "symbol": r["symbol"],
                    "direction": r.get("direction"),
                    "alarms": r.get("alarms"),
                    "why_fa": (r.get("why_fa") or [])[:3],
                }
                for r in watches
            ],
            "results": results,
        }
        return summary


def save_cycle(summary: dict[str, Any], path: str | None = None) -> str:
    os.makedirs(ARTIFACTS, exist_ok=True)
    if path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(ARTIFACTS, f"phoenix_cycle_{ts}.json")
    # lighter disk copy without huge by_tf dumps optional
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
    return path


def print_summary_fa(summary: dict[str, Any]) -> None:
    print("=" * 60)
    print("پنل ققنوس · متد حمید نسخهٔ ۳ · قوانین برای همهٔ ارزها یکسان")
    print("=" * 60)
    print(f"اسکن: {summary['symbols_scanned']} ارز")
    print(f"SETUP: {summary['setups']} · WATCH: {summary['watches']}")
    dom = summary.get("dominance") or {}
    print(f"دامیننس (پروکسی): {dom.get('bias')} — {dom.get('root_fa')}")
    print("-" * 60)
    if summary["signals"]:
        print("سیگنال‌ها:")
        for s in summary["signals"]:
            g = s.get("geometry") or {}
            print(
                f"  • {s['symbol']} {s['direction'].upper()} @15m "
                f"entry={g.get('entry')} stop={g.get('stop')} "
                f"RR1={g.get('rr1')} lev={g.get('leverage')}"
            )
    else:
        print("سیگنالی نیست — آلارم بگذار و برو ارز بعدی.")
    if summary["watch_list"][:8]:
        print("-" * 60)
        print("نمونه WATCH:")
        for w in summary["watch_list"][:8]:
            a = w.get("alarms") or {}
            print(f"  • {w['symbol']} · {w.get('direction')} · آلارم {a.get('alarm_1')} / {a.get('alarm_2')}")
    print("=" * 60)
