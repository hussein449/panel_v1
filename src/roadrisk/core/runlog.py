"""Run log and reproducibility manifest.

Two things make the product defensible rather than merely correct:

1. **Nothing is silent.** Every gate result, every descent, every dropped term and
   every sign flag is appended here and travels to the report.
2. **Every result is reproducible.** The manifest fingerprints the code, the registry
   and the input data. A number that cannot be regenerated in six months, when a
   ministry challenges it, is a liability.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pandas as pd

from roadrisk import __version__


class Level(StrEnum):
    """Why an event was recorded, not how severe it is."""

    INFO = "info"
    WARNING = "warning"
    DESCENT = "descent"
    REFUSAL = "refusal"
    FLAG = "flag"


@dataclass(frozen=True)
class LogEvent:
    sequence: int
    timestamp: str
    stage: str
    level: Level
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "level": self.level.value,
            "code": self.code,
            "message": self.message,
            "data": self.data,
        }


class RunLog:
    """Append-only event log for a single assessment."""

    def __init__(self) -> None:
        self._events: list[LogEvent] = []

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    @property
    def events(self) -> list[LogEvent]:
        return list(self._events)

    def record(
        self,
        stage: str,
        level: Level,
        code: str,
        message: str,
        **data: Any,
    ) -> LogEvent:
        event = LogEvent(
            sequence=len(self._events) + 1,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            stage=stage,
            level=level,
            code=code,
            message=message,
            data=data,
        )
        self._events.append(event)
        return event

    def info(self, stage: str, code: str, message: str, **data: Any) -> LogEvent:
        return self.record(stage, Level.INFO, code, message, **data)

    def warning(self, stage: str, code: str, message: str, **data: Any) -> LogEvent:
        return self.record(stage, Level.WARNING, code, message, **data)

    def descent(self, stage: str, code: str, message: str, **data: Any) -> LogEvent:
        return self.record(stage, Level.DESCENT, code, message, **data)

    def refusal(self, stage: str, code: str, message: str, **data: Any) -> LogEvent:
        return self.record(stage, Level.REFUSAL, code, message, **data)

    def flag(self, stage: str, code: str, message: str, **data: Any) -> LogEvent:
        return self.record(stage, Level.FLAG, code, message, **data)

    def of_level(self, level: Level) -> list[LogEvent]:
        return [e for e in self._events if e.level is level]

    def as_records(self) -> list[dict[str, Any]]:
        return [e.as_dict() for e in self._events]


@dataclass(frozen=True)
class RunManifest:
    """Everything needed to reproduce a result, and a fingerprint over it.

    ``created_at`` is recorded but excluded from the fingerprint, so two runs over the
    same inputs with the same code fingerprint identically.
    """

    engine_version: str
    python_version: str
    platform: str
    package_versions: dict[str, str]
    registry_version: str
    registry_sha256: str | None
    panel_sha256: str
    panel_shape: tuple[int, int]
    settings: dict[str, Any]
    created_at: str

    @property
    def fingerprint(self) -> str:
        payload = {
            "engine_version": self.engine_version,
            "python_version": self.python_version,
            "package_versions": self.package_versions,
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "panel_sha256": self.panel_sha256,
            "panel_shape": list(self.panel_shape),
            "settings": self.settings,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "package_versions": self.package_versions,
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "panel_sha256": self.panel_sha256,
            "panel_shape": list(self.panel_shape),
            "settings": self.settings,
            "created_at": self.created_at,
            "fingerprint": self.fingerprint,
        }


def build_manifest(
    panel: pd.DataFrame,
    *,
    registry_version: str,
    registry_sha256: str | None,
    settings: dict[str, Any] | None = None,
) -> RunManifest:
    """Fingerprint the code, the registry and the data behind one run."""
    return RunManifest(
        engine_version=__version__,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        package_versions=_package_versions(),
        registry_version=registry_version,
        registry_sha256=registry_sha256,
        panel_sha256=hash_frame(panel),
        panel_shape=(int(panel.shape[0]), int(panel.shape[1])),
        settings=dict(settings or {}),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def hash_frame(frame: pd.DataFrame) -> str:
    """Content hash of a dataframe, stable across runs and row order preserved.

    Column names participate, so a renamed column produces a different hash even when
    the values are identical.
    """
    digest = hashlib.sha256()
    digest.update("|".join(map(str, frame.columns)).encode("utf-8"))
    values = pd.util.hash_pandas_object(frame, index=True).to_numpy()
    digest.update(values.tobytes())
    return digest.hexdigest()


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("numpy", "pandas", "statsmodels", "pydantic", "yaml"):
        try:
            module = __import__(name)
        except ImportError:  # pragma: no cover - all are hard dependencies
            continue
        key = "pyyaml" if name == "yaml" else name
        versions[key] = str(getattr(module, "__version__", "unknown"))
    return versions


__all__ = [
    "Level",
    "LogEvent",
    "RunLog",
    "RunManifest",
    "build_manifest",
    "hash_frame",
]
