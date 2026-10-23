"""Run the read-only demo research observer independently of broker execution."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ultimate_khorshid.tools.research_observer import main

if __name__=='__main__':
    raise SystemExit(main())
