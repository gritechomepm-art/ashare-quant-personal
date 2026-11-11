"""Fetch a small public watchlist from Tencent's quote endpoint.
No AKShare import, no all-market crawl, no credentials. Strict parsing rejects
partial or malformed snapshots before publication.
"""
import argparse, json, re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
CST=ZoneInfo("Asia/Shanghai")
DEFAULT_WATCHLIST=ROOT/"data"/"watchlist_public.json"

def market_symbol(code):
    code=str(code).strip()
    if not re.fullmatch(r"\d{6}",code): raise ValueError(f"Invalid A-share code: {code}")
    if code.startswith("6"): return "sh"+code
    if code.startswith(("0","3")): return "sz"+code
    if code.startswith(("4","8")): return "bj"+code
    raise ValueError(f"Unsupported A-share market code: {code}")

def number(value,field,required=False):
    value=(value or "").strip()
    if not value:
        if required: raise ValueError(f"Missing Tencent quote field: {field}")
        return None
    try: n=float(value)
    except ValueError as exc: raise ValueError(f"Invalid Tencent field {field}: {value!r}") from exc
    if n!=n or n in (float("inf"),float("-inf")): raise ValueError(f"Non-finite Tencent field: {field}")
    return n

def parse_tencent_response(raw,requested_codes):
    found={}
    for market,code,body in re.findall(r'v_(sh|sz|bj)(\d{6})="([^"]*)"',raw):
        f=body.split("~")
        if len(f)<35 or code not in requested_codes or f[2]!=code: continue
        price=number(f[3],"price",True); prev=number(f[4],"prev_close",True)
        if price<=0 or prev<=0: raise ValueError(f"Invalid price for {code}")
        stamp=(f[30] or "").strip()
        if not re.fullmatch(r"\d{14}",stamp): raise ValueError(f"Invalid Tencent timestamp for {code}: {stamp!r}")
        qt=datetime.strptime(stamp,"%Y%m%d%H%M%S").replace(tzinfo=CST).isoformat()
        found[code]={"name":f[1].strip(),"price":round(price,3),"prev_close":round(prev,3),
          "open":number(f[5],"open"),"volume_lots":int(number(f[6],"volume_lots") or 0),
          "change":number(f[31],"change"),"change_pct":number(f[32],"change_pct"),
          "high":number(f[33],"high"),"low":number(f[34],"low"),
          "amount_wan":number(f[37],"amount_wan") if len(f)>37 else None,
          "quote_time":qt,"source":"Tencent qt.gtimg.cn","market_symbol":market+code}
    missing=sorted(set(requested_codes)-set(found))
    if missing: raise ValueError("Tencent response missing symbols: "+", ".join(missing))
    return found

def fetch_quotes(codes,timeout=15):
    url="https://qt.gtimg.cn/q="+",".join(market_symbol(c) for c in codes)
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; ASharePersonalResearch/1.2)",
      "Referer":"https://gu.qq.com/","Accept":"*/*"})
    with urlopen(req,timeout=timeout) as res:
        if res.status!=200: raise RuntimeError(f"Tencent HTTP {res.status}")
        raw=res.read().decode("gb18030",errors="strict")
    quotes=parse_tencent_response(raw,codes)
    now=datetime.now(CST)
    return {"schema":1,"status":"ok","source":"腾讯财经 qt.gtimg.cn（非官方公开行情接口）",
      "fetched_at":now.isoformat(timespec="seconds"),
      "quote_time_latest":max(q["quote_time"] for q in quotes.values()),
      "market_timezone":"Asia/Shanghai","count":len(quotes),"quotes":quotes,
      "warning":"行情快照可能延迟、限流或变更，不代表交易所实时行情。"}

def load_codes(path):
    codes=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(codes,list) or not codes: raise ValueError("Watchlist must be a non-empty JSON array")
    codes=list(dict.fromkeys(str(x).strip() for x in codes))
    for c in codes: market_symbol(c)
    return codes

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--codes",nargs="*",default=None)
    ap.add_argument("--watchlist",default=str(DEFAULT_WATCHLIST))
    ap.add_argument("--output",default=str(ROOT/"data"/"quotes.json"))
    args=ap.parse_args()
    codes=args.codes if args.codes else load_codes(args.watchlist)
    payload=fetch_quotes(codes)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(out)
    print(json.dumps({"status":payload["status"],"source":payload["source"],"count":payload["count"],
      "fetched_at":payload["fetched_at"],"quote_time_latest":payload["quote_time_latest"],
      "codes":sorted(payload["quotes"])},ensure_ascii=False))
    return payload

if __name__=="__main__": main()
