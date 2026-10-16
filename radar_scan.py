import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Four original symbols plus two experimental candidates.
CORE_SYMBOLS = ("NVDL", "TSLL", "MSTU", "AMDL")
EXTRA_SYMBOLS = ("CONL", "PLTU")
SYMBOLS = CORE_SYMBOLS + EXTRA_SYMBOLS
KEY = os.environ.get("TWELVEDATA_API_KEY", "").strip()
NY = ZoneInfo("America/New_York")
MAX_DELAY_MINUTES = 15


def fetch(symbol):
    params = urllib.parse.urlencode({
        "symbol": symbol, "interval": "5min", "outputsize": 120,
        "timezone": "America/New_York", "apikey": KEY,
    })
    req = urllib.request.Request(
        "https://api.twelvedata.com/time_series?" + params,
        headers={"User-Agent": "stock-radar/1.2"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)
    if data.get("status") == "error" or not data.get("values"):
        raise ValueError(data.get("message", "No candle data"))
    bars = []
    for item in reversed(data["values"]):
        try:
            dt = datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)
            bar = {"dt": dt}
            for field in ("open", "high", "low", "close", "volume"):
                bar[field] = float(item[field])
            if all(math.isfinite(bar[k]) for k in ("open", "high", "low", "close", "volume")):
                bars.append(bar)
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def analyze(symbol, all_bars):
    now = datetime.now(NY)
    bars = [
        b for b in all_bars
        if b["dt"] + timedelta(minutes=5) <= now
        and (9, 30) <= (b["dt"].hour, b["dt"].minute) < (16, 0)
        and b["dt"].weekday() < 5
    ]
    result = {
        "symbol": symbol, "group": "core" if symbol in CORE_SYMBOLS else "extra",
        "status": "資料不足", "signal": False, "rank_score": None,
    }
    if not bars:
        return result
    latest = bars[-1]
    candle_end = latest["dt"] + timedelta(minutes=5)
    delay = max(0, round((now - candle_end).total_seconds() / 60, 1))
    market_open = now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)
    fresh = market_open and delay <= MAX_DELAY_MINUTES
    result.update({
        "bar_time_et": latest["dt"].strftime("%Y-%m-%d %H:%M"),
        "bar_end_time_et": candle_end.strftime("%Y-%m-%d %H:%M"),
        "data_delay_minutes": delay,
        "data_is_fresh": fresh,
        "market_is_open": market_open,
        "close": round(latest["close"], 2),
    })
    if len(bars) < 35:
        return result

    closes = [b["close"] for b in bars]
    ema = closes[0]
    for close in closes[1:]:
        ema = close * (2 / 21) + ema * (19 / 21)

    today = [b for b in bars if b["dt"].date() == latest["dt"].date()]
    total_volume = sum(b["volume"] for b in today)
    vwap = (
        sum(((b["high"] + b["low"] + b["close"]) / 3) * b["volume"] for b in today) / total_volume
        if total_volume > 0 else None
    )
    prev_volumes = [b["volume"] for b in bars[-21:-1]]
    avg_volume = sum(prev_volumes) / len(prev_volumes)
    volume_ratio = latest["volume"] / avg_volume if avg_volume > 0 else 0

    ranges = []
    for i in range(1, len(bars)):
        b, prev = bars[i], bars[i - 1]
        ranges.append(max(
            b["high"] - b["low"],
            abs(b["high"] - prev["close"]),
            abs(b["low"] - prev["close"]),
