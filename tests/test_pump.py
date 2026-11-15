"""تست ایجنت پامپ: تشخیص ≥۸٪/۱۵m، عوامل، شباهت‌یابی، پیگیری/یادگیری، اختیار ۵٪."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from phoenix.notify import fmt_pump  # noqa: E402
from phoenix.pump import agent, sources  # noqa: E402

NOW = datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc)


def _row(sym: str, c15: float, **kw):
    base = {"symbol": sym, "pair": sym + "USDT", "price": 1.0, "change_15m": c15, "change_15m_src": "binance",
            "change_1h": c15 + 2, "change_24h": c15 + 5, "change_7d": 30.0, "market_cap": 20e6, "volume_24h": 50e6,
            "rank": 400, "ath_change": -90.0, "tags": ["memes", "solana-ecosystem"], "cg_id": None, "name": sym,
            "date_added": None, "trending": True}
    base.update(kw)
    return base


def _snapshot(rows: dict, btc_15m: float = 0.2):
    return {"rows": rows, "snapshot": {"_ts": NOW.isoformat()}, "sources_ok": ["binance", "coingecko", "coinmarketcap"],
            "trending": [], "btc_15m": btc_15m, "btc_1h": 0.5, "universe": {"binance": 1}}


def test_symbol_filter_rejects_non_ascii_and_stables():
    assert sources.is_tradeable_base("SOL")
    assert not sources.is_tradeable_base("牛来")
    assert not sources.is_tradeable_base("USDC")
    assert not sources.is_tradeable_base("BTCUP")


def test_tags_compact_and_mcap_tier():
    assert agent.compact_tags(["Memes", "Solana Ecosystem", "ai-big-data"]) == ["tag:meme", "tag:solana-eco", "tag:ai"]
    assert agent.mcap_tier(10e6) == "micro_cap" and agent.mcap_tier(2e9) == "mid_cap" and agent.mcap_tier(None) == "micro_cap"


def test_autonomy_clamp_is_five_percent():
    p = agent.clamp_params({"threshold_pct": 20, "numeric_weight": 0.1, "watch_pct": 5.1})
    assert p["threshold_pct"] == 8.4 and p["numeric_weight"] == round(0.55 * 0.95, 4) and p["watch_pct"] == 5.1
    assert agent.clamp_params({})["min_similarity"] == 0.45


def test_detects_pump_and_watch_tier(monkeypatch):
    monkeypatch.setattr(sources, "binance_volume_spike", lambda *_a, **_k: {"vol_spike": 4.0, "vol_pre_spike": 1.0, "green_streak": 3,
                                                                              "ret_1h": 9.0, "ret_4h": 12.0})
    rows = {"AAA": _row("AAA", 9.5), "BBB": _row("BBB", 6.0), "CCC": _row("CCC", 1.0), "BTC": _row("BTC", 0.2)}
    state, events = {}, []
    intel = {"market": {"fear_greed": 20}, "symbols": {"AAAUSDT": {"events": ["listing"], "sentiment": 0.6, "risk": 0.0}},
             "items": [{"title": "Binance lists AAA", "symbols": ["AAAUSDT"]}], "social": {"AAAUSDT": {"hot": True}}}
    res = agent.run_cycle(state, events, intel, snapshot=_snapshot(rows), now=NOW)
    assert [e["symbol"] for e in res["new_events"]] == ["AAA"]
    assert [w["symbol"] for w in res["watch"]] == ["BBB"]
    ev = events[0]
    for f in ("heavy_money", "green_streak", "trending", "social_hot", "deep_drawdown", "weekly_uptrend", "fear_extreme",
              "us_session", "micro_cap", "news_listing", "news_positive", "tag:meme"):
        assert f in ev["factors"], f
    assert ev["pattern_fa"].startswith("الگوی مشابهی در حافظه نیست")
    assert 0 <= ev["attention"] <= 1 and ev["attention_fa"]
    assert state["params"] == agent.LOCKED_PARAMS and state["cycle"] == 1
    assert "AAA" in state["opinion_fa"]
    txt = fmt_pump(ev)
    assert "AAA" in txt and "+9.5" in txt and "حواس‌جمعی" in txt


def test_same_symbol_cooldown_updates_max_not_duplicate(monkeypatch):
    monkeypatch.setattr(sources, "binance_volume_spike", lambda *_a, **_k: None)
    rows = {"AAA": _row("AAA", 9.0)}
    state, events = {}, []
    agent.run_cycle(state, events, None, snapshot=_snapshot(rows), now=NOW)
    rows2 = {"AAA": _row("AAA", 12.0)}
    res = agent.run_cycle(state, events, None, snapshot=_snapshot(rows2), now=NOW + timedelta(minutes=15))
    assert not res["new_events"] and len(events) == 1 and events[0]["max_change_15m"] == 12.0


def test_similarity_finds_past_pump_with_shared_factors(monkeypatch):
    monkeypatch.setattr(sources, "binance_volume_spike", lambda *_a, **_k: {"vol_spike": 5.0, "vol_pre_spike": 2.5, "green_streak": 4,
                                                                              "ret_1h": 10.0, "ret_4h": 10.0})
    state, events = {}, []
    agent.run_cycle(state, events, None, snapshot=_snapshot({"AAA": _row("AAA", 10.0)}), now=NOW - timedelta(days=2))
    res = agent.run_cycle(state, events, None, snapshot=_snapshot({"ZZZ": _row("ZZZ", 11.0)}), now=NOW)
    ev = res["new_events"][0]
    assert ev["similar"] and ev["similar"][0]["symbol"] == "AAA" and ev["similar"][0]["similarity"] >= 0.8
    assert "heavy_money" in ev["similar"][0]["shared"] and "حجم سنگین" in " ".join(ev["similar"][0]["shared_fa"])
    assert "شبیه 1 پامپ قبلی" in ev["pattern_fa"]
    # پامپ کاملاً متفاوت (لارج‌کپ، بدون حجم، خلاف BTC) شباهت کمتری دارد
    s_far, _ = agent.similarity(ev, {**ev, "factors": ["large_cap", "against_btc"], "change_15m": 30, "change_24h": -20,
                                     "mcap_tier": "large_cap", "vol_spike": None, "ath_change": -5}, 0.55)
    assert s_far < ev["similar"][0]["similarity"]


def test_followups_learning_and_self_review(monkeypatch):
    monkeypatch.setattr(sources, "binance_volume_spike", lambda *_a, **_k: {"vol_spike": 4.0, "vol_pre_spike": 1.0, "green_streak": 2,
                                                                              "ret_1h": 0, "ret_4h": 0})
    state, events = {}, []
    t0 = NOW - timedelta(hours=30)
    # ۱۲ پامپ که همه بعداً برگشتند (قیمت ۱.۰ → ۰.۹)
    for i in range(12):
        sym = f"S{i:02d}"
        agent.run_cycle(state, events, None, snapshot=_snapshot({sym: _row(sym, 9.0)}), now=t0 + timedelta(minutes=15 * i))
    assert len(events) == 12
    later = t0 + timedelta(hours=28)
    rows = {e["symbol"]: _row(e["symbol"], 0.0, price=0.9) for e in events}
    state["cycle"] = agent.REVIEW_EVERY_CYCLES - 1  # چرخهٔ بعدی = بازبینی
    res = agent.run_cycle(state, events, None, snapshot=_snapshot(rows), now=later)
    assert all(e["follow"]["status"] == "done" and e["follow"]["24h"] < 0 for e in events)
    assert res["new_followups"] == 36 and state["skills"]["followups_done"] == 12
    hm = state["skills"]["factor_stats"]["heavy_money"]
    assert hm["n"] == 12 and hm["cont_4h"] < 0.2
    assert state["skills"]["lessons"] and "برگشتی" in state["skills"]["lessons"][0]
    # اختیار ۵٪: آستانه فقط نیم‌قدم و داخل باند بالا رفت و در ژورنال ثبت شد
    assert res["review"] and res["review"]["param"] == "threshold_pct"
    assert 8.0 < state["params"]["threshold_pct"] <= 8.4 and state["journal"][-1]["reason_fa"]
    # پامپ تازه با همان عوامل → توجه پایین (احتمال برگشت)
    res2 = agent.run_cycle(state, events, None, snapshot=_snapshot({"NEW": _row("NEW", 9.0)}), now=later + timedelta(minutes=15))
    assert res2["new_events"][0]["attention"] < 0.4 and res2["new_events"][0]["attention_fa"] == "احتمال برگشت/فیک"
    payload = agent.panel_payload(state, events)
    assert payload["total_events"] == 13 and payload["factor_stats"] and payload["params"]["threshold_pct"] > 8.0
