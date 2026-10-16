import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
    request = urllib.request.Request(
        "https://api.twelvedata.com/time_series?" + params,
        headers={"User-Agent": "stock-radar/1.3"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if data.get("status") == "error" or not data.get("values"):
        raise ValueError(data.get("message", "No candle data returned"))
    bars = []
    for item in reversed(data["values"]):
        try:
            dt = datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)
            bar = {"dt": dt}
            for field in ("open", "high", "low", "close", "volume"):
                bar[field] = float(item[field])
            if all(math.isfinite(bar[field]) for field in ("open", "high", "low", "close", "volume")):
                bars.append(bar)
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def analyze(symbol, bars):
    now = datetime.now(NY)
    market_open = now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)
    # Twelve Data timestamps identify candle starts. Exclude unfinished candles.
    bars = [b for b in bars if b["dt"] + timedelta(minutes=5) <= now
            and (9, 30) <= (b["dt"].hour, b["dt"].minute) < (16, 0)]
    result = {"symbol": symbol, "group": "core" if symbol in CORE_SYMBOLS else "extra",
              "status": "資料不足", "signal": False, "rank_score": None,
              "data_is_fresh": False, "market_is_open": market_open}
    if not bars:
        return result
    latest = bars[-1]
    end = latest["dt"] + timedelta(minutes=5)
    delay = max(0, (now - end).total_seconds() / 60)
    fresh = market_open and latest["dt"].date() == now.date() and delay <= MAX_DELAY_MINUTES
    result.update({"bar_time_et": latest["dt"].strftime("%Y-%m-%d %H:%M"),
                   "bar_end_time_et": end.strftime("%Y-%m-%d %H:%M"),
                   "data_delay_minutes": round(delay, 1), "data_is_fresh": fresh,
                   "close": round(latest["close"], 2),
                   "status": "觀察中" if fresh else ("行情延遲" if market_open else "行情過期")})
    if len(bars) < 35:
        result["status"] = "資料不足" if fresh else result["status"]
        return result

    closes = [b["close"] for b in bars]
    ema = closes[0]
    for close in closes[1:]:
        ema = close * (2 / 21) + ema * (19 / 21)
    today = [b for b in bars if b["dt"].date() == latest["dt"].date()]
    total_volume = sum(b["volume"] for b in today)
    vwap = (sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in today)
            / total_volume if total_volume > 0 else None)
    previous_volumes = [b["volume"] for b in bars[-21:-1]]
    avg_volume = sum(previous_volumes) / len(previous_volumes) if previous_volumes else 0
    volume_ratio = latest["volume"] / avg_volume if avg_volume > 0 else 0

    true_ranges = []
    for i in range(1, len(bars)):
        b, prev = bars[i], bars[i - 1]
        true_ranges.append(max(b["high"] - b["low"],
                               abs(b["high"] - prev["close"]),
                               abs(b["low"] - prev["close"])))
    atr = sum(true_ranges[-14:]) / 14
    prior_high = max(b["high"] for b in bars[-21:-1])
    breakout = latest["close"] > prior_high
    above_ema = latest["close"] > ema
    above_vwap = vwap is not None and latest["close"] > vwap
    volume_ok = volume_ratio >= 1.5
    signal = bool(fresh and breakout and above_ema and above_vwap and volume_ok)
    entry = max(latest["close"], prior_high)
    stop = entry - max(atr * 1.5, entry * 0.003)
    risk = entry - stop
    score = round((2 if breakout else 0) + (1 if above_ema else 0)
                  + (1 if above_vwap else 0) + min(volume_ratio, 5) / 2, 3)
    result.update({"status": "候選進場" if signal else result["status"],
                   "signal": signal, "rank_score": score if fresh else None,
                   "ema20": round(ema, 3), "vwap": round(vwap, 3) if vwap is not None else None,
                   "volume_ratio": round(volume_ratio, 2), "breakout": breakout,
                   "entry_reference": round(entry, 2), "stop_reference": round(stop, 2),
                   "target_1_5R": round(entry + 1.5 * risk, 2),
                   "target_2R": round(entry + 2 * risk, 2), "atr14": round(atr, 3)})
    return result


def main():
    if not KEY:
        raise RuntimeError("Missing TWELVEDATA_API_KEY GitHub Actions secret")
    results = []
    for symbol in SYMBOLS:
        try:
            item = analyze(symbol, fetch(symbol))
        except Exception as exc:
            item = {"symbol": symbol, "group": "core" if symbol in CORE_SYMBOLS else "extra",
                    "status": "資料取得失敗", "signal": False, "rank_score": None,
                    "data_is_fresh": False, "error": str(exc)}
        results.append(item)
        print(json.dumps(item, ensure_ascii=False))
    eligible = [r for r in results if r.get("data_is_fresh") and r.get("rank_score") is not None]
    eligible.sort(key=lambda r: (r["signal"], r["rank_score"]), reverse=True)
    top_candidates = [{"rank": i, "symbol": r["symbol"], "score": r["rank_score"],
                       "signal": r["signal"]} for i, r in enumerate(eligible[:5], 1)]
    payload = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "source": "Twelve Data", "interval": "5min",
               "max_acceptable_delay_minutes": MAX_DELAY_MINUTES,
               "candidate_universe": list(SYMBOLS), "top_candidates": top_candidates,
               "results": results}
    with open("radar.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("TOP CANDIDATES:", json.dumps(top_candidates, ensure_ascii=False))


if __name__ == "__main__":
    main()
