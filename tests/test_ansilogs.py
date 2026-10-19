import io
import logging
import re
import sys
from collections.abc import Iterator
from typing import Any

import pytest

import ansilogs
from ansilogs import ColoredFormatter, StderrHandler

LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d host ansilogs\.tests\[\d+\] (\w+) (.*)$")


def _record(level: int, msg: str, *args: Any, exc_info: Any = None) -> logging.LogRecord:
    return logging.LogRecord("ansilogs.tests", level, __file__, 1, msg, args, exc_info)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch) -> Iterator[logging.Logger]:
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)
    yield root


def _ours(root: logging.Logger) -> list[StderrHandler]:
    # pytest attaches its own capture handlers to the root logger while a test runs.
    return [h for h in root.handlers if isinstance(h, StderrHandler)]


def test_plain_layout_is_one_line() -> None:
    line = ColoredFormatter(colors=False, hostname="host").format(_record(logging.INFO, "sent %d bytes", 5))
    match = LINE.match(line)
    assert match is not None
    assert match.groups() == ("INFO", "sent 5 bytes")


def test_coloredlogs_style_matches_coloredlogs_defaults() -> None:
    record = _record(logging.WARNING, "careful")
    line = ColoredFormatter(colors=True, hostname="host", style="coloredlogs").format(record)
    timestamp = ColoredFormatter(colors=False).formatTime(record, ansilogs.DATE_FORMAT)
    assert line == (
        f"\x1b[32m{timestamp}\x1b[0m \x1b[35mhost\x1b[0m \x1b[34mansilogs.tests[{record.process}]\x1b[0m "
        "\x1b[1;30mWARNING\x1b[0m \x1b[33mcareful\x1b[0m"
    )


def test_default_style_layout() -> None:
    record = _record(logging.WARNING, "careful")
    line = ColoredFormatter(colors=True, hostname="host").format(record)
    timestamp = ColoredFormatter(colors=False).formatTime(record, ansilogs.DATE_FORMAT)
    assert line == (
        f"\x1b[2m{timestamp}\x1b[0m \x1b[2mhost\x1b[0m \x1b[36mansilogs.tests\x1b[0m\x1b[2m[{record.process}]\x1b[0m "
        "\x1b[1;33mWARNING\x1b[0m \x1b[33mcareful\x1b[0m"
    )


@pytest.mark.parametrize(
    ("style", "level", "level_code", "message_code"),
    [
        ("default", logging.DEBUG, "2", "2"),
        ("default", logging.INFO, "1;32", ""),
        ("default", logging.WARNING, "1;33", "33"),
        ("default", logging.ERROR, "1;31", "31"),
        ("default", logging.CRITICAL, "1;37;41", "1;31"),
        ("default", 25, "1", ""),
        ("coloredlogs", logging.DEBUG, "1;30", "32"),
        ("coloredlogs", logging.INFO, "1;30", ""),
        ("coloredlogs", logging.CRITICAL, "1;30", "1;31"),
    ],
)
def test_level_and_message_colors(style: str, level: int, level_code: str, message_code: str) -> None:
    line = ColoredFormatter(colors=True, style=style).format(_record(level, "msg"))
    levelname = logging.getLevelName(level)
    message = f"\x1b[{message_code}mmsg\x1b[0m" if message_code else "msg"
    assert line.endswith(f"\x1b[{level_code}m{levelname}\x1b[0m {message}")


def test_record_is_left_untouched() -> None:
    warning = _record(logging.WARNING, "msg")
    ColoredFormatter(colors=True).format(warning)
    assert warning.message == "msg"
    assert warning.levelname == "WARNING"


def test_hostname_with_percent_is_literal() -> None:
    line = ColoredFormatter(colors=False, hostname="a%sb").format(_record(logging.INFO, "msg"))
    assert " a%sb " in line


def test_traceback_is_appended_uncolored() -> None:
    def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError) as excinfo:
        boom()
    record = _record(logging.ERROR, "failed", exc_info=(excinfo.type, excinfo.value, excinfo.tb))
    lines = ColoredFormatter(colors=True).format(record).splitlines()
    assert lines[0].endswith("\x1b[1;31mERROR\x1b[0m \x1b[31mfailed\x1b[0m")
    assert lines[1] == "Traceback (most recent call last):"
    assert lines[-1] == "ValueError: boom"


def test_handler_writes_to_the_current_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = StderrHandler()
    handler.setFormatter(ColoredFormatter(colors=False))
    first, second = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stderr", first)
    handler.handle(_record(logging.INFO, "one"))
    monkeypatch.setattr(sys, "stderr", second)
    handler.handle(_record(logging.INFO, "two"))
    assert first.getvalue().endswith(" INFO one\n")
    assert second.getvalue().endswith(" INFO two\n")


def test_handler_tolerates_missing_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", None)
    StderrHandler().handle(_record(logging.INFO, "dropped"))


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        if self.closed:
            raise ValueError
        return True


def test_supports_color_requires_a_terminal() -> None:
    assert not ansilogs.supports_color(io.StringIO())
    if sys.platform != "win32":
        assert ansilogs.supports_color(_Tty())


def test_supports_color_rejects_a_closed_stream() -> None:
    stream = _Tty()
    stream.close()
    assert not ansilogs.supports_color(stream)


def test_no_color_and_force_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert ansilogs.supports_color(io.StringIO())
    monkeypatch.setenv("NO_COLOR", "1")
    assert not ansilogs.supports_color(_Tty())
    monkeypatch.setenv("NO_COLOR", "")
    assert ansilogs.supports_color(io.StringIO())


def test_install_is_idempotent_and_relaxes_the_root_level(root: logging.Logger) -> None:
    ansilogs.install(logging.INFO, colors=False)
    ansilogs.install(logging.INFO, colors=False)
    (handler,) = _ours(root)
    assert handler.level == logging.INFO
    assert root.level == logging.INFO
    ansilogs.set_level("DEBUG")
    assert handler.level == logging.DEBUG
    assert root.level == logging.DEBUG


def test_set_level_installs_when_needed(root: logging.Logger) -> None:
    ansilogs.set_level(logging.DEBUG)
    (handler,) = _ours(root)
    assert handler.level == logging.DEBUG


def test_install_colors_follow_stderr(root: logging.Logger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    ansilogs.install()
    (handler,) = _ours(root)
    formatter = handler.formatter
    assert isinstance(formatter, ColoredFormatter)
    assert not formatter.colors
