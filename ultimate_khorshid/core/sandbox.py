"""Sandbox اجرای کد — docker > firejail > restricted.

- backend="auto": بهترین موجود انتخاب می‌شود (امن‌ترین).
- backend="docker": ایزوله واقعی (نیاز به Docker)؛ network=none، حافظه/CPU محدود.
- backend="firejail": سندباکس لینوکسی سبک (اگر نصب بود).
- backend="off"/"restricted": اجرای مستقیم با همان محافظت‌های قبلی (اخطار شفاف).

هر اجرا بک‌اند استفاده‌شده را گزارش می‌دهد تا امنیت «نامرئی» نباشد.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

DOCKER_IMAGE = "python:3.12-slim"


def has_docker() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def has_firejail() -> bool:
    return shutil.which("firejail") is not None


def detect_backend() -> str:
    if has_docker():
        return "docker"
    if has_firejail():
        return "firejail"
    return "restricted"


def docker_cmd(workdir: str, inner: List[str], network: bool = False,
               memory: str = "256m", cpus: str = "0.5") -> List[str]:
    cmd = ["docker", "run", "--rm",
           "--network", "none" if not network else "bridge",
           "--memory", memory, "--cpus", cpus,
           "--pids-limit", "64",
           "-v", f"{workdir}:/work:rw", "-w", "/work",
           DOCKER_IMAGE, *inner]
    return cmd


def firejail_cmd(inner: List[str], workdir: str = "") -> List[str]:
    cmd = ["firejail", "--quiet", "--noprofile", "--net=none",
           "--private-tmp"]
    if workdir:
        cmd += ["--whitelist=" + workdir]
    return cmd + ["--"] + inner


def run_shell(command: str, backend: str = "auto", workdir: str = "",
              timeout: float = 30.0, network: bool = False,
              env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str, str]:
    """(returncode, stdout, stderr, backend_used)."""
    backend = _resolve(backend)
    wd = workdir or os.getcwd()
    if backend == "docker":
        cmd = docker_cmd(wd, ["sh", "-c", command], network=network)
    elif backend == "firejail":
        cmd = firejail_cmd(["sh", "-c", command], wd)
    else:
        return _run_local(["sh", "-c", command], wd, timeout, env, "restricted")
    return _run_local(cmd, wd, timeout + 30, env, backend)


def run_python(code: str, backend: str = "auto", workdir: str = "",
               timeout: float = 30.0, network: bool = False) -> Tuple[int, str, str, str]:
    backend = _resolve(backend)
    if backend == "docker":
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         dir=workdir or None) as f:
            f.write(code)
            host_path = f.name
        try:
            rel = os.path.basename(host_path)
            wd = workdir or os.path.dirname(host_path)
            cmd = docker_cmd(wd, ["python", f"/work/{rel}"], network=network)
            return _run_local(cmd, wd, timeout + 30, None, backend)
        finally:
            try:
                os.unlink(host_path)
            except Exception:
                pass
    if backend == "firejail":
        cmd = firejail_cmd(["python3", "-c", code], workdir or "")
        return _run_local(cmd, workdir or os.getcwd(), timeout, None, backend)
    import sys
    return _run_local([sys.executable, "-c", code], workdir or os.getcwd(),
                      timeout, None, "restricted")


def _resolve(backend: str) -> str:
    b = (backend or "auto").lower()
    if b in ("off", "none", "restricted", "local"):
        return "restricted"
    if b == "docker":
        return "docker" if has_docker() else "restricted"
    if b == "firejail":
        return "firejail" if has_firejail() else "restricted"
    return detect_backend()


def _run_local(cmd: List[str], wd: str, timeout: float,
               env: Optional[Dict[str, str]], used: str) -> Tuple[int, str, str, str]:
    try:
        r = subprocess.run(cmd, cwd=wd, capture_output=True, text=True,
                           timeout=max(1.0, timeout), env=env)
        return r.returncode, (r.stdout or "")[-8000:], (r.stderr or "")[-4000:], used
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout بعد از {timeout} ثانیه", used
    except Exception as e:
        return 125, "", f"خطای اجرا: {e}", used
