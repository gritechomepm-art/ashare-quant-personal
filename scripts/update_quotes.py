"""Best-effort full-market public quote snapshot. Reject partial provider responses."""
import argparse
from pathlib import Path
import akshare as ak
from core import ROOT,atomic_json,norm_spot

def main(output=ROOT/'quotes.json'):
    payload=norm_spot(ak.stock_zh_a_spot_em())
    # Intraday frontend only needs name and latest price; keep this branch lean.
    payload['quotes']={code:{k:q[k] for k in ('name','price','change_pct')}
        for code,q in payload['quotes'].items()}
    atomic_json(Path(output),payload)
    print('Saved',payload['count'],'quotes at',payload['fetched_at'])
    return payload

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',default=str(ROOT/'quotes.json'))
    args=ap.parse_args()
    main(Path(args.output))
