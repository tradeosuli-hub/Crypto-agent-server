"""تست ایجنت‌های اطلاعات، عیب‌یابی، بات و دپارتمان‌های خبر/سوشال."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from phoenix import watchdog  # noqa: E402
from phoenix.intel import agent, sources  # noqa: E402
from phoenix.notify import Notifier  # noqa: E402
from phoenix.org.departments import dept_news, dept_social  # noqa: E402
from phoenix.org.memory import Memory  # noqa: E402


def test_kind_classification_and_title_sentiment():
    assert sources.classify_kind("Binance Will Delist ABC, DEF") == "delisting"
    assert sources.classify_kind("Protocol exploit drains $40M") == "security"
    assert sources.classify_kind("Team announces token unlock schedule") == "token_unlock"
    assert sources.classify_kind("Bitcoin ETFs rebound with $119M inflow") == "etf_flow"
    assert agent.title_sentiment("Bitcoin ETFs rebound with $119M inflow") > 0
    assert agent.title_sentiment("Crypto liquidations hit $550M as Bitcoin dips below $84K") < 0


def test_extract_tickers_only_known():
    known = {"BTC", "ETH", "SOL"}
    assert sources.extract_tickers("Bitcoin and SOL rally while XYZ dumps", known) == ["SOL", "BTC"]


def test_aggregate_symbols_decay_and_risk():
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    items = [
        {"published": (now - timedelta(hours=1)).isoformat(), "importance": 9, "sentiment": -0.9, "risk": 1.0,
         "kind": "security", "symbols": ["ABCUSDT"]},
        {"published": (now - timedelta(hours=40)).isoformat(), "importance": 6, "sentiment": 0.6, "risk": 0.0,
         "kind": "listing", "symbols": ["ABCUSDT", "XYZUSDT"]},
        {"published": (now - timedelta(hours=90)).isoformat(), "importance": 9, "sentiment": 0.9, "risk": 0.0,
         "kind": "listing", "symbols": ["OLDUSDT"]},
    ]
    agg = agent.aggregate_symbols(items, now)
    assert "OLDUSDT" not in agg  # خارج از پنجره
    assert agg["ABCUSDT"]["risk"] > 0.9 and agg["ABCUSDT"]["sentiment"] < 0
    assert set(agg["ABCUSDT"]["events"]) == {"security", "listing"}
    assert agg["XYZUSDT"]["sentiment"] > 0


def test_news_and_social_departments_use_fresh_intel_only():
    mem = Memory(tempfile.mkdtemp())
    res = {"symbol": "ABCUSDT", "direction": "long"}
    assert dept_news(res, mem)["silent"]  # بدون اطلاعات → خاموش
    mem.data["intel"] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market": {"fear_greed": 50},
        "symbols": {"ABCUSDT": {"sentiment": -0.9, "risk": 1.0, "events": ["security"]}},
        "social": {"ABCUSDT": {"sentiment": 0.8, "note_fa": "هیجان", "hot": True}},
    }
    n = dept_news(res, mem)
    assert "high_risk_news" in n["flags"] and n["direction"] == "flat"
    s = dept_social(res, mem)
    assert s["direction"] == "long" and s["strength"] <= 0.7 and "social_hot" in s["flags"]
    mem.data["intel"]["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    assert dept_news(res, mem)["silent"] and dept_social(res, mem)["silent"]  # کهنه → خاموش


def test_notifier_is_silent_without_credentials(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    n = Notifier({})
    assert n.send("x") is False and n.poll_commands({}) == 0 and n.sent_now == 0


def test_watchdog_log_classification():
    assert watchdog.classify_log("requests.exceptions.HTTPError: 451 Client Error") == "binance_block"
    assert watchdog.classify_log("HTTP 429 Too Many Requests") == "rate_limit"
    assert watchdog.classify_log("Traceback (most recent call last): KeyError 'x'") == "code_error"
    assert watchdog.classify_log("Ensure GitHub Pages has been enabled") == "pages_disabled"
    assert watchdog.classify_log("::warning::memory persist failed after retries") == "memory_push"
    assert watchdog.classify_log("The job running on runner has exceeded the maximum execution time") == "timeout"


def test_watchdog_creates_incident_then_resolves(monkeypatch):
    gh = watchdog.GitHub(token=None, repo=None)
    gh.ok = False  # بدون API → اجرای موفقی دیده نمی‌شود → اسکن «متوقف» تلقی می‌شود
    mem = {"intel": {"updated_at": datetime.now(timezone.utc).isoformat()}, "incidents": []}
    h = watchdog.run(gh, mem, None)
    assert any(p["kind"] == "scan_stalled" for p in h["problems"])
    assert len(h["new_incidents"]) == 1 and h["new_incidents"][0]["kind"] == "scan_stalled"
    assert mem["incidents"][0]["resolved_at"] is None
    # دور بعد: سلامت برگشته → رخداد حل‌شده و تجربه ثبت می‌شود
    monkeypatch.setattr(watchdog, "check_health", lambda *_a, **_k: {"checked_at": datetime.now(timezone.utc).isoformat(),
                                                                      "checks": [], "problems": [], "runs": {}})
    h2 = watchdog.run(gh, mem, None)
    assert mem["incidents"][0]["resolved_at"] and not h2["open_incidents"]


class _FakeGH:
    """GitHub ساختگی: اسکن تازه و موفق ولی هیچ اجرای بعدی در صف → حلقهٔ خودگردان مرده."""
    ok = True

    def __init__(self):
        self.dispatched = []
        now = datetime.now(timezone.utc).isoformat()
        self._runs = {
            watchdog.SCAN_WF: [{"id": 1, "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
                                "created_at": now, "updated_at": now, "url": "u", "branch": "b"}],
            watchdog.INTEL_WF: [{"id": 2, "status": "in_progress", "conclusion": None, "event": "workflow_dispatch",
                                 "created_at": now, "updated_at": now, "url": "u", "branch": "b"}],
        }

    def runs(self, wf, n=12):
        return self._runs.get(wf, [])

    def branch_age_min(self, _b):
        return 1.0

    def dispatch(self, wf, inputs=None, ref=None):
        self.dispatched.append((wf, inputs or {}, ref or watchdog.DEFAULT_BRANCH))
        return True

    def failed_log_excerpt(self, _id):
        return ""


def test_watchdog_revives_dead_loop_on_own_branch():
    gh = _FakeGH()
    mem = {"intel": {"updated_at": datetime.now(timezone.utc).isoformat()}, "incidents": []}
    h = watchdog.run(gh, mem, None)
    kinds = {p["kind"] for p in h["problems"]}
    assert "scan_loop_dead" in kinds and "intel_loop_dead" not in kinds
    assert not any(p["kind"] == "scan_stalled" for p in h["problems"])
    assert gh.dispatched == [(watchdog.SCAN_WF, {"delay_min": "0"}, watchdog.DEFAULT_BRANCH)]
    assert "main" not in watchdog.DEFAULT_BRANCH
    inc = h["new_incidents"][0]
    assert inc["action"] == "revive" and inc["severity"] == "medium"
