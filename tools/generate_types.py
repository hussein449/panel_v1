"""Generate the TypeScript the front end reads, from the Python that defines it.

    python tools/generate_types.py            # write both files
    python tools/generate_types.py --check    # fail if either committed file is stale

Two outputs, one rule:

* `web/src/report/types.ts` — **the payload**, from `roadrisk.contract` (step 5.1a).
  What a run *is*: the thing `<Report>` draws.
* `web/shell/lib/wire.ts` — **the envelope**, from `roadrisk.store.records`,
  `roadrisk.api.schemas` and `roadrisk.api.errors` (step 5.3b). What the API says around
  a payload: projects, corridors, jobs, run records, artefacts, health, and the shape of
  a refusal.

`web/src/report/types.ts` was hand-maintained. That was reasonable while one renderer read one
file, and stops being reasonable the moment there is an API: two descriptions of one
payload, in two languages, kept in step by whoever remembers. Step 4.7 is what that
costs — `posterior.coefficients` is a mapping, the page had it typed as a list, and every
coefficient silently fell back to its frequentist interval under a *credible interval*
heading for three steps.

**The second output exists because the shell would otherwise repeat that mistake with
new names.** A website is the first client that has to describe `GET /jobs/{id}` in
TypeScript, and a hand-written `Job` in `web/shell/` is exactly the 5.1a defect one layer
out: `status` gains a sixth value in `JobStatus` and the shell renders it as nothing at
all. So the envelope is projected too, from the same models FastAPI generates its
OpenAPI from.

Both outputs are committed, because installing this package must never need a Python
toolchain to build the front end — the same reason the compiled report page is committed.

**Determinism is a feature.** Definitions are emitted in sorted order and nothing here
depends on dictionary iteration order, so regenerating without changing the models
produces a byte-identical file. That is what lets `--check` be a test.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from roadrisk.contract import SCHEMA_VERSION, Run  # noqa: E402

TARGET = REPO / "web" / "src" / "report" / "types.ts"
WIRE_TARGET = REPO / "web" / "shell" / "lib" / "wire.ts"

HEADER = f"""/**
 * The JSON contract, as TypeScript.
 *
 * GENERATED FILE — do not edit by hand.
 *
 * Source of truth: `src/roadrisk/contract/` on the Python side.
 * Regenerate:      python tools/generate_types.py
 * Payload schema:  {SCHEMA_VERSION}
 *
 * These types describe the payload completely, not partially. The Python models they
 * come from forbid undeclared fields, so a key the engine emits and the contract has
 * not declared fails a test rather than arriving here unannounced.
 *
 * A field typed `T | null` is one the payload carries as null; a field marked `?` is
 * one the payload omits entirely. The distinction matters most in Mode B, where the
 * count-shaped fields are *absent* rather than null — a null is a hole a renderer fills
 * with a dash, which reads as "not available" rather than "this mode does not produce
 * one".
 */
"""

WIRE_HEADER = f"""/**
 * What crosses the wire, as TypeScript.
 *
 * GENERATED FILE — do not edit by hand.
 *
 * Source of truth: `roadrisk.store.records`, `roadrisk.api.schemas` and
 *                  `roadrisk.api.errors` on the Python side.
 * Regenerate:      python tools/generate_types.py
 * Payload schema:  {SCHEMA_VERSION}
 *
 * The *envelope*, not the payload. `types.ts` in the report library describes what a run
 * is; this describes what the API says around one — the project it belongs to, the job
 * that produced it, the files it wrote, and what this deployment admits about itself.
 *
 * Generated for the same reason the payload is. A hand-written `Job` here is the step
 * 4.7 defect one layer out: `JobStatus` grows a sixth value, the shell has five, and a
 * job in the new state renders as nothing at all.
 *
 * Two names are not the Python ones, and both are deliberate:
 *
 * * **`StoredRun`** is `roadrisk.store.records.Run` — the row, not the payload. The
 *   payload is `Run` in the report library, and one file cannot hold two `Run`s.
 * * **`StoredRun.payload`** and **`Job.params`** are `dict[str, Any]` in Python, because
 *   the store deliberately knows nothing about what it is storing. They are typed here,
 *   because the shell does.
 *
 * **A response has every field; a request body does not.** A Python default is about
 * construction — a `Job` needs no id, because the store is about to give it one — and
 * FastAPI still serialises the field, default and all. So the shapes the API returns
 * carry no `?` at all, and the bodies it accepts carry one wherever a client may leave
 * a field out.
 */

import type {{ Run as ReportRun }} from "roadrisk-report/report";
"""

SCALARS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}

#: Definitions renamed on the way out. See the wire header for why.
WIRE_RENAME = {"Run": "StoredRun"}

#: Fields the store types as an opaque object and the shell types properly.
#:
#: `(interface, field) -> TypeScript`. The Python side is right to be vague — a store
#: that knew the shape of a payload would have to be migrated whenever the payload
#: changed — and the shell is right to be specific, because it renders the thing.
WIRE_FIELD_TYPES = {
    ("StoredRun", "payload"): "ReportRun",
    ("Job", "params"): "JobSpec",
}

#: Shapes the API only ever *returns*, whose every field is therefore always there.
#:
#: A Python default is about construction — `Job()` does not need an id, because the
#: store is about to give it one. It is not about transport: FastAPI serialises a
#: response model whole, so a field with a default goes out carrying its default and is
#: never omitted. Projecting those as `id?: string` would describe a response the API
#: cannot produce, and would make every reader of a job write `job.id!` to get past it.
#:
#: Request bodies are the opposite and are deliberately absent from this set: there,
#: a default *is* a field the client may leave out. `JobOptions` is both — nested in a
#: submission and in a stored spec — and keeps the request reading, because a client
#: forced to spell out all eleven defaults is worse off than a reader handling a `?`.
WIRE_COMPLETE = frozenset(
    {
        "AdapterOut",
        "ArtefactOut",
        "Corridor",
        "ErrorBody",
        "FactorOut",
        "FieldError",
        "Health",
        "Job",
        "JobSpec",
        "LicenceOut",
        "Project",
        "Refusal",
        "RegistryOut",
        "RunSummary",
        "StoredRun",
        "TierOut",
    }
)


def ts_type(schema: dict[str, Any], rename: dict[str, str] | None = None) -> str:
    """One JSON-Schema node as a TypeScript type expression."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return (rename or {}).get(name, name)

    if "anyOf" in schema:
        parts = [ts_type(option, rename) for option in schema["anyOf"]]
        # `null` last reads better and matches how the hand-written file was written.
        parts.sort(key=lambda part: part == "null")
        return " | ".join(dict.fromkeys(parts))

    if "const" in schema:
        return json.dumps(schema["const"])

    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])

    kind = schema.get("type")

    if kind == "array":
        if "prefixItems" in schema:
            return (
                "["
                + ", ".join(ts_type(item, rename) for item in schema["prefixItems"])
                + "]"
            )
        items = schema.get("items")
        if not items:
            return "unknown[]"
        inner = ts_type(items, rename)
        return f"({inner})[]" if " " in inner else f"{inner}[]"

    if kind == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict) and extra:
            return f"Record<string, {ts_type(extra, rename)}>"
        return "Record<string, unknown>"

    if isinstance(kind, list):
        return " | ".join(SCALARS.get(item, "unknown") for item in kind)

    return SCALARS.get(kind, "unknown")


def doc_comment(text: str | None, indent: str = "") -> list[str]:
    """A description as a JSDoc block, or nothing."""
    if not text:
        return []
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    out = [f"{indent}/**"]
    out.extend(f"{indent} * {line}".rstrip() for line in lines)
    out.append(f"{indent} */")
    return out


def render_interface(
    name: str,
    schema: dict[str, Any],
    rename: dict[str, str] | None = None,
    field_types: dict[tuple[str, str], str] | None = None,
    complete: frozenset[str] = frozenset(),
) -> str:
    """One `$defs` entry as an exported interface."""
    lines: list[str] = []
    lines.extend(doc_comment(schema.get("description")))
    lines.append(f"export interface {name} {{")

    required = set(schema.get("required", ()))
    for field, spec in schema.get("properties", {}).items():
        lines.extend(doc_comment(spec.get("description"), indent="  "))
        optional = "" if field in required or name in complete else "?"
        override = (field_types or {}).get((name, field))
        lines.append(f"  {field}{optional}: {override or ts_type(spec, rename)};")

    lines.append("}")
    return "\n".join(lines)


def render_definition(
    name: str,
    schema: dict[str, Any],
    rename: dict[str, str] | None = None,
    field_types: dict[tuple[str, str], str] | None = None,
    complete: frozenset[str] = frozenset(),
) -> str:
    """One `$defs` entry, as an interface or — for an enum — as a union of literals.

    An enum has no properties, so putting one through `render_interface` produces an
    empty interface: a type that accepts every object and describes nothing. The payload
    contract has no enums; the wire is nothing but them.
    """
    if "enum" in schema and "properties" not in schema:
        lines = doc_comment(schema.get("description"))
        lines.append(f"export type {name} = {ts_type(schema, rename)};")
        return "\n".join(lines)
    return render_interface(name, schema, rename, field_types, complete)


def render() -> str:
    """The payload contract, whole."""
    schema = Run.model_json_schema()
    definitions = schema.get("$defs", {})

    blocks = [HEADER.rstrip()]
    for name in sorted(definitions):
        blocks.append(render_definition(name, definitions[name]))

    root = {key: value for key, value in schema.items() if key != "$defs"}
    blocks.append(render_interface("Run", root))

    return "\n\n".join(blocks) + "\n"


def _wire_definitions() -> dict[str, dict[str, Any]]:
    """Every model the API puts on the wire, as one pool of definitions.

    Imported here rather than at module scope so that regenerating the payload types
    still works in a checkout without the `api` extra installed. The payload contract
    imports nothing; the API models import FastAPI, and needing FastAPI to regenerate
    `types.ts` would be a dependency this tool has no business having.
    """
    from pydantic import BaseModel

    from roadrisk.api.errors import ErrorBody
    from roadrisk.api.schemas import (
        ArtefactOut,
        CorridorCreate,
        CorridorPatch,
        Health,
        JobSpec,
        JobSubmission,
        ProjectCreate,
        ProjectPatch,
        RegistryOut,
        RunSummary,
    )
    from roadrisk.store.records import Corridor, Job, Project
    from roadrisk.store.records import Run as StoredRun

    class _Wire(BaseModel):
        """A model that exists only to pull every response shape into one `$defs`.

        Nothing is emitted for this class itself. It is the union of what the routes
        return and what they accept, and adding a route's shape here is what makes it
        exist in TypeScript.
        """

        health: Health
        registry: RegistryOut
        projects: list[Project]
        corridors: list[Corridor]
        jobs: list[Job]
        run: StoredRun
        run_summaries: list[RunSummary]
        artefacts: list[ArtefactOut]
        new_project: ProjectCreate
        edit_project: ProjectPatch
        new_corridor: CorridorCreate
        edit_corridor: CorridorPatch
        submission: JobSubmission
        job_spec: JobSpec
        refusal: ErrorBody

    definitions: dict[str, dict[str, Any]] = _Wire.model_json_schema().get("$defs", {})
    return definitions


def render_wire() -> str:
    """The API envelope, whole."""
    definitions = _wire_definitions()

    blocks = [WIRE_HEADER.rstrip()]
    for name in sorted(definitions, key=lambda key: WIRE_RENAME.get(key, key)):
        blocks.append(
            render_definition(
                WIRE_RENAME.get(name, name),
                definitions[name],
                WIRE_RENAME,
                WIRE_FIELD_TYPES,
                WIRE_COMPLETE,
            )
        )

    return "\n\n".join(blocks) + "\n"


def _check(target: Path, generated: str, source: str) -> int:
    if not target.exists():
        print(f"{target} does not exist. Run: python tools/generate_types.py")
        return 1
    if target.read_text(encoding="utf-8") != generated:
        print(
            f"{target.relative_to(REPO)} is out of date with "
            f"{source}.\nRun: python tools/generate_types.py"
        )
        return 1
    print(f"{target.relative_to(REPO)} is up to date.")
    return 0


def _write(target: Path, generated: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generated, encoding="utf-8")
    print(f"Wrote {target.relative_to(REPO)} ({len(generated.splitlines())} lines).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write. Exit non-zero if a committed file is out of date.",
    )
    args = parser.parse_args()

    try:
        wire = render_wire()
    except ImportError as exc:
        # Not a failure. A checkout without the `api` extra can still regenerate the
        # payload types, and saying which half was skipped is better than either
        # pretending both were done or refusing to do the half that works.
        print(f"Skipping {WIRE_TARGET.relative_to(REPO)}: {exc}", file=sys.stderr)
        wire = None

    if args.check:
        status = _check(TARGET, render(), "src/roadrisk/contract/")
        if wire is not None:
            status |= _check(WIRE_TARGET, wire, "the API and store models")
        return status

    _write(TARGET, render())
    if wire is not None:
        _write(WIRE_TARGET, wire)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
