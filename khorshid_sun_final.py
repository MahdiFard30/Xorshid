#!/usr/bin/env python3
"""Solar desktop companion. Run --demo first; Ctrl+C in the terminal exits."""
import argparse
import codecs
import json
import math
import os
from pathlib import Path
import secrets
import signal
import socket
import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QProcess, QProcessEnvironment
from PySide6.QtGui import QImage, QPainter, QColor, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget
from sun_visual import SunTexture

STATES = ('idle', 'listening', 'thinking', 'speaking')


class Sun(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.texture = SunTexture(args.image, min(420, args.size))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(args.size, args.size)
        screens = QApplication.screens()
        screen = screens[min(args.screen, len(screens) - 1)]
        self.screen_ref = screen
        self.place()
        screen.availableGeometryChanged.connect(self.place)
        self.state = 'idle'
        self.energy, self.voice = 0.25, 0.0
        self.rms, self.rms_at = 0.0, 0.0
        self.start = self.previous = time.monotonic()
        self.state_at = self.start
        self.exact_until = 0.0
        self.has_exact_events = False
        self.phase = 0.0
        self.process = None
        self.stopping = False
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.pending = ''
        self.token = secrets.token_urlsafe(24)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(('127.0.0.1', args.port))
        except OSError:
            self.sock.close()
            raise RuntimeError(f'Port {args.port} is busy. Close the other sun or use --port 47832.')
        self.sock.setblocking(False)
        self.frame = self.texture.frame(0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(round(1000 / args.fps))

    def place(self, *_):
        rect = self.screen_ref.availableGeometry()
        self.move(max(rect.left(), rect.right() + 1 - self.width() - self.args.right),
                  min(rect.top() + self.args.top, max(rect.top(), rect.bottom() + 1 - self.height())))

    def change(self, state):
        self.state = state
        self.state_at = time.monotonic()
        if state != 'speaking':
            self.rms = 0.0

    def receive(self, now):
        # Bound work per frame so bursts cannot starve the UI.
        for _ in range(160):
            try:
                raw, _ = self.sock.recvfrom(2048)
            except BlockingIOError:
                break
            except OSError:
                return
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                # Child receives a random token. Overlay-only accepts empty-token local clients.
                expected = '' if self.args.overlay_only else self.token
                if not secrets.compare_digest(str(message.get('token', '')), expected):
                    continue
                state = message.get('state')
                if state not in STATES:
                    continue
                self.has_exact_events = True
                self.change(state)
                self.exact_until = now + (3 if state == 'idle' else 120)
                if state == 'speaking' and 'rms' in message:
                    rms = float(message['rms'])
                    if math.isfinite(rms):
                        self.rms = max(0, min(1, rms))
                        self.rms_at = now
            except (ValueError, TypeError, UnicodeError):
                continue

    def tick(self):
        now = time.monotonic()
        dt = min(now - self.previous, 0.1)
        self.previous = now
        t = now - self.start
        self.receive(now)
        if self.args.demo:
            cycle = t % 20
            self.state = 'idle' if cycle < 5 else 'listening' if cycle < 9 else 'thinking' if cycle < 12 else 'speaking'
            self.rms = (0.012 + 0.16 * max(0, math.sin(t * 3.7)) * (0.5 + 0.5 * math.sin(t * 10))) if self.state == 'speaking' else 0
            self.rms_at = now
        elif not self.has_exact_events and now - self.state_at > 15 and self.state != 'idle':
            self.change('idle')  # Recovery only; not a claimed speech-end detector.
        live_rms = self.rms if now - self.rms_at < 0.22 else 0
        db = 20 * math.log10(max(live_rms, 1e-6))
        target_voice = max(0, min(1, (db + 48) / 36)) if self.state == 'speaking' else 0
        tau = 0.045 if target_voice > self.voice else 0.18
        self.voice += (target_voice - self.voice) * (1 - math.exp(-dt / tau))
        target = {'idle': 0.25, 'listening': 0.09, 'thinking': 0.33, 'speaking': 0.63 + 0.35 * self.voice}[self.state]
        self.energy += (target - self.energy) * (1 - math.exp(-dt / 0.28))
        self.phase += dt * (0.65 + 0.7 * self.energy)
        self.frame = self.texture.frame(self.phase, self.energy, self.voice)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = self.width()
        glow = QRadialGradient(size / 2, size / 2, size * 0.47)
        glow.setColorAt(0, QColor(255, 165, 40, int(8 + 10 * self.energy)))
        glow.setColorAt(0.56, QColor(255, 147, 18, int(8 + 19 * self.energy)))
        glow.setColorAt(1, QColor(255, 120, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, size, size))
        n = self.texture.n
        image = QImage(self.frame.data, n, n, self.frame.strides[0], QImage.Format.Format_RGBA8888_Premultiplied)
        painter.drawImage(QRectF(0, 0, size, size), image)
        painter.end()

    def launch(self, command):
        self.process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUNBUFFERED', '1')
        env.insert('KHORSHID_SUN_PORT', str(self.args.port))
        env.insert('KHORSHID_SUN_TOKEN', self.token)
        self.process.setProcessEnvironment(env)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_logs)
        self.process.errorOccurred.connect(self.process_error)
        self.process.finished.connect(self.process_finished)
        self.process.start(command[0], command[1:])

    def read_logs(self):
        chunk = self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        print(chunk, end='', flush=True)
        self.pending += chunk.replace('\r', '\n')
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            self.log_state(line)
        self.pending = self.pending[-16384:]

    def log_state(self, line):
        # Compatibility only with the exact Persian markers in the uploaded wrapper.
        if self.has_exact_events:
            return
        if '🎤 دور' in line:
            self.change('idle')
        elif '🎤 ضبط' in line or '⏺ ضبط' in line:
            self.change('listening')
        elif '🧠' in line or 'در حال فهمیدن' in line or '⚙️ در حال انجام کار' in line:
            self.change('thinking')
        elif '🤖' in line:
            self.change('speaking')

    def process_error(self, error):
        print(f'\nKhorshid process error: {self.process.errorString()}', file=sys.stderr)
        if error == QProcess.ProcessError.FailedToStart:
            QApplication.exit(1)

    def process_finished(self, code, status):
        self.read_logs()
        self.change('idle')
        print(f'\nKhorshid exited ({code}).')
        if not self.stopping:
            QApplication.exit(code if code else 0)

    def cleanup(self):
        if self.stopping:
            return
        self.stopping = True
        self.timer.stop()
        self.sock.close()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            pid = int(self.process.processId())
            own_group = False
            if os.name == 'posix':
                try:
                    own_group = os.getpgid(pid) == pid
                except ProcessLookupError:
                    pass
            if own_group:
                try:
                    os.killpg(pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
            else:
                self.process.terminate()
            if not self.process.waitForFinished(1800):
                if own_group:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    self.process.kill()
                self.process.waitForFinished(1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, default=Path(__file__).with_name('khorshid_sun_final.png'))
    parser.add_argument('--size', type=int, default=500)
    parser.add_argument('--right', type=int, default=26)
    parser.add_argument('--top', type=int, default=42)
    parser.add_argument('--screen', type=int, default=0, help='Screen index, starting at 0')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--port', type=int, default=47831)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--demo', action='store_true', help='Visual demonstration with synthetic amplitude, no Khorshid')
    group.add_argument('--overlay-only', action='store_true', help='Do not start Khorshid; accept local bridge events')
    parser.add_argument('command', nargs=argparse.REMAINDER, help='Optional: -- python your_agent.py')
    args = parser.parse_args()
    if not 160 <= args.size <= 640 or not 10 <= args.fps <= 60 or not 1024 <= args.port <= 65535 or args.screen < 0:
        parser.error('size:160..640, fps:10..60, port:1024..65535, screen >= 0')
    if not args.image.is_file():
        parser.error(f'Image not found: {args.image}')
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(True)
    try:
        sun = Sun(args)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    app.aboutToQuit.connect(sun.cleanup)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    sun.show()
    if not args.demo and not args.overlay_only:
        command = args.command
        if command[:1] == ['--']:
            command = command[1:]
        sun.launch(command or [sys.executable, str(Path(__file__).with_name('sun_khorshid.py'))])
        print('Sun ready. Starting Khorshid with capture and audio hooks; existing hotkey settings are preserved.')
    else:
        print('Sun demo (synthetic voice).' if args.demo else 'Sun ready, overlay only.')
    print('Exit: Ctrl+C in this terminal.')
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
