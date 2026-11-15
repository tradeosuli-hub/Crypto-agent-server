"""
ایجنت پامپ — هر ~۱۵ دقیقه در Workflow جداگانه.

۱) جمع‌آوری: Binance (تغییر دقیق ۱۵ دقیقه + جهش حجم) · CoinGecko (جهان ارزها، مارکت‌کپ، ATH، ترند) ·
   CoinMarketCap (رتبه، تگ‌های تکنولوژی/دسته) · intel.json ایجنت اطلاعات (خبر/رویداد/سوشال همان ارز)
۲) تشخیص: رشد ≥ آستانه (قفل‌شده ۸٪) در ۱۵ دقیقه → «رویداد پامپ» با اثر انگشت عددی + خبری + دسته‌ای
۳) شباهت‌یابی: مقایسه با پامپ‌های روزهای قبل (حافظهٔ دائمی) → پامپ‌های مشابه + عوامل مشترک (فارسی)
۴) پیگیری و یادگیری: قیمت ۱h/۴h/۲۴h بعد از هر پامپ ثبت می‌شود → نرخ ادامه/برگشت برای هر عامل (مهارت)
۵) اختیار ۵٪: پارامترهای خودش را فقط در باند ±۵٪ مقدار قفل‌شده و با دلیل ثبت‌شده تغییر می‌دهد و نظر آزاد می‌دهد
۶) مغز (Grok، اختیاری): «چرا الآن؟» با جست‌وجوی زندهٔ X، برای پامپ‌های تازه → یادآوری به کاربر در تلگرام/پنل

هیچ‌چیز این ایجنت قطعی نیست؛ هدف «حواس‌جمعی» است، نه سیگنال. قوانین ققنوس دست نمی‌خورند.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from phoenix import brain
from phoenix.pump import sources

# ---- ثابت‌های قفل‌شده (اختیار ایجنت فقط ±AUTONOMY روی این‌ها) ----
AUTONOMY = 0.05
LOCKED_PARAMS = {
    "threshold_pct": 8.0,      # پامپ = رشد ≥ این درصد در ۱۵ دقیقه
    "watch_pct": 5.0,          # پیش‌پامپ (فقط نمایش)
    "numeric_weight": 0.55,    # سهم شباهت عددی در برابر شباهت عوامل (Jaccard)
    "min_similarity": 0.45,    # حداقل شباهت برای گزارش «مشابه»
}
BINANCE_TOP = 200
PUMPS_KEEP = 1500
HISTORY_DAYS = 60
FOLLOW_HOURS = (1, 4, 24)
SAME_SYMBOL_COOLDOWN_H = 2
BRAIN_PER_CYCLE = 3
REVIEW_EVERY_CYCLES = 24          # ~۶ ساعت
MIN_FOLLOWUPS_FOR_REVIEW = 10
EWMA_ALPHA = 0.2
MCAP_TIERS = ((50e6, "micro_cap"), (500e6, "small_cap"), (5e9, "mid_cap"), (float("inf"), "large_cap"))

FACTOR_FA = {
    "heavy_money": "حجم سنگین یکهویی (≥۳× میانگین ۲۴h)",
    "pre_accumulation": "ورود پول قبل از پامپ",
    "green_streak": "چند کندل سبز پیاپی",
    "trending": "در ترند CoinGecko",
    "social_hot": "داغ در X / سوشال",
    "new_coin": "ارز تازه‌لیست (< ۳۰ روز)",
    "near_ath": "نزدیک سقف تاریخی",
    "deep_drawdown": "افت سنگین از سقف (> ۸۰٪)",
    "weekly_uptrend": "روند هفتگی صعودی",
    "weekly_downtrend": "روند هفتگی نزولی (شورت‌اسکوییز؟)",
    "already_up_24h": "از قبل در ۲۴h بالا بود",
    "btc_tailwind": "همراه با رشد BTC",
    "against_btc": "خلاف BTC",
    "fear_extreme": "ترس شدید بازار",
    "greed_extreme": "طمع شدید بازار",
    "asia_session": "سشن آسیا", "eu_session": "سشن اروپا", "us_session": "سشن آمریکا",
    "micro_cap": "میکروکپ", "small_cap": "اسمال‌کپ", "mid_cap": "میدکپ", "large_cap": "لارج‌کپ",
    "not_on_binance": "خارج از بایننس",
    "news_listing": "خبر لیستینگ", "news_delisting": "خبر حذف", "news_token_unlock": "آزادسازی توکن",
    "news_token_burn": "سوزاندن توکن", "news_security": "هک/امنیت", "news_regulation": "خبر قانون‌گذاری",
    "news_project": "خبر پروژه/آپدیت", "news_etf_flow": "جریان ETF", "news_macro": "خبر کلان", "news_market": "خبر بازار",
    "news_positive": "خبر مثبت اخیر", "news_negative": "خبر منفی اخیر",
}
# تگ‌های CMC/CoinGecko → دستهٔ فشرده (تکنولوژی/روایت)
TAG_MAP = [
    ("memes", "tag:meme"), ("meme", "tag:meme"), ("ai-big-data", "tag:ai"), ("artificial intelligence", "tag:ai"), ("ai agents", "tag:ai"),
    ("gaming", "tag:gaming"), ("play-to-earn", "tag:gaming"), ("metaverse", "tag:gaming"), ("defi", "tag:defi"), ("dex", "tag:defi"),
    ("layer-1", "tag:l1"), ("layer 1", "tag:l1"), ("smart-contracts", "tag:l1"), ("layer-2", "tag:l2"), ("layer 2", "tag:l2"),
    ("real-world-assets", "tag:rwa"), ("rwa", "tag:rwa"), ("privacy", "tag:privacy"), ("depin", "tag:depin"), ("oracle", "tag:oracle"),
    ("solana-ecosystem", "tag:solana-eco"), ("solana ecosystem", "tag:solana-eco"), ("bnb-chain", "tag:bnb-eco"), ("base-ecosystem", "tag:base-eco"),
    ("binance-launchpool", "tag:binance-launch"), ("binance-alpha", "tag:binance-launch"), ("launchpool", "tag:binance-launch"),
    ("exchange", "tag:exchange"), ("stablecoin", "tag:stable"), ("nft", "tag:nft"), ("pow", "tag:pow"), ("mineable", "tag:pow"),
    ("perpetual", "tag:perp-dex"), ("bitcoin-ecosystem", "tag:btc-eco"), ("brc-20", "tag:btc-eco"), ("restaking", "tag:restaking"),
    ("liquid-staking", "tag:lst"), ("socialfi", "tag:socialfi"), ("politifi", "tag:politifi"), ("zk", "tag:zk"),
]
TAG_FA = {"tag:meme": "میم‌کوین", "tag:ai": "هوش مصنوعی", "tag:gaming": "گیمینگ/متاورس", "tag:defi": "دیفای", "tag:l1": "لایه ۱",
          "tag:l2": "لایه ۲", "tag:rwa": "RWA", "tag:privacy": "حریم خصوصی", "tag:depin": "DePIN", "tag:oracle": "اوراکل",
          "tag:solana-eco": "اکوسیستم سولانا", "tag:bnb-eco": "اکوسیستم BNB", "tag:base-eco": "اکوسیستم Base",
          "tag:binance-launch": "Launchpool/Alpha بایننس", "tag:exchange": "توکن صرافی", "tag:stable": "استیبل", "tag:nft": "NFT",
          "tag:pow": "اثبات کار", "tag:perp-dex": "Perp DEX", "tag:btc-eco": "اکوسیستم بیت‌کوین", "tag:restaking": "ری‌استیکینگ",
          "tag:lst": "استیکینگ نقد", "tag:socialfi": "SocialFi", "tag:politifi": "PolitiFi", "tag:zk": "ZK"}


def factor_fa(key: str) -> str:
    return FACTOR_FA.get(key) or TAG_FA.get(key) or key


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _f(x: Any, default: float | None = None) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def mcap_tier(mcap: float | None) -> str:
    if not mcap or mcap <= 0:
        return "micro_cap"
    for lim, name in MCAP_TIERS:
        if mcap < lim:
            return name
    return "large_cap"


def compact_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        tl = str(t).lower()
        for needle, key in TAG_MAP:
            if needle in tl and key not in out:
                out.append(key)
    return out[:6]


# ---------------------------------------------------------------- پارامترها و اختیار ۵٪

def clamp_params(params: dict[str, float]) -> dict[str, float]:
    """هر پارامتر حداکثر ±AUTONOMY نسبت به مقدار قفل‌شده — اختیار ۵٪ قابل دورزدن نیست."""
    out = {}
    for k, locked in LOCKED_PARAMS.items():
        lo, hi = locked * (1 - AUTONOMY), locked * (1 + AUTONOMY)
        out[k] = round(min(hi, max(lo, float(params.get(k, locked)))), 4)
    return out


def ensure_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("cycle", 0)
    state["params"] = clamp_params(state.get("params") or {})
    state["locked"] = dict(LOCKED_PARAMS)
    state["autonomy"] = AUTONOMY
    state.setdefault("snapshot", {})
    state.setdefault("journal", [])
    state.setdefault("skills", {"factor_stats": {}, "lessons": [], "followups_done": 0})
    state.setdefault("watch", [])
    state.setdefault("opinion_fa", "")
    return state


# ---------------------------------------------------------------- جمع‌آوری

def gather(state: dict[str, Any], top_n: int = BINANCE_TOP) -> dict[str, Any]:
    """یک تصویر از بازار: برای هر نماد پایه (BTC) یک ردیف ادغام‌شده از سه منبع."""
    sources_ok: list[str] = []
    bin_top, bin_meta = sources.binance_universe(top_n)
    if bin_meta:
        sources_ok.append("binance")
    cg = sources.coingecko_markets(2)
    if cg:
        sources_ok.append("coingecko")
    cmc = sources.cmc_listing(500)
    if cmc:
        sources_ok.append("coinmarketcap")
    trending = sources.coingecko_trending()

    now = _now()
    prev_snap = state.get("snapshot") or {}
    snap_age_min = None
    pts = _parse(prev_snap.get("_ts"))
    if pts:
        snap_age_min = (now - pts).total_seconds() / 60

    def snap_change(base: str, price: float | None) -> float | None:
        """تغییر از اسنپ‌شات چرخهٔ قبل (۱۰–۲۵ دقیقه پیش) — برای همهٔ ارزها، بدون هزینهٔ API."""
        if not price or not snap_age_min or not (10 <= snap_age_min <= 25):
            return None
        p0 = _f((prev_snap.get(base) or {}).get("p"))
        return round((price / p0 - 1) * 100, 3) if p0 and p0 > 0 else None

    # نامزدهای پنجرهٔ غلتان دقیق ۱۵ دقیقه: ۲۰۰ پرحجم + هر چه در اسنپ‌شات/۱h/۲۴h داغ است (کل ۷۰۰ جفت زیر نظر است)
    cand = set(bin_top) | {"BTCUSDT"}
    for base, row in list(cg.items()) + list(cmc.items()):
        pair = base + "USDT"
        if pair in bin_meta and ((_f(row.get("change_1h")) or 0) >= 4 or (_f(row.get("change_24h")) or 0) >= 15):
            cand.add(pair)
    for pair, m in bin_meta.items():
        sc = snap_change(pair[:-4], m.get("last"))
        if m.get("change_24h", 0) >= 15 or (sc is not None and sc >= 3):
            cand.add(pair)
    cand_list = sorted(cand, key=lambda s: -bin_meta.get(s, {}).get("quote_volume", 0))[:400]
    rolling = sources.binance_rolling_15m(cand_list)

    rows: dict[str, dict[str, Any]] = {}
    bases = set(cg) | set(cmc) | {p[:-4] for p in bin_meta}
    for base in bases:
        pair = base + "USDT"
        g, c, r, bm = cg.get(base, {}), cmc.get(base, {}), rolling.get(pair), bin_meta.get(pair, {})
        price = (r or {}).get("last") or bm.get("last") or _f(g.get("price"))
        change_15m = (r or {}).get("change_15m")
        src15 = "binance" if change_15m is not None else None
        if change_15m is None:
            change_15m = snap_change(base, price)
            src15 = "snapshot" if change_15m is not None else None
        rows[base] = {
            "symbol": base, "pair": pair if pair in bin_meta else None, "price": price,
            "change_15m": change_15m, "change_15m_src": src15,
            "change_1h": _f(g.get("change_1h")) if g.get("change_1h") is not None else _f(c.get("change_1h")),
            "change_24h": _f(g.get("change_24h")) if g.get("change_24h") is not None else (_f(c.get("change_24h")) if c.get("change_24h") is not None else bm.get("change_24h")),
            "change_7d": _f(g.get("change_7d")) if g.get("change_7d") is not None else _f(c.get("change_7d")),
            "market_cap": _f(g.get("market_cap")) or _f(c.get("market_cap")),
            "volume_24h": _f(g.get("volume_24h")) or _f(c.get("volume_24h")) or bm.get("quote_volume"),
            "rank": g.get("rank") or c.get("rank"), "ath_change": _f(g.get("ath_change")),
            "tags": c.get("tags") or [], "cg_id": g.get("id"), "name": g.get("name") or c.get("name"),
            "date_added": c.get("date_added"), "trending": base in trending,
            "quote_volume_15m": (r or {}).get("quote_volume_15m"), "trades_15m": (r or {}).get("trades_15m"),
        }

    new_snap: dict[str, Any] = {"_ts": _iso(now)}
    for base, row in rows.items():
        if row["price"]:
            new_snap[base] = {"p": row["price"]}
    btc = rows.get("BTC") or {}
    return {"rows": rows, "snapshot": new_snap, "sources_ok": sources_ok, "trending": trending,
            "btc_15m": btc.get("change_15m"), "btc_1h": btc.get("change_1h"),
            "universe": {"binance": len(bin_meta), "coingecko": len(cg), "coinmarketcap": len(cmc), "rolling": len(rolling)}}


# ---------------------------------------------------------------- اثر انگشت و عوامل

def news_context(symbol: str, intel: dict[str, Any] | None) -> dict[str, Any]:
    intel = intel or {}
    pair = symbol + "USDT"
    node = (intel.get("symbols") or {}).get(pair) or {}
    titles = [i.get("title") for i in (intel.get("items") or []) if pair in (i.get("symbols") or [])][:4]
    soc = (intel.get("social") or {}).get(pair) or {}
    return {"events": list(node.get("events") or []), "sentiment": node.get("sentiment", 0.0), "risk": node.get("risk", 0.0),
            "titles": titles, "social_hot": bool(soc.get("hot")), "social_sentiment": soc.get("sentiment")}


def derive_factors(ev: dict[str, Any]) -> list[str]:
    f: list[str] = []
    vs = ev.get("vol_spike")
    if vs is not None and vs >= 3:
        f.append("heavy_money")
    if (ev.get("vol_pre_spike") or 0) >= 2:
        f.append("pre_accumulation")
    if (ev.get("green_streak") or 0) >= 3:
        f.append("green_streak")
    if ev.get("trending"):
        f.append("trending")
    if (ev.get("news") or {}).get("social_hot"):
        f.append("social_hot")
    added = _parse(ev.get("date_added"))
    if added and (_now() - added) < timedelta(days=30):
        f.append("new_coin")
    ath = ev.get("ath_change")
    if ath is not None:
        if ath > -15:
            f.append("near_ath")
        elif ath < -80:
            f.append("deep_drawdown")
    c7 = ev.get("change_7d")
    if c7 is not None:
        if c7 > 20:
            f.append("weekly_uptrend")
        elif c7 < -15:
            f.append("weekly_downtrend")
    c24 = ev.get("change_24h")
    if c24 is not None and (c24 - (ev.get("change_15m") or 0)) > 20:
        f.append("already_up_24h")
    b = ev.get("btc_15m")
    if b is not None:
        if b > 0.5:
            f.append("btc_tailwind")
        elif b < -0.5:
            f.append("against_btc")
    fg = ev.get("fear_greed")
    if fg is not None:
        if fg < 25:
            f.append("fear_extreme")
        elif fg > 75:
            f.append("greed_extreme")
    h = ev.get("hour_utc")
    if h is not None:
        f.append("asia_session" if h < 7 else "eu_session" if h < 13 else "us_session" if h < 21 else "asia_session")
    f.append(ev.get("mcap_tier") or "micro_cap")
    if not ev.get("pair"):
        f.append("not_on_binance")
    news = ev.get("news") or {}
    for k in news.get("events") or []:
        f.append(f"news_{k}")
    s = _f(news.get("sentiment")) or 0.0
    if news.get("titles"):
        f.append("news_positive" if s > 0.15 else "news_negative" if s < -0.15 else "news_market")
    f.extend(ev.get("tags_compact") or [])
    return list(dict.fromkeys(f))


def _vec(ev: dict[str, Any]) -> list[float]:
    """بردار عددی نرمال‌شده برای فاصله."""
    tier_idx = {"micro_cap": 0, "small_cap": 1, "mid_cap": 2, "large_cap": 3}.get(ev.get("mcap_tier") or "", 0) / 3
    vs = ev.get("vol_spike")
    return [
        min(1.0, (ev.get("change_15m") or 0) / 30),
        max(-1.0, min(1.0, (ev.get("change_1h") or 0) / 50)),
        max(-1.0, min(1.0, (ev.get("change_24h") or 0) / 100)),
        max(-1.0, min(1.0, (ev.get("change_7d") or 0) / 100)),
        min(1.0, math.log1p(vs) / math.log1p(20)) if vs else 0.0,
        min(1.0, math.log1p(ev.get("vol_to_mcap") or 0) / math.log1p(5)),
        tier_idx,
        max(-1.0, min(0.0, (ev.get("ath_change") or -50) / 100)),
        max(-1.0, min(1.0, (ev.get("btc_15m") or 0) / 3)),
    ]


def similarity(a: dict[str, Any], b: dict[str, Any], numeric_weight: float) -> tuple[float, list[str]]:
    va, vb = _vec(a), _vec(b)
    dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(va, vb)) / len(va))
    num = max(0.0, 1.0 - dist / 0.6)
    fa, fb = set(a.get("factors") or []), set(b.get("factors") or [])
    shared = sorted(fa & fb)
    jac = len(shared) / len(fa | fb) if (fa | fb) else 0.0
    score = numeric_weight * num + (1 - numeric_weight) * jac
    return round(score, 3), shared


def find_similar(ev: dict[str, Any], history: list[dict[str, Any]], params: dict[str, float], k: int = 5) -> list[dict[str, Any]]:
    out = []
    for h in history:
        if h.get("id") == ev.get("id"):
            continue
        score, shared = similarity(ev, h, params["numeric_weight"])
        if score >= params["min_similarity"]:
            out.append({"id": h["id"], "symbol": h["symbol"], "ts": h["ts"], "change_15m": h.get("change_15m"),
                        "similarity": score, "shared": shared, "shared_fa": [factor_fa(x) for x in shared][:6],
                        "follow": h.get("follow") or {}})
    out.sort(key=lambda x: -x["similarity"])
    return out[:k]


# ---------------------------------------------------------------- یادگیری (مهارت)

def _cont(stats: dict[str, Any], key: str) -> float | None:
    v = stats.get(key)
    return float(v) if v is not None else None


def attention_score(ev: dict[str, Any], skills: dict[str, Any]) -> tuple[float, str]:
    """۰..۱ — چقدر حواسمان باشد. از نرخ ادامهٔ آموخته‌شدهٔ عوامل + سرنوشت پامپ‌های مشابه."""
    fs = skills.get("factor_stats") or {}
    score, n = 0.5, 0
    for f in ev.get("factors") or []:
        st = fs.get(f)
        if st and st.get("n", 0) >= 3 and _cont(st, "cont_4h") is not None:
            w = min(1.0, st["n"] / 10)
            score += (st["cont_4h"] - 0.5) * 0.4 * w
            n += 1
    sims = ev.get("similar") or []
    done = [s for s in sims if (s.get("follow") or {}).get("4h") is not None]
    if done:
        rate = sum(1 for s in done if s["follow"]["4h"] > 0) / len(done)
        score += (rate - 0.5) * 0.3
    if "heavy_money" in (ev.get("factors") or []):
        score += 0.05
    if (ev.get("news") or {}).get("risk", 0) >= 0.7:
        score -= 0.15
    score = round(max(0.0, min(1.0, score)), 3)
    label = "قابل توجه" if score >= 0.62 else "احتمال برگشت/فیک" if score <= 0.38 else "معمولی"
    return score, label


def update_followups(events: list[dict[str, Any]], rows: dict[str, dict[str, Any]], skills: dict[str, Any], now: datetime) -> int:
    """قیمت‌های بعدی هر پامپ را پر می‌کند و آمار عوامل را به‌روز می‌کند. خروجی: تعداد پیگیری‌های تازه."""
    fs = skills.setdefault("factor_stats", {})
    newly = 0
    for ev in events:
        fol = ev.setdefault("follow", {"peak": None, "status": "running"})
        if fol.get("status") == "done":
            continue
        t0 = _parse(ev.get("ts"))
        row = rows.get(ev["symbol"])
        p0, p1 = _f(ev.get("price")), _f((row or {}).get("price"))
        if not t0 or not p0 or not p1:
            continue
        move = round((p1 / p0 - 1) * 100, 2)
        age_h = (now - t0).total_seconds() / 3600
        fol["peak"] = max(fol.get("peak") if fol.get("peak") is not None else move, move)
        fol["last"] = move
        for h in FOLLOW_HOURS:
            key = f"{h}h"
            if fol.get(key) is None and age_h >= h - 0.2:
                fol[key] = move
                newly += 1
                for f in ev.get("factors") or []:
                    st = fs.setdefault(f, {"n": 0})
                    ck, mk = f"cont_{key}", f"move_{key}"
                    cont = 1.0 if move > 0 else 0.0
                    st[ck] = round((1 - EWMA_ALPHA) * st.get(ck, 0.5) + EWMA_ALPHA * cont, 3)
                    st[mk] = round((1 - EWMA_ALPHA) * st.get(mk, 0.0) + EWMA_ALPHA * move, 2)
                    if h == FOLLOW_HOURS[0]:
                        st["n"] = int(st.get("n", 0)) + 1
                if h == FOLLOW_HOURS[-1]:
                    fol["status"] = "done"
                    skills["followups_done"] = int(skills.get("followups_done", 0)) + 1
    return newly


def self_review(state: dict[str, Any], events: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """اختیار ۵٪: هر ~۶ ساعت، اگر نمونهٔ کافی هست، یک پارامتر را در باند مجاز جابه‌جا می‌کند — با دلیل."""
    skills = state["skills"]
    if state["cycle"] % REVIEW_EVERY_CYCLES != 0 or skills.get("followups_done", 0) < MIN_FOLLOWUPS_FOR_REVIEW:
        return None
    done = [e for e in events if (e.get("follow") or {}).get("4h") is not None]
    if not done:
        return None
    rate = sum(1 for e in done if e["follow"]["4h"] > 0) / len(done)
    p = state["params"]
    locked = LOCKED_PARAMS["threshold_pct"]
    step = locked * AUTONOMY / 2
    decision = None
    if rate < 0.35 and p["threshold_pct"] < locked * (1 + AUTONOMY) - 1e-9:
        new = clamp_params({**p, "threshold_pct": p["threshold_pct"] + step})["threshold_pct"]
        decision = {"param": "threshold_pct", "from": p["threshold_pct"], "to": new,
                    "reason_fa": f"فقط {rate:.0%} پامپ‌ها بعد از ۴ ساعت بالاتر ماندند → آستانه کمی سخت‌تر تا هشدار کمتر و قوی‌تر باشد"}
    elif rate > 0.6 and p["threshold_pct"] > locked * (1 - AUTONOMY) + 1e-9:
        new = clamp_params({**p, "threshold_pct": p["threshold_pct"] - step})["threshold_pct"]
        decision = {"param": "threshold_pct", "from": p["threshold_pct"], "to": new,
                    "reason_fa": f"{rate:.0%} پامپ‌ها ادامه داشتند → آستانه کمی نرم‌تر تا زودتر حواسمان جمع شود"}
    if not decision:
        return None
    p[decision["param"]] = decision["to"]
    state["params"] = clamp_params(p)
    entry = {"ts": _iso(now), "cycle": state["cycle"], **decision,
             "decision_fa": f"{decision['param']}: {decision['from']} → {decision['to']} (در باند ±{int(AUTONOMY*100)}٪ قفل‌شده)"}
    state["journal"] = (state.get("journal") or [])[-199:] + [entry]
    return entry


def lessons(skills: dict[str, Any]) -> list[str]:
    fs = skills.get("factor_stats") or {}
    good = sorted([(k, v) for k, v in fs.items() if v.get("n", 0) >= 3 and _cont(v, "cont_4h") is not None and v["cont_4h"] >= 0.6],
                  key=lambda kv: -kv[1]["cont_4h"])[:4]
    bad = sorted([(k, v) for k, v in fs.items() if v.get("n", 0) >= 3 and _cont(v, "cont_4h") is not None and v["cont_4h"] <= 0.4],
                 key=lambda kv: kv[1]["cont_4h"])[:4]
    def fmt(items: list[tuple[str, dict[str, Any]]]) -> str:
        return "، ".join("{} {:.0%}".format(factor_fa(k), v["cont_4h"]) for k, v in items)

    out = []
    if good:
        out.append("عوامل ادامه‌دار (۴h): " + fmt(good))
    if bad:
        out.append("عوامل برگشتی (۴h): " + fmt(bad))
    return out


def opinion(state: dict[str, Any], new_events: list[dict[str, Any]], events_24h: list[dict[str, Any]], market: dict[str, Any]) -> str:
    """نظر آزاد ایجنت (قاعده‌محور؛ اگر مغز باشد یک جمله از او هم اضافه می‌شود)."""
    parts: list[str] = []
    if new_events:
        parts.append("این چرخه " + "، ".join(f"{e['symbol']} +{e['change_15m']:.1f}٪" for e in new_events[:4]) + " پامپ کرد.")
    if events_24h:
        from collections import Counter
        cnt = Counter(f for e in events_24h for f in (e.get("factors") or []) if not f.endswith("_session"))
        top = [f"{factor_fa(k)} ({n})" for k, n in cnt.most_common(4)]
        parts.append(f"در ۲۴ ساعت اخیر {len(events_24h)} پامپ؛ عوامل پرتکرار: {'، '.join(top)}.")
        done = [e for e in events_24h if (e.get("follow") or {}).get("4h") is not None]
        if done:
            rate = sum(1 for e in done if e["follow"]["4h"] > 0) / len(done)
            parts.append(f"از {len(done)} پامپ پیگیری‌شده، {rate:.0%} بعد از ۴ ساعت هنوز بالاتر بودند.")
    else:
        parts.append("۲۴ ساعت اخیر پامپ ≥ آستانه ندیدم؛ بازار آرام است.")
    parts.extend(lessons(state["skills"]))
    fg = market.get("fear_greed")
    if fg is not None:
        parts.append(f"ترس‌وطمع {fg}؛ " + ("در طمع شدید پامپ‌ها زودتر برمی‌گردند — احتیاط." if fg > 75 else
                                        "در ترس شدید پامپ‌ها بیشتر شورت‌اسکوییزند." if fg < 25 else "شرایط احساسی خنثی."))
    text = " ".join(parts)
    if new_events and brain.available():
        res = brain.ask_json(
            "تو تحلیلگر پامپ‌های کریپتو هستی. بی‌طرف و کوتاه. فقط JSON: {\"opinion_fa\": \"حداکثر دو جمله به فارسی\"}",
            f"پامپ‌های تازه: {[{k: e.get(k) for k in ('symbol','change_15m','vol_spike','factors')} for e in new_events[:4]]}\n"
            f"خلاصهٔ قاعده‌محور: {text}", max_tokens=300)
        if res and res.get("opinion_fa"):
            text += " 🧠 " + str(res["opinion_fa"])[:300]
    return text[:900]


def ask_brain_why(ev: dict[str, Any]) -> dict[str, Any] | None:
    """«چرا الآن؟» — فقط با مغز؛ با Grok از X هم می‌پرسد."""
    if not brain.available():
        return None
    res = brain.ask_json(
        "تو تحلیلگر میز معاملاتی هستی. برای ارزی که همین الآن در ۱۵ دقیقه پامپ کرده، با جست‌وجوی X و وب بگو محتمل‌ترین دلیل چیست "
        "(خبر، لیستینگ، نهنگ، روایت/تکنولوژی، شورت‌اسکوییز، دستکاری) و به چه ارزهای قبلی شبیه است. قطعی حرف نزن. فقط JSON: "
        "{\"why_fa\": \"یک تا دو جمله\", \"kind\": \"news|listing|whale|narrative|squeeze|manipulation|unknown\", "
        "\"similar_fa\": \"یک خط\", \"confidence\": 0..1, \"remind_fa\": \"یک جملهٔ یادآوری برای کاربر\"}",
        f"ارز: {ev['symbol']} ({ev.get('name')}) · +{ev.get('change_15m')}٪ در ۱۵ دقیقه · 1h {ev.get('change_1h')} · 24h {ev.get('change_24h')}\n"
        f"جهش حجم: {ev.get('vol_spike')}× · مارکت‌کپ: {ev.get('market_cap')} · تگ‌ها: {ev.get('tags')[:8]}\n"
        f"عوامل: {[factor_fa(f) for f in ev.get('factors') or []]}\nخبرهای ۴۸h: {(ev.get('news') or {}).get('titles')}",
        live_x_search=True, max_tokens=500, timeout=90,
    )
    if not res:
        return None
    return {k: res.get(k) for k in ("why_fa", "kind", "similar_fa", "confidence", "remind_fa")}


# ---------------------------------------------------------------- چرخه

def _event_id(symbol: str, ts: datetime) -> str:
    return "P" + hashlib.sha1(f"{symbol}:{ts.strftime('%Y%m%d%H%M')}".encode()).hexdigest()[:10]


def build_event(row: dict[str, Any], ctx: dict[str, Any], intel: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    mcap = row.get("market_cap")
    vol24 = row.get("volume_24h")
    market = (intel or {}).get("market") or {}
    ev: dict[str, Any] = {
        "id": _event_id(row["symbol"], now), "ts": _iso(now), "symbol": row["symbol"], "name": row.get("name"), "pair": row.get("pair"),
        "price": row.get("price"), "change_15m": round(row["change_15m"], 2), "change_15m_src": row.get("change_15m_src"),
        "change_1h": row.get("change_1h"), "change_24h": row.get("change_24h"), "change_7d": row.get("change_7d"),
        "market_cap": mcap, "mcap_tier": mcap_tier(mcap), "rank": row.get("rank"), "volume_24h": vol24,
        "vol_to_mcap": round(vol24 / mcap, 3) if vol24 and mcap else None, "ath_change": row.get("ath_change"),
        "tags": (row.get("tags") or [])[:12], "tags_compact": compact_tags(row.get("tags") or []), "date_added": row.get("date_added"),
        "trending": bool(row.get("trending")), "btc_15m": ctx.get("btc_15m"), "btc_1h": ctx.get("btc_1h"),
        "fear_greed": market.get("fear_greed"), "btc_dominance": market.get("btc_dominance"),
        "hour_utc": now.hour, "weekday": now.weekday(), "news": news_context(row["symbol"], intel),
        "follow": {"peak": None, "status": "running"}, "notified": False, "max_change_15m": round(row["change_15m"], 2),
    }
    if ev["pair"]:
        vs = sources.binance_volume_spike(ev["pair"])
        if vs:
            ev.update(vs)
    if not ev["tags_compact"] and row.get("cg_id") and ctx.get("cg_budget", 0) > 0:
        ctx["cg_budget"] -= 1
        cats = sources.coingecko_categories(row["cg_id"])
        ev["tags"] = ev["tags"] or cats
        ev["tags_compact"] = compact_tags(cats)
    ev["factors"] = derive_factors(ev)
    ev["factors_fa"] = [factor_fa(f) for f in ev["factors"]]
    return ev


def run_cycle(state: dict[str, Any], events: list[dict[str, Any]], intel: dict[str, Any] | None,
              snapshot: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """یک چرخهٔ کامل. snapshot را فقط تست‌ها می‌دهند؛ در اجرا خودش gather می‌کند."""
    now = now or _now()
    ensure_state(state)
    state["cycle"] = int(state.get("cycle", 0)) + 1
    snap = snapshot or gather(state)
    rows = snap["rows"]
    params = state["params"]
    cutoff = now - timedelta(days=HISTORY_DAYS)
    events[:] = [e for e in events if (_parse(e.get("ts")) or now) >= cutoff][-PUMPS_KEEP:]

    # ۱) پیگیری پامپ‌های قبلی (یادگیری)
    new_follow = update_followups(events, rows, state["skills"], now)

    # ۲) تشخیص
    ctx = {"btc_15m": snap.get("btc_15m"), "btc_1h": snap.get("btc_1h"), "cg_budget": 3}
    new_events: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    recent = {e["symbol"]: e for e in events if (_parse(e.get("ts")) or cutoff) >= now - timedelta(hours=SAME_SYMBOL_COOLDOWN_H)}
    hot = sorted((r for r in rows.values() if r.get("change_15m") is not None and r["change_15m"] >= params["watch_pct"]),
                 key=lambda r: -r["change_15m"])
    for r in hot:
        if r["change_15m"] >= params["threshold_pct"]:
            prev = recent.get(r["symbol"])
            if prev:
                prev["max_change_15m"] = max(prev.get("max_change_15m") or 0, round(r["change_15m"], 2))
                continue
            ev = build_event(r, ctx, intel, now)
            ev["similar"] = find_similar(ev, events, params)
            new_events.append(ev)
        else:
            watch.append({"symbol": r["symbol"], "pair": r.get("pair"), "change_15m": round(r["change_15m"], 2),
                          "change_1h": r.get("change_1h"), "change_24h": r.get("change_24h"), "mcap_tier": mcap_tier(r.get("market_cap"))})

    # ۳) مغز برای تازه‌ها (محدود) + امتیاز توجه
    for i, ev in enumerate(new_events):
        if i < BRAIN_PER_CYCLE:
            ev["brain"] = ask_brain_why(ev)
        ev["attention"], ev["attention_fa"] = attention_score(ev, state["skills"])
        shared_all = [s for sim in ev["similar"] for s in sim["shared"]]
        if ev["similar"]:
            from collections import Counter
            common = [factor_fa(k) for k, _ in Counter(shared_all).most_common(3)]
            ev["pattern_fa"] = (f"شبیه {len(ev['similar'])} پامپ قبلی (بیشترین: {ev['similar'][0]['symbol']} "
                                f"{ev['similar'][0]['similarity']:.0%})؛ وجه مشترک: {'، '.join(common) or '—'}")
        else:
            ev["pattern_fa"] = "الگوی مشابهی در حافظه نیست — پامپ تازه‌نوع؛ ثبت شد تا دفعهٔ بعد مرجع باشد"
        events.append(ev)

    # ۴) اختیار ۵٪ و نظر آزاد
    review = self_review(state, events, now)
    events_24h = [e for e in events if (_parse(e.get("ts")) or cutoff) >= now - timedelta(hours=24)]
    state["skills"]["lessons"] = lessons(state["skills"])
    state["opinion_fa"] = opinion(state, new_events, events_24h, (intel or {}).get("market") or {})
    state["watch"] = watch[:30]
    state["snapshot"] = snap["snapshot"]
    state["sources_ok"] = snap["sources_ok"]
    state["universe"] = snap.get("universe")
    state["btc_15m"] = snap.get("btc_15m")
    state["updated_at"] = _iso(now)
    state["brain"] = brain.provider()
    return {"new_events": new_events, "watch": watch, "new_followups": new_follow, "review": review,
            "events_24h": len(events_24h), "sources_ok": snap["sources_ok"]}


def panel_payload(state: dict[str, Any], events: list[dict[str, Any]], days: int = 7) -> dict[str, Any]:
    """آنچه داشبورد (تب پامپ) می‌خواند."""
    now = _now()
    cutoff = now - timedelta(days=days)
    recent = [e for e in events if (_parse(e.get("ts")) or now) >= cutoff]
    recent.sort(key=lambda e: e.get("ts") or "", reverse=True)
    fs = state.get("skills", {}).get("factor_stats") or {}
    stats = [{"factor": k, "fa": factor_fa(k), **v} for k, v in fs.items() if v.get("n", 0) >= 1]
    stats.sort(key=lambda s: -s.get("n", 0))
    return {
        "updated_at": state.get("updated_at"), "cycle": state.get("cycle"), "params": state.get("params"), "locked": state.get("locked"),
        "autonomy": AUTONOMY, "sources_ok": state.get("sources_ok"), "universe": state.get("universe"), "brain": state.get("brain"),
        "btc_15m": state.get("btc_15m"), "watch": state.get("watch"), "opinion_fa": state.get("opinion_fa"),
        "journal": (state.get("journal") or [])[-30:], "lessons": state.get("skills", {}).get("lessons") or [],
        "followups_done": state.get("skills", {}).get("followups_done", 0), "factor_stats": stats[:40],
        "events": recent[:120], "total_events": len(events),
    }
