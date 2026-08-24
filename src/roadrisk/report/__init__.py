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
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from roadrisk import __version__
from roadrisk.contract import SCHEMA_VERSION
from roadrisk.report.limitations import Limitation, as_dicts, collect_limitations
from roadrisk.report.pdf import (
    PDF_FILENAME,
    BrowserNotFound,
    PdfExportFailed,
    find_browser,
    to_pdf,
)

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
    assessment_payload = assessment.as_dict()
    corridor_payload = corridor.as_dict() if corridor is not None else None
    return {
        "assessment": assessment_payload,
        "corridor": corridor_payload,
        # Assembled here rather than in the page, so that the API and the worker get
        # the same list without deriving it a second time — and so that removing it
        # is a code change with a failing test attached rather than a template edit.
        # There is no argument that omits it.
        "limitations": as_dicts(
            collect_limitations(assessment_payload, corridor_payload)
        ),
        "generated_at": stamp,
        "engine_version": __version__,
        # The payload's own version, separate from the engine's. It moves when the
        # *shape* changes, so a consumer reading a run stored months ago can tell
        # whether it still knows how to read it — which is what 5.1b's promise that a
        # stored run re-renders without a refit actually rests on.
        "schema_version": SCHEMA_VERSION,
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

    ``allow_nan=False`` is the belt to :func:`_finite`'s braces. Python writes ``NaN``
    and ``Infinity`` as bare tokens, which JavaScript's ``JSON.parse`` rejects — and
    the failure is silent in the worst possible way, because the page cannot tell an
    unparseable run from an absent one, so it quietly offers a file picker where the
    report should be. Sanitising first and then refusing to serialise anything
    non-finite means that cannot reach a client.
    """
    payload = json.dumps(
        _finite(run), ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    return (
        '<script id="roadrisk-run" type="application/json">'
        + payload.replace("<", "\\u003c")
        + "</script>"
    )


def _finite(value: Any) -> Any:
    """Replace every non-finite float with ``null``, recursively.

    A ``NaN`` arriving here is not a corrupt payload — it is a quantity that genuinely
    could not be computed, such as a mean deviation over folds that produced nothing.
    JSON has a word for that and it is ``null``, which the page already renders as an
    absent value. Losing a whole report over one uncomputable diagnostic would be the
    worse trade by a distance.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(item) for item in value]
    return value


__all__ = [
    "PDF_FILENAME",
    "Limitation",
    "PLACEHOLDER",
    "REPORT_FILENAME",
    "TEMPLATE_PATH",
    "BrowserNotFound",
    "PdfExportFailed",
    "ReportTemplateError",
    "build_run",
    "collect_limitations",
    "find_browser",
    "render_report",
    "to_pdf",
    "write_report",
]
