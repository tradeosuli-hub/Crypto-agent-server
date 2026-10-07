"""تست قوانین سازمان — اجماع، A34، قاضی نتیجه، یادگیری."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from phoenix.org.consensus import devils_advocate, effective_weights, weighted_consensus  # noqa: E402
from phoenix.org.departments import BASE_WEIGHTS, department_reports  # noqa: E402
from phoenix.org.memory import Memory  # noqa: E402
from phoenix.org.office import decide_symbol, run_org_cycle  # noqa: E402
from phoenix.org.outcomes import judge_decision, manual_close  # noqa: E402


def _mem() -> Memory:
    return Memory(tempfile.mkdtemp())


def _rep(dept, direction, strength, silent=False, flags=None):
    return {"dept": dept, "direction": direction, "strength": strength, "silent": silent, "flags": flags or [], "note_fa": ""}


def _result(verdict="SETUP", direction="long", wall="solid", price=100.0):
    return {
        "ok": True,
        "symbol": "TESTUSDT",
        "verdict": verdict,
        "direction": direction,
        "dominance": {"ok": True, "bias": "risk_on", "btc_ret_24h": 0.03, "root_fa": "x"},
        "wall": {"mid": 98.0, "verdict": wall, "reactions": 3},
        "geometry": {"entry": 100.0, "stop": 97.0, "targets": [106.0, 110.0], "rr1": 2.0, "leverage": 5, "valid": True},
        "params": {"items": {"volume": {"ok": True, "blind": False, "fa": "حجم"}, "news_events": {"ok": None, "blind": True},
                             "fvg_inside_ob": {"ok": True, "blind": False}, "trendline": {"ok": True, "blind": False}}},
        "by_tf": {
            "4h": {"direction": "long", "structure": {"bos": "bull", "trend": "up", "choch": None}},
            "1h": {"direction": "long", "structure": {"bos": None, "trend": "up", "choch": None}},
            "15m": {"direction": direction, "price": price,
                    "structure": {"bos": "bull", "trend": "up", "choch": None},
                    "channels": [{"upper": 104.0, "lower": 96.0}],
                    "trigger": {"direction": direction, "shadow_ratio": 2.0, "penetration": 0.5},
                    "reentry": None, "wall": {"mid": 98.0, "verdict": wall, "reactions": 3}},
        },
        "why_fa": ["ماشه"],
    }


def test_base_weights_locked_and_sum_to_one():
    assert abs(sum(BASE_WEIGHTS.values()) - 1.0) < 1e-9
    assert BASE_WEIGHTS["dominance"] == 0.20 and BASE_WEIGHTS["structure"] == 0.20


def test_effective_weights_follow_accuracy_and_normalize():
    mem = _mem()
    reps = [_rep("dominance", "long", .8), _rep("structure", "long", .8), _rep("liquidity", "long", .6)]
    w0 = effective_weights(reps, "r", mem)
    assert abs(sum(w0.values()) - 1.0) < 1e-6
    for _ in range(10):
        mem.update_accuracy("structure", "r", True)
        mem.update_accuracy("dominance", "r", False)
    w1 = effective_weights(reps, "r", mem)
    assert w1["structure"] > w0["structure"] and w1["dominance"] < w0["dominance"]


def test_no_single_agent_signal_and_conflict_veto():
    mem = _mem()
    one = [_rep("structure", "long", .9)] + [_rep(d, "flat", 0, silent=True) for d in ("dominance", "liquidity")]
    c = weighted_consensus(one, "r", mem)
    a = devils_advocate(c, one, _result(), open_positions=0, data_age_sec=0)
    assert a["veto"] and any("دپارتمان" in v for v in a["vetoes"])

    reps = [_rep("structure", "long", .9), _rep("liquidity", "short", 1.0), _rep("volume", "long", .5)]
    c = weighted_consensus(reps, "r", mem)
    assert c["conflict"]
    a = devils_advocate(c, reps, _result(), open_positions=0, data_age_sec=0)
    assert a["veto"]


def test_dominance_supremacy_requires_dual_confirmation():
    mem = _mem()
    reps = [_rep("dominance", "short", .9), _rep("structure", "long", .5), _rep("liquidity", "long", .5),
            _rep("volume", "long", .5), _rep("pattern", "long", .9), _rep("order_block", "long", .9)]
    c = weighted_consensus(reps, "r", mem)
    a = devils_advocate(c, reps, _result(), open_positions=0, data_age_sec=0)
    assert c["direction"] == "long"
    assert any("دامیننس" in v for v in a["vetoes"])
    reps[1]["strength"] = reps[2]["strength"] = 0.7
    c = weighted_consensus(reps, "r", mem)
    a = devils_advocate(c, reps, _result(), open_positions=0, data_age_sec=0)
    assert not any("دامیننس" in v for v in a["vetoes"])


def test_hard_vetoes_stale_channel_break_max_positions():
    mem = _mem()
    reps = [_rep("dominance", "long", .8), _rep("structure", "long", .8, flags=["channel_break_without_pullback"]),
            _rep("liquidity", "long", .8)]
    c = weighted_consensus(reps, "r", mem)
    a = devils_advocate(c, reps, _result(), open_positions=4, data_age_sec=5 * 3600)
    joined = " ".join(a["vetoes"])
    assert "پولبک" in joined and "کهنه" in joined and "سقف" in joined


def test_departments_from_real_result_and_ob_without_history_is_zero_weight():
    mem = _mem()
    regime, reps = department_reports(_result(wall="untested"), mem)
    assert regime == "risk_on/up"
    ob = next(r for r in reps if r["dept"] == "order_block")
    assert ob["silent"] and "ob_no_history" in ob["flags"]
    assert sum(1 for r in reps if not r["silent"]) >= 3


def test_office_signal_requires_ghoghnoos_setup_and_records_decision():
    mem = _mem()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = decide_symbol(_result(verdict="WATCH"), mem, now=now)
    assert row["final"] == "WATCH" and not mem.open_decisions()
    row = decide_symbol(_result(verdict="SETUP"), mem, now=now)
    assert row["final"] == "SIGNAL", row
    assert len(mem.open_decisions()) == 1
    # همان ارز دوباره → تصمیم باز دارد → سیگنال تکراری نمی‌دهد
    row2 = decide_symbol(_result(verdict="SETUP"), mem, now=now)
    assert row2["final"] != "SIGNAL"


def _candles(start: datetime, path: list[tuple[float, float, float]]) -> pd.DataFrame:
    rows = []
    for i, (lo, hi, close) in enumerate(path):
        rows.append({"open_time": start + timedelta(minutes=15 * i), "open": close, "high": hi, "low": lo, "close": close, "volume": 1.0})
    return pd.DataFrame(rows)


def test_judge_tp_sl_expired_and_learning_updates_accuracy():
    mem = _mem()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decide_symbol(_result(verdict="SETUP"), mem, now=now)
    d = mem.open_decisions()[0]
    # TP: ورود لمس، سپس تارگت
    tp_path = _candles(now, [(99.5, 100.5, 100.2), (100.0, 103.0, 102.5), (102.0, 106.5, 106.0)])
    v = judge_decision(dict(d), tp_path, now)
    assert v["outcome"] == "TP" and v["pnl_r"] == 2.0
    # SL
    sl_path = _candles(now, [(99.5, 100.5, 100.2), (96.5, 100.0, 97.5)])
    assert judge_decision(dict(d), sl_path, now)["outcome"] == "SL"
    # expired: ورود هرگز لمس نشد در ۴۸ ساعت
    far = [(110.0, 111.0, 110.5)] * 200
    assert judge_decision(dict(d), _candles(now, far), now)["outcome"] == "expired"

    # یادگیری از طریق چرخه با fetch_klines ساختگی
    out = run_org_cycle([], mem, fetch_klines=lambda s, tf, n: tp_path, now=now)
    assert out["learned_now"] and out["learned_now"][0]["outcome"] == "TP"
    assert mem.data["counters"]["tp"] == 1
    assert mem.accuracy("structure", "risk_on/up") > 0.5
    assert mem.data["experience"][-1]["symbol"] == "TESTUSDT"


def test_manual_close_and_audit_every_ten():
    mem = _mem()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(10):
        r = _result(verdict="SETUP")
        r["symbol"] = f"S{i}USDT"
        row = decide_symbol(r, mem, now=now + timedelta(minutes=i))
        if row["final"] == "SIGNAL":
            manual_close(mem, row["decision_id"], "TP", 1.5)
        else:
            # سقف ۴ پوزیشن باز → وتو؛ پس اول بسته می‌کنیم
            pass
    assert mem.data["counters"]["closed"] >= 1
    # تا ۱۰ بسته‌شده ممیزی تولید شود
    while mem.data["counters"]["closed"] < 10:
        r = _result(verdict="SETUP")
        r["symbol"] = f"X{mem.data['counters']['closed']}USDT"
        row = decide_symbol(r, mem, now=now)
        assert row["final"] == "SIGNAL", row
        manual_close(mem, row["decision_id"], "SL")
    assert mem.data["audits"] and mem.data["audits"][-1]["level"] == 10
    mem.save()
    again = Memory(mem.root)
    assert again.data["counters"]["closed"] == 10


def test_veto_only_applies_to_real_setups():
    mem = _mem()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    weak = _result(verdict="WATCH")
    weak["by_tf"]["15m"]["channels"] = [{"upper": 99.0, "lower": 90.0}]  # شکست کانال بدون پولبک
    row = decide_symbol(weak, mem, now=now)
    assert row["final"] == "WATCH" and row["vetoes"]  # رأی مشورتی ثبت می‌شود ولی حکم WATCH می‌ماند
    strong = _result(verdict="SETUP")
    strong["by_tf"]["15m"]["channels"] = [{"upper": 99.0, "lower": 90.0}]
    row = decide_symbol(strong, mem, now=now)
    assert row["final"] == "VETO" and any("پولبک" in v for v in row["vetoes"])
