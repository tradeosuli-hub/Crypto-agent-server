"""موتور تحلیل تکنیکال متد حمید — مشترک برای همهٔ ارزها."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

WallVerdict = Literal[
    "untested",
    "young",
    "solid",
    "hammer_dulling",
    "wall_eroding",
    "wall_cracking",
]


@dataclass
class OrderBlock:
    low: float
    high: float
    mid: float
    index: int
    bullish_impulse: bool  # حرکت بعد از کندل صعودی بود؟
    reactions: int = 0
    verdict: WallVerdict = "untested"
    penetrations: list[float] = field(default_factory=list)
    rejections: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class Channel:
    lookback: int
    upper: float
    mid: float
    lower: float
    slope: float
    touches: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Level:
    price: float
    strength: Literal["very_strong", "strong", "normal"]
    kind: Literal["support", "resistance", "pivot"]
    touches: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def volume_z(series: pd.Series, window: int = 20) -> pd.Series:
    m = series.rolling(window, min_periods=5).mean()
    s = series.rolling(window, min_periods=5).std().replace(0, np.nan)
    return (series - m) / s


def _body_dominant(o: float, h: float, l: float, c: float) -> bool:
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return body > (upper + lower) and body > 0


def order_blocks(
    df: pd.DataFrame,
    walkback: int = 6,
    merge: bool = True,
) -> list[OrderBlock]:
    """اولین کندل رنگ مخالف قبل از حرکت تکانه‌ای با بدنه > مجموع شدوها."""
    if len(df) < walkback + 3:
        return []
    blocks: list[OrderBlock] = []
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)

    for i in range(walkback + 1, n - 1):
        # impulse candle i: strong move
        impulse_up = c[i] > o[i] and (c[i] - o[i]) > (h[i] - l[i]) * 0.55
        impulse_dn = c[i] < o[i] and (o[i] - c[i]) > (h[i] - l[i]) * 0.55
        if not (impulse_up or impulse_dn):
            continue
        want_bull = not impulse_up  # before up move look for red (bearish) candle
        found: list[int] = []
        for j in range(1, walkback + 1):
            k = i - j
            if k < 0:
                break
            is_bull = c[k] >= o[k]
            if is_bull == want_bull:
                continue
            if not _body_dominant(o[k], h[k], l[k], c[k]):
                continue
            found.append(k)
            if not merge:
                break
            # check consecutive previous
            if k - 1 >= 0:
                prev_bull = c[k - 1] >= o[k - 1]
                if prev_bull != want_bull and _body_dominant(o[k - 1], h[k - 1], l[k - 1], c[k - 1]):
                    found.append(k - 1)
            break
        if not found:
            continue
        lows = [l[k] for k in found]
        highs = [h[k] for k in found]
        lo, hi = min(lows), max(highs)
        blocks.append(
            OrderBlock(
                low=float(lo),
                high=float(hi),
                mid=float((lo + hi) / 2),
                index=int(min(found)),
                bullish_impulse=bool(impulse_up),
            )
        )

    # keep unique by mid proximity
    uniq: list[OrderBlock] = []
    for b in sorted(blocks, key=lambda x: x.index):
        if uniq and abs(b.mid - uniq[-1].mid) / max(b.mid, 1e-12) < 0.0015:
            # merge widen
            uniq[-1].low = min(uniq[-1].low, b.low)
            uniq[-1].high = max(uniq[-1].high, b.high)
            uniq[-1].mid = (uniq[-1].low + uniq[-1].high) / 2
            continue
        uniq.append(b)
    return uniq[-40:]


def annotate_reactions(
    df: pd.DataFrame,
    blocks: list[OrderBlock],
    atr_s: pd.Series,
    gap: int = 5,
    min_atr: float = 1.0,
    touch_pct: float = 0.25,
) -> list[OrderBlock]:
    """قانون ۸ — واکنش تاریخی."""
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    atr_v = atr_s.values
    for b in blocks:
        pens: list[float] = []
        rejs: list[float] = []
        last_i = -999
        band = max(b.high - b.low, 1e-12)
        for i in range(b.index + gap, len(df)):
            # touch?
            if l[i] > b.high or h[i] < b.low:
                continue
            penetrate = 0.0
            if c[i] >= b.mid:
                penetrate = max(0.0, (b.high - l[i]) / band)
            else:
                penetrate = max(0.0, (h[i] - b.low) / band)
            if penetrate < touch_pct:
                continue
            # rejection strength: move away after touch
            bounce = abs(c[i] - ((b.low + b.high) / 2)) / max(atr_v[i], 1e-12)
            if bounce < min_atr * 0.35 and i + 1 < len(df):
                bounce = abs(c[i + 1] - c[i]) / max(atr_v[i], 1e-12)
            if bounce < min_atr * 0.25:
                continue
            if i - last_i < gap:
                continue
            last_i = i
            pens.append(float(penetrate))
            rejs.append(float(bounce))
            b.reactions += 1
        b.penetrations = pens
        b.rejections = rejs
        b.verdict = wall_state(pens, rejs)
    return blocks


def wall_state(penetrations: list[float], rejections: list[float]) -> WallVerdict:
    """قانون دیوار و چکش — جهت تغییر حکم می‌دهد، نه تعداد."""
    if not penetrations:
        return "untested"
    if len(penetrations) == 1:
        return "young"
    p1, p2 = penetrations[-2], penetrations[-1]
    r1 = rejections[-2] if len(rejections) >= 2 else rejections[-1]
    r2 = rejections[-1]
    deeper = p2 > p1 * 1.15
    shallower = p2 < p1 * 0.85
    weaker = r2 < r1 * 0.85
    stronger = r2 > r1 * 1.15
    if deeper and weaker:
        return "wall_cracking"
    if deeper:
        return "wall_eroding"
    if shallower and stronger:
        return "solid"
    if (not deeper) and weaker:
        return "hammer_dulling"
    if shallower or stronger:
        return "solid"
    return "young"


def live_walls(
    blocks: list[OrderBlock],
    price: float,
    tradeable: set[str] | None = None,
) -> dict[str, OrderBlock | None]:
    """نزدیک‌ترین دیوار زنده زیر و بالای قیمت (فقط همین دو، بقیه نمایشی‌اند)."""
    if tradeable:
        blocks = [b for b in blocks if b.verdict in tradeable] or blocks
    below = [b for b in blocks if b.mid < price]
    above = [b for b in blocks if b.mid > price]
    bel = min(below, key=lambda b: price - b.mid, default=None)
    abv = min(above, key=lambda b: b.mid - price, default=None)
    return {"below": bel, "above": abv}


def wick_rejection(
    df: pd.DataFrame,
    band: OrderBlock,
    min_shadow_ratio: float = 1.0,
    min_pen_pct: float = 0.2,
    lookback: int = 2,
) -> dict[str, Any] | None:
    """ماشه: ورود به دیوار + بسته‌شدن بیرون + شدو ≥ بدنه."""
    band_h = max(band.high - band.low, 1e-12)
    for offset in range(1, lookback + 1):
        if len(df) < offset:
            continue
        row = df.iloc[-offset]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body = abs(c - o)
        # بدنهٔ خیلی کوچک را با کف کوچک نسبت به رنج کندل جایگزین کن تا نسبت بی‌نهایت نشود
        range_ = max(h - l, 1e-12)
        body_eff = max(body, range_ * 0.05)
        upper = h - max(o, c)
        lower = min(o, c) - l
        # long rejection from below into band
        if l <= band.high and c >= band.low:
            pen = (min(band.high, h) - max(band.low, l)) / band_h
            if pen >= min_pen_pct and lower >= body_eff * min_shadow_ratio and c > band.low:
                if c >= o or lower >= upper:  # bullish lean
                    return {
                        "direction": "long",
                        "penetration": float(pen),
                        "shadow_ratio": float(lower / body_eff),
                        "candle_offset": offset,
                        "band": band.to_dict(),
                    }
        # short rejection from above into band
        if h >= band.low and c <= band.high:
            pen = (min(band.high, h) - max(band.low, l)) / band_h
            if pen >= min_pen_pct and upper >= body_eff * min_shadow_ratio and c < band.high:
                if c <= o or upper >= lower:
                    return {
                        "direction": "short",
                        "penetration": float(pen),
                        "shadow_ratio": float(upper / body_eff),
                        "candle_offset": offset,
                        "band": band.to_dict(),
                    }
    return None


def regression_channel(df: pd.DataFrame, lookback: int) -> Channel | None:
    if len(df) < max(20, lookback // 4):
        lb = min(len(df), lookback)
    else:
        lb = min(len(df), lookback)
    if lb < 20:
        return None
    sub = df.iloc[-lb:]
    y = sub["close"].values.astype(float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    resid = y - fitted
    std = float(np.std(resid))
    if std <= 0:
        return None
    upper = float(fitted[-1] + 2 * std)
    lower = float(fitted[-1] - 2 * std)
    mid = float(fitted[-1])
    # touches
    touches = int(((sub["high"].values >= fitted + 1.5 * std) | (sub["low"].values <= fitted - 1.5 * std)).sum())
    return Channel(lookback=lb, upper=upper, mid=mid, lower=lower, slope=float(slope), touches=touches)


def channels(df: pd.DataFrame, lookbacks: list[int]) -> list[Channel]:
    out: list[Channel] = []
    for lb in lookbacks:
        ch = regression_channel(df, lb)
        if ch:
            out.append(ch)
    return out


def channel_reentry(df: pd.DataFrame, ch: Channel) -> dict[str, Any] | None:
    """بازگشت بی‌قید و شرط به کانال."""
    if len(df) < 5:
        return None
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    # look for recent break outside then close back inside
    for i in range(len(df) - 1, max(len(df) - 8, 1), -1):
        outside_up = highs[i - 1] > ch.upper and closes[i - 1] > ch.mid
        outside_dn = lows[i - 1] < ch.lower and closes[i - 1] < ch.mid
        back_in = ch.lower <= closes[i] <= ch.upper
        if outside_up and back_in:
            return {
                "active": True,
                "direction": "short",
                "target": ch.lower,
                "alt_target": ch.mid,
                "channel": ch.to_dict(),
            }
        if outside_dn and back_in:
            return {
                "active": True,
                "direction": "long",
                "target": ch.upper,
                "alt_target": ch.mid,
                "channel": ch.to_dict(),
            }
    return None


def support_resistance(df: pd.DataFrame, window: int = 3) -> list[Level]:
    """نردبان سطوح از کف/سقف‌های محلی."""
    highs = df["high"].values
    lows = df["low"].values
    levels: list[Level] = []
    for i in range(window, len(df) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            levels.append(Level(price=float(highs[i]), strength="normal", kind="resistance", touches=0))
        if lows[i] == min(lows[i - window : i + window + 1]):
            levels.append(Level(price=float(lows[i]), strength="normal", kind="support", touches=0))
    # cluster & count touches
    if not levels:
        return []
    levels = sorted(levels, key=lambda x: x.price)
    clustered: list[Level] = []
    tol = float(df["close"].iloc[-1]) * 0.003
    for lv in levels:
        if clustered and abs(clustered[-1].price - lv.price) <= tol:
            clustered[-1].touches += 1
            clustered[-1].price = (clustered[-1].price + lv.price) / 2
            continue
        clustered.append(Level(price=lv.price, strength="normal", kind=lv.kind, touches=1))
    for lv in clustered:
        # wick confirmation boost
        wick_hits = 0
        for i in range(len(df)):
            if abs(highs[i] - lv.price) <= tol or abs(lows[i] - lv.price) <= tol:
                wick_hits += 1
        lv.touches = max(lv.touches, wick_hits)
        if lv.touches >= 3:
            lv.strength = "very_strong"
        elif lv.touches >= 2:
            lv.strength = "strong"
        else:
            lv.strength = "normal"
    return clustered[-30:]


def detect_fvg(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Fair Value Gap با افت جاذبه پس از برخورد."""
    gaps: list[dict[str, Any]] = []
    h = df["high"].values
    l = df["low"].values
    for i in range(2, len(df)):
        # bullish FVG: low[i] > high[i-2]
        if l[i] > h[i - 2]:
            gaps.append({"low": float(h[i - 2]), "high": float(l[i]), "dir": "bull", "idx": i, "power": 1.0})
        # bearish FVG
        if h[i] < l[i - 2]:
            gaps.append({"low": float(h[i]), "high": float(l[i - 2]), "dir": "bear", "idx": i, "power": 1.0})
    # decay by later touches
    for g in gaps:
        touches = 0
        for j in range(g["idx"] + 1, len(df)):
            if l[j] <= g["high"] and h[j] >= g["low"]:
                touches += 1
                g["power"] *= 0.5
        g["touches"] = touches
        g["spent"] = g["power"] < 0.3
    return gaps[-20:]


def bos_choch(df: pd.DataFrame, confirm: int = 2) -> dict[str, Any]:
    """شکست ساختار با تأیید دو کندلی."""
    if len(df) < 30:
        return {"bos": None, "choch": None, "trend": "flat"}
    swing_high = float(df["high"].iloc[-20:-2].max())
    swing_low = float(df["low"].iloc[-20:-2].min())
    c1 = float(df["close"].iloc[-2])
    c0 = float(df["close"].iloc[-1])
    o0 = float(df["open"].iloc[-1])
    bos = None
    if c1 > swing_high and c0 > swing_high and o0 > swing_high:
        bos = "bull"
    elif c1 < swing_low and c0 < swing_low and o0 < swing_low:
        bos = "bear"
    # crude trend from last 40 closes
    slope = np.polyfit(np.arange(40), df["close"].iloc[-40:].values.astype(float), 1)[0] if len(df) >= 40 else 0
    trend = "up" if slope > 0 else "down" if slope < 0 else "flat"
    choch = None
    if trend == "up" and bos == "bear":
        choch = "bear"
    if trend == "down" and bos == "bull":
        choch = "bull"
    return {"bos": bos, "choch": choch, "trend": trend, "confirm_candles": confirm}


def liquidation_map(
    df: pd.DataFrame,
    leverages: tuple[int, ...] = (10, 25, 50, 100),
    bins: int = 40,
) -> list[dict[str, float]]:
    """فالبک نقشهٔ لیکوییدیشن از قیمت+حجم (تا وقتی CoinGlass نباشد)."""
    price = float(df["close"].iloc[-1])
    clusters: dict[float, float] = {}
    for _, row in df.tail(120).iterrows():
        p = float(row["close"])
        v = float(row["volume"])
        for lev in leverages:
            long_liq = p * (1 - 1 / lev)
            short_liq = p * (1 + 1 / lev)
            for lp in (long_liq, short_liq):
                key = round(lp / price, 4)  # relative
                clusters[key] = clusters.get(key, 0.0) + v / lev
    if not clusters:
        return []
    # absolute prices near current
    items = sorted(
        [{"price": price * k, "score": s} for k, s in clusters.items()],
        key=lambda x: -x["score"],
    )
    return items[:bins]


def nearest_liq_outside(
    clusters: list[dict[str, float]],
    entry: float,
    direction: str,
    atr_v: float,
    buffer_atr: float = 0.25,
) -> float:
    buf = max(atr_v * buffer_atr, atr_v * 0.1)
    if direction == "long":
        cands = sorted([c["price"] for c in clusters if c["price"] < entry], reverse=True)
        if not cands:
            return entry - atr_v
        return cands[0] - buf
    cands = sorted([c["price"] for c in clusters if c["price"] > entry])
    if not cands:
        return entry + atr_v
    return cands[0] + buf


def rsi_divergence(df: pd.DataFrame, window: int = 60) -> dict[str, Any]:
    if len(df) < window:
        return {"bull_div": False, "bear_div": False, "rsi": None}
    sub = df.iloc[-window:]
    r = rsi(sub["close"])
    price_ll = sub["close"].iloc[-1] <= sub["close"].min() * 1.01
    price_hh = sub["close"].iloc[-1] >= sub["close"].max() * 0.99
    rsi_now = float(r.iloc[-1])
    rsi_min = float(r.min())
    rsi_max = float(r.max())
    bull = price_ll and rsi_now > rsi_min * 1.05
    bear = price_hh and rsi_now < rsi_max * 0.95
    return {"bull_div": bull, "bear_div": bear, "rsi": rsi_now}
