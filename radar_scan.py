import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SYMBOLS = ("NVDL", "TSLL", "MSTU", "AMDL")
KEY = os.environ.get("TWELVEDATA_API_KEY", "").strip()
NY = ZoneInfo("America/New_York")
MAX_DELAY_MINUTES = 15


def fetch(symbol):
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": "5min",
        "outputsize": 120,
        "timezone": "America/New_York",
        "apikey": KEY,
    })
    req = urllib.request.Request(
        "https://api.twelvedata.com/time_series?" + params,
        headers={"User-Agent": "stock-radar/1.1"},
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
    # API bar timestamp is the START of a 5-minute candle.
    # Exclude incomplete candles and extended-hours candles.
    bars = [
        b for b in all_bars
        if b["dt"] + timedelta(minutes=5) <= now
        and (9, 30) <= (b["dt"].hour, b["dt"].minute) < (16, 0)
        and b["dt"].weekday() < 5
    ]
    result = {"symbol": symbol, "status": "資料不足", "signal": False}
    if not bars:
        return result

    latest = bars[-1]
    candle_end = latest["dt"] + timedelta(minutes=5)
    delay = max(0, round((now - candle_end).total_seconds() / 60, 1))
    is_market_open = now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)
    is_fresh = is_market_open and delay <= MAX_DELAY_MINUTES
    result.update({
        "bar_time_et": latest["dt"].strftime("%Y-%m-%d %H:%M"),
        "bar_end_time_et": candle_end.strftime("%Y-%m-%d %H:%M"),
        "data_delay_minutes": delay,
        "data_is_fresh": is_fresh,
        "market_is_open": is_market_open,
        "close": round(latest["close"], 2),
    })
    if len(bars) < 35:
        return result

    closes = [b["close"] for b in bars]
    ema = closes[0]
    alpha = 2 / 21
    for close in closes[1:]:
        ema = close * alpha + ema * (1 - alpha)

    today = [b for b in bars if b["dt"].date() == latest["dt"].date()]
    total_volume = sum(b["volume"] for b in today)
    vwap = (
        sum(((b["high"] + b["low"] + b["close"]) / 3) * b["volume"] for b in today)
        / total_volume if total_volume > 0 else None
    )

    previous_volumes = [b["volume"] for b in bars[-21:-1]]
    average_volume = sum(previous_volumes) / len(previous_volumes)
    volume_ratio = latest["volume"] / average_volume if average_volume > 0 else 0

    true_ranges = []
    for i in range(1, len(bars)):
        b, previous = bars[i], bars[i - 1]
        true_ranges.append(max(
            b["high"] - b["low"],
            abs(b["high"] - previous["close"]),
            abs(b["low"] - previous["close"]),
        ))
    atr = sum(true_ranges[-14:]) / 14

    previous_high = max(b["high"] for b in bars[-21:-1])
    breakout = latest["close"] > previous_high
    entry = previous_high
    stop = entry - 1.5 * atr
    risk = entry - stop
    technical_setup = (
        vwap is not None and latest["close"] > ema
        and latest["close"] > vwap
        and volume_ratio >= 1.5 and breakout and risk > 0
    )
    signal = bool(technical_setup and is_fresh)
    status = "候選進場" if signal else ("行情過期" if not is_fresh else "觀察中")

    result.update({
        "status": status,
        "ema20": round(ema, 3),
        "vwap": round(vwap, 3) if vwap is not None else None,
        "volume_ratio": round(volume_ratio, 2),
        "breakout": breakout,
        "entry_reference": round(entry, 2),
        "stop_reference": round(stop, 2),
        "target_1_5R": round(entry + 1.5 * risk, 2),
        "target_2R": round(entry + 2 * risk, 2),
        "atr14": round(atr, 3),
        "signal": signal,
    })
    return result


def main():
    if not KEY:
        raise RuntimeError("Missing TWELVEDATA_API_KEY GitHub Actions secret")
    results = []
    for symbol in SYMBOLS:
        try:
            item = analyze(symbol, fetch(symbol))
        except Exception as exc:
            item = {"symbol": symbol, "status": "資料取得失敗", "signal": False, "error": str(exc)}
        results.append(item)
        print(json.dumps(item, ensure_ascii=False))

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Twelve Data",
        "interval": "5min",
        "max_acceptable_delay_minutes": MAX_DELAY_MINUTES,
        "results": results,
    }
    with open("radar.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
