"""Startup from another directory must still locate the moved runtime files."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_live_launcher_resolves_existing_child_from_another_directory(tmp_path):
    script=('import runpy,sys,types,json; '
            'sys.modules["ultimate_khorshid.interface.desktop"]=types.SimpleNamespace('
            'main=lambda argv,**kw:print(json.dumps(kw["default_command"]))); '
            'runpy.run_path(sys.argv[1],run_name="__main__")')
    result=subprocess.run([sys.executable,'-c',script,str(ROOT/'khorshid_live.py')],cwd=tmp_path,
                          capture_output=True,text=True,check=True,timeout=15)
    args=json.loads(result.stdout)
    child=Path(args[-1])
    assert child.is_file() and child.parent==ROOT/'ultimate_khorshid/interface'
    assert args[0]==sys.executable


def test_desktop_launcher_help_from_another_directory(tmp_path):
    pytest.importorskip('PySide6')
    result=subprocess.run([sys.executable,str(ROOT/'khorshid.py'),'--help'],cwd=tmp_path,
                          capture_output=True,text=True,check=True,timeout=15)
    assert '--overlay-only' in result.stdout


def test_live_launcher_preserves_help_without_starting_a_session(tmp_path):
    pytest.importorskip('PySide6')
    result=subprocess.run([sys.executable,str(ROOT/'khorshid_live.py'),'--help'],cwd=tmp_path,
                          capture_output=True,text=True,check=True,timeout=15)
    assert '--overlay-only' in result.stdout and '--size' in result.stdout


def test_live_runtime_keeps_project_root_and_imports_shared_components():
    from ultimate_khorshid.interface import khorshid_gemini_live_runner as runner
    from ultimate_khorshid.interface import khorshid_live_trial as shared
    assert runner.ROOT==ROOT and shared.ROOT==ROOT
    assert runner.PushToTalk is shared.PushToTalk


def test_moved_tts_assets_and_diagnostic_paths():
    from ultimate_khorshid.cli.diagnostics import personal_tts_status
    from ultimate_khorshid.voice.tts_worker import ROOT as worker_root
    assert worker_root==ROOT
    assert (ROOT/'ultimate_khorshid/assets/my_voice_prompt.wav').is_file()
    assert (ROOT/'ultimate_khorshid/assets/khorshid_sun_final.png').is_file()
    assert personal_tts_status(ROOT).startswith('✅')
