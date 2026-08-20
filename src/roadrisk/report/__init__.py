"""Step 4.3 — the report page, and how a run gets into it.

There is one renderer, and it is not here. The page is a React view over the JSON
contract that step 4.1 built, living in `web/` and compiled to a single self-contained
HTML file that this package ships. What *is* here is the seam: taking a finished run
and putting it inside that page.

**Why injection rather than fetching.** The done-when for this step is that a report
opens from a run directory with no server running. A browser will not ``fetch()`` a
local file — `file://` requests are blocked by CORS with no origin to grant — so a
page that loaded ``assessment.json`` at runtime would need a web server, and the one
product that assesses a corridor with no network and no API key would have put the
network back in at the last step. Instead the payload is written *into* the document
as a JSON script block, which the page reads out of its own DOM.

**Why one file.** Same reason. No sibling assets, no stylesheet, no CDN: the report is
a thing you can email, and an emailed report that loses its formatting is not a
deliverable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from roadrisk import __version__

#: The compiled page. Built by ``npm run build`` in ``web/`` and committed, so that
#: installing this package never needs a JavaScript toolchain.
TEMPLATE_PATH = Path(__file__).parent / "static" / "index.html"

#: The exact placeholder the build emits. Matched literally rather than by pattern: if
#: the front end ever renames it, this must fail loudly at the seam instead of quietly
#: producing a report that shows a file picker to a client.
PLACEHOLDER = '<script id="roadrisk-run" type="application/json">null</script>'

REPORT_FILENAME = "report.html"


class ReportTemplateError(RuntimeError):
    """The compiled page is missing or no longer has somewhere to put the run."""


def build_run(
    assessment: Any,
    corridor: Any = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the payload the page consumes.

    This is the only function here that touches an engine object, and all it does is
    ask for its dictionary. Everything downstream — :func:`render_report`,
    :func:`write_report`, the page itself — sees plain JSON, which is what lets a run
    stored months ago render identically today.

    Args:
        assessment: The :class:`~roadrisk.core.engine.Assessment`.
        corridor: The :class:`~roadrisk.geo.pipeline.CorridorPanel`, when the panel
            came from geography. A panel handed straight to the engine has none, and
            the page renders without the map, provenance and licensing sections rather
            than inventing them.
        generated_at: Timestamp for the footer. Defaults to now, in UTC.

    Returns:
        A JSON-shaped dictionary.
    """
    stamp = generated_at or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "assessment": assessment.as_dict(),
        "corridor": corridor.as_dict() if corridor is not None else None,
        "generated_at": stamp,
        "engine_version": __version__,
    }


def render_report(run: Mapping[str, Any]) -> str:
    """Put a run inside the compiled page and hand back the whole document.

    Args:
        run: The payload from :func:`build_run` — or anything JSON-shaped with the
            same keys, including one read back from disk.

    Raises:
        ReportTemplateError: The compiled page is missing, or no longer carries the
            placeholder this writes into.

    Returns:
        A complete, self-contained HTML document.
    """
    if not TEMPLATE_PATH.exists():  # pragma: no cover - only in a broken install
        raise ReportTemplateError(
            f"The compiled report page is missing from {TEMPLATE_PATH}. It is built "
            "by `npm run build` in the web/ directory and committed with the package."
        )

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ReportTemplateError(
            "The compiled report page no longer contains the run placeholder "
            f"{PLACEHOLDER!r}. The front end and this writer have drifted apart; "
            "rebuild web/ or fix the placeholder rather than shipping a report with "
            "no run in it."
        )

    return template.replace(PLACEHOLDER, _script_block(run), 1)


def write_report(run: Mapping[str, Any], path: Path) -> Path:
    """Write a rendered report to ``path``, creating its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(run), encoding="utf-8")
    return path


# ---- internals ---------------------------------------------------------------


def _script_block(run: Mapping[str, Any]) -> str:
    """Serialise the run so that no value in it can close the script tag.

    In JSON a ``<`` can only ever appear inside a string literal, so escaping every
    one of them as ``\\u003c`` is both sufficient and lossless: a corridor named
    ``</script>`` survives the round trip and cannot end the block early. ASCII-only
    output means the document's encoding cannot change what the page parses either.
    """
    payload = json.dumps(run, ensure_ascii=True, separators=(",", ":"))
    return (
        '<script id="roadrisk-run" type="application/json">'
        + payload.replace("<", "\\u003c")
        + "</script>"
    )


__all__ = [
    "PLACEHOLDER",
    "REPORT_FILENAME",
    "TEMPLATE_PATH",
    "ReportTemplateError",
    "build_run",
    "render_report",
    "write_report",
]
