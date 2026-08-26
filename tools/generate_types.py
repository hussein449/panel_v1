"""Step 5.1a — generate `web/src/report/types.ts` from the payload contract.

    python tools/generate_types.py            # write web/src/report/types.ts
    python tools/generate_types.py --check    # fail if the committed file is stale

`web/src/report/types.ts` was hand-maintained. That was reasonable while one renderer read one
file, and stops being reasonable the moment there is an API: two descriptions of one
payload, in two languages, kept in step by whoever remembers. Step 4.7 is what that
costs — `posterior.coefficients` is a mapping, the page had it typed as a list, and every
coefficient silently fell back to its frequentist interval under a *credible interval*
heading for three steps.

So there is one description now, in `roadrisk.contract`, and this projects it into
TypeScript. The output is committed, because installing the package must never need a
Python toolchain to build the front end — the same reason the compiled report page is
committed.

**Determinism is a feature.** Definitions are emitted in sorted order and nothing here
depends on dictionary iteration order, so regenerating without changing the contract
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

SCALARS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def ts_type(schema: dict[str, Any]) -> str:
    """One JSON-Schema node as a TypeScript type expression."""
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]

    if "anyOf" in schema:
        parts = [ts_type(option) for option in schema["anyOf"]]
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
            return "[" + ", ".join(ts_type(item) for item in schema["prefixItems"]) + "]"
        items = schema.get("items")
        if not items:
            return "unknown[]"
        inner = ts_type(items)
        return f"({inner})[]" if " " in inner else f"{inner}[]"

    if kind == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict) and extra:
            return f"Record<string, {ts_type(extra)}>"
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


def render_interface(name: str, schema: dict[str, Any]) -> str:
    """One `$defs` entry as an exported interface."""
    lines: list[str] = []
    lines.extend(doc_comment(schema.get("description")))
    lines.append(f"export interface {name} {{")

    required = set(schema.get("required", ()))
    for field, spec in schema.get("properties", {}).items():
        lines.extend(doc_comment(spec.get("description"), indent="  "))
        optional = "" if field in required else "?"
        lines.append(f"  {field}{optional}: {ts_type(spec)};")

    lines.append("}")
    return "\n".join(lines)


def render() -> str:
    """The whole file."""
    schema = Run.model_json_schema()
    definitions = schema.get("$defs", {})

    blocks = [HEADER.rstrip()]
    for name in sorted(definitions):
        blocks.append(render_interface(name, definitions[name]))

    root = {key: value for key, value in schema.items() if key != "$defs"}
    blocks.append(render_interface("Run", root))

    return "\n\n".join(blocks) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write. Exit non-zero if the committed file is out of date.",
    )
    args = parser.parse_args()

    generated = render()

    if args.check:
        if not TARGET.exists():
            print(f"{TARGET} does not exist. Run: python tools/generate_types.py")
            return 1
        current = TARGET.read_text(encoding="utf-8")
        if current != generated:
            print(
                f"{TARGET.relative_to(REPO)} is out of date with "
                "src/roadrisk/contract/.\nRun: python tools/generate_types.py"
            )
            return 1
        print(f"{TARGET.relative_to(REPO)} is up to date.")
        return 0

    TARGET.write_text(generated, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(REPO)} ({len(generated.splitlines())} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
