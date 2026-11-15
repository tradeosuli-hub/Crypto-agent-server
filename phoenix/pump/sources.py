"""
منابع دادهٔ ایجنت پامپ — همه رایگان و تأییدشده:

  Binance  /api/v3/ticker?windowSize=15m   تغییر دقیق ۱۵ دقیقهٔ هر جفت USDT (پنجرهٔ غلتان)
  Binance  /api/v3/klines 15m              جهش حجم (حجم این ۱۵ دقیقه نسبت به میانگین ۲۴ ساعت)
  CoinGecko /coins/markets                 جهان ارزها (شامل غیر بایننسی)، مارکت‌کپ، تغییر 1h/24h/7d، فاصله از ATH
  CoinMarketCap data-api (بدون کلید) یا API رسمی (با CMC_API_KEY)   رتبه، تگ‌ها (تکنولوژی/دسته)، تغییر 1h/24h/7d

هر منبعی که جواب ندهد فقط «خاموش» می‌شود؛ ایجنت با بقیه ادامه می‌دهد.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from phoenix.market_data import BINANCE_HOSTS, _BLOCKED

UA = {"User-Agent": "Mozilla/5.0 (PhoenixOrg; +https://github.com/tradeosuli-hub/Crypto-agent-server)"}
TIMEOUT = 25
COINGECKO = "https://api.coingecko.com/api/v3"
CMC_PUBLIC = "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listing"
CMC_PRO = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

_STABLE = {"USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "USD1", "RLUSD", "BUSD", "PYUSD", "USDD", "FRAX",
           "EUR", "AEUR", "EURI", "XAUT", "PAXG", "WBTC", "WETH", "STETH", "WSTETH", "WEETH", "CBBTC", "BFUSD", "USDS"}


def _get(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response | None:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params or {}, headers={**UA, **(headers or {})}, timeout=TIMEOUT)
            if r.status_code in (429, 418):
                time.sleep(2.0 * (attempt + 1))
                continue
            return r if r.ok else None
        except Exception:  # noqa: BLE001
            time.sleep(0.5 * (attempt + 1))
    return None


def _binance_get(path: str, params: dict[str, Any]) -> Any:
    """GET بایننس با میزبان‌های جایگزین (۴۵۱/۴۰۳/قطعی → میزبان بعدی)."""
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f"{host}{path}", params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code in _BLOCKED:
                continue
            if r.status_code in (429, 418):
                time.sleep(2.0)
                continue
            if 400 <= r.status_code < 500:
                return None  # خطای درخواست (مثلاً نماد نامعتبر) — میزبان دیگر فرقی نمی‌کند
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            continue
        except Exception:  # noqa: BLE001
            continue
    return None


_SYMBOL_OK = re.compile(r"^[A-Z0-9\-._]{1,50}$")


def is_tradeable_base(base: str) -> bool:
    b = base.upper()
    return bool(_SYMBOL_OK.match(b)) and b not in _STABLE and not b.endswith(("UP", "DOWN", "BULL", "BEAR"))


# ---------------------------------------------------------------- Binance

def binance_universe(top_n: int = 200) -> tuple[list[str], dict[str, dict[str, float]]]:
    """جفت‌های USDT برتر از نظر حجم ۲۴ ساعت + تغییر ۲۴h. خروجی: (نمادها، {symbol: {quote_volume, change_24h, last}})."""
    data = _binance_get("/api/v3/ticker/24hr", {}) or []
    rows = []
    for t in data:
        s = str(t.get("symbol", ""))
        if not s.endswith("USDT") or not is_tradeable_base(s[:-4]):
            continue
        try:
            rows.append((s, float(t.get("quoteVolume", 0)), float(t.get("priceChangePercent", 0)), float(t.get("lastPrice", 0))))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    meta = {s: {"quote_volume": qv, "change_24h": ch, "last": last} for s, qv, ch, last in rows}
    return [r[0] for r in rows[:top_n]], meta


def binance_rolling_15m(symbols: list[str]) -> dict[str, dict[str, float]]:
    """تغییر دقیق پنجرهٔ غلتان ۱۵ دقیقه. وزن API برای هر دسته ≤۱۰۰ نماد حداکثر ۲۰۰ است → دسته‌های ۱۰۰تایی."""
    out: dict[str, dict[str, float]] = {}
    symbols = [s for s in symbols if _SYMBOL_OK.match(s)]
    for i in range(0, len(symbols), 100):
        batch = symbols[i:i + 100]
        data = _binance_get("/api/v3/ticker", {"symbols": json.dumps(batch, separators=(",", ":")), "windowSize": "15m"})
        if data is None and len(batch) > 25:
            # یک نماد خراب کل دسته را رد می‌کند → دسته‌های کوچک‌تر
            data = []
            for j in range(0, len(batch), 25):
                part = _binance_get("/api/v3/ticker", {"symbols": json.dumps(batch[j:j + 25], separators=(",", ":")), "windowSize": "15m"})
                data.extend(part or [])
                time.sleep(0.2)
        for t in data or []:
            try:
                out[t["symbol"]] = {
                    "change_15m": float(t["priceChangePercent"]), "last": float(t["lastPrice"]),
                    "quote_volume_15m": float(t["quoteVolume"]), "trades_15m": float(t.get("count", 0)),
                    "high_15m": float(t["highPrice"]), "low_15m": float(t["lowPrice"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
        time.sleep(0.2)
    return out


def binance_volume_spike(symbol: str, bars: int = 97) -> dict[str, float] | None:
    """نسبت حجم ۱۵ دقیقهٔ اخیر به میانگین ۲۴ ساعت قبل + تعداد کندل‌های سبز متوالی."""
    raw = _binance_get("/api/v3/klines", {"symbol": symbol, "interval": "15m", "limit": bars})
    if not raw or len(raw) < 10:
        return None
    try:
        vols = [float(k[7]) for k in raw]           # quote volume
        closes = [float(k[4]) for k in raw]
        opens = [float(k[1]) for k in raw]
        base = vols[:-1]
        mean = sum(base) / max(len(base), 1)
        spike = vols[-1] / mean if mean > 0 else 0.0
        # بزرگ‌ترین حجم ۲۴ ساعت نسبت به میانگین → آیا «پول سنگین یکهویی» قبل از این کندل هم آمده بود؟
        pre = max(base[-4:]) / mean if mean > 0 and len(base) >= 4 else 0.0
        green = 0
        for o, c in zip(reversed(opens), reversed(closes)):
            if c > o:
                green += 1
            else:
                break
        ret_1h = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 and closes[-5] > 0 else 0.0
        ret_4h = (closes[-1] / closes[-17] - 1) * 100 if len(closes) >= 17 and closes[-17] > 0 else 0.0
        return {"vol_spike": round(spike, 2), "vol_pre_spike": round(pre, 2), "green_streak": green,
                "ret_1h": round(ret_1h, 2), "ret_4h": round(ret_4h, 2)}
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------- CoinGecko

def coingecko_markets(pages: int = 2) -> dict[str, dict[str, Any]]:
    """۲۵۰×pages ارز برتر از نظر حجم. کلید: نماد بزرگ (BTC). بدون کلید API."""
    out: dict[str, dict[str, Any]] = {}
    for page in range(1, pages + 1):
        r = _get(f"{COINGECKO}/coins/markets", {
            "vs_currency": "usd", "order": "volume_desc", "per_page": 250, "page": page,
            "price_change_percentage": "1h,24h,7d", "sparkline": "false",
        })
        if not r:
            break
        try:
            rows = r.json()
        except Exception:  # noqa: BLE001
            break
        for c in rows:
            sym = str(c.get("symbol", "")).upper()
            if not sym or not is_tradeable_base(sym) or sym in out:
                continue
            out[sym] = {
                "id": c.get("id"), "name": c.get("name"), "price": c.get("current_price"),
                "rank": c.get("market_cap_rank"), "market_cap": c.get("market_cap"), "volume_24h": c.get("total_volume"),
                "change_1h": c.get("price_change_percentage_1h_in_currency"),
                "change_24h": c.get("price_change_percentage_24h_in_currency"),
                "change_7d": c.get("price_change_percentage_7d_in_currency"),
                "ath_change": c.get("ath_change_percentage"), "ath_date": c.get("ath_date"),
            }
        time.sleep(1.2)
    return out


def coingecko_trending() -> list[str]:
    r = _get(f"{COINGECKO}/search/trending")
    if not r:
        return []
    try:
        return [str(c["item"]["symbol"]).upper() for c in r.json().get("coins", [])][:15]
    except Exception:  # noqa: BLE001
        return []


def coingecko_categories(coin_id: str) -> list[str]:
    r = _get(f"{COINGECKO}/coins/{coin_id}", {"localization": "false", "tickers": "false", "market_data": "false",
                                               "community_data": "false", "developer_data": "false", "sparkline": "false"})
    if not r:
        return []
    try:
        return [str(x) for x in (r.json().get("categories") or []) if x][:12]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- CoinMarketCap

def cmc_listing(limit: int = 500) -> dict[str, dict[str, Any]]:
    """با CMC_API_KEY از API رسمی؛ بدون کلید از data-api عمومی سایت. کلید: نماد."""
    out: dict[str, dict[str, Any]] = {}
    key = os.environ.get("CMC_API_KEY")
    if key:
        r = _get(CMC_PRO, {"start": 1, "limit": limit, "sort": "volume_24h", "convert": "USD"},
                 {"X-CMC_PRO_API_KEY": key, "Accept": "application/json"})
        rows = []
        if r:
            try:
                rows = r.json().get("data") or []
            except Exception:  # noqa: BLE001
                rows = []
        for c in rows:
            q = (c.get("quote") or {}).get("USD") or {}
            _cmc_put(out, c.get("symbol"), c.get("cmc_rank"), c.get("tags") or [], q.get("percent_change_1h"),
                     q.get("percent_change_24h"), q.get("percent_change_7d"), q.get("volume_24h"), q.get("market_cap"),
                     c.get("date_added"), c.get("name"))
        if out:
            return out
    r = _get(CMC_PUBLIC, {"start": 1, "limit": limit, "sortBy": "volume_24h", "sortType": "desc", "convert": "USD",
                          "cryptoType": "all", "tagType": "all"})
    if not r:
        return out
    try:
        rows = ((r.json().get("data") or {}).get("cryptoCurrencyList")) or []
    except Exception:  # noqa: BLE001
        return out
    for c in rows:
        q = (c.get("quotes") or [{}])[0]
        _cmc_put(out, c.get("symbol"), c.get("cmcRank"), c.get("tags") or [], q.get("percentChange1h"), q.get("percentChange24h"),
                 q.get("percentChange7d"), q.get("volume24h"), q.get("marketCap"), c.get("dateAdded"), c.get("name"))
    return out


def _cmc_put(out: dict[str, dict[str, Any]], symbol: Any, rank: Any, tags: list[Any], c1h: Any, c24h: Any, c7d: Any,
             vol: Any, mcap: Any, added: Any, name: Any) -> None:
    sym = str(symbol or "").upper()
    if not sym or sym in out or not is_tradeable_base(sym):
        return
    out[sym] = {"rank": rank, "tags": [str(t) for t in tags][:20], "change_1h": c1h, "change_24h": c24h, "change_7d": c7d,
                "volume_24h": vol, "market_cap": mcap, "date_added": added, "name": name}
