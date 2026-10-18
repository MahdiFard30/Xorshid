"""Desktop approval in a separate Qt process; no GUI imports in headless use."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

_dialog_lock = threading.Lock()


def desktop_confirm(message: str) -> bool:
    """Default deny on missing display, timeout, cancellation or dialog failure."""
    if os.environ.get("KHORSHID_CONFIRM_GUI") != "1":
        return False
    with _dialog_lock:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ultimate_khorshid.core.approval"],
                input=json.dumps({"message": message}, ensure_ascii=False),
                text=True, capture_output=True, timeout=120,
                cwd=Path(__file__).resolve().parents[2],
            )
            return result.returncode == 0 and result.stdout.strip() == "approved"
        except (OSError, subprocess.TimeoutExpired):
            return False


def main() -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    request = json.loads(sys.stdin.read(20000))
    app = QApplication([sys.argv[0]])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dialog = QMessageBox()
    dialog.setWindowTitle("خورشید — اجازهٔ انجام کار")
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setText(str(request["message"]))
    dialog.setInformativeText("فقط در صورت موافقت با همین عملیات، تأیید کنید.")
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    dialog.button(QMessageBox.StandardButton.Yes).setText("تأیید")
    dialog.button(QMessageBox.StandardButton.No).setText("لغو")
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    QTimer.singleShot(110000, dialog.reject)
    accepted = dialog.exec() == QMessageBox.StandardButton.Yes
    print("approved" if accepted else "denied", flush=True)
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
