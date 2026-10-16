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
        ))
    atr = sum(ranges[-14:]) / 14
    previous_high = max(b["high"] for b in bars[-21:-1])
    breakout = latest["close"] > previous_high
    entry = previous_high
    stop = entry - 1.5 * atr
    risk = entry - stop
    above_ema = latest["close"] > ema
    above_vwap = vwap is not None and latest["close"] > vwap
    setup = above_ema and above_vwap and volume_ratio >= 1.5 and breakout and risk > 0
    signal = bool(setup and fresh)

    # A transparent technical ranking, NOT a prediction or trade instruction.
    score = (
        (25 if above_ema else 0)
        + (25 if above_vwap else 0)
        + (25 if breakout else 0)
        + min(25, max(0, volume_ratio - 1) * 12.5)
    )
    result.update({
        "status": "候選進場" if signal else ("行情過期" if not fresh else "觀察中"),
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
        "rank_score": round(score, 1),
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
            item = {
                "symbol": symbol,
                "group": "core" if symbol in CORE_SYMBOLS else "extra",
                "status": "資料取得失敗", "signal": False,
                "rank_score": None, "error": str(exc),
            }
        results.append(item)
        print(json.dumps(item, ensure_ascii=False))

    # Exclude stale, missing, and invalid records from actionable candidates.
    eligible = [r for r in results if r.get("data_is_fresh") and r.get("rank_score") is not None]
    eligible.sort(key=lambda r: (r["signal"], r["rank_score"]), reverse=True)
    top_candidates = [
        {"rank": i, "symbol": r["symbol"], "score": r["rank_score"], "signal": r["signal"]}
        for i, r in enumerate(eligible[:5], start=1)
    ]
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Twelve Data", "interval": "5min",
        "max_acceptable_delay_minutes": MAX_DELAY_MINUTES,
        "candidate_universe": list(SYMBOLS),
        "top_candidates": top_candidates,
        "results": results,
    }
    with open("radar.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("TOP CANDIDATES:", json.dumps(top_candidates, ensure_ascii=False))


if __name__ == "__main__":
    main()
