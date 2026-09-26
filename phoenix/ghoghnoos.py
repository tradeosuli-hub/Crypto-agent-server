"""استراتژی ققنوس — متد حمید نسخهٔ ۳ برای همهٔ ارزها."""
from __future__ import annotations

import os
import sys
from typing import Any

import numpy as np
import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from strategies.hamid_method import SPEC, gates  # noqa: E402
from phoenix import ta  # noqa: E402

TFS = ("4h", "1h", "15m", "5m")
WEIGHTS = SPEC["timeframe_weights"]
DECIDE_TF = SPEC["cascade"]["decide_only_on"]
PARAM_MIN = SPEC["params"]["min_score"]
PARAM_MIN_VIS = SPEC["params"]["min_visible"]
TRADE_WALLS = set(SPEC["order_block"]["tradeable_wall_verdicts"])
MIN_RR = SPEC["targets"]["min_rr_for_target_1"]
RISK_PCT = SPEC["risk"]["risk_pct"]
LEV_MIN = SPEC["risk"]["leverage_min"]
LEV_MAX = SPEC["risk"]["leverage_max"]


def _score_direction(direction: str | None) -> float:
    if direction == "long":
        return 1.0
    if direction == "short":
        return -1.0
    return 0.0


def analyze_tf(
    df: pd.DataFrame,
    tf: str,
    h1_blocks: list[ta.OrderBlock] | None = None,
    dominance: dict[str, Any] | None = None,
    dxy: Any = None,
    news: Any = None,
) -> dict[str, Any]:
    """تحلیل یک تایم‌فریم فقط از کندل‌های همان تایم."""
    if df is None or len(df) < 50:
        return {"tf": tf, "verdict": "blind", "direction": "flat", "score": 0.0, "why_fa": ["داده ناکافی"]}

    atr_s = ta.atr(df)
    atr_now = float(atr_s.iloc[-1])
    price = float(df["close"].iloc[-1])
    lookbacks = SPEC["channel"]["lookbacks"]
    chans = ta.channels(df, lookbacks)
    outer = chans[0] if chans else None
    reentry = ta.channel_reentry(df, outer) if outer else None

    ob_cfg = SPEC["order_block"]
    blocks = ta.order_blocks(df, walkback=ob_cfg["walkback"], merge=ob_cfg["merge_consecutive"])
    blocks = ta.annotate_reactions(
        df,
        blocks,
        atr_s,
        gap=ob_cfg["reaction_gap_candles"],
        min_atr=ob_cfg["reaction_min_atr"],
        touch_pct=ob_cfg["reaction_touch_pct_of_band"],
    )

    # H1 anchor for lower TFs
    if h1_blocks and tf in ("15m", "5m") and ob_cfg["require_h1_anchor"]:
        anchored = []
        for b in blocks:
            near = any(
                abs(b.mid - hb.mid) <= atr_now * ob_cfg["anchor_atr"] * 3
                or abs(b.low - hb.low) <= atr_now * ob_cfg["anchor_atr"] * 3
                or abs(b.high - hb.high) <= atr_now * ob_cfg["anchor_atr"] * 3
                for hb in h1_blocks
            )
            if near or b.reactions >= 1:
                anchored.append(b)
        if anchored:
            blocks = anchored

    walls = ta.live_walls(blocks, price)
    levels = ta.support_resistance(df)
    fvgs = ta.detect_fvg(df)
    structure = ta.bos_choch(df, confirm=SPEC["break_confirm_candles"])
    div = ta.rsi_divergence(df)
    vz = ta.volume_z(df["volume"])
    vol_now = float(vz.iloc[-1]) if not np.isnan(vz.iloc[-1]) else 0.0
    liq = ta.liquidation_map(df)

    # trigger on live walls
    trigger = None
    wall_used = None
    for side in ("below", "above"):
        w = walls.get(side)
        if w is None:
            continue
        if w.verdict not in TRADE_WALLS and w.verdict not in ("young", "untested"):
            # still allow young for bias but not setup unless tradeable
            pass
        tr_cfg = SPEC["trigger"]
        cand = ta.wick_rejection(
            df,
            w,
            min_shadow_ratio=tr_cfg["min_shadow_to_body_ratio"],
            min_pen_pct=tr_cfg["min_penetration_pct_of_band"],
            lookback=tr_cfg["lookback_candles"],
        )
        if cand and w.verdict in TRADE_WALLS:
            trigger = cand
            wall_used = w
            break
        if cand and trigger is None and w.verdict in ("young", "solid", "hammer_dulling"):
            trigger = cand
            wall_used = w

    direction = "flat"
    if trigger:
        direction = trigger["direction"]
    elif reentry:
        direction = reentry["direction"]
    elif structure["bos"]:
        direction = "long" if structure["bos"] == "bull" else "short"

    params = _params_checklist(
        df=df,
        direction=direction,
        outer=outer,
        wall=wall_used,
        blocks=blocks,
        fvgs=fvgs,
        structure=structure,
        div=div,
        vol_now=vol_now,
        reentry=reentry,
        dominance=dominance,
        dxy=dxy,
        news=news,
    )

    score_vis = params["visible"]
    score = params["score"]
    has_trigger = trigger is not None and wall_used is not None and wall_used.verdict in TRADE_WALLS
    if has_trigger and score >= PARAM_MIN and score_vis >= PARAM_MIN_VIS:
        verdict = "setup"
    elif direction != "flat":
        verdict = "bias"
    else:
        verdict = "flat"

    geometry = None
    if direction in ("long", "short") and wall_used is not None:
        geometry = build_geometry(
            df=df,
            direction=direction,
            wall=wall_used,
            channel=outer,
            levels=levels,
            liq=liq,
            atr_v=atr_now,
            reentry=reentry,
        )

    why = []
    if trigger:
        why.append(
            f"ماشهٔ شدوی پس‌زننده ({trigger['direction']}) · نفوذ {trigger['penetration']:.2f} · نسبت شدو {trigger['shadow_ratio']:.2f}"
        )
    if reentry:
        why.append(f"بازگشت به کانال → {reentry['direction']} · تارگت {reentry['target']:.6g}")
    if wall_used:
        why.append(f"دیوار {wall_used.verdict} · واکنش‌های گذشته {wall_used.reactions}")
    why.append(f"پارامترها {score}/{params['visible_total']} (قابل‌بررسی {score_vis})")

    return {
        "tf": tf,
        "verdict": verdict,
        "direction": direction,
        "score": _score_direction(direction) * (0.5 + 0.5 * min(score / 10, 1)),
        "price": price,
        "atr": atr_now,
        "channels": [c.to_dict() for c in chans],
        "reentry": reentry,
        "walls": {
            "below": walls["below"].to_dict() if walls["below"] else None,
            "above": walls["above"].to_dict() if walls["above"] else None,
        },
        "wall": wall_used.to_dict() if wall_used else None,
        "trigger": trigger,
        "levels": [lv.to_dict() for lv in levels[-12:]],
        "structure": structure,
        "params": params,
        "geometry": geometry,
        "fvg_count": len(fvgs),
        "why_fa": why,
        "_blocks": blocks,  # internal
    }


def _params_checklist(
    *,
    df: pd.DataFrame,
    direction: str,
    outer: ta.Channel | None,
    wall: ta.OrderBlock | None,
    blocks: list[ta.OrderBlock],
    fvgs: list[dict],
    structure: dict,
    div: dict,
    vol_now: float,
    reentry: dict | None,
    dominance: dict | None,
    dxy: Any,
    news: Any,
) -> dict[str, Any]:
    """ده پارامتر — کور ≠ رد."""
    items: dict[str, dict[str, Any]] = {}

    # 1 DXY
    if dxy is None:
        items["dxy"] = {"ok": None, "blind": True, "fa": "شاخص دلار · بی‌داده"}
    else:
        items["dxy"] = {"ok": bool(dxy), "blind": False, "fa": "شاخص دلار"}

    # 2 trendline / channel
    if outer is None:
        items["trendline"] = {"ok": None, "blind": True, "fa": "ترندلاین · بی‌داده"}
    else:
        align = True
        if direction == "long" and outer.slope < 0 and not reentry:
            align = False
        if direction == "short" and outer.slope > 0 and not reentry:
            align = False
        if reentry:
            align = True
        items["trendline"] = {"ok": align, "blind": False, "fa": "اصول ترندلاین/کانال"}

    # 3 dominance
    if dominance is None or dominance.get("bias") == "blind":
        items["dominance_align"] = {"ok": None, "blind": True, "fa": "دامیننس · کور"}
    else:
        ok = True
        if direction == "long" and not dominance.get("allow_long", True):
            ok = False
        if direction == "short" and not dominance.get("allow_short", True):
            ok = False
        items["dominance_align"] = {"ok": ok, "blind": False, "fa": "عدم تناقض با دامیننس"}

    # 4 OB align with channel
    if wall is None or outer is None:
        items["ob_channel_align"] = {"ok": None, "blind": True, "fa": "هم‌جهتی اوردر بلاک با کانال · ناکافی"}
    else:
        ok = True
        if direction == "long" and wall.mid > float(df["close"].iloc[-1]):
            ok = False
        if direction == "short" and wall.mid < float(df["close"].iloc[-1]):
            ok = False
        items["ob_channel_align"] = {"ok": ok, "blind": False, "fa": "هم‌جهتی اوردر بلاک با کانال"}

    # 5 BOS/CHoCH
    st = structure
    if st.get("trend") == "flat" and not st.get("bos"):
        items["bos_choch"] = {"ok": None, "blind": True, "fa": "BOS/CHoCH · مبهم"}
    else:
        ok = True
        if direction == "long" and st.get("trend") == "down" and st.get("choch") != "bull":
            ok = False
        if direction == "short" and st.get("trend") == "up" and st.get("choch") != "bear":
            ok = False
        items["bos_choch"] = {"ok": ok, "blind": False, "fa": "BOS/CHoCH و عدم خلاف روند"}

    # 6 FVG inside OB
    if wall is None:
        items["fvg_inside_ob"] = {"ok": None, "blind": True, "fa": "FVG داخل اوردر بلاک · بدون باند"}
    else:
        hit = any(
            not g.get("spent")
            and g["low"] <= wall.high
            and g["high"] >= wall.low
            for g in fvgs
        )
        items["fvg_inside_ob"] = {"ok": hit, "blind": False, "fa": "هم‌پوشانی FVG با اوردر بلاک"}

    # 7 historical tests
    min_tests = SPEC["params"]["ob_min_tests_for_param7"]
    if wall is None:
        items["ob_historical_tests"] = {"ok": None, "blind": True, "fa": "تست تاریخی باند · بدون باند"}
    else:
        items["ob_historical_tests"] = {
            "ok": wall.reactions >= min_tests or wall.reactions >= 1,
            "blind": False,
            "fa": f"سابقهٔ تست باند ({wall.reactions})",
        }

    # 8 history + RSI
    if div.get("rsi") is None:
        items["history_rsi_div"] = {"ok": None, "blind": True, "fa": "RSI · بی‌داده"}
    else:
        ok = True
        if direction == "long" and div.get("bear_div"):
            ok = False
        if direction == "short" and div.get("bull_div"):
            ok = False
        if direction == "long" and div["rsi"] > 78:
            ok = False
        if direction == "short" and div["rsi"] < 22:
            ok = False
        items["history_rsi_div"] = {"ok": ok, "blind": False, "fa": "تاریخچه + RSI + واگرایی"}

    # 9 volume — داده هست ⇒ قابل‌بررسی؛ تأیید اگر ضعف شدید حجم نباشد
    vol_ok = True
    if direction in ("long", "short"):
        vol_ok = vol_now >= -0.5
    items["volume"] = {
        "ok": vol_ok,
        "blind": False,
        "fa": f"حجم (z={vol_now:.2f})",
    }

    # 10 news
    if news is None:
        items["news_events"] = {"ok": None, "blind": True, "fa": "خبر/رویداد · بی‌داده"}
    else:
        items["news_events"] = {"ok": bool(news), "blind": False, "fa": "خبر و رویداد"}

    visible = [k for k, v in items.items() if not v["blind"]]
    passed = [k for k in visible if items[k]["ok"]]
    # scaled score to /10 preserving ratio when some blind
    if len(visible) == 0:
        score = 0
    else:
        score = round(len(passed) / len(visible) * 10)
    return {
        "items": items,
        "score": score,
        "passed": len(passed),
        "visible": len(visible),
        "visible_total": 10,
        "passed_names": passed,
        "blind_names": [k for k, v in items.items() if v["blind"]],
        "failed_names": [k for k in visible if not items[k]["ok"]],
    }


def build_geometry(
    *,
    df: pd.DataFrame,
    direction: str,
    wall: ta.OrderBlock,
    channel: ta.Channel | None,
    levels: list[ta.Level],
    liq: list[dict],
    atr_v: float,
    reentry: dict | None,
) -> dict[str, Any]:
    price = float(df["close"].iloc[-1])
    edge = SPEC["entry"]["edge_offset_atr"] * atr_v
    if direction == "long":
        entry = wall.high + edge
        stop_ob = wall.low - edge
    else:
        entry = wall.low - edge
        stop_ob = wall.high + edge

    # 2 liquidity
    stop_liq = ta.nearest_liq_outside(
        liq, entry, direction, atr_v, SPEC["stop"]["cluster_buffer_atr"]
    )

    # 3 channel
    if channel:
        stop_ch = channel.lower - edge if direction == "long" else channel.upper + edge
    else:
        stop_ch = entry - atr_v if direction == "long" else entry + atr_v

    # 4 previous swing same TF
    swing_low = float(df["low"].iloc[-30:-1].min())
    swing_high = float(df["high"].iloc[-30:-1].max())
    stop_sw = swing_low - edge if direction == "long" else swing_high + edge

    candidates = [stop_ob, stop_liq, stop_ch, stop_sw]
    if direction == "long":
        stop = min(candidates)  # farthest below
        # ensure min ATR distance
        min_stop = entry - SPEC["stop"]["min_stop_atr"] * atr_v
        stop = min(stop, min_stop)
    else:
        stop = max(candidates)
        min_stop = entry + SPEC["stop"]["min_stop_atr"] * atr_v
        stop = max(stop, min_stop)

    # targets from structure
    targets: list[float] = []
    if reentry and reentry.get("target"):
        targets.append(float(reentry["target"]))
    if direction == "long":
        above = sorted({lv.price for lv in levels if lv.price > entry})
        targets.extend(above[:4])
        if channel:
            targets.extend([channel.mid, channel.upper])
    else:
        below = sorted({lv.price for lv in levels if lv.price < entry}, reverse=True)
        targets.extend(below[:4])
        if channel:
            targets.extend([channel.mid, channel.lower])
    # unique ordered
    uniq: list[float] = []
    for t in targets:
        if direction == "long" and t <= entry:
            continue
        if direction == "short" and t >= entry:
            continue
        if not uniq or abs(uniq[-1] - t) / entry > 0.001:
            uniq.append(float(t))
    uniq = uniq[:4]

    risk = abs(entry - stop)
    rr1 = abs(uniq[0] - entry) / risk if uniq and risk > 0 else 0.0
    stop_pct = risk / entry * 100 if entry else 0
    # leverage for 1% account risk
    lev = RISK_PCT / max(stop_pct, 0.05)
    lev = float(max(LEV_MIN, min(LEV_MAX, lev)))
    notional_pct = RISK_PCT / max(stop_pct, 0.05) * 100
    notional_pct = min(notional_pct, LEV_MAX * 100)

    return {
        "entry": entry,
        "stop": stop,
        "stop_conditions": {
            "behind_ob": stop_ob,
            "outside_liq": stop_liq,
            "inside_channel": stop_ch,
            "beyond_swing": stop_sw,
            "chosen": stop,
        },
        "targets": uniq,
        "rr1": round(rr1, 3),
        "stop_pct": round(stop_pct, 3),
        "leverage": round(lev, 2),
        "notional_pct_of_equity": round(min(notional_pct, 2000), 1),
        "risk_pct": RISK_PCT,
        "valid": rr1 >= MIN_RR and len(uniq) >= 1,
    }


def evaluate_symbol(
    symbol: str,
    frames: dict[str, pd.DataFrame],
    dominance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """حکم ققنوس برای یک ارز — قوانین برای همه یکسان."""
    dominance = dominance or {"bias": "blind", "allow_long": True, "allow_short": True}

    # 1h first for anchors
    h1 = analyze_tf(frames.get("1h"), "1h", dominance=dominance)
    h1_blocks = h1.pop("_blocks", [])
    by_tf: dict[str, Any] = {}
    for tf in TFS:
        if tf == "1h":
            by_tf[tf] = {k: v for k, v in h1.items()}
            continue
        res = analyze_tf(
            frames.get(tf),
            tf,
            h1_blocks=h1_blocks if tf in ("15m", "5m") else None,
            dominance=dominance,
        )
        res.pop("_blocks", None)
        by_tf[tf] = res

    # weighted score
    total = 0.0
    for tf in TFS:
        total += by_tf[tf]["score"] * WEIGHTS.get(tf, 0.0)

    d15 = by_tf["15m"]
    d1 = by_tf["1h"]
    d4 = by_tf["4h"]

    direction = d15["direction"]
    # conflict: both higher TFs opposite
    conflict = False
    if direction == "long" and d1["direction"] == "short" and d4["direction"] == "short":
        conflict = True
    if direction == "short" and d1["direction"] == "long" and d4["direction"] == "long":
        conflict = True

    dom_ok = True
    if direction == "long" and not dominance.get("allow_long", True):
        dom_ok = False
    if direction == "short" and not dominance.get("allow_short", True):
        dom_ok = False
    # dual confirm bypass: structure + liquidity (reentry or trigger)
    dual = bool(d15.get("trigger") and (d15.get("reentry") or d1.get("reentry")))
    if dual:
        dom_ok = True

    geom = d15.get("geometry")
    params = d15.get("params") or {}
    setup_ok = (
        d15["verdict"] == "setup"
        and params.get("score", 0) >= PARAM_MIN
        and params.get("visible", 0) >= PARAM_MIN_VIS
        and not conflict
        and dom_ok
        and geom is not None
        and geom.get("valid")
        and geom.get("rr1", 0) >= MIN_RR
    )

    if setup_ok:
        verdict = "SETUP"
    elif direction != "flat" or d1["verdict"] in ("setup", "bias") or d4["verdict"] in ("setup", "bias"):
        verdict = "WATCH"
    elif d15["verdict"] == "blind":
        verdict = "BLIND"
    else:
        verdict = "FLAT"

    alarms = _alarms(by_tf, direction)
    why = list(d15.get("why_fa") or [])
    if conflict:
        why.append("تضاد جهت ۱۵دقیقه با هر دو تایم بالاتر")
    if not dom_ok:
        why.append("تناقض با دامیننس")
    if geom and not geom.get("valid"):
        why.append(f"هندسه نامعتبر · R:R={geom.get('rr1')} (حداقل {MIN_RR})")
    if verdict != "SETUP":
        why.append("ستاپ حد نصاب نگرفت → آلارم و برو ارز بعدی")

    scenarios = {
        "primary": {
            "direction": direction if direction != "flat" else d1["direction"],
            "note_fa": "مسیر اصلی روی فلش آبی (مرجع ۱ساعته + تأیید ۱۵دقیقه)",
        },
        "alt": {
            "direction": "short" if direction == "long" else "long" if direction == "short" else "flat",
            "note_fa": "سناریو ۲ اگر ۲ بار دیگر ریجکت شود و کندل‌ها ضعیف‌تر شوند",
        },
    }

    invalidator = None
    if direction == "long" and geom:
        invalidator = f"شکست و بسته‌شدن زیر استاپ/دیوار {geom['stop']:.6g}"
    elif direction == "short" and geom:
        invalidator = f"شکست و بسته‌شدن بالای استاپ/دیوار {geom['stop']:.6g}"

    return {
        "ok": True,
        "symbol": symbol,
        "verdict": verdict,
        "direction": direction if verdict == "SETUP" else (direction if direction != "flat" else "flat"),
        "decide_tf": DECIDE_TF,
        "score": round(total, 4),
        "confidence": round(min(1.0, abs(total)), 4),
        "by_tf": {tf: {k: v for k, v in by_tf[tf].items() if not k.startswith("_")} for tf in TFS},
        "params": params,
        "trigger": d15.get("trigger"),
        "reentry": d15.get("reentry"),
        "wall": d15.get("wall"),
        "geometry": geom if verdict == "SETUP" else geom,
        "dominance": dominance,
        "alarms": alarms,
        "scenarios": scenarios,
        "invalidator_fa": invalidator,
        "why_fa": why,
        "gates": gates(),
        "method": "hamid_method_v3",
        "applies_to": "all_symbols",
    }


def _alarms(by_tf: dict, direction: str) -> dict[str, Any]:
    """دو نقطهٔ آلارم وقتی ستاپ نیست."""
    points: list[float] = []
    for tf in ("1h", "15m", "4h"):
        w = by_tf.get(tf, {}).get("walls") or {}
        for side in ("below", "above"):
            b = w.get(side)
            if b:
                points.append(float(b["mid"]))
        chans = by_tf.get(tf, {}).get("channels") or []
        if chans:
            points.append(float(chans[0]["upper"]))
            points.append(float(chans[0]["lower"]))
    points = sorted(set(round(p, 8) for p in points))
    price = by_tf.get("15m", {}).get("price") or by_tf.get("1h", {}).get("price")
    if price and points:
        below = [p for p in points if p < price]
        above = [p for p in points if p > price]
        a1 = below[-1] if below else (points[0] if points else None)
        a2 = above[0] if above else (points[-1] if points else None)
    else:
        a1 = points[0] if points else None
        a2 = points[1] if len(points) > 1 else None
    return {
        "alarm_1": a1,
        "alarm_2": a2,
        "note_fa": "آلارم بگذار و برو ارز بعدی",
    }


def confirm(guardian_direction: str, ghoghnoos: dict[str, Any]) -> dict[str, Any]:
    """تأیید نگهبان نسبت به حکم ققنوس."""
    gdir = ghoghnoos.get("direction")
    gver = ghoghnoos.get("verdict")
    if gver in ("FLAT", "BLIND") or gdir in (None, "flat"):
        return {"tag": None, "mult": 1.0, "note_fa": "ققنوس حکمی ندارد؛ دستکاری نمی‌شود"}
    if guardian_direction == gdir:
        return {"tag": "تأیید ققنوس", "mult": 1.10, "note_fa": "هم‌جهت با ققنوس"}
    return {"tag": "بدون تأیید ققنوس", "mult": 0.50, "note_fa": "خلاف ققنوس"}
