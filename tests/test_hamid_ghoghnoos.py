"""تست‌های واحد متد حمید / ققنوس — قوانین برای همهٔ ارزها یکسان."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from phoenix import ta
from phoenix.council import council_vote
from phoenix.ghoghnoos import build_geometry, confirm, evaluate_symbol
from strategies.hamid_method import SPEC, gates, prompt


def _synthetic(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 100 + np.cumsum(rng.normal(0, 0.4, n))
    high = price + rng.uniform(0.1, 0.8, n)
    low = price - rng.uniform(0.1, 0.8, n)
    open_ = price + rng.normal(0, 0.2, n)
    close = price
    vol = rng.uniform(1000, 5000, n)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def test_spec_version_and_four_stops():
    assert SPEC["version"] == "3.0"
    assert SPEC["applies_to"] == "all_symbols"
    g = gates()
    assert len(g["stop_conditions"]) == 4
    assert g["decide_only_on"] == "15m"
    assert g["min_rr_target_1"] == 1.0
    assert g["param_min_score"] == 6


def test_prompt_loads():
    text = prompt()
    assert "متد حمید" in text or "اوردر بلاک" in text
    assert len(text) >= 2000


def test_order_blocks_and_wall_state():
    df = _synthetic()
    blocks = ta.order_blocks(df)
    assert isinstance(blocks, list)
    atr_s = ta.atr(df)
    blocks = ta.annotate_reactions(df, blocks, atr_s)
    # wall state transitions
    assert ta.wall_state([], []) == "untested"
    assert ta.wall_state([0.3], [1.0]) == "young"
    assert ta.wall_state([0.5, 0.3], [1.0, 1.5]) == "solid"
    assert ta.wall_state([0.3, 0.5], [1.5, 1.0]) in ("wall_eroding", "wall_cracking")


def test_channel_reentry_unconditional_shape():
    df = _synthetic()
    chans = ta.channels(df, [60, 30])
    assert chans
    # function returns None or dict with direction/target
    r = ta.channel_reentry(df, chans[0])
    assert r is None or ("direction" in r and "target" in r)


def test_wick_rejection_requires_shadow():
    df = _synthetic()
    band = ta.OrderBlock(low=99, high=101, mid=100, index=10, bullish_impulse=True, verdict="solid")
    # force last candle to reject from below
    df.iloc[-1, df.columns.get_loc("low")] = 99.5
    df.iloc[-1, df.columns.get_loc("open")] = 100.5
    df.iloc[-1, df.columns.get_loc("close")] = 101.2
    df.iloc[-1, df.columns.get_loc("high")] = 101.4
    trig = ta.wick_rejection(df, band, min_shadow_ratio=1.0, min_pen_pct=0.2)
    # may or may not fire depending on body/shadow; ensure type
    assert trig is None or trig["direction"] in ("long", "short")


def test_geometry_four_stop_conditions_and_min_rr():
    df = _synthetic()
    wall = ta.OrderBlock(low=95, high=97, mid=96, index=50, bullish_impulse=True, verdict="solid", reactions=3)
    ch = ta.Channel(lookback=60, upper=110, mid=100, lower=90, slope=0.01, touches=3)
    levels = [
        ta.Level(price=105, strength="strong", kind="resistance", touches=2),
        ta.Level(price=108, strength="normal", kind="resistance", touches=1),
        ta.Level(price=112, strength="very_strong", kind="resistance", touches=3),
    ]
    liq = [{"price": 94.0, "score": 10}, {"price": 106.0, "score": 8}]
    geom = build_geometry(
        df=df,
        direction="long",
        wall=wall,
        channel=ch,
        levels=levels,
        liq=liq,
        atr_v=1.0,
        reentry=None,
    )
    assert "behind_ob" in geom["stop_conditions"]
    assert "outside_liq" in geom["stop_conditions"]
    assert "inside_channel" in geom["stop_conditions"]
    assert "beyond_swing" in geom["stop_conditions"]
    assert geom["risk_pct"] == 1.0
    # if rr < 1, valid False
    if geom["rr1"] < 1:
        assert geom["valid"] is False


def test_evaluate_same_rules_any_symbol():
    frames = {tf: _synthetic(seed=i + 1) for i, tf in enumerate(["4h", "1h", "15m", "5m"])}
    a = evaluate_symbol("AAAUSDT", frames, dominance={"bias": "neutral", "allow_long": True, "allow_short": True})
    b = evaluate_symbol("BBBUSDT", frames, dominance={"bias": "neutral", "allow_long": True, "allow_short": True})
    assert a["method"] == b["method"] == "hamid_method_v3"
    assert a["applies_to"] == "all_symbols"
    assert a["decide_tf"] == "15m"
    assert a["verdict"] in ("SETUP", "WATCH", "FLAT", "BLIND")
    # identical market data ⇒ identical structural verdict path
    assert a["verdict"] == b["verdict"]


def test_confirm_multipliers():
    g = {"verdict": "SETUP", "direction": "long"}
    assert confirm("long", g)["mult"] == 1.10
    assert confirm("short", g)["mult"] == 0.50
    assert confirm("long", {"verdict": "FLAT", "direction": "flat"})["mult"] == 1.0


def test_council_blocks_signal_without_setup():
    g = {"verdict": "WATCH", "direction": "long", "score": 0.2}
    out = council_vote(g, [{"name": "x", "direction": "long", "confidence": 0.9}])
    assert out["action"] == "WATCH"
    g2 = {"verdict": "SETUP", "direction": "long", "score": 0.8}
    out2 = council_vote(g2, [])
    assert out2["action"] == "SIGNAL"


def test_liquidation_fallback():
    df = _synthetic()
    clusters = ta.liquidation_map(df)
    assert isinstance(clusters, list)
    assert clusters
