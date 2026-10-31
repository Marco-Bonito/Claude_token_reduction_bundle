"""Path resolution shared by the routing scripts.

Code lives in the plugin (read-only). Data lives in the project, so each project learns on its own:
  <project root>/.claude/routing/   routing-table.json, lessons.md, history/

Project root = the nearest folder with .git above the current directory, else the current directory.
Override with the TOKEN_ROUTING_DIR environment variable.
On first use, the defaults are copied into the project data folder.
"""
import os
import shutil
import sys
from pathlib import Path

# Windows consoles default to cp1252 and crash on characters such as "→". Force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PKG = Path(__file__).resolve().parent
DEFAULTS = PKG / "defaults"
TEMPLATES = PKG / "templates"
SEEDED = ("routing-table.json", "lessons.md")


def project_root() -> Path:
    cwd = Path.cwd().resolve()
    for c in (cwd, *cwd.parents):
        if (c / ".git").exists():
            return c
    return cwd


def data_dir() -> Path:
    env = os.environ.get("TOKEN_ROUTING_DIR")
    d = Path(env).expanduser() if env else project_root() / ".claude" / "routing"
    d.mkdir(parents=True, exist_ok=True)
    for name in SEEDED:
        if not (d / name).exists():
            shutil.copy(DEFAULTS / name, d / name)
    return d
