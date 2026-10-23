"""Read-only audit of the latest recorded demo runs; never launches MetaTrader."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ultimate_khorshid.tools.trade_audit import build

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/trading-audit/20261022')
    args=parser.parse_args();result=build(ROOT,args.output)
    print(json.dumps(result['summary'],ensure_ascii=False));print(args.output/'REPORT_FA.md')
