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
from typing import IO, NamedTuple, Optional, Union

__all__ = [
    "DATE_FORMAT",
    "STYLES",
    "ColoredFormatter",
    "StderrHandler",
    "Style",
    "install",
    "set_level",
    "supports_color",
]

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_RESET = "\x1b[0m"


class Style(NamedTuple):
    """SGR codes per field ("" = uncolored). ``level``/``message`` map a level number to its code."""

    time: str
    host: str
    name: str
    pid: Optional[str]  # None: the pid takes the name's color
    level: dict[int, str]
    level_default: str  # level-name code for levels missing from ``level``
    message: dict[int, str]


STYLES: dict[str, Style] = {
    # Metadata recedes, the level name carries the severity, debug output is dimmed.
    "default": Style(
        time="2",
        host="2",
        name="36",
        pid="2",
        level={
            logging.DEBUG: "2",
            logging.INFO: "1;32",
            logging.WARNING: "1;33",
            logging.ERROR: "1;31",
            logging.CRITICAL: "1;37;41",
        },
        level_default="1",
        message={logging.DEBUG: "2", logging.WARNING: "33", logging.ERROR: "31", logging.CRITICAL: "1;31"},
    ),
    # coloredlogs' defaults, byte for byte.
    "coloredlogs": Style(
        time="32",
        host="35",
        name="34",
        pid=None,
        level={},
        level_default="1;30",
        message={logging.DEBUG: "32", logging.WARNING: "33", logging.ERROR: "31", logging.CRITICAL: "1;31"},
    ),
}

# SetConsoleMode flag that makes a Windows console interpret ANSI escape sequences.
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_ERROR_HANDLE = -12


def _sgr(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}{_RESET}" if code else text


class ColoredFormatter(logging.Formatter):
    """
    ``<time> <host> <name>[<pid>] <LEVEL> <message>``, with ANSI colors when ``colors`` is set.

    ``style`` names an entry of :data:`STYLES` (``"default"`` or ``"coloredlogs"``). Fixed colors
    are baked into the format string once; per record only the level name and the message are
    wrapped in their level's color. Tracebacks and stack info are appended uncolored.
    """

    def __init__(self, colors: bool = True, hostname: Optional[str] = None, style: str = "default") -> None:
        theme = STYLES[style]
        host = (hostname or socket.gethostname()).replace("%", "%%")

        def paint(code: str, text: str) -> str:
            return _sgr(code, text) if colors else text

        if theme.pid is None:
            name = paint(theme.name, "%(name)s[%(process)d]")
        else:
            name = paint(theme.name, "%(name)s") + paint(theme.pid, "[%(process)d]")
        level = "%(levelname)s" if theme.level else paint(theme.level_default, "%(levelname)s")
        super().__init__(
            f"{paint(theme.time, '%(asctime)s')} {paint(theme.host, host)} {name} {level} %(message)s",
            datefmt=DATE_FORMAT,
        )
        self.colors = colors
        self.style_name = style
        self._theme = theme

    def formatMessage(self, record: logging.LogRecord) -> str:
        if not self.colors:
            return super().formatMessage(record)
        theme = self._theme
        level_code = theme.level.get(record.levelno, theme.level_default) if theme.level else ""
        message_code = theme.message.get(record.levelno, "")
        if not level_code and not message_code:
            return super().formatMessage(record)
        levelname, message = record.levelname, record.message
        record.levelname = _sgr(level_code, levelname)
        record.message = _sgr(message_code, message)
        try:
            return super().formatMessage(record)
        finally:
            record.levelname, record.message = levelname, message


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


def install(level: Union[int, str] = logging.INFO, colors: Optional[bool] = None, style: str = "default") -> None:
    """
    Attach a colored stderr handler to the root logger and show records from ``level`` up.

    Calling it again reconfigures the existing handler instead of adding another. ``colors``
    defaults to :func:`supports_color` for the current ``sys.stderr``; ``style`` names an entry of
    :data:`STYLES` (``"coloredlogs"`` reproduces coloredlogs' look).
    """
    handler = _installed_handler()
    if handler is None:
        handler = StderrHandler()
        logging.getLogger().addHandler(handler)
    handler.setFormatter(ColoredFormatter(colors=supports_color() if colors is None else colors, style=style))
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
