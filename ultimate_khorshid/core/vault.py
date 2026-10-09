"""Credential Vault — زنجیره امن کلیدها: env → OS keyring → config.

- اگر پکیج keyring نصب باشد، از گاوصندوق سیستم‌عامل استفاده می‌شود:
    pip install keyring
- وگرنه fallback به مقدار کانفیگ (فایل 600) + هشدار یک‌بارمصرف.
"""

from __future__ import annotations

import os
from typing import Optional

SERVICE = "ultimate-jarvis"
_warned = False


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except Exception:
        return None


def backend_name() -> str:
    kr = _keyring()
    if kr is None:
        return "config-file"
    try:
        kr.get_password(SERVICE, "__probe__")
        return "os-keyring"
    except Exception:
        return "config-file"


def get_secret(name: str, fallback: str = "") -> str:
    """خواندن راز: متغیر محیطی → keyring → fallback."""
    v = os.environ.get(name, "")
    if v:
        return v
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(SERVICE, name) or ""
            if v:
                return v
        except Exception:
            pass
    return fallback or ""


def set_secret(name: str, value: str) -> str:
    """ذخیره راز در keyring. نام بک‌اند را برمی‌گرداند؛ اگر keyring نبود raise."""
    kr = _keyring()
    if kr is None:
        raise RuntimeError(
            "keyring نصب نیست. نصب: pip install keyring\n"
            "یا کلید را در config.toml بگذار (دسترسی 600) یا متغیر محیطی.")
    kr.set_password(SERVICE, name, value)
    return "os-keyring"


def delete_secret(name: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, name)
        return True
    except Exception:
        return False


def warn_if_plain() -> Optional[str]:
    """هشدار یک‌بارمصرف اگر keyring در دسترس نیست."""
    global _warned
    if _warned or _keyring() is not None:
        return None
    _warned = True
    return ("⚠️ keyring نصب نیست؛ کلیدها از فایل/env خوانده می‌شوند. "
            "برای امنیت بیشتر: pip install keyring")
