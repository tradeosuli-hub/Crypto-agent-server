"""
منابع اطلاعاتی تأییدشده (رایگان، بدون کلید) — هر تابع لیستی از آیتم‌های خام با قالب یکسان برمی‌گرداند:
  {"source", "title", "url", "published", "kind", "raw_symbols": [...]}
هر منبع در خطا لیست خالی می‌دهد؛ هیچ منبعی کل چرخه را نمی‌اندازد.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

UA = {"User-Agent": "Mozilla/5.0 (PhoenixOrg; +https://github.com/tradeosuli-hub/Crypto-agent-server)"}
TIMEOUT = 20

RSS_FEEDS = {
    "cointelegraph": "https://cointelegraph.com/rss",
    "theblock": "https://www.theblock.co/rss.xml",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
}
# کاتالوگ‌های اعلان رسمی بایننس
BINANCE_CATALOGS = {48: "listing", 161: "delisting", 49: "exchange_news"}
BINANCE_CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
COINGECKO = "https://api.coingecko.com/api/v3"
FNG = "https://api.alternative.me/fng/"

TICKER_RE = re.compile(r"\b([A-Z]{2,10})\b")
# کلیدواژه‌های رویداد توکنی → نوع
EVENT_KEYWORDS = [
    ("unlock", "token_unlock"), ("vesting", "token_unlock"), ("آنلاک", "token_unlock"),
    ("burn", "token_burn"), ("buyback", "token_burn"),
    ("delist", "delisting"), ("will list", "listing"), ("listing", "listing"), ("launches", "listing"),
    ("hack", "security"), ("exploit", "security"), ("drain", "security"), ("breach", "security"),
    ("etf", "etf_flow"),
    ("sec ", "regulation"), ("lawsuit", "regulation"), ("regulat", "regulation"), ("ban ", "regulation"),
    ("fed ", "macro"), ("fomc", "macro"), ("cpi", "macro"), ("rate cut", "macro"), ("rate hike", "macro"), ("tariff", "macro"),
    ("mainnet", "project"), ("upgrade", "project"), ("hard fork", "project"), ("airdrop", "project"), ("partnership", "project"),
    ("liquidat", "market"), ("whale", "market"), ("outflow", "market"), ("inflow", "market"),
]


def _get(url: str, params: dict[str, Any] | None = None) -> requests.Response | None:
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        return r if r.ok else None
    except Exception:  # noqa: BLE001
        return None


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def classify_kind(title: str) -> str:
    t = " " + title.lower() + " "
    for kw, kind in EVENT_KEYWORDS:
        if kw in t:
            return kind
    return "news"


def extract_tickers(title: str, known: set[str]) -> list[str]:
    """تیکرهای شناخته‌شده (BTC, ETH, …) داخل عنوان؛ فقط آن‌هایی که واقعاً جفت USDT دارند."""
    found = []
    for m in TICKER_RE.findall(title):
        if m in known and m not in found:
            found.append(m)
    # نام‌های رایج
    aliases = {"bitcoin": "BTC", "ethereum": "ETH", "ether": "ETH", "solana": "SOL", "cardano": "ADA", "ripple": "XRP",
               "dogecoin": "DOGE", "bnb": "BNB", "binance coin": "BNB", "avalanche": "AVAX", "polygon": "POL",
               "chainlink": "LINK", "toncoin": "TON", "tron": "TRX", "litecoin": "LTC", "polkadot": "DOT", "sui": "SUI",
               "aptos": "APT", "near": "NEAR", "arbitrum": "ARB", "optimism": "OP", "pepe": "PEPE", "shiba": "SHIB"}
    low = title.lower()
    for name, tk in aliases.items():
        if name in low and tk in known and tk not in found:
            found.append(tk)
    return found


def rss_items(known: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, url in RSS_FEEDS.items():
        r = _get(url)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            if not title:
                continue
            link = (it.findtext("link") or "").strip()
            pub = it.findtext("pubDate")
            try:
                dt = parsedate_to_datetime(pub) if pub else None
            except Exception:  # noqa: BLE001
                dt = None
            out.append({
                "source": name, "title": title, "url": link, "published": _iso(dt),
                "kind": classify_kind(title), "raw_symbols": extract_tickers(title, known),
            })
    return out


def binance_announcements(known: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cat, kind in BINANCE_CATALOGS.items():
        r = _get(BINANCE_CMS, {"type": 1, "pageNo": 1, "pageSize": 15, "catalogId": cat})
        if not r:
            continue
        try:
            arts = r.json()["data"]["catalogs"][0]["articles"]
        except Exception:  # noqa: BLE001
            continue
        for a in arts:
            title = a.get("title", "")
            ms = a.get("releaseDate")
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None
            k = kind if kind != "exchange_news" else classify_kind(title)
            out.append({
                "source": "binance", "title": title,
                "url": f"https://www.binance.com/en/support/announcement/{a.get('code')}",
                "published": _iso(dt), "kind": k, "raw_symbols": extract_tickers(title, known),
            })
    return out


def coingecko_market() -> dict[str, Any]:
    """نبض بازار: دامیننس واقعی BTC/USDT، تغییر مارکت‌کپ، ترندها، ترس‌وطمع."""
    info: dict[str, Any] = {}
    g = _get(f"{COINGECKO}/global")
    if g:
        try:
            d = g.json()["data"]
            info["btc_dominance"] = round(float(d["market_cap_percentage"].get("btc", 0)), 2)
            info["usdt_dominance"] = round(float(d["market_cap_percentage"].get("usdt", 0)), 2)
            info["mcap_change_24h"] = round(float(d.get("market_cap_change_percentage_24h_usd", 0)), 2)
        except Exception:  # noqa: BLE001
            pass
    t = _get(f"{COINGECKO}/search/trending")
    if t:
        try:
            info["trending"] = [c["item"]["symbol"].upper() for c in t.json().get("coins", [])][:10]
        except Exception:  # noqa: BLE001
            pass
    f = _get(FNG)
    if f:
        try:
            x = f.json()["data"][0]
            info["fear_greed"] = int(x["value"])
            info["fear_greed_label"] = x["value_classification"]
        except Exception:  # noqa: BLE001
            pass
    return info
