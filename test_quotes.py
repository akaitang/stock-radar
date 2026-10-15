
import json
import os
import urllib.parse
import urllib.request

SYMBOLS = ["NVDL", "TSLL", "MSTU", "AMDL"]
API_KEY = os.environ.get("TWELVEDATA_API_KEY", "").strip()

if not API_KEY:
    raise SystemExit("Missing TWELVEDATA_API_KEY")

for symbol in SYMBOLS:
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": "5min",
        "outputsize": 10,
        "apikey": API_KEY
    })
    url = "https://api.twelvedata.com/time_series?" + params

    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            data = json.load(response)

        if data.get("status") == "error" or not data.get("values"):
            print(symbol, "FAILED:", data.get("message", "No data"))
            continue

        bar = data["values"][0]
        print(
            symbol, "OK",
            "Time:", bar.get("datetime"),
            "Close:", bar.get("close"),
            "Volume:", bar.get("volume")
        )
    except Exception as error:
        print(symbol, "FAILED:", error)
