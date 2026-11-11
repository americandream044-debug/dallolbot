"""Shared visual language for the cyber-terminal interface."""
from __future__ import annotations

NEON = "#00FF9C"
CYAN = "#00D9FF"
PURPLE = "#B56BFF"
BLACK = "#0D1117"
DIM = "#8B949E"

BANNER = r"""
╔══════════════════════════════════╗
║   DASTURLASH & AI  /  CONTROL     ║
║       ▄▀█ █ █   ▄▀█ ▀█▀           ║
║       █▀█ █▄█   █▀█  █            ║
╚══════════════════════════════════╝
""".strip()


def terminal_header(section: str) -> str:
    """Return a compact terminal prompt heading."""
    return f"<code>root@dasturlash:~$</code> <b>{section}</b>"


def progress_bar(percent: int, width: int = 10) -> str:
    """Build a text progress bar with safe bounds."""
    pct = max(0, min(100, percent))
    filled = round(width * pct / 100)
    return f"{'▓' * filled}{'░' * (width - filled)} {pct}%"
