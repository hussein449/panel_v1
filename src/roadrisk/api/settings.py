"""What the API needs told, and the one setting that is a security boundary.

Read from the environment rather than from a file, because every deployment target in
Stage 6 — Fly, Render, a container — configures that way, and a config file is one more
thing to mount.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Directory that artefact files must resolve inside. **Unset means no downloads.**
#:
#: Artefacts are stored by reference: the database holds a `file://` URI, and serving
#: one means opening whatever string is in that column. That is a file-read primitive
#: pointed at the server's disk, and it does not become safe by being written by a
#: trusted CLI today — 5.2a puts a worker on the other end of it.
#:
#: So the root is an allow-list, there is no default, and with nothing set every
#: download is refused rather than every path being served. The failure mode of the
#: safe default is a 409 that names this variable; the failure mode of the convenient
#: default is `/etc/passwd`.
ARTEFACT_ROOT_ENV = "ROADRISK_ARTEFACT_ROOT"

#: Rows a client may submit inline with a job. A 100 km corridor at 500 m units over 24
#: monthly periods is 4,800 rows, so this is roughly ten times the largest panel the
#: pipeline produces today — big enough that nobody legitimate meets it, small enough
#: that the body cannot be used to fill `jsonb`.
MAX_PANEL_ROWS_ENV = "ROADRISK_MAX_PANEL_ROWS"

DEFAULT_MAX_PANEL_ROWS = 50_000
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class ApiSettings:
    """Everything the app is told, resolved once at startup."""

    #: Where artefact files must live. None disables artefact download entirely.
    artefact_root: Path | None = None
    max_panel_rows: int = DEFAULT_MAX_PANEL_ROWS
    default_page_size: int = DEFAULT_PAGE_SIZE
    max_page_size: int = MAX_PAGE_SIZE

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ApiSettings:
        """Read the environment. Malformed values are refused, never defaulted over."""
        source = os.environ if environ is None else environ

        root = source.get(ARTEFACT_ROOT_ENV)
        raw_rows = source.get(MAX_PANEL_ROWS_ENV)
        try:
            rows = int(raw_rows) if raw_rows else DEFAULT_MAX_PANEL_ROWS
        except ValueError as exc:
            raise ValueError(
                f"${MAX_PANEL_ROWS_ENV} must be a whole number of rows, "
                f"got {raw_rows!r}."
            ) from exc
        if rows < 1:
            raise ValueError(f"${MAX_PANEL_ROWS_ENV} must be at least 1, got {rows}.")

        return cls(
            artefact_root=Path(root).resolve() if root else None,
            max_panel_rows=rows,
        )


__all__ = [
    "ARTEFACT_ROOT_ENV",
    "DEFAULT_MAX_PANEL_ROWS",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_PANEL_ROWS_ENV",
    "ApiSettings",
]
