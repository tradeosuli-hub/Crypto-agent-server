"""
دفتر تصمیم نهایی — یک چرخهٔ کامل سازمان روی خروجی پنل ققنوس.

برای هر ارز:
  گزارش ۹ دپارتمان → حافظهٔ تجربه → اجماع وزنی → A34 → دروازهٔ ریسک → تصمیم
دروازهٔ ریسک: SETUP ققنوس پیش‌نیاز است (بدون آن فقط WATCH)، هندسه معتبر، R:R ≥ ۱.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from phoenix.org.consensus import devils_advocate, weighted_consensus
from phoenix.org.departments import BASE_WEIGHTS, DEPT_FA, department_reports
from phoenix.org.memory import Memory
from phoenix.org.outcomes import judge_open_decisions, manual_close


def _decision_id(symbol: str, direction: str, entry: float, ts: str) -> str:
    raw = f"{symbol}|{direction}|{entry}|{ts[:13]}"
    return "D" + hashlib.sha1(raw.encode()).hexdigest()[:10]


def decide_symbol(result: dict[str, Any], memory: Memory, *, now: datetime, data_age_sec: float = 0.0) -> dict[str, Any]:
    regime, reports = department_reports(result, memory)
    consensus = weighted_consensus(reports, regime, memory)
    advocate = devils_advocate(
        consensus, reports, result,
        open_positions=len(memory.open_decisions()),
        data_age_sec=data_age_sec,
    )
    gh_verdict = result.get("verdict")
    gh_dir = result.get("direction")
    geom = result.get("geometry") or {}

    # دروازهٔ ریسک
    gate: list[str] = []
    if gh_verdict != "SETUP":
        gate.append("ققنوس SETUP ندارد (ماشهٔ ۱۵دقیقه/حد نصاب) → فقط WATCH")
    if gh_verdict == "SETUP" and consensus["direction"] != gh_dir:
        gate.append(f"جهت شورا ({consensus['direction']}) با ققنوس ({gh_dir}) یکی نیست")
    if not geom.get("valid"):
        gate.append("هندسه نامعتبر")
    if memory.has_open(result.get("symbol", "")):
        gate.append("همین ارز تصمیم باز دارد")

    # ترتیب: بدون SETUP ققنوس چیزی برای وتو نیست → حکم ققنوس (WATCH/FLAT/BLIND) با رأی مشورتی شورا.
    # روی SETUP واقعی: وتوی A34 → VETO · ایراد دروازه → HOLD · وگرنه SIGNAL
    if gh_verdict != "SETUP":
        final = gh_verdict or "FLAT"
    elif advocate["veto"]:
        final = "VETO"
    elif gate:
        final = "HOLD"
    else:
        final = "SIGNAL"

    decision: dict[str, Any] | None = None
    if final == "SIGNAL":
        ts = now.isoformat()
        decision = {
            "id": _decision_id(result["symbol"], gh_dir, float(geom["entry"]), ts),
            "ts": ts,
            "status": "open",
            "symbol": result["symbol"],
            "direction": gh_dir,
            "entry": geom["entry"],
            "stop": geom["stop"],
            "targets": geom.get("targets") or [],
            "rr1": geom.get("rr1"),
            "leverage": geom.get("leverage"),
            "regime": regime,
            "wall_verdict": (result.get("wall") or {}).get("verdict"),
            "confidence": advocate["confidence"],
            "consensus_strength": consensus["strength"],
            "weights": consensus["weights"],
            "votes": consensus["votes"],
            "objections": advocate["objections"],
            "why_fa": (result.get("why_fa") or [])[:4],
        }
        memory.add_decision(decision)

    return {
        "symbol": result.get("symbol"),
        "ghoghnoos": gh_verdict,
        "direction": consensus["direction"],
        "final": final,
        "regime": regime,
        "strength": consensus["strength"],
        "confidence": advocate["confidence"],
        "conflict": consensus["conflict"],
        "departments_reporting": consensus["departments_reporting"],
        "weights": consensus["weights"],
        "votes": consensus["votes"],
        "vetoes": advocate["vetoes"],
        "objections": advocate["objections"],
        "gate_fa": gate,
        "decision_id": decision["id"] if decision else None,
    }


def board(memory: Memory, regime_hint: str | None = None) -> dict[str, Any]:
    """تابلوی Mission Control: وزن پایه، دقت، تعداد نمونه به تفکیک دپارتمان."""
    rows = []
    for dept, base in BASE_WEIGHTS.items():
        regimes = memory.data["accuracy"].get(dept, {})
        n = sum(int(v.get("n", 0)) for v in regimes.values())
        acc_hint = memory.accuracy(dept, regime_hint) if regime_hint else None
        avg = round(sum(float(v.get("acc", 0.5)) for v in regimes.values()) / len(regimes), 3) if regimes else 0.5
        rows.append({
            "dept": dept,
            "fa": DEPT_FA[dept],
            "base_weight": base,
            "accuracy_avg": avg,
            "accuracy_regime": acc_hint,
            "samples": n,
            "regimes": regimes,
        })
    return {
        "departments": rows,
        "counters": memory.data["counters"],
        "open_decisions": memory.open_decisions(),
        "closed_recent": [d for d in memory.data["decisions"] if d.get("status") == "closed"][-30:],
        "experience_recent": memory.data["experience"][-30:],
        "audits": memory.data["audits"][-10:],
    }


def run_org_cycle(
    results: list[dict[str, Any]],
    memory: Memory,
    fetch_klines: Callable[[str, str, int], pd.DataFrame] | None = None,
    *,
    manual_close_spec: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    ۱) داوری تصمیم‌های باز (یادگیری از نتیجه)  ۲) تصمیم تازه برای هر ارز  ۳) تابلو
    manual_close_spec: "D1234abcd:TP:1.8" برای ثبت دستی نتیجه.
    """
    now = now or datetime.now(timezone.utc)
    learned: list[dict[str, Any]] = []
    if manual_close_spec:
        parts = manual_close_spec.split(":")
        if len(parts) >= 2:
            exp = manual_close(memory, parts[0].strip(), parts[1].strip(),
                               float(parts[2]) if len(parts) > 2 and parts[2].strip() else None)
            if exp:
                learned.append(exp)
    if fetch_klines is not None:
        learned.extend(judge_open_decisions(memory, fetch_klines, now))

    rows = []
    for r in results:
        if not r.get("ok", True):
            continue
        try:
            rows.append(decide_symbol(r, memory, now=now))
        except Exception as exc:  # noqa: BLE001
            rows.append({"symbol": r.get("symbol"), "final": "ERROR", "error": str(exc)})
    order = {"SIGNAL": 0, "VETO": 1, "HOLD": 2, "WATCH": 3, "FLAT": 4, "BLIND": 5, "ERROR": 6}
    rows.sort(key=lambda x: (order.get(x.get("final"), 9), -(x.get("confidence") or 0)))
    signals = [row for row in rows if row["final"] == "SIGNAL"]
    regime_hint = rows[0]["regime"] if rows and rows[0].get("regime") else None
    return {
        "generated_at": now.isoformat(),
        "flow_fa": "دپارتمان‌ها → حافظهٔ تجربه → اجماع وزنی → A34 → دروازهٔ ریسک → تصمیم نهایی → قاضی نتیجه → تجربه",
        "signals": signals,
        "new_decisions": [memory.find_decision(s["decision_id"]) for s in signals if s.get("decision_id")],
        "learned_now": learned,
        "rows": rows,
        "board": board(memory, regime_hint),
    }
