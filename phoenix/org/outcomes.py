"""
قاضی نتیجه + موتور ریشه‌یابی + موتور تجربه.

هر تصمیم باز با کندل‌های ۱۵دقیقهٔ بعد از صدور داوری می‌شود:
  ورود لمس شد؟ → اول استاپ یا اول تارگت۱؟ → TP / SL / expired / timeout
سپس ریشه‌یابی: کدام دپارتمان‌ها درست رأی دادند، کدام غلط → دقت غلتان به‌روز می‌شود
و یک «تجربه» به حافظهٔ دائمی اضافه می‌شود.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from phoenix.org.memory import Memory

ENTRY_WINDOW = timedelta(hours=48)
RESULT_WINDOW = timedelta(days=5)
AUDIT_EVERY = (10, 100, 1000)


def _ts(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def judge_decision(decision: dict[str, Any], candles: pd.DataFrame, now: datetime) -> dict[str, Any] | None:
    """خروجی: {"outcome": TP|SL|expired|timeout, "exit": float, "pnl_r": float, "closed_at": iso} یا None اگر هنوز باز است."""
    entry = float(decision["entry"])
    stop = float(decision["stop"])
    tp1 = float(decision["targets"][0]) if decision.get("targets") else None
    direction = decision["direction"]
    opened = _ts(decision["ts"])
    risk = abs(entry - stop) or 1e-12
    entered_at: datetime | None = None
    if decision.get("entered_at"):
        entered_at = _ts(decision["entered_at"])

    if candles is None or candles.empty:
        return None
    has_col = "open_time" in candles.columns
    for ts, row in candles.iterrows():
        t = row["open_time"] if has_col else ts
        t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t < opened:
            continue
        hi, lo = float(row["high"]), float(row["low"])
        if entered_at is None:
            if lo <= entry <= hi:
                entered_at = t
                decision["entered_at"] = t.isoformat()
            elif t - opened > ENTRY_WINDOW:
                return {"outcome": "expired", "exit": None, "pnl_r": 0.0, "closed_at": t.isoformat()}
            else:
                continue
        # پس از ورود: استاپ همیشه اول بررسی می‌شود (محافظه‌کارانه)
        if direction == "long":
            if lo <= stop:
                return {"outcome": "SL", "exit": stop, "pnl_r": -1.0, "closed_at": t.isoformat()}
            if tp1 is not None and hi >= tp1:
                return {"outcome": "TP", "exit": tp1, "pnl_r": round((tp1 - entry) / risk, 3), "closed_at": t.isoformat()}
        else:
            if hi >= stop:
                return {"outcome": "SL", "exit": stop, "pnl_r": -1.0, "closed_at": t.isoformat()}
            if tp1 is not None and lo <= tp1:
                return {"outcome": "TP", "exit": tp1, "pnl_r": round((entry - tp1) / risk, 3), "closed_at": t.isoformat()}
        if t - entered_at > RESULT_WINDOW:
            last = float(row["close"])
            pnl = (last - entry) / risk if direction == "long" else (entry - last) / risk
            return {"outcome": "timeout", "exit": last, "pnl_r": round(pnl, 3), "closed_at": t.isoformat()}
    return None


def root_cause(decision: dict[str, Any], outcome: str) -> dict[str, Any]:
    """کدام دپارتمان‌ها درست بودند، کدام غلط."""
    direction = decision["direction"]
    votes = decision.get("votes") or {}
    right, wrong, silent = [], [], []
    for dept, v in votes.items():
        if v.get("silent"):
            silent.append(dept)
            continue
        agreed = v.get("direction") == direction
        if outcome == "TP":
            (right if agreed else wrong).append(dept)
        elif outcome == "SL":
            (wrong if agreed else right).append(dept)
    lesson = []
    if outcome == "SL":
        if "channel_break_without_pullback" in {f for v in votes.values() for f in v.get("flags", [])}:
            lesson.append("شکست کانال بدون پولبک باید وتو می‌شد")
        if wrong:
            lesson.append("دپارتمان‌های هم‌جهت که اشتباه کردند: " + "، ".join(wrong))
        if right:
            lesson.append("دپارتمان‌هایی که مخالف بودند و درست گفتند: " + "، ".join(right))
    elif outcome == "TP":
        lesson.append("تأییدکننده‌های درست: " + "، ".join(right) if right else "بدون تأیید قوی")
        if wrong:
            lesson.append("مخالفانی که اشتباه کردند: " + "، ".join(wrong))
    else:
        lesson.append("بدون نتیجهٔ قطعی — دقت تغییر نمی‌کند")
    return {"right": right, "wrong": wrong, "silent": silent, "lesson_fa": " · ".join(lesson)}


def apply_learning(memory: Memory, decision: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    outcome = verdict["outcome"]
    rc = root_cause(decision, outcome)
    regime = decision.get("regime", "unknown")
    if outcome in ("TP", "SL"):
        for dept in rc["right"]:
            memory.update_accuracy(dept, regime, True)
        for dept in rc["wrong"]:
            memory.update_accuracy(dept, regime, False)
    decision.update({
        "status": "closed",
        "outcome": outcome,
        "exit": verdict.get("exit"),
        "pnl_r": verdict.get("pnl_r"),
        "closed_at": verdict.get("closed_at"),
        "root_cause": rc,
    })
    c = memory.data["counters"]
    c["closed"] = int(c.get("closed", 0)) + 1
    key = {"TP": "tp", "SL": "sl"}.get(outcome, "expired")
    c[key] = int(c.get(key, 0)) + 1
    exp = {
        "ts": verdict.get("closed_at"),
        "decision_id": decision["id"],
        "symbol": decision["symbol"],
        "direction": decision["direction"],
        "regime": regime,
        "wall_verdict": decision.get("wall_verdict"),
        "outcome": outcome,
        "pnl_r": verdict.get("pnl_r"),
        "confidence": decision.get("confidence"),
        "lesson_fa": f"{decision['symbol']} {decision['direction']} در رژیم {regime} "
                     f"(دیوار {decision.get('wall_verdict')}) → {outcome} ({verdict.get('pnl_r')}R). {rc['lesson_fa']}",
    }
    memory.add_experience(exp)
    _maybe_audit(memory)
    return exp


def _maybe_audit(memory: Memory) -> None:
    closed = int(memory.data["counters"].get("closed", 0))
    if closed == 0 or not any(closed % n == 0 for n in AUDIT_EVERY):
        return
    level = max(n for n in AUDIT_EVERY if closed % n == 0)
    decs = [d for d in memory.data["decisions"] if d.get("status") == "closed"][-level:]
    tp = sum(1 for d in decs if d.get("outcome") == "TP")
    sl = sum(1 for d in decs if d.get("outcome") == "SL")
    pnl = sum(float(d.get("pnl_r") or 0) for d in decs)
    memory.data["audits"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "closed_total": closed,
        "window": len(decs),
        "tp": tp,
        "sl": sl,
        "win_rate": round(tp / max(tp + sl, 1), 3),
        "sum_r": round(pnl, 3),
        "accuracy_snapshot": memory.data["accuracy"],
    })


def judge_open_decisions(
    memory: Memory,
    fetch_klines: Callable[[str, str, int], pd.DataFrame],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """همهٔ تصمیم‌های باز را داوری می‌کند و تجربه‌های تازه را برمی‌گرداند."""
    now = now or datetime.now(timezone.utc)
    new_exps: list[dict[str, Any]] = []
    for d in memory.open_decisions():
        try:
            candles = fetch_klines(d["symbol"], "15m", 500)
        except Exception as exc:  # noqa: BLE001
            d["judge_error"] = str(exc)
            continue
        verdict = judge_decision(d, candles, now)
        if verdict:
            new_exps.append(apply_learning(memory, d, verdict))
    return new_exps


def manual_close(memory: Memory, decision_id: str, outcome: str, pnl_r: float | None = None) -> dict[str, Any] | None:
    """ثبت دستی نتیجهٔ معامله (مثل run_org.py --close) — ریشه‌یابی خودکار."""
    d = memory.find_decision(decision_id)
    if not d or d.get("status") != "open":
        return None
    outcome = outcome.upper()
    if outcome not in ("TP", "SL"):
        outcome = "timeout"
    verdict = {
        "outcome": outcome,
        "exit": None,
        "pnl_r": float(pnl_r) if pnl_r is not None else (1.0 if outcome == "TP" else -1.0 if outcome == "SL" else 0.0),
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }
    return apply_learning(memory, d, verdict)
