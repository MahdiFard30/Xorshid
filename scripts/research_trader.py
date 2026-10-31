"""Run the read-only demo research observer independently of broker execution."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ultimate_khorshid.tools.research_observer import main

if __name__=='__main__':
    # Reporting is independent: a reporting failure never stops research/trading.
    try:
        from ultimate_khorshid.tools.post_trade_review import ensure_started
        ensure_started(Path(__file__).resolve().parents[1])
    except Exception as exc:
        print('Post-trade reporter unavailable: '+str(exc),flush=True)
    raise SystemExit(main())
