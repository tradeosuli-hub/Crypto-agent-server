"""دفتر اجماع وزنی + وکیل مدافع شیطان (A34) — طبق ORG_RUNTIME_FA.md"""
from __future__ import annotations

from typing import Any

from phoenix.org.departments import BASE_WEIGHTS
from phoenix.org.memory import Memory

MIN_DEPARTMENTS = 3
MIN_STRENGTH = 0.35
CONFLICT_RATIO = 0.60
MAX_OPEN_POSITIONS = 4
STALE_SEC = 4 * 3600
DUAL_CONFIRM_MIN = 0.60
BIG_OBJECTION = 0.15
SMALL_OBJECTION = 0.05


def effective_weights(reports: list[dict[str, Any]], regime: str, memory: Memory) -> dict[str, float]:
    """وزن مؤثر = وزن پایه × (۰٫۵ + دقت غلتان همان دپارتمان در همان رژیم)، سپس نرمال به ۱."""
    raw: dict[str, float] = {}
    for r in reports:
        if r["silent"]:
            continue
        base = BASE_WEIGHTS.get(r["dept"], 0.0)
        raw[r["dept"]] = base * (0.5 + memory.accuracy(r["dept"], regime))
    total = sum(raw.values()) or 1.0
    return {k: round(v / total, 6) for k, v in raw.items()}


def weighted_consensus(reports: list[dict[str, Any]], regime: str, memory: Memory) -> dict[str, Any]:
    weights = effective_weights(reports, regime, memory)
    mass = {"long": 0.0, "short": 0.0}
    reporting = [r for r in reports if not r["silent"]]
    for r in reporting:
        if r["direction"] in mass:
            mass[r["direction"]] += weights.get(r["dept"], 0.0) * r["strength"]
    if mass["long"] == mass["short"]:
        direction = "flat"
    else:
        direction = "long" if mass["long"] > mass["short"] else "short"
    agree = mass[direction] if direction != "flat" else 0.0
    oppose = mass["short" if direction == "long" else "long"] if direction != "flat" else 0.0
    strength = round(abs(mass["long"] - mass["short"]), 4)
    conflict = direction != "flat" and oppose > CONFLICT_RATIO * agree and oppose > 0
    return {
        "direction": direction,
        "strength": strength,
        "mass": {k: round(v, 4) for k, v in mass.items()},
        "weights": weights,
        "departments_reporting": len(reporting),
        "conflict": conflict,
        "regime": regime,
        "votes": {r["dept"]: {"direction": r["direction"], "strength": r["strength"],
                             "silent": r["silent"], "flags": r["flags"], "note_fa": r["note_fa"]}
                  for r in reports},
    }


def _dept(reports: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for r in reports:
        if r["dept"] == name:
            return r
    return None


def devils_advocate(
    consensus: dict[str, Any],
    reports: list[dict[str, Any]],
    result: dict[str, Any],
    *,
    open_positions: int,
    data_age_sec: float,
) -> dict[str, Any]:
    """A34 — وتوی قطعی یا اعتراض. فقط حقایق کد را می‌بیند، نه سلیقه."""
    vetoes: list[str] = []
    objections: list[tuple[str, float]] = []
    flags = {f for r in reports for f in r["flags"]}
    direction = consensus["direction"]

    if consensus["departments_reporting"] < MIN_DEPARTMENTS:
        vetoes.append(f"کمتر از {MIN_DEPARTMENTS} دپارتمان گزارش دادند")
    if direction == "flat":
        vetoes.append("اجماع بدون جهت")
    if consensus["strength"] < MIN_STRENGTH:
        vetoes.append(f"قدرت اجماع {consensus['strength']:.2f} < {MIN_STRENGTH}")
    if consensus["conflict"]:
        vetoes.append("تضاد دپارتمان‌ها (جرم مخالف > ۶۰٪ موافق)")
    if "high_risk_news" in flags:
        vetoes.append("رویداد خبری پرریسک")
    if data_age_sec > STALE_SEC:
        vetoes.append("دادهٔ کهنه (> ۴ ساعت)")
    if "channel_break_without_pullback" in flags:
        vetoes.append("شکست کانال بدون پولبک")
    if open_positions >= MAX_OPEN_POSITIONS:
        vetoes.append(f"سقف {MAX_OPEN_POSITIONS} پوزیشن باز پر است")

    # USDT.D بر هر اندیکاتوری برتری دارد — خلاف دامیننس فقط با تأیید دوگانه
    dom = _dept(reports, "dominance")
    if dom and not dom["silent"] and dom["direction"] not in ("flat", direction) and direction != "flat":
        st = _dept(reports, "structure")
        liq = _dept(reports, "liquidity")
        dual = (
            st and liq and st["direction"] == direction and liq["direction"] == direction
            and st["strength"] >= DUAL_CONFIRM_MIN and liq["strength"] >= DUAL_CONFIRM_MIN
        )
        if not dual:
            vetoes.append("خلاف دامیننس بدون تأیید دوگانهٔ ساختار و لیکوئیدیتی (هر دو ≥ ۰٫۶)")

    # اعتراض بزرگ: ورود خلاف H4 خارج از لبهٔ کانال
    h4_dir = ((result.get("by_tf") or {}).get("4h") or {}).get("direction")
    d15 = (result.get("by_tf") or {}).get("15m") or {}
    chans = d15.get("channels") or []
    price = d15.get("price")
    if direction != "flat" and h4_dir not in (None, "flat", direction) and chans and price:
        outer = chans[0]
        band = max(outer["upper"] - outer["lower"], 1e-12)
        at_edge = (
            (direction == "long" and (price - outer["lower"]) / band <= 0.2)
            or (direction == "short" and (outer["upper"] - price) / band <= 0.2)
        )
        if not at_edge:
            objections.append(("ورود خلاف H4 خارج از لبهٔ کانال", BIG_OBJECTION))
    if "weak_volume" in flags:
        objections.append(("حجم ضعیف", SMALL_OBJECTION))

    penalty = round(sum(p for _, p in objections), 3)
    confidence = round(max(0.0, consensus["strength"] - penalty), 4)
    return {
        "veto": bool(vetoes),
        "vetoes": vetoes,
        "objections": [{"fa": fa, "penalty": p} for fa, p in objections],
        "penalty": penalty,
        "confidence": confidence,
    }
