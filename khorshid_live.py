#!/usr/bin/env python3
"""Launch Gemini Live with the shared Khorshid desktop interface."""
from pathlib import Path
import sys

from ultimate_khorshid.interface.desktop import main as desktop_main


def main(argv=None):
    child = Path(__file__).resolve().parent / 'ultimate_khorshid/interface/khorshid_gemini_live_runner.py'
    if not child.is_file():
        raise SystemExit('Missing Gemini Live runner: ' + str(child))
    return desktop_main(argv, default_command=[sys.executable, str(child)])


if __name__ == '__main__':
    raise SystemExit(main())
