"""
Run inside a fresh Windows console (``CREATE_NEW_CONSOLE``) by ``test_windows_console.py``.

Turns ANSI processing off, writes a raw escape sequence (the control: it must land on screen
literally), then lets ``ansilogs.install()`` turn processing on and logs a warning (which must
render without escape codes). Reports the console modes and the screen text as JSON.
"""

import ctypes
import json
import logging
import sys
from ctypes import wintypes

import ansilogs

ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
STD_ERROR_HANDLE = -12
GENERIC_READ_WRITE = 0x80000000 | 0x40000000
FILE_SHARE_READ_WRITE = 0x1 | 0x2
OPEN_EXISTING = 3


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]  # noqa: RUF012 (ctypes API)


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 (ctypes API)
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wintypes.WORD),
        ("srWindow", wintypes.SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


def main() -> None:
    assert sys.platform == "win32"
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    report = {}
    stderr_handle = kernel32.GetStdHandle(STD_ERROR_HANDLE)
    mode = wintypes.DWORD()
    report["stderr_is_console"] = bool(kernel32.GetConsoleMode(stderr_handle, ctypes.byref(mode)))
    if report["stderr_is_console"]:
        kernel32.SetConsoleMode(stderr_handle, mode.value & ~ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        sys.stderr.write("\x1b[33mCONTROL\x1b[0m\n")
        sys.stderr.flush()

        ansilogs.install(logging.INFO)
        kernel32.GetConsoleMode(stderr_handle, ctypes.byref(mode))
        report["vt_after_install"] = bool(mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        (handler,) = [h for h in logging.getLogger().handlers if isinstance(h, ansilogs.StderrHandler)]
        formatter = handler.formatter
        report["colors"] = isinstance(formatter, ansilogs.ColoredFormatter) and formatter.colors
        logging.getLogger("ansilogs.console").warning("hello from a console")

        screen = kernel32.CreateFileW(
            "CONOUT$", GENERIC_READ_WRITE, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None
        )
        info = CONSOLE_SCREEN_BUFFER_INFO()
        kernel32.GetConsoleScreenBufferInfo(screen, ctypes.byref(info))
        width = info.dwSize.X
        rows = []
        for y in range(info.dwCursorPosition.Y + 1):
            buffer = ctypes.create_unicode_buffer(width)
            read = wintypes.DWORD()
            kernel32.ReadConsoleOutputCharacterW(screen, buffer, width, COORD(0, y), ctypes.byref(read))
            rows.append(buffer.value[: read.value].rstrip())
        report["screen"] = rows
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(report, f)


if __name__ == "__main__":
    main()
