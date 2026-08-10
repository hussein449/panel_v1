"""Load and validate a factor registry from YAML.

Failures name the offending factor rather than its list index, because a registry is
edited by hand and ``factors.11.expected_sign`` helps nobody.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from roadrisk.core.errors import RegistryError
from roadrisk.core.registry.schema import Registry

DEFAULT_REGISTRY_PATH = Path(__file__).with_name("factors.yaml")


def load_registry(path: str | Path | None = None) -> Registry:
    """Read, parse and validate a registry file.

    Args:
        path: Registry YAML. Defaults to the registry shipped with the package.

    Raises:
        RegistryError: The file is missing, is not valid YAML, or fails validation.
    """
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    try:
        raw_bytes = registry_path.read_bytes()
    except OSError as exc:
        raise RegistryError(f"cannot read registry at {registry_path}: {exc}") from exc

    registry = parse_registry(raw_bytes.decode("utf-8"), origin=str(registry_path))
    registry.source_path = str(registry_path)
    registry.sha256 = hashlib.sha256(raw_bytes).hexdigest()
    return registry


def parse_registry(text: str, *, origin: str = "<string>") -> Registry:
    """Parse a registry from YAML text.

    Raises:
        RegistryError: The text is not valid YAML or fails validation.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"{origin} is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryError(
            f"{origin} must contain a mapping with 'version' and 'factors' keys, "
            f"got {type(data).__name__}"
        )

    _reject_legacy_schema(data, origin)

    try:
        return Registry.model_validate(data)
    except ValidationError as exc:
        raise RegistryError(
            f"{origin} failed validation:\n{_describe(exc, data)}"
        ) from exc


_LEGACY_KEYS = ("default_weight", "weight_source")


def _reject_legacy_schema(data: dict[str, Any], origin: str) -> None:
    """Name the migration rather than letting `extra='forbid'` produce a riddle.

    Registries written before 0.2 carried a single `default_weight` plus a
    `weight_source` string. A weight now declares the context it is valid in, which
    is what stopped US rural two-lane coefficients from being applied silently to any
    corridor anywhere.
    """
    factors = data.get("factors")
    if not isinstance(factors, list):
        return

    offenders = [
        str(entry.get("name", f"#{index}"))
        for index, entry in enumerate(factors)
        if isinstance(entry, dict) and any(key in entry for key in _LEGACY_KEYS)
    ]
    if not offenders:
        return

    raise RegistryError(
        f"{origin} uses the pre-0.2 single-weight schema. Replace `default_weight` "
        "and `weight_source` with a `weights:` list, where each entry declares "
        "`value`, `source`, `family`, and optionally `facility_type`, `region`, "
        "`severity`, `scope` and `assumes`. See docs/WEIGHTS.md.\n"
        f"  affected factor(s): {', '.join(offenders)}"
    )


def _describe(exc: ValidationError, data: dict[str, Any]) -> str:
    """Render a ValidationError with factor names instead of list indices."""
    factors = data.get("factors")
    lines: list[str] = []
    for err in exc.errors():
        loc = list(err["loc"])
        if len(loc) >= 2 and loc[0] == "factors" and isinstance(loc[1], int):
            name = _factor_name_at(factors, loc[1])
            rest = ".".join(str(p) for p in loc[2:])
            where = f"factor '{name}'" + (f" → {rest}" if rest else "")
        else:
            where = ".".join(str(p) for p in loc) or "<root>"
        lines.append(f"  {where}: {err['msg']}")
    return "\n".join(lines)


def _factor_name_at(factors: Any, index: int) -> str:
    if isinstance(factors, list) and index < len(factors):
        entry = factors[index]
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            return entry["name"]
    return f"#{index}"


__all__ = ["DEFAULT_REGISTRY_PATH", "load_registry", "parse_registry"]
