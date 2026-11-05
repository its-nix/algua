"""Select actual driver Python by its Bash owner, never global heredoc position."""
from __future__ import annotations

import re

_PYTHON = re.compile(r"<<'PY'[^\n]*\n(.*?)\n^PY$", re.DOTALL | re.MULTILINE)


def function_python(script: str, name: str) -> str:
    """Extract the unique Python heredoc inside the named, flat Bash function.

    Hide heredocs while locating the closing Bash brace: Python dictionaries can otherwise
    look like a function terminator. Preserve offsets so the returned source is byte-for-byte
    the driver's actual Python, including its argv and subprocess implementation.
    """
    masked = _PYTHON.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), script)
    starts = list(re.finditer(r"^" + re.escape(name) + r"\(\) \{\s*$", masked, re.MULTILINE))
    assert len(starts) == 1, f"expected one Bash function {name!r}"
    start = starts[0].end()
    end = re.search(r"^\}$", masked[start:], re.MULTILINE)
    assert end is not None, f"missing closing Bash brace for {name!r}"
    bodies = _PYTHON.findall(script[start:start + end.start()])
    assert len(bodies) == 1, f"expected one Python heredoc in {name!r}"
    return bodies[0]


def command_python(script: str, command: str) -> str:
    """Extract Python owned by one explicit standalone command, including its argv anchor."""
    headers = list(re.finditer(r"^" + re.escape(command) + r"[^\n]*<<'PY'[^\n]*\n",
                               script, re.MULTILINE))
    assert len(headers) == 1, f"expected one driver command {command!r}"
    start = script.index("<<'PY'", headers[0].start(), headers[0].end())
    body = _PYTHON.match(script, start)
    assert body is not None, f"missing Python heredoc for {command!r}"
    return body.group(1)
