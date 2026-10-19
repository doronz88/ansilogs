import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs a Windows console")


def test_install_turns_on_ansi_processing_in_a_real_console(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    child = Path(__file__).with_name("console_child.py")
    subprocess.run(
        [sys.executable, str(child), str(report_path)],
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        check=True,
        timeout=60,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stderr_is_console"], report
    screen = report["screen"]
    # Control: with processing off, the escape sequence lands on screen literally.
    assert any("[33mCONTROL" in row for row in screen), screen
    assert report["vt_after_install"], report
    assert report["colors"], report
    (line,) = [row for row in screen if "hello from a console" in row]
    assert "WARNING hello from a console" in line
    assert "\x1b" not in line
    assert "[0m" not in line
