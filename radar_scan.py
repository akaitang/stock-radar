import os, json, math, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SYMBOLS = ('NVDL','TSLL','MSTU','AMDL')
KEY = os.environ.get('TWELVEDATA_API_KEY','').strip()
NY = ZoneInfo('America/New_York')

def fetch(symbol):
    params = urllib.parse.urlencode({'symbol':symbol,'interval':'5min','outputsize':120,'timezone':'America/New_York','apikey':KEY})
    req = urllib.request.Request('https://api.twelvedata.com/time_series?'+params, headers={'User-Agent':'stock-radar/1.0'})
    with urllib.request.urlopen(req,timeout=30) as r: data=json.load(r)
    if data.get('status')=='error' or not data.get('values'):
        raise ValueError(data.get('message','No candle data'))
    bars=[]
    for x in reversed(data['values']):
        try:
            dt=datetime.strptime(x['datetime'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            b={'dt':dt,'open':float(x['open']),'high':float(x['high']),'low':float(x['low']),'close':float(x['close']),'volume':float(x['volume'])}
            if all(math.isfinite(b[k]) for k in ('open','high','low','close','volume')): bars.append(b)
        except (ValueError,TypeError,KeyError): continue
    return bars

def analyze(symbol,bars):
    now=datetime.now(NY)
    # Exclude still-forming candles, and exclude extended-hours bars.
    bars=[b for b in bars if b['dt']+timedelta(minutes=5)<=now and (9,30)<=(b['dt'].hour,b['dt'].minute)<(16,0)]
    if len(bars)<35: return {'symbol':symbol,'status':'資料不足','bars':len(bars)}
    last=bars[-1]
    # Only use current session for VWAP. A new trading day resets the VWAP.
    today=[b for b in bars if b['dt'].date()==last['dt'].date()]
    volsum=sum(b['volume'] for b in today)
    if volsum<=0: return {'symbol':symbol,'status':'缺少成交量'}
    vwap=sum(((b['high']+b['low']+b['close'])/3)*b['volume'] for b in today)/volsum
    ema=bars[0]['close']; alpha=2/21
    for b in bars[1:]: ema=alpha*b['close']+(1-alpha)*ema
    prev=bars[-7:-1]
    breakout=max(b['high'] for b in prev)
    avgvol=sum(b['volume'] for b in bars[-21:-1])/20
    volratio=last['volume']/avgvol if avgvol>0 else 0
    trs=[]
    for i in range(1,len(bars)):
        b,p=bars[i],bars[i-1]
        trs.append(max(b['high']-b['low'],abs(b['high']-p['close']),abs(b['low']-p['close'])))
    atr=sum(trs[-14:])/14
    entry=round(breakout+0.01,2)
    stop=round(entry-1.5*atr,2)
    risk=entry-stop
    trend=last['close']>ema and last['close']>vwap
    signal=last['close']>breakout and trend and volratio>=1.5
    status='候選進場' if signal else ('等待突破' if trend else '觀察中')
    return {'symbol':symbol,'status':status,'bar_time_et':last['dt'].strftime('%Y-%m-%d %H:%M'), 'close':round(last['close'],3),'ema20':round(ema,3),'vwap':round(vwap,3),'volume_ratio':round(volratio,2),'breakout':round(breakout,3),'entry_reference':entry,'stop_reference':stop,'target_1_5R':round(entry+1.5*risk,2),'target_2R':round(entry+2*risk,2),'atr14':round(atr,3),'signal':signal}

def main():
    if not KEY: raise SystemExit('Missing TWELVEDATA_API_KEY')
    results=[]
    for symbol in SYMBOLS:
        try:
            result=analyze(symbol,fetch(symbol))
        except Exception as exc:
            result={'symbol':symbol,'status':'API 錯誤','error':str(exc)}
        results.append(result)
        print(json.dumps(result,ensure_ascii=False))
    payload={'generated_at_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'source':'Twelve Data','interval':'5min','results':results}
    with open('radar.json','w',encoding='utf-8') as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)
    print('Saved radar.json')
if __name__=='__main__': main()
