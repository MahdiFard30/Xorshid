"""Quiet the foreground PTT terminal; preserve signals and restore its settings.

This does not intercept keys sent to other applications. Use only while a
foreground hotkey listener owns the terminal, not in a background shell job.
"""
import atexit
import os
import sys


class QuietTerminal:
    def __init__(self):
        self.fd = None
        self.saved = None

    def start(self):
        if self.fd is not None or os.name != 'posix':
            return
        try:
            import termios
            fd = sys.stdin.fileno()
            if not os.isatty(fd) or os.tcgetpgrp(fd) != os.getpgrp():
                return
            saved = termios.tcgetattr(fd)
            quiet = saved[:]
            quiet[3] &= ~(termios.ECHO | termios.ECHONL)
            termios.tcsetattr(fd, termios.TCSANOW, quiet)
            self.fd, self.saved = fd, saved
            atexit.register(self.close)
        except (OSError, ValueError, AttributeError, termios.error):
            return

    def discard(self):
        if self.fd is not None:
            try:
                import termios
                # Prevent held hotkey characters reaching the shell on exit.
                termios.tcflush(self.fd, termios.TCIFLUSH)
            except (OSError, termios.error):
                pass

    def close(self):
        if self.fd is None:
            return
        import termios
        fd, saved = self.fd, self.saved
        self.fd = self.saved = None
        try:
            termios.tcsetattr(fd, termios.TCSAFLUSH, saved)
        except (OSError, termios.error):
            pass
        atexit.unregister(self.close)
