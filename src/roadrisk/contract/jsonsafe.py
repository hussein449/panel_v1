"""Making a payload actually JSON, rather than nearly JSON.

Python's `json.dumps` writes `NaN`, `Infinity` and `-Infinity` as bare tokens by
default. That is a Python extension, not JSON: the specification has no infinity and no
not-a-number, so every strict reader refuses them — a browser's `JSON.parse`, Postgres's
`jsonb`, `jq`, and any consumer written in another language.

The result is a payload that looks fine from Python and is unreadable everywhere else,
which is the worst shape a contract can be in. Step 4.4 found this in the report and
guarded the HTML embedding; the JSON files written beside it kept the bare tokens, so a
Mode B run — whose dispersion ratio is infinite, because a crash-free panel has mean
zero — wrote a `run.json` that the report's own file picker could not read back.

So the sanitising happens once, at the point a payload is assembled, and everything
downstream inherits it.

**`null`, not zero, and not a string.** A non-finite value here is a quantity that
genuinely could not be computed — a variance-to-mean ratio with nothing in the
denominator, a mean deviation over folds that produced nothing. JSON's word for that is
`null`, which every renderer in this project already draws as an absent value. Zero
would be a number nobody measured, and `"Infinity"` would be a string that arithmetic
silently fails on later.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def finite(value: Any) -> Any:
    """Recursively replace every non-finite float with ``None``.

    Idempotent, so applying it again at a serialisation boundary costs nothing and is
    worth doing as a belt to this braces — a payload assembled by hand, or read from an
    older file, has not been through here.

    Args:
        value: Any JSON-shaped structure.

    Returns:
        The same structure with `NaN`, `Infinity` and `-Infinity` replaced by ``None``.
        Tuples become lists, because JSON has one sequence type and pretending
        otherwise only defers the surprise.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {key: finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [finite(item) for item in value]
    return value


def non_finite_paths(value: Any, path: str = "$") -> list[str]:
    """Every place a non-finite float is hiding, for tests and for error messages.

    Naming the path matters more here than the count: "one non-finite float" sends
    somebody hunting through 300 kB, and
    `$.assessment.log[17].data.ratio` does not.
    """
    if isinstance(value, float):
        return [] if math.isfinite(value) else [path]
    if isinstance(value, Mapping):
        found: list[str] = []
        for key, item in value.items():
            found.extend(non_finite_paths(item, f"{path}.{key}"))
        return found
    if isinstance(value, list | tuple):
        found = []
        for index, item in enumerate(value):
            found.extend(non_finite_paths(item, f"{path}[{index}]"))
        return found
    return []
