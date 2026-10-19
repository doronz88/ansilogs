"""
Colored, single-line log output for command-line tools.

A small, dependency-free replacement for ``coloredlogs.install()``::

    import logging
    import ansilogs

    ansilogs.install(logging.DEBUG)

Each record is one line, ``<time> <host> <name>[<pid>] <LEVEL> <message>``, colored with ANSI
escape codes when stderr is a terminal (honoring ``NO_COLOR`` and ``FORCE_COLOR``, and switching
Windows consoles to ANSI processing). The handler writes to whatever ``sys.stderr`` is at the
time of each record, so redirections (test capture, live progress displays) are respected.
"""

import logging
import os
import socket
import sys
from typing import IO, Optional, Union

__all__ = ["DATE_FORMAT", "ColoredFormatter", "StderrHandler", "install", "set_level", "supports_color"]

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_RESET = "\x1b[0m"
_TIME = "32"  # green
_HOST = "35"  # magenta
_NAME = "34"  # blue
_LEVEL_NAME = "1;30"  # bold black
_MESSAGE_BY_LEVEL = {
    logging.DEBUG: "32",  # green
    logging.WARNING: "33",  # yellow
    logging.ERROR: "31",  # red
    logging.CRITICAL: "1;31",  # bold red
}

# SetConsoleMode flag that makes a Windows console interpret ANSI escape sequences.
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_ERROR_HANDLE = -12


def _sgr(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}{_RESET}"


class ColoredFormatter(logging.Formatter):
    """
    ``<time> <host> <name>[<pid>] <LEVEL> <message>``, with ANSI colors when ``colors`` is set.

    The colors are baked into the format string once; per record only the message is wrapped in
    its level's color. Tracebacks and stack info are appended uncolored.
    """

    def __init__(self, colors: bool = True, hostname: Optional[str] = None) -> None:
        host = (hostname or socket.gethostname()).replace("%", "%%")
        fields = [
            ("%(asctime)s", _TIME),
            (host, _HOST),
            ("%(name)s[%(process)d]", _NAME),
            ("%(levelname)s", _LEVEL_NAME),
        ]
        prefix = " ".join(_sgr(code, text) if colors else text for text, code in fields)
        super().__init__(f"{prefix} %(message)s", datefmt=DATE_FORMAT)
        self.colors = colors

    def formatMessage(self, record: logging.LogRecord) -> str:
        code = _MESSAGE_BY_LEVEL.get(record.levelno) if self.colors else None
        if code is None:
            return super().formatMessage(record)
        message = record.message
        record.message = _sgr(code, message)
        try:
            return super().formatMessage(record)
        finally:
            record.message = message


class StderrHandler(logging.Handler):
    """Writes each record to the current ``sys.stderr`` (looked up per record, never cached)."""

    terminator = "\n"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            stream = sys.stderr
            if stream is None:
                return
            stream.write(line + self.terminator)
            stream.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


def _enable_windows_ansi(stream: IO[str]) -> bool:
    """Switch the Windows console behind ``stream`` to ANSI processing; False if it isn't a console."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    if stream is not sys.__stderr__:
        # Only the process' own stderr maps to the standard error console handle.
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(_STD_ERROR_HANDLE)
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        return True
    return bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))


def supports_color(stream: Optional[IO[str]] = None) -> bool:
    """
    Whether to color output written to ``stream`` (default: ``sys.stderr``).

    ``NO_COLOR`` (non-empty) disables colors and ``FORCE_COLOR`` (non-empty) forces them;
    otherwise the stream must be a terminal, and on Windows a console that accepts ANSI codes.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = sys.stderr if stream is None else stream
    if stream is None:
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        if isatty is None or not isatty():
            return False
    except ValueError:  # closed stream
        return False
    return _enable_windows_ansi(stream)


def _installed_handler() -> Optional[StderrHandler]:
    return next((h for h in logging.getLogger().handlers if isinstance(h, StderrHandler)), None)


def install(level: Union[int, str] = logging.INFO, colors: Optional[bool] = None) -> None:
    """
    Attach a colored stderr handler to the root logger and show records from ``level`` up.

    Calling it again reconfigures the existing handler instead of adding another. ``colors``
    defaults to :func:`supports_color` for the current ``sys.stderr``.
    """
    handler = _installed_handler()
    if handler is None:
        handler = StderrHandler()
        logging.getLogger().addHandler(handler)
    handler.setFormatter(ColoredFormatter(colors=supports_color() if colors is None else colors))
    set_level(level)


def set_level(level: Union[int, str]) -> None:
    """
    Show records from ``level`` up: sets the handler's level (installing it if needed) and relaxes
    the root logger's level if it would filter those records out.
    """
    handler = _installed_handler()
    if handler is None:
        install(level)
        return
    handler.setLevel(level)
    root = logging.getLogger()
    if root.getEffectiveLevel() > handler.level:
        root.setLevel(handler.level)
