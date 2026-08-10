"""How total crashes divide between crash types.

This is what makes the un-squashing possible. Published weights are **crash-type
specific**: iRAP prices grade for run-off and head-on crashes, and street lighting for
intersection crashes. Summing them into one score treats a run-off-only weight as
though it moved every crash on the road, which overstates it.

With a crash mix the engine can score each crash type separately and then combine:

    combined = sum over types of  share[type] * exp(log_score[type])

A weight scoped to one type moves only that type's score, and the share dilutes it
correctly. A weight scoped ``total`` enters every type, so it survives the combination
at full strength — meaning a registry of only total-scope weights produces exactly the
score it did before. The change is a strict improvement, not a re-scaling.
"""

from __future__ import annotations

from dataclasses import dataclass

from roadrisk.core.errors import RoadRiskError
from roadrisk.core.registry.schema import CrashScope

#: The crash types a score is decomposed into. ``TOTAL`` is deliberately absent — it is
#: a marker meaning "applies to every type", not a type of its own.
BUCKETS: tuple[CrashScope, ...] = (
    CrashScope.RUN_OFF_HEAD_ON,
    CrashScope.INTERSECTION,
    CrashScope.PEDESTRIAN,
    CrashScope.OTHER,
)

_TOLERANCE = 1e-6


@dataclass(frozen=True)
class CrashMix:
    """The share of crashes falling into each crash type, and where it came from."""

    shares: dict[CrashScope, float]
    source: str

    def __post_init__(self) -> None:
        missing = [b for b in BUCKETS if b not in self.shares]
        if missing:
            raise RoadRiskError(
                "crash mix is missing share(s) for: "
                + ", ".join(b.value for b in missing)
                + ". Every crash type must be accounted for, or the combination "
                "silently loses crashes."
            )
        extra = [k for k in self.shares if k not in BUCKETS]
        if extra:
            raise RoadRiskError(
                "crash mix declares share(s) for non-bucket type(s): "
                + ", ".join(str(k) for k in extra)
            )
        negative = [b.value for b in BUCKETS if self.shares[b] < 0]
        if negative:
            raise RoadRiskError(
                f"crash mix has negative share(s) for: {', '.join(negative)}"
            )
        total = sum(self.shares[b] for b in BUCKETS)
        if abs(total - 1.0) > _TOLERANCE:
            raise RoadRiskError(
                f"crash mix shares sum to {total:.6f}, not 1.0. Shares are a "
                "partition of total crashes — they cannot overlap or leave a gap."
            )

    def share(self, bucket: CrashScope) -> float:
        return self.shares[bucket]

    def describe(self) -> str:
        return " · ".join(
            f"{b.value} {self.shares[b]:.1%}" for b in BUCKETS if self.shares[b] > 0
        )

    def as_dict(self) -> dict[str, float | str]:
        payload: dict[str, float | str] = {
            b.value: round(self.shares[b], 6) for b in BUCKETS
        }
        payload["source"] = self.source
        return payload


# ---------------------------------------------------------------------------
# The cited default
# ---------------------------------------------------------------------------
#
# AASHTO HSM Table 10-4, "Default Distribution by Collision Type for Specific Crash
# Severity Levels on Rural Two-Lane, Two-Way Roadway Segments", Fatal-and-Injury
# column. Based on HSIS data for Washington State, 2002-2006.
#
#   run_off_head_on : ran off road 54.5 + overturned 3.7 + head-on 3.4
#                     + opposite-direction sideswipe (70% of 3.8) 2.66   = 64.26
#   intersection    : angle collision                                    = 10.00
#   pedestrian      : collision with pedestrian 0.7 + with bicycle 0.4   =  1.10
#   other           : animal 3.8 + other single-vehicle 0.7 + rear-end 16.4
#                     + same-direction sideswipe (30% of 3.8) 1.14
#                     + other multiple-vehicle 2.6                       = 24.64
#                                                                 total  = 100.00
#
# The Fatal-and-Injury column is used rather than All-Severity because the registry's
# speed weights are injury-specific and a panel counting all severities would need its
# own mix anyway.

HSM_RURAL_TWO_LANE_INJURY = CrashMix(
    shares={
        CrashScope.RUN_OFF_HEAD_ON: 0.6426,
        CrashScope.INTERSECTION: 0.1000,
        CrashScope.PEDESTRIAN: 0.0110,
        CrashScope.OTHER: 0.2464,
    },
    source=(
        "AASHTO HSM Table 10-4, default distribution by collision type for rural "
        "two-lane two-way roadway segments, fatal-and-injury column (HSIS Washington "
        "2002-2006). Run-off/head-on aggregates ran-off-road, overturned, head-on and "
        "opposite-direction sideswipe; intersection uses angle collisions; pedestrian "
        "aggregates pedestrian and bicycle collisions."
    ),
)

#: Used when the caller declares nothing. Carries the same regional transfer problem as
#: any other HSM number, and the engine says so.
DEFAULT_CRASH_MIX = HSM_RURAL_TWO_LANE_INJURY


def uniform_mix() -> CrashMix:
    """An explicitly uninformative mix, for when no distribution is defensible.

    Not a default. It exists so a caller who genuinely has no basis for a split can say
    so out loud rather than borrowing Washington State's.
    """
    share = 1.0 / len(BUCKETS)
    return CrashMix(
        shares=dict.fromkeys(BUCKETS, share),
        source="Uniform — no crash type distribution was available or defensible.",
    )


__all__ = [
    "BUCKETS",
    "DEFAULT_CRASH_MIX",
    "HSM_RURAL_TWO_LANE_INJURY",
    "CrashMix",
    "uniform_mix",
]
