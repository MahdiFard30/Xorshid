"""Run the hardware-independent suite against temporary local state.

Usage from the project: .venv/bin/python tests/run_offline.py
Local HTTP sockets are required. urllib requests to external hosts are rejected.
Hardware/real-service tests are deliberately excluded, not counted as passes.
"""
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
from urllib.parse import urlsplit
from unittest.mock import Mock, patch


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    import pytest
    with tempfile.TemporaryDirectory(prefix="khorshid-offline-tests-") as directory:
        home = Path(directory)
        original_expand = os.path.expanduser

        def expand(p):
            value = os.fspath(p)
            if value == "~":
                return str(home)
            return str(home / value[2:]) if value.startswith("~/") else original_expand(value)

        clean_env = {k: v for k, v in os.environ.items()
                     if k not in {"KHORSHID_MODEL", "KHORSHID_ENGINE", "KHORSHID_CONFIG", "KHORSHID_LIVE",
                                  "KHORSHID_VOICE", "KHORSHID_AGENT", "KHORSHID_LANG",
                                  "GROQ_API_KEY", "KHORSHID_GROQ_MODEL"}}
        with patch.object(Path, "home", return_value=home), patch("os.path.expanduser", side_effect=expand), \
                patch.dict(os.environ, clean_env, clear=True):
            from ultimate_khorshid.core import config, sandbox
            from ultimate_khorshid.server import app  # capture HISTORY_DB inside temporary home
            del app
            paths = [home / ".ultimate-jarvis/config.toml", Path("configs/default.toml")]
            original_urlopen = urllib.request.urlopen

            def local_urlopen(request, *args, **kwargs):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
                    raise AssertionError("External network is forbidden in offline verification")
                return original_urlopen(request, *args, **kwargs)

            with patch.object(config, "DEFAULT_CONFIG_PATHS", paths), \
                    patch.object(sandbox, "detect_backend", return_value="restricted"), \
                    patch('ultimate_khorshid.voice.ducking.service', Mock()), \
                    patch.object(urllib.request, "urlopen", side_effect=local_urlopen):
                exclude = ("not browser_tool_never_crashes and not screenshot_bytes_fallback "
                           "and not hotkey_manager_no_pynput_safe and not notify_tool "
                           "and not telegram_answers_and_channel and not stt_chain_and_wake "
                           "and not vault_env_and_memory and not vision_endpoint")
                return pytest.main(["tests", "evals", "-k", exclude, "-q",
                                    "-p", "no:cacheprovider", "--basetemp", str(home / "pytest")])


if __name__ == "__main__":
    raise SystemExit(main())
