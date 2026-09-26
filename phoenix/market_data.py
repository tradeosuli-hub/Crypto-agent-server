"""داده‌های بازار — Binance Vision (عمومی)؛ قوانین برای همهٔ ارزها یکسان."""
from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests

# api.binance.com از برخی لوکیشن‌ها 451 می‌دهد؛ data-api عمومی است.
BINANCE_DATA = "https://data-api.binance.vision"
OKX = "https://www.okx.com"

TF_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
}


class MarketDataError(RuntimeError):
    pass


def _get(url: str, params: dict[str, Any] | None = None, timeout: float = 25.0) -> Any:
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, params=params or {}, timeout=timeout)
            if r.status_code in (429, 418):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.4 * (attempt + 1))
    raise MarketDataError(f"request failed: {url} :: {last_err}")


def list_usdt_spot(limit: int | None = None) -> list[str]:
    """همهٔ جفت‌های USDT اسپات در حال معامله — قوانین برای همه یکسان."""
    data = _get(f"{BINANCE_DATA}/api/v3/exchangeInfo")
    syms = []
    for s in data.get("symbols", []):
        if (
            s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed", True)
        ):
            # فیلتر لوریج‌توکن‌ها
            base = s.get("baseAsset", "")
            if base.endswith(("UP", "DOWN", "BULL", "BEAR")):
                continue
            syms.append(s["symbol"])
    syms.sort()
    if limit:
        return syms[:limit]
    return syms


# استیبل/فیات‌مانند — برای پنل سیگنال ترید مفید نیستند
_STABLE_BASES = {
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "AEUR", "EURI",
    "USD1", "RLUSD", "USDE", "BFUSD", "XUSD", "USD", "PAX", "BUSD",
}


def _is_tradeable_usdt(symbol: str) -> bool:
    if not symbol.endswith("USDT"):
        return False
    if any(x in symbol for x in ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")):
        return False
    base = symbol[:-4]
    if base in _STABLE_BASES:
        return False
    return True


def top_usdt_by_volume(n: int = 50) -> list[str]:
    tickers = _get(f"{BINANCE_DATA}/api/v3/ticker/24hr")
    usdt = [t for t in tickers if _is_tradeable_usdt(str(t.get("symbol", "")))]
    usdt.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    return [t["symbol"] for t in usdt[:n]]


# سازگاری با نام قبلی
list_usdt_perpetuals = list_usdt_spot


def klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    iv = TF_MAP.get(interval, interval)
    raw = _get(
        f"{BINANCE_DATA}/api/v3/klines",
        {"symbol": symbol, "interval": iv, "limit": limit},
    )
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(raw, columns=cols)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df


def fetch_multi_tf(symbol: str, limit: int = 500) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for tf in ("4h", "1h", "15m", "5m"):
        out[tf] = klines(symbol, tf, limit=limit)
        time.sleep(0.03)
    return out


def fetch_dominance_proxy() -> dict[str, Any]:
    """
    پروکسی دامیننس تتر از BTC (تا وقتی USDT.D واقعی نباشد).
    کور بودن = بدون وتو.
    """
    try:
        btc = klines("BTCUSDT", "1h", limit=80)
        ret = float(btc["close"].iloc[-1] / btc["close"].iloc[-24] - 1)
        vol_z = float(
            (btc["volume"].iloc[-1] - btc["volume"].tail(24).mean())
            / max(float(btc["volume"].tail(24).std()), 1e-12)
        )
        if ret < -0.02 and vol_z > 0.5:
            bias, allow_long, allow_short = "risk_off", False, True
            root = "ریزش واقعی محتمل"
        elif ret > 0.02 and vol_z > 0:
            bias, allow_long, allow_short = "risk_on", True, False
            root = "پول تازه / ریسک‌آن محتمل"
        else:
            bias, allow_long, allow_short = "neutral", True, True
            root = "خنثی / دادهٔ پروکسی ضعیف"
        return {
            "ok": True,
            "proxy": True,
            "bias": bias,
            "allow_long": allow_long,
            "allow_short": allow_short,
            "root_fa": root,
            "btc_ret_24h": ret,
            "note_fa": "دامیننس واقعی USDT.D در دسترس نیست؛ از پروکسی BTC استفاده شد.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "proxy": True,
            "bias": "blind",
            "allow_long": True,
            "allow_short": True,
            "root_fa": "کور",
            "error": str(exc),
            "note_fa": "دامیننس کور است؛ وتو نمی‌کند.",
        }
