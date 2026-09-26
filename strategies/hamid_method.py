"""متد حمید نسخهٔ ۳ — بارگذاری اسپک و پرامپت."""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))

PROMPT_FILES = (
    os.path.join(_ROOT, "docs", "HAMID_METHOD_V3_PROMPT.txt"),
    os.path.join(_ROOT, "docs", "HAMID_METHOD_PROMPT.txt"),
)
MIN_PROMPT_BYTES = 2000
SPEC_PATH = os.path.join(_HERE, "hamid_method_spec.json")


@lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    with open(SPEC_PATH, encoding="utf-8") as fh:
        return json.load(fh)


SPEC = load_spec()


def prompt(version: str = "latest") -> str:
    paths = PROMPT_FILES if version == "latest" else [
        p for p in PROMPT_FILES if version.lower() in os.path.basename(p).lower()
    ]
    tried: list[str] = []
    for p in paths:
        tried.append(p)
        if os.path.exists(p) and os.path.getsize(p) >= MIN_PROMPT_BYTES:
            with open(p, encoding="utf-8") as fh:
                return fh.read()
    raise FileNotFoundError("پرامپت متد پیدا نشد یا ناقص بود: " + " | ".join(tried))


def prompt_path(version: str = "latest") -> str:
    for p in PROMPT_FILES:
        if version != "latest" and version.lower() not in os.path.basename(p).lower():
            continue
        if os.path.exists(p) and os.path.getsize(p) >= MIN_PROMPT_BYTES:
            return os.path.abspath(p)
    raise FileNotFoundError("پرامپت متد پیدا نشد")


def gates() -> dict[str, Any]:
    """گیت‌های سخت پنل — استخراج‌شده از اسپک."""
    ob = SPEC["order_block"]
    tr = SPEC["trigger"]
    ch = SPEC["channel"]
    return {
        "master_timeframe": SPEC["cascade"]["master_timeframe"],
        "execution_timeframe": SPEC["cascade"]["execution_timeframe"],
        "decide_only_on": SPEC["cascade"]["decide_only_on"],
        "applies_to": SPEC["applies_to"],
        "order_block_needs_historical_reaction": True,
        "order_block_needs_h1_anchor": ob["require_h1_anchor"],
        "tradeable_wall_verdicts": list(ob["tradeable_wall_verdicts"]),
        "entry_needs_wick_rejection": tr["entry_needs_wick_rejection"],
        "min_shadow_to_body_ratio": tr["min_shadow_to_body_ratio"],
        "min_penetration_pct_of_band": tr["min_penetration_pct_of_band"],
        "only_live_walls": ob["live_walls_only"],
        "channel_reentry_is_unconditional": ch["reentry_rule"]["unconditional"],
        "min_rr_target_1": SPEC["targets"]["min_rr_for_target_1"],
        "param_min_score": SPEC["params"]["min_score"],
        "stop_conditions": list(SPEC["stop"]["conditions_all_required"]),
        "size_is_adjusted_not_the_stop": SPEC["stop"]["size_is_adjusted_not_the_stop"],
    }


def available() -> bool:
    return os.path.exists(SPEC_PATH) and os.path.getsize(SPEC_PATH) > 100


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"متد حمید نسخهٔ {SPEC['version']} — به‌روزرسانی {SPEC['updated']}")
    print(f"اسپک در دسترس: {available()}  ({SPEC_PATH})")
    print(json.dumps(gates(), ensure_ascii=False, indent=2))
    try:
        p = prompt()
        print(f"\nپرامپت: {prompt_path()}  ({len(p):,} کاراکتر · {len(p.splitlines())} خط)")
    except Exception as exc:  # noqa: BLE001
        print("\n!! پرامپت خوانده نشد:", exc)
    print("\nکارهای باقی‌مانده:")
    for item in SPEC.get("not_yet_implemented", []):
        print("  -", item)
