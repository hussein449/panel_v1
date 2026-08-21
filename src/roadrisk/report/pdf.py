"""Step 4.5 — the PDF, which is this report printed rather than re-rendered.

There is no second template and no second renderer. `report.html` is loaded into a
headless browser and printed, so the PDF and the screen are the same document by
construction: they cannot disagree, because there is only one of them. Everything that
makes it a printed document — the running mode banner, the page counters, the tables
that keep their headers across a break — is `@media print` CSS on the page itself.

**Why a browser and not a PDF library.** The alternative is a Python renderer such as
WeasyPrint, and it cannot render this page: the report is a React application, so its
content does not exist until a script has run. Printing the page that clients actually
read is the only way to be sure the file matches what they saw.

**The browser is not a dependency.** Nothing here is needed to *produce* a report —
`report.html` is complete on its own and any reader can open it and press Ctrl+P. This
exists for the runs that have to be stored or emailed as a PDF without a person in the
loop, which is what the Stage 5 worker will need. When no browser is found, that is
reported as what to do next rather than as a failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

PDF_FILENAME = "report.pdf"

#: Tried in order. Chrome and Edge share an engine, so either produces the same file.
BROWSER_COMMANDS: tuple[str, ...] = (
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    "microsoft-edge",
)

#: Checked when nothing on ``PATH`` matches, because Windows installers do not add one.
BROWSER_PATHS: tuple[str, ...] = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)

#: ``--print-to-pdf-no-header`` is not optional and is easy to get wrong: the flag that
#: reads as the obvious one, ``--no-pdf-header-footer``, is silently ignored, and
#: without the right one Chrome stamps a date and the file's own URL onto every page.
BASE_FLAGS: tuple[str, ...] = (
    "--headless",
    "--disable-gpu",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--print-to-pdf-no-header",
    "--virtual-time-budget=10000",
)


class BrowserNotFound(RuntimeError):
    """No Chrome or Edge was found, so the PDF could not be printed."""


class PdfExportFailed(RuntimeError):
    """A browser was found and printing it still did not produce a file."""


def find_browser(explicit: str | Path | None = None) -> Path | None:
    """Locate a Chromium-family browser, or return ``None``.

    Args:
        explicit: A path the caller supplied, or the ``ROADRISK_BROWSER`` environment
            variable when that is set. Checked first and never second-guessed.

    Returns:
        The browser's path, or ``None`` when there is nothing to print with.
    """
    candidate = explicit or os.environ.get("ROADRISK_BROWSER")
    if candidate:
        path = Path(candidate)
        return path if path.exists() else None

    for command in BROWSER_COMMANDS:
        found = shutil.which(command)
        if found:
            return Path(found)

    return next((Path(p) for p in BROWSER_PATHS if Path(p).exists()), None)


def to_pdf(
    html_path: Path,
    pdf_path: Path | None = None,
    *,
    browser: str | Path | None = None,
    timeout_s: float = 120.0,
) -> Path:
    """Print a written report to PDF.

    Args:
        html_path: A ``report.html`` produced by :func:`roadrisk.report.write_report`.
        pdf_path: Where to write. Defaults to ``report.pdf`` beside the HTML.
        browser: An explicit browser path, overriding discovery.
        timeout_s: How long to let the browser run before giving up.

    Raises:
        FileNotFoundError: There is no report at ``html_path``.
        BrowserNotFound: Nothing to print with, with the alternative spelled out.
        PdfExportFailed: The browser ran and produced nothing usable.

    Returns:
        The path written.
    """
    html_path = Path(html_path).resolve()
    if not html_path.exists():
        raise FileNotFoundError(f"No report to print at {html_path}")

    target = Path(pdf_path).resolve() if pdf_path else html_path.with_name(PDF_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)

    executable = find_browser(browser)
    if executable is None:
        raise BrowserNotFound(
            "No Chrome, Chromium or Edge was found, so the PDF could not be printed. "
            "The report itself is complete and needs none of this: open "
            f"{html_path} in any browser and print it, or choose Save as PDF. To "
            "automate it, install Chrome or set ROADRISK_BROWSER to its path."
        )

    with tempfile.TemporaryDirectory(prefix="roadrisk-print-") as profile:
        command: Sequence[str] = [
            str(executable),
            *BASE_FLAGS,
            f"--user-data-dir={profile}",
            f"--print-to-pdf={target}",
            html_path.as_uri(),
        ]
        try:
            result = subprocess.run(  # noqa: S603 - fixed flags, paths we resolved
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfExportFailed(
                f"{executable.name} did not finish printing within {timeout_s:.0f}s. "
                f"The report is readable at {html_path}."
            ) from exc

    if not target.exists() or target.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise PdfExportFailed(
            f"{executable.name} exited with code {result.returncode} and wrote no PDF."
            + (f" It said: {detail[-1]}" if detail else "")
            + f" The report is readable at {html_path}."
        )

    return target


__all__ = [
    "PDF_FILENAME",
    "BrowserNotFound",
    "PdfExportFailed",
    "find_browser",
    "to_pdf",
]
