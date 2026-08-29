"""Adjusted daily market data and deterministic derived features."""
from dataclasses import dataclass
from statistics import fmean, stdev
from math import sqrt
from . import alpaca

DATA_HOST="https://data.alpaca.markets"
@dataclass(frozen=True)
class TickerFeatures:
    ticker:str; price:float; ret_1m:float|None; ret_12m:float|None; pct_off_52w_high:float|None; vol_60d:float|None; above_200d_ma:bool|None; bars_available:int

def fetch_bars(tickers,start,end):
    result={}
    for i in range(0,len(tickers),200):
        params={"symbols":','.join(tickers[i:i+200]),"timeframe":"1Day","start":start,"end":end,"limit":10000,"adjustment":"all"}
        while True:
            data=alpaca._request("GET",f"{DATA_HOST}/v2/stocks/bars",params=params)
            for symbol, rows in data.get("bars",{}).items(): result.setdefault(symbol,[]).extend(rows)
            token=data.get("next_page_token")
            if not token: break
            params={**params,"page_token":token}
    return result

def compute_features(bars,as_of):
    out={}
    for ticker,rows in bars.items():
        rows=sorted((r for r in rows if r["t"][:10]<=as_of),key=lambda r:r["t"])
        closes=[float(r["c"]) for r in rows]; n=len(closes)
        if not n: continue
        returns=[closes[i]/closes[i-1]-1 for i in range(1,n)]
        out[ticker]=TickerFeatures(ticker,closes[-1],closes[-1]/closes[-22]-1 if n>=22 else None,closes[-1]/closes[-253]-1 if n>=253 else None,closes[-1]/max(closes[-252:])-1 if n>=2 else None,stdev(returns[-60:])*sqrt(252) if n>=61 else None,closes[-1]>fmean(closes[-200:]) if n>=200 else None,n)
    return out

def compute_breadth(features):
    values=[f.above_200d_ma for f in features.values() if f.above_200d_ma is not None]
    return sum(values)/len(values) if values else None
