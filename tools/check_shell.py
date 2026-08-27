"""Step 5.3b — prove the banner is on every screen, against a shell that is running.

    roadrisk serve &                       # the API, on 127.0.0.1:8000
    cd web/shell && npm run build && npm run start &
    python tools/check_shell.py

`tests/test_shell.py` asserts the *arrangement* — one root layout, the banner rendered
there, no page importing it — which is what makes the property hold for routes nobody has
written yet. This asserts the **result**: every route this app actually has, fetched over
HTTP, with the banner in the HTML that came back.

Both are worth having and neither replaces the other. A structural test cannot see a
banner that renders to nothing because health threw; a fetch cannot see the twelfth route
somebody adds next year. This one is also the only check that reads the *server-rendered*
HTML, which is the whole reason the banner is a server component: it is in the document,
not painted into it afterwards, so a reader with no JavaScript still gets it.

**Routes are discovered, not listed.** Every `page.tsx` under `web/shell/app` is a route
and every one of them is fetched, so adding a screen adds a check. A hard-coded list
would pass on the day it was written and go quietly out of date, which is the exact
failure mode this step exists to prevent.

It needs no dependencies beyond the standard library, and it creates one project and one
demonstration job in whatever service it is pointed at.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "web" / "shell" / "app"

#: What every screen must carry. The `aria-label` rather than a class name, because it is
#: what the banner *is* to a reader who cannot see it, and it is not styling.
DEPLOYMENT_BANNER = 'aria-label="What this deployment is"'

#: What every screen about a run must carry, on top of the above.
RUN_BANNER = 'aria-label="What produced this run"'


def get(url: str, tenant: str | None = None, timeout: float = 30.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    if tenant:
        request.add_header("X-Tenant-Id", tenant)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def post(url: str, body: dict, tenant: str) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Tenant-Id": tenant},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"POST {url} answered {error.code}: {error.read().decode('utf-8', 'replace')}"
        ) from error


def routes() -> list[str]:
    """Every route in the app, as a URL path with its parameters still in it."""
    found = []
    for page in sorted(APP.rglob("page.tsx")):
        parts = [
            part
            for part in page.relative_to(APP).parent.parts
            # A route group — `(marketing)` — is a folder that organises files without
            # appearing in the URL. There are none today; discovering routes wrongly the
            # day somebody adds one would be worse than the four lines that handle it.
            if not (part.startswith("(") and part.endswith(")"))
        ]
        found.append("/" + "/".join(parts))
    return found


def fill(route: str, values: dict[str, str]) -> str | None:
    """Substitute `[runId]` and friends. Returns None if something has no value."""
    for name, value in values.items():
        route = route.replace(f"[{name}]", value)
    return None if "[" in route else route


def make_a_run(api: str, tenant: str) -> dict[str, str]:
    """One project and one demonstration run, so the parameterised routes resolve."""
    project = post(f"{api}/projects", {"name": "shell check"}, tenant)
    job = post(f"{api}/jobs", {"project_id": project["id"], "demo": True}, tenant)

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status, body = get(f"{api}/jobs/{job['id']}", tenant)
        state = json.loads(body)["status"]
        if state == "succeeded":
            break
        if state in {"failed", "rejected"}:
            raise SystemExit(f"the demonstration job {state}: {json.loads(body)['error']}")
        time.sleep(0.5)
    else:
        raise SystemExit("the demonstration job never finished")

    _, body = get(f"{api}/jobs/{job['id']}/run", tenant)
    run = json.loads(body)
    return {
        "projectId": project["id"],
        "jobId": job["id"],
        "runId": run["id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", default="http://127.0.0.1:3000")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--tenant",
        default=os.environ.get("ROADRISK_TENANT_ID"),
        help="The tenant the shell is serving. Must be the same one.",
    )
    args = parser.parse_args()

    if not args.tenant:
        parser.error("--tenant, or $ROADRISK_TENANT_ID, is required")

    values = make_a_run(args.api.rstrip("/"), args.tenant)
    print(f"project {values['projectId']}  job {values['jobId']}  run {values['runId']}\n")

    # A path no route matches, so that `not-found.tsx` is checked too. A 404 is a screen.
    checks = [*routes(), "/no-such-page"]

    failures = 0
    for route in checks:
        url = fill(route, values)
        if url is None:
            print(f"  SKIP  {route}  (no value for its parameter)")
            continue

        status, html = get(f"{args.shell.rstrip('/')}{url}")
        problems = []
        if status not in (200, 404):
            problems.append(f"status {status}")
        if DEPLOYMENT_BANNER not in html:
            problems.append("no deployment banner")
        if route.startswith("/runs/[runId]") and RUN_BANNER not in html:
            problems.append("no mode banner")

        if problems:
            failures += 1
            print(f"  FAIL  {url}  — {', '.join(problems)}")
        else:
            marker = "banner + mode" if route.startswith("/runs/[runId]") else "banner"
            print(f"  ok    {url}  ({status}, {marker}, {len(html):,} bytes)")

    print()
    if failures:
        print(f"{failures} of {len(checks)} screens are missing something.")
        return 1
    print(f"All {len(checks)} screens carry the banner they must carry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
