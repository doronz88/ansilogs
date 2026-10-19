# ansilogs

Colored, single-line log output for command-line tools. A small, dependency-free replacement
for `coloredlogs.install()` with the same default look.

```python
import logging

import ansilogs

ansilogs.install(logging.DEBUG)
logging.getLogger(__name__).warning("careful")
```

```
2026-10-19 09:35:12 my-host my_tool.cli[4242] WARNING careful
```

- One line per record: `<time> <host> <name>[<pid>] <LEVEL> <message>`; tracebacks follow
  uncolored.
- Colors only when stderr is a terminal. `NO_COLOR` (non-empty) disables them, `FORCE_COLOR`
  (non-empty) forces them. On Windows the console is switched to ANSI processing; if that
  fails, output is plain.
- Records go to whatever `sys.stderr` is at the time (test capture and live progress displays
  that redirect stderr keep working).

## API

- `install(level=logging.INFO, colors=None)`: attach the handler to the root logger (once) and
  show records from `level` up. `colors=None` means `supports_color()`.
- `set_level(level)`: change the shown level (installs the handler if needed).
- `supports_color(stream=None)`: the color decision used by `install()`.
- `ColoredFormatter(colors=True, hostname=None)` and `StderrHandler` for custom setups.

## Migrating from coloredlogs

```diff
-import coloredlogs
-coloredlogs.install(level=logging.DEBUG)
+import ansilogs
+ansilogs.install(logging.DEBUG)
```

`coloredlogs.set_level(level)` becomes `ansilogs.set_level(level)`. `COLOREDLOGS_*` environment
variables and custom field/level styles are not supported.
