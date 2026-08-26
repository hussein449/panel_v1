"""Write `docs/openapi.json` from the app, the way 5.1a writes `web/src/report/types.ts`.

    python tools/generate_openapi.py            # rewrite the document
    python tools/generate_openapi.py --check    # what the test runs

**Why generate a file at all when FastAPI serves one at `/openapi.json`.** Because the
client is not always running against a server. Step 5.3b's Next.js shell wants a
description of this API at build time, a reviewer wants to read the surface without
installing the package, and "what did this endpoint look like last release" is a
question `git log` should be able to answer. A served document answers none of those.

**What `--check` asserts, and what it deliberately does not.** It compares the paths,
the operations, the parameters and the schema names — the API's actual surface. It does
*not* compare the whole document byte for byte, because a FastAPI upgrade legitimately
changes how it words a description or orders a `anyOf`, and a test that failed on that
would be a test people learn to regenerate past without reading. The surface is the
contract. The rendering of it is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUTPUT = ROOT / "docs" / "openapi.json"


def document() -> dict[str, Any]:
    """The OpenAPI document, built over a store that needs nothing.

    A memory store explicitly, not the environment default: generating a description of
    the API must never depend on a database being reachable, and it must produce the
    same bytes on a laptop as in CI.
    """
    from roadrisk.api import create_app, shared_store
    from roadrisk.api.settings import ApiSettings
    from roadrisk.store import MemoryStore

    app = create_app(
        store_provider=shared_store(MemoryStore()), settings=ApiSettings()
    )
    return app.openapi()


def surface(spec: dict[str, Any]) -> dict[str, Any]:
    """The part of the document that is the contract.

    Paths, methods, status codes, parameter names and the names of the schemas — change
    any of those and somebody's client breaks. Everything else is prose.
    """
    paths: dict[str, Any] = {}
    for path, operations in spec.get("paths", {}).items():
        for method, operation in operations.items():
            paths[f"{method.upper()} {path}"] = {
                "operationId": operation.get("operationId"),
                "parameters": sorted(
                    f"{p.get('in')}:{p.get('name')}"
                    for p in operation.get("parameters", [])
                ),
                "requestBody": _schema_names(operation.get("requestBody", {})),
                "responses": sorted(operation.get("responses", {})),
            }
    return {
        "openapi": spec.get("openapi"),
        "paths": dict(sorted(paths.items())),
        "schemas": sorted(spec.get("components", {}).get("schemas", {})),
    }


def _schema_names(request_body: dict[str, Any]) -> list[str]:
    found = set()
    for media in request_body.get("content", {}).values():
        ref = media.get("schema", {}).get("$ref")
        if ref:
            found.add(ref.rsplit("/", 1)[-1])
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed document's surface has drifted.",
    )
    args = parser.parse_args()

    spec = document()
    rendered = json.dumps(spec, indent=2, sort_keys=True) + "\n"

    if not args.check:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8")
        print(
            f"Wrote {OUTPUT.relative_to(ROOT)} — "
            f"{len(spec['paths'])} paths, "
            f"{len(spec.get('components', {}).get('schemas', {}))} schemas."
        )
        return 0

    if not OUTPUT.exists():
        print(f"{OUTPUT.relative_to(ROOT)} does not exist. Run this without --check.")
        return 1

    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if surface(committed) == surface(spec):
        print(f"{OUTPUT.relative_to(ROOT)} describes the API as it is.")
        return 0

    print(
        f"{OUTPUT.relative_to(ROOT)} no longer describes this API. "
        "Run: python tools/generate_openapi.py"
    )
    _report(surface(committed), surface(spec))
    return 1


def _report(committed: dict[str, Any], current: dict[str, Any]) -> None:
    """Name what moved, because "the document has drifted" is not actionable."""
    for key in ("paths", "schemas"):
        was = set(committed[key] if isinstance(committed[key], list) else committed[key])
        now = set(current[key] if isinstance(current[key], list) else current[key])
        for gone in sorted(was - now):
            print(f"  removed {key[:-1]}: {gone}")
        for added in sorted(now - was):
            print(f"  added {key[:-1]}:   {added}")
    for name, operation in current["paths"].items():
        if name in committed["paths"] and committed["paths"][name] != operation:
            print(f"  changed: {name}")


if __name__ == "__main__":
    raise SystemExit(main())
