"""
ایجنت اطلاعات (خبر + رویداد + سوشال) — خروجی: intel.json در حافظهٔ دائمی.

قالب:
{
  "updated_at", "market": {...coingecko/fng...},
  "items": [ {id, source, kind, kind_fa, title, url, published, symbols, importance, sentiment, summary_fa} ... ],
  "symbols": { "BTCUSDT": {"sentiment": -1..1, "risk": 0..1, "events": [kinds], "last": iso} },
  "social": { "BTCUSDT": {"sentiment", "note_fa", "citations"} }   ← فقط با Grok
}
اهمیت ۰–۱۰ قاعده‌محور است؛ اگر مغز (brain) در دسترس باشد برای آیتم‌های مهم خلاصهٔ فارسی و اصلاح امتیاز می‌گیرد.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from phoenix import brain
from phoenix.intel import sources

KIND_FA = {
    "listing": "لیستینگ", "delisting": "حذف از صرافی", "token_unlock": "آزادسازی توکن", "token_burn": "سوزاندن توکن",
    "security": "هک / امنیت", "regulation": "قانون‌گذاری", "macro": "کلان اقتصادی", "project": "پروژه / آپدیت",
    "market": "جریان بازار", "etf_flow": "جریان ETF", "news": "خبر",
}
BASE_IMPORTANCE = {
    "security": 9, "delisting": 8, "regulation": 7, "macro": 7, "token_unlock": 6, "listing": 6, "etf_flow": 6,
    "token_burn": 5, "project": 4, "market": 4, "news": 2,
}
# اثر نوع رویداد روی جهت (برای دپارتمان خبر) و ریسک (برای وتوی A34)
KIND_SENTIMENT = {"listing": 0.6, "token_burn": 0.4, "project": 0.2, "delisting": -0.8, "security": -0.9,
                  "token_unlock": -0.4, "regulation": -0.2, "macro": 0.0, "market": 0.0, "etf_flow": 0.0, "news": 0.0}
KIND_RISK = {"security": 1.0, "delisting": 0.9, "regulation": 0.6, "macro": 0.5, "token_unlock": 0.5}
# احساس از خود عنوان (مستقل از نوع)
TITLE_SENTIMENT = [
    ("inflow", 0.4), ("outflow", -0.4), ("record high", 0.3), ("all-time high", 0.3), ("surge", 0.3), ("rall", 0.3),
    ("soar", 0.3), ("jump", 0.2), ("rebound", 0.2), ("plunge", -0.3), ("crash", -0.4), ("dump", -0.3), ("dips below", -0.3),
    ("falls", -0.2), ("drop", -0.2), ("liquidations", -0.2), ("sell-off", -0.3), ("selloff", -0.3), ("fear", -0.2),
    ("approv", 0.3), ("reject", -0.3), ("delay", -0.2), ("adopt", 0.2), ("partner", 0.2),
]


def title_sentiment(title: str) -> float:
    t = title.lower()
    s = sum(v for kw, v in TITLE_SENTIMENT if kw in t)
    return max(-1.0, min(1.0, s))

ITEMS_KEEP = 400
WINDOW_HOURS = 48
TELEGRAM_MIN_IMPORTANCE = 6


def _id(item: dict[str, Any]) -> str:
    return "N" + hashlib.sha1((item.get("url") or item.get("title", "")).encode()).hexdigest()[:12]


def _importance(item: dict[str, Any], symbols_watched: set[str]) -> int:
    score = BASE_IMPORTANCE.get(item["kind"], 2)
    if item["source"] == "binance":
        score += 1
    if any(s in symbols_watched for s in item["symbols"]):
        score += 1
    if "BTC" in item["symbols"] or "ETH" in item["symbols"]:
        score += 1
    return max(0, min(10, score))


def _symbols_usdt(raw: list[str]) -> list[str]:
    return [f"{t}USDT" for t in raw]


def collect(known_tickers: set[str], watched_symbols: set[str], previous: dict[str, Any] | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    prev_items = {i["id"]: i for i in (previous or {}).get("items", [])}
    raw = sources.rss_items(known_tickers) + sources.binance_announcements(known_tickers)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in raw:
        item = {**r, "symbols": _symbols_usdt(r.pop("raw_symbols", []))}
        item["id"] = _id(item)
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        item["kind_fa"] = KIND_FA.get(item["kind"], "خبر")
        item["importance"] = _importance(item, watched_symbols)
        item["sentiment"] = round(max(-1.0, min(1.0, KIND_SENTIMENT.get(item["kind"], 0.0) + title_sentiment(item["title"]))), 3)
        item["risk"] = KIND_RISK.get(item["kind"], 0.0)
        old = prev_items.get(item["id"])
        if old:
            item["summary_fa"] = old.get("summary_fa")
            item["first_seen"] = old.get("first_seen")
            item["notified"] = old.get("notified", False)
        else:
            item["first_seen"] = now.isoformat()
            item["notified"] = False
        items.append(item)

    # آیتم‌های قدیمی که دیگر در فید نیستند ولی هنوز در پنجره‌اند را نگه دار
    for old in prev_items.values():
        if old["id"] not in seen:
            try:
                age = now - datetime.fromisoformat((old.get("first_seen") or "").replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                age = timedelta(days=9)
            if age < timedelta(hours=WINDOW_HOURS):
                items.append(old)

    items.sort(key=lambda i: (i.get("published") or i.get("first_seen") or ""), reverse=True)
    items = items[:ITEMS_KEEP]

    _enrich_with_brain([i for i in items if i["importance"] >= TELEGRAM_MIN_IMPORTANCE and not i.get("summary_fa")][:6])

    market = sources.coingecko_market()
    per_symbol = aggregate_symbols(items, now)
    social = (previous or {}).get("social") or {}
    return {
        "updated_at": now.isoformat(),
        "market": market,
        "items": items,
        "symbols": per_symbol,
        "social": social,
        "brain": brain.provider(),
        "sources_ok": sorted({i["source"] for i in items}),
    }


def aggregate_symbols(items: list[dict[str, Any]], now: datetime) -> dict[str, dict[str, Any]]:
    """برای هر ارز: احساس وزنی، ریسک بیشینه و نوع رویدادها در ۴۸ ساعت اخیر."""
    agg: dict[str, dict[str, Any]] = {}
    for it in items:
        ts = it.get("published") or it.get("first_seen")
        try:
            age_h = (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:  # noqa: BLE001
            age_h = 999
        if age_h > WINDOW_HOURS:
            continue
        decay = max(0.2, 1 - age_h / WINDOW_HOURS)
        w = (it["importance"] / 10) * decay
        for s in it.get("symbols") or []:
            node = agg.setdefault(s, {"sent_sum": 0.0, "w_sum": 0.0, "risk": 0.0, "events": [], "last": ts, "count": 0})
            node["sent_sum"] += it["sentiment"] * w
            node["w_sum"] += w
            node["risk"] = max(node["risk"], it["risk"] * decay)
            node["count"] += 1
            if it["kind"] not in node["events"] and it["kind"] != "news":
                node["events"].append(it["kind"])
    out: dict[str, dict[str, Any]] = {}
    for s, n in agg.items():
        out[s] = {
            "sentiment": round(n["sent_sum"] / n["w_sum"], 3) if n["w_sum"] else 0.0,
            "risk": round(n["risk"], 3),
            "events": n["events"],
            "count": n["count"],
            "last": n["last"],
        }
    return out


def _enrich_with_brain(items: list[dict[str, Any]]) -> None:
    if not items or not brain.available():
        return
    titles = "\n".join(f"{i['id']} | {i['kind']} | {i['title']}" for i in items)
    res = brain.ask_json(
        "تو تحلیلگر خبر کریپتو در یک میز معاملاتی هستی. برای هر خبر یک خلاصهٔ یک‌خطی فارسی و اثر احتمالی روی قیمت بده. "
        "خروجی فقط JSON: {\"items\": [{\"id\":..., \"summary_fa\":..., \"importance\": 0-10, \"sentiment\": -1..1}]}",
        titles, max_tokens=900,
    )
    if not res:
        return
    by_id = {i["id"]: i for i in items}
    for row in res.get("items") or []:
        it = by_id.get(row.get("id"))
        if not it:
            continue
        if row.get("summary_fa"):
            it["summary_fa"] = str(row["summary_fa"])[:300]
        try:
            it["importance"] = max(it["importance"], min(10, int(row.get("importance", it["importance"]))))
            it["sentiment"] = max(-1.0, min(1.0, float(row.get("sentiment", it["sentiment"]))))
        except Exception:  # noqa: BLE001
            pass


def social_pulse(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """نبض X برای چند ارز — فقط با Grok (جست‌وجوی زنده). بدون کلید: خالی."""
    if brain.provider() != "xai" or not symbols:
        return {}
    res = brain.ask_json(
        "تو تحلیلگر سوشال در میز معاملاتی هستی. با جست‌وجوی X و وب، برای هر ارز احساس غالب تریدرهای حرفه‌ای در ۲۴ ساعت اخیر "
        "را بده. فقط JSON: {\"symbols\": {\"BTCUSDT\": {\"sentiment\": -1..1, \"note_fa\": \"یک خط\", \"hot\": true/false}}}",
        "ارزها: " + ", ".join(symbols[:8]),
        live_x_search=True, max_tokens=800, timeout=90,
    )
    out: dict[str, dict[str, Any]] = {}
    for s, v in ((res or {}).get("symbols") or {}).items():
        try:
            out[s.upper()] = {"sentiment": max(-1.0, min(1.0, float(v.get("sentiment", 0)))),
                              "note_fa": str(v.get("note_fa", ""))[:200], "hot": bool(v.get("hot", False)),
                              "updated_at": datetime.now(timezone.utc).isoformat()}
        except Exception:  # noqa: BLE001
            continue
    return out


def important_unnotified(intel: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in intel.get("items", []) if i.get("importance", 0) >= TELEGRAM_MIN_IMPORTANCE and not i.get("notified")]
