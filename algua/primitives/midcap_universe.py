"""Read the approved midcap CONFIG literal without importing authored strategy code."""
from __future__ import annotations

import ast
import re
from pathlib import Path

UNIVERSE_MODULE = "algua/strategies/momentum/midcap_weekly_momentum_smoke.py"


def midcap_symbols(root: Path) -> list[str]:
    """Read the reviewed literal CONFIG without executing authored strategy Python."""
    try:
        tree = ast.parse((root / UNIVERSE_MODULE).read_text())
        configs = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "CONFIG" for t in node.targets)]
        if len(configs) != 1 or not isinstance(configs[0], ast.Call):
            raise ValueError
        values = [k.value for k in configs[0].keywords if k.arg == "universe"]
        if len(values) != 1:
            raise ValueError
        value = values[0]
        if (not isinstance(value, ast.Call) or value.args or value.keywords
                or not isinstance(value.func, ast.Attribute) or value.func.attr != "split"
                or not isinstance(value.func.value, ast.Constant)
                or not isinstance(value.func.value.value, str)):
            raise ValueError
        symbols = sorted(value.func.value.value.split())
        if len(symbols) != 300 or len(set(symbols)) != 300 or any(
                re.fullmatch(r"[A-Z][A-Z0-9-]*", s) is None for s in symbols):
            raise ValueError
        return symbols
    except (OSError, SyntaxError, ValueError):
        raise ValueError("research_profile:universe_invalid") from None

