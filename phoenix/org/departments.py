"""
۹ دپارتمان — هر کدام یک استراتژی حرفه‌ای جداگانه دارد و فقط «گزارش» می‌دهد.
هیچ دپارتمانی به‌تنهایی سیگنال نمی‌دهد (قانون سازمان).

گزارش: {"dept", "direction": long|short|flat, "strength": 0..1, "silent": bool, "flags": [...], "note_fa"}
"""
from __future__ import annotations

from typing import Any

from phoenix.org.memory import Memory

# وزن‌های پایهٔ قفل‌شده (ORG_RUNTIME_FA.md)
BASE_WEIGHTS: dict[str, float] = {
    "dominance": 0.20,
    "structure": 0.20,
    "liquidity": 0.15,
    "volume": 0.10,
    "news": 0.10,
    "order_block": 0.10,
    "pattern": 0.05,
    "social": 0.05,
    "historical_memory": 0.05,
}

DEPT_FA: dict[str, str] = {
    "dominance": "دامیننس (USDT.D)",
    "structure": "ساختار بازار",
    "liquidity": "لیکوئیدیتی",
    "volume": "حجم",
    "news": "خبر",
    "order_block": "اردربلاک",
    "pattern": "الگو",
    "social": "سوشال",
    "historical_memory": "حافظهٔ تاریخی",
}


def _rep(dept: str, direction: str = "flat", strength: float = 0.0, *, silent: bool = False,
         flags: list[str] | None = None, note_fa: str = "") -> dict[str, Any]:
    return {
        "dept": dept,
        "direction": direction if not silent else "flat",
        "strength": round(max(0.0, min(1.0, strength)), 3),
        "silent": silent,
        "flags": flags or [],
        "note_fa": note_fa,
    }


def regime_of(result: dict[str, Any]) -> str:
    """رژیم بازار = دامیننس × روند ۴ساعته. دقت دپارتمان‌ها به تفکیک همین کلید ذخیره می‌شود."""
    bias = (result.get("dominance") or {}).get("bias") or "blind"
    h4 = (result.get("by_tf") or {}).get("4h") or {}
    trend = (h4.get("structure") or {}).get("trend") or "flat"
    return f"{bias}/{trend}"


def _tf(result: dict[str, Any], tf: str) -> dict[str, Any]:
    return (result.get("by_tf") or {}).get(tf) or {}


def dept_dominance(result: dict[str, Any]) -> dict[str, Any]:
    dom = result.get("dominance") or {}
    if not dom.get("ok") or dom.get("bias") in (None, "blind"):
        return _rep("dominance", silent=True, note_fa="دامیننس کور — وتو نمی‌کند")
    ret = abs(float(dom.get("btc_ret_24h") or 0.0))
    strength = min(1.0, 0.5 + ret * 8)
    if dom["bias"] == "risk_off":
        return _rep("dominance", "short", strength, note_fa=dom.get("root_fa", ""))
    if dom["bias"] == "risk_on":
        return _rep("dominance", "long", strength, note_fa=dom.get("root_fa", ""))
    return _rep("dominance", "flat", 0.3, note_fa="خنثی")


def dept_structure(result: dict[str, Any]) -> dict[str, Any]:
    votes: dict[str, float] = {"long": 0.0, "short": 0.0}
    flags: list[str] = []
    for tf, w in (("4h", 0.5), ("1h", 0.3), ("15m", 0.2)):
        d = _tf(result, tf)
        st = d.get("structure") or {}
        if st.get("bos") == "bull":
            votes["long"] += w
        elif st.get("bos") == "bear":
            votes["short"] += w
        elif st.get("trend") == "up":
            votes["long"] += w * 0.5
        elif st.get("trend") == "down":
            votes["short"] += w * 0.5
        if st.get("choch"):
            flags.append(f"choch_{tf}")
    d15 = _tf(result, "15m")
    chans = d15.get("channels") or []
    price = d15.get("price")
    if chans and price and not d15.get("reentry"):
        outer = chans[0]
        if price > outer["upper"] or price < outer["lower"]:
            flags.append("channel_break_without_pullback")
    if votes["long"] == votes["short"]:
        return _rep("structure", "flat", 0.2, flags=flags, note_fa="ساختار بی‌تصمیم")
    direction = "long" if votes["long"] > votes["short"] else "short"
    strength = abs(votes["long"] - votes["short"])
    return _rep("structure", direction, strength, flags=flags,
                note_fa=f"H4 اصلی · H1 تأیید · M15 ورود — {direction}")


def dept_liquidity(result: dict[str, Any]) -> dict[str, Any]:
    d15 = _tf(result, "15m")
    trig = d15.get("trigger")
    reentry = d15.get("reentry") or _tf(result, "1h").get("reentry")
    if not trig and not reentry:
        return _rep("liquidity", "flat", 0.1, note_fa="برداشت نقدینگی دیده نشد")
    if trig:
        strength = min(1.0, 0.4 + float(trig.get("shadow_ratio", 1.0)) * 0.2 + float(trig.get("penetration", 0)) * 0.3)
        return _rep("liquidity", trig["direction"], strength, flags=["sweep_rejection"],
                    note_fa="شدوی پس‌زننده = برداشت نقدینگی + ریجکت")
    return _rep("liquidity", reentry["direction"], 0.55, flags=["channel_reentry"],
                note_fa="بازگشت به کانال → هدف ضلع مقابل")


def dept_volume(result: dict[str, Any]) -> dict[str, Any]:
    items = (result.get("params") or {}).get("items") or {}
    vol = items.get("volume")
    direction = result.get("direction") or "flat"
    if not vol or vol.get("blind"):
        return _rep("volume", silent=True, note_fa="حجم بی‌داده")
    if vol.get("ok"):
        return _rep("volume", direction, 0.5, note_fa=vol.get("fa", "حجم تأیید"))
    return _rep("volume", "flat", 0.1, flags=["weak_volume"], note_fa=vol.get("fa", "حجم ضعیف"))


INTEL_MAX_AGE_H = 6  # اگر ایجنت اطلاعات بیش از این عقب باشد، خبر/سوشال خاموش می‌شوند (کور ≠ رد)
HIGH_RISK = 0.7


def _intel_fresh(memory: Memory) -> dict[str, Any] | None:
    intel = memory.data.get("intel") or {}
    ts = intel.get("updated_at")
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return None
    return intel if age_h <= INTEL_MAX_AGE_H else None


def dept_news(result: dict[str, Any], memory: Memory | None = None) -> dict[str, Any]:
    """خبر و رویداد توکنی از ایجنت اطلاعات (لیستینگ/دی‌لیست/آنلاک/سوزاندن/هک/قانون/کلان)."""
    intel = _intel_fresh(memory) if memory else None
    if not intel:
        return _rep("news", silent=True, note_fa="ایجنت اطلاعات تازه نیست → خاموش")
    node = (intel.get("symbols") or {}).get(result.get("symbol", ""))
    market = intel.get("market") or {}
    flags: list[str] = []
    if node and node.get("risk", 0) >= HIGH_RISK:
        flags.append("high_risk_news")
    if not node:
        # بدون خبر اختصاصی: نبض کلی بازار (ترس‌وطمع) با قدرت کم
        fg = market.get("fear_greed")
        if fg is None:
            return _rep("news", "flat", 0.1, note_fa="بدون خبر اختصاصی")
        if fg <= 20:
            return _rep("news", "long", 0.25, note_fa=f"ترس شدید ({fg}) — contrarian ملایم")
        if fg >= 80:
            return _rep("news", "short", 0.25, note_fa=f"طمع شدید ({fg}) — contrarian ملایم")
        return _rep("news", "flat", 0.1, note_fa=f"ترس‌وطمع {fg} خنثی")
    sent = float(node.get("sentiment", 0))
    events = "، ".join(KIND_FA_SHORT.get(e, e) for e in node.get("events") or []) or "خبر"
    if flags:
        return _rep("news", "flat", 0.0, flags=flags, note_fa=f"رویداد پرریسک: {events}")
    if abs(sent) < 0.15:
        return _rep("news", "flat", 0.15, note_fa=f"{events} · خنثی")
    return _rep("news", "long" if sent > 0 else "short", min(1.0, abs(sent)), flags=[f"news_{e}" for e in node.get("events") or []],
                note_fa=f"{events} · احساس {sent:+.2f}")


KIND_FA_SHORT = {"listing": "لیستینگ", "delisting": "دی‌لیست", "token_unlock": "آنلاک", "token_burn": "سوزاندن",
                 "security": "هک", "regulation": "قانون", "macro": "کلان", "project": "پروژه", "market": "جریان"}


def dept_order_block(result: dict[str, Any]) -> dict[str, Any]:
    wall = result.get("wall") or _tf(result, "15m").get("wall")
    if not wall:
        return _rep("order_block", "flat", 0.0, note_fa="دیوار زنده‌ای در کار نیست")
    price = _tf(result, "15m").get("price") or 0
    toward = "long" if wall["mid"] < price else "short"
    verdict = wall.get("verdict")
    if verdict in ("untested",) or int(wall.get("reactions", 0)) == 0:
        # OB بدون واکنش تاریخی معتبر نیست → وزن صفر
        return _rep("order_block", silent=True, flags=["ob_no_history"], note_fa="OB بدون تست تاریخی → وزن صفر")
    table = {"solid": (toward, 0.9), "hammer_dulling": (toward, 0.6), "young": (toward, 0.4),
             "wall_eroding": ("flat", 0.2), "wall_cracking": ("short" if toward == "long" else "long", 0.5)}
    direction, strength = table.get(verdict, ("flat", 0.1))
    return _rep("order_block", direction, strength, flags=[f"wall_{verdict}"],
                note_fa=f"دیوار {verdict} · {wall.get('reactions')} واکنش")


def dept_pattern(result: dict[str, Any]) -> dict[str, Any]:
    items = (result.get("params") or {}).get("items") or {}
    direction = result.get("direction") or "flat"
    hits = 0
    flags: list[str] = []
    for key in ("fvg_inside_ob", "history_rsi_div", "trendline", "ob_channel_align"):
        it = items.get(key)
        if it and not it.get("blind") and it.get("ok"):
            hits += 1
            flags.append(key)
    if direction == "flat" or hits == 0:
        return _rep("pattern", "flat", 0.1, note_fa="الگوی تأییدکننده‌ای نیست")
    return _rep("pattern", direction, 0.25 * hits, flags=flags, note_fa=f"{hits} الگوی هم‌جهت")


def dept_social(result: dict[str, Any], memory: Memory | None = None) -> dict[str, Any]:
    """نبض X از Grok (ایجنت اطلاعات). بدون کلید یا داده: خاموش."""
    intel = _intel_fresh(memory) if memory else None
    node = ((intel or {}).get("social") or {}).get(result.get("symbol", ""))
    if not node:
        return _rep("social", silent=True, note_fa="سوشال بی‌داده (Grok وصل نیست یا این ارز پوشش ندارد)")
    sent = float(node.get("sentiment", 0))
    if abs(sent) < 0.2:
        return _rep("social", "flat", 0.1, note_fa=node.get("note_fa") or "خنثی")
    # سوشال داغ + یک‌طرفه = ریسک شلوغی؛ قدرت را سقف می‌زنیم
    strength = min(0.7, abs(sent)) * (0.8 if node.get("hot") else 1.0)
    return _rep("social", "long" if sent > 0 else "short", strength,
                flags=["social_hot"] if node.get("hot") else [], note_fa=node.get("note_fa") or "")


def dept_historical_memory(result: dict[str, Any], memory: Memory, regime: str) -> dict[str, Any]:
    direction = result.get("direction") or "flat"
    if direction == "flat":
        return _rep("historical_memory", "flat", 0.0, note_fa="بدون جهت برای جست‌وجوی حافظه")
    exps = memory.similar_experiences(result.get("symbol", ""), regime, direction)
    if len(exps) < 3:
        return _rep("historical_memory", silent=True, note_fa=f"تجربهٔ کافی نیست ({len(exps)}/3)")
    wins = sum(1 for e in exps if e.get("outcome") == "TP")
    wr = wins / len(exps)
    strength = abs(wr - 0.5) * 2
    if wr >= 0.5:
        return _rep("historical_memory", direction, strength,
                    note_fa=f"حافظه: {wins}/{len(exps)} موفق در {regime}")
    opposite = "short" if direction == "long" else "long"
    return _rep("historical_memory", opposite, strength, flags=["memory_against"],
                note_fa=f"حافظه مخالف: فقط {wins}/{len(exps)} موفق در {regime}")


def department_reports(result: dict[str, Any], memory: Memory) -> tuple[str, list[dict[str, Any]]]:
    regime = regime_of(result)
    reports = [
        dept_dominance(result),
        dept_structure(result),
        dept_liquidity(result),
        dept_volume(result),
        dept_news(result, memory),
        dept_order_block(result),
        dept_pattern(result),
        dept_social(result, memory),
        dept_historical_memory(result, memory, regime),
    ]
    return regime, reports
