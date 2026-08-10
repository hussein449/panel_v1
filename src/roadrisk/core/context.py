"""What kind of corridor is being assessed, and against what crash data.

Before this existed, the engine applied whatever weight the registry held to whatever
corridor it was given, and said nothing. A weight estimated on US rural two-lane
highways from injury-crash data was applied unchanged to an urban arterial in Beirut
counting fatal crashes. That is the single largest error source in Mode B and it was
invisible.

Declaring the context does not make a weight correct. It makes a *mismatch visible* —
the engine can then prefer a better-matched weight, warn when it has to reach, and put
both facts in the report.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from roadrisk.core.contract import LENGTH_COLUMN
from roadrisk.core.crashmix import DEFAULT_CRASH_MIX, CrashMix
from roadrisk.core.registry.schema import FacilityType, Region, Severity


@dataclass(frozen=True)
class RunContext:
    """The declared and measured context of one assessment.

    ``facility_type``, ``region`` and ``severity`` are declared by the caller — nobody
    can infer them from a panel. ``segment_length_km`` and ``reference_aadt`` are
    *measured* where possible, so the assumption checks they feed cannot be gamed by
    declaring a convenient value.
    """

    facility_type: FacilityType = FacilityType.ANY
    region: Region = Region.GLOBAL
    severity: Severity = Severity.ALL
    crash_mix: CrashMix = DEFAULT_CRASH_MIX
    segment_length_km: float | None = None
    reference_aadt: float | None = None

    @property
    def is_declared(self) -> bool:
        """False when the caller told us nothing about the corridor."""
        return not (
            self.facility_type is FacilityType.ANY
            and self.region is Region.GLOBAL
            and self.severity is Severity.ALL
        )

    def describe(self) -> str:
        return (
            f"{self.facility_type.value} · {self.region.value} · "
            f"{self.severity.value} crashes"
        )

    @property
    def uses_default_crash_mix(self) -> bool:
        return self.crash_mix is DEFAULT_CRASH_MIX

    def measured_from(self, panel: pd.DataFrame) -> RunContext:
        """Fill the measurable fields from the panel, leaving declarations alone."""
        if LENGTH_COLUMN not in panel.columns:
            return self
        median_length = float(panel[LENGTH_COLUMN].median())
        return RunContext(
            facility_type=self.facility_type,
            region=self.region,
            severity=self.severity,
            crash_mix=self.crash_mix,
            segment_length_km=median_length,
            reference_aadt=self.reference_aadt,
        )

    def actuals(self) -> dict[str, float]:
        """Measured run conditions, keyed to match a weight's ``assumes``."""
        values: dict[str, float] = {}
        if self.segment_length_km is not None:
            values["segment_length_km"] = self.segment_length_km
        if self.reference_aadt is not None:
            values["reference_aadt"] = self.reference_aadt
        return values


__all__ = ["RunContext"]
