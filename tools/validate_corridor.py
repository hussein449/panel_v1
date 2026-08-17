"""Run the pipeline against a named real corridor, and report what separates on it.

    python tools/validate_corridor.py            # the second corridor, NL N201
    python tools/validate_corridor.py B9         # the first one, as a control
    python tools/validate_corridor.py --list

The project has been validated on **one** road since 2026-08-10, and every document in
it says so. This is how a second one gets added and re-run, rather than being a thing
somebody did once in a terminal.

**Why these roads, and why N201 by default.** `STEPS.md` names the criterion for the
second corridor: *"pick one where access density and ramp density separate — the M51
ramp/RAF inversion is not diagnosable on a single corridor."* That is a measurable
property, so the candidates below were measured rather than chosen off a map, and the
numbers each one produced are recorded against it. B9 cannot settle the inversion at all:
one unit of fifty has a ramp anywhere near it.

**The crashes are synthetic and the model output is therefore not a finding.** Nobody
has given us a police extract for these roads. What a run here validates is the
*geometry and adapter path* — fetch, stitch, project, segment, snap, twelve Tier A
factors, fusion, provenance — and the shape of the design matrix that comes out. The
mode banner it prints is a statement about the pipeline, not about the road.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from roadrisk.core.context import FacilityType, Region, RunContext, Severity
from roadrisk.core.diagnostics import compute_vif
from roadrisk.core.engine import assess
from roadrisk.geo import build_corridor_panel
from roadrisk.geo.cache import FileCache
from roadrisk.geo.demo import monthly_periods, synthetic_crashes
from roadrisk.geo.osm import BoundingBox, HttpOverpassClient, fetch_corridor

#: The two columns the second corridor exists to pull apart.
SEPARATION = ("access_density", "ramp_density")


@dataclass(frozen=True)
class Candidate:
    """A real road, and what measuring it actually produced."""

    name: str
    ref: str
    bbox: BoundingBox
    region: Region
    facility_type: FacilityType
    note: str
    chosen: bool = False


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        name="N201",
        ref="N201",
        bbox=BoundingBox(south=52.18, west=4.40, north=52.38, east=5.10),
        region=Region.EUROPE,
        facility_type=FacilityType.RURAL_MULTILANE,
        chosen=True,
        note=(
            "The second corridor. 33.5 km, 67 units, and the best separation of the "
            "candidates: r = -0.06 between access and ramp density, with 18 units "
            "carrying accesses and no ramp, 15 carrying a ramp and no access, and 5 "
            "carrying both. It runs from open polder into the edge of Amsterdam, so "
            "the two mechanisms genuinely occur apart from each other."
        ),
    ),
    Candidate(
        name="B9",
        ref="B9",
        bbox=BoundingBox(south=34.80, west=32.80, north=35.05, east=33.05),
        region=Region.EUROPE,
        facility_type=FacilityType.RURAL_TWO_LANE,
        note=(
            "The first corridor, kept as the control. Limassol into the Troodos: 25 km, "
            "50 units, genuinely windy. It CANNOT separate the two columns — one unit "
            "of fifty has a ramp near it, so ramp_density is very nearly constant and "
            "is dropped before fitting. That is the whole reason a second road was "
            "needed."
        ),
    ),
    Candidate(
        name="A1",
        ref="A1",
        bbox=BoundingBox(south=34.65, west=32.90, north=35.05, east=33.45),
        region=Region.EUROPE,
        facility_type=FacilityType.RURAL_MULTILANE,
        note=(
            "Cyprus motorway, divided — the run reports the excluded carriageway. "
            "68.7 km, 137 units, r = +0.14. Plenty of ramps (48 units) but few "
            "accesses (22), so it separates less cleanly than N201."
        ),
    ),
    Candidate(
        name="JO15",
        ref="15",
        bbox=BoundingBox(south=31.50, west=35.70, north=32.05, east=36.20),
        region=Region.MIDDLE_EAST,
        facility_type=FacilityType.RURAL_MULTILANE,
        note=(
            "Jordan's Desert Highway, and the one in the actual target market. 53 km, "
            "107 units, r = -0.06 — separation nearly as good as N201's. Not chosen "
            "because OSM has no maxspeed along it, so the panel loses speed_limit, the "
            "single most important factor in the registry. Worth revisiting: a corridor "
            "that exposes a coverage gap in the target region is worth more than a "
            "tidy one, once there is crash data to go with it."
        ),
    ),
    Candidate(
        name="N247",
        ref="N247",
        bbox=BoundingBox(south=52.35, west=4.90, north=52.60, east=5.15),
        region=Region.EUROPE,
        facility_type=FacilityType.RURAL_TWO_LANE,
        note=(
            "26 km, 52 units. Rejected: 32 units carry accesses and only 5 carry a "
            "ramp, so it is closer to a second B9 than to a contrast with it."
        ),
    ),
)

BY_NAME = {candidate.name.upper(): candidate for candidate in CANDIDATES}


#: Units a single-mechanism cell needs before the corridor can be said to separate the
#: two columns. A handful of units carrying a ramp and no access is an anecdote; the
#: fit cannot tell the two mechanisms apart from it.
MIN_SINGLE_MECHANISM_UNITS = 5


@dataclass(frozen=True)
class Separation:
    """Whether this corridor can tell the two columns apart, and by how much."""

    measured: bool
    report: str
    separates: bool = False
    near_constant: tuple[str, ...] = ()


def separation(panel, columns=SEPARATION) -> Separation:
    """How independently the two columns vary — the reason this corridor was picked."""
    units = panel.drop_duplicates("unit_id")
    missing = [c for c in columns if c not in units.columns]
    if missing:
        return Separation(
            measured=False,
            report=f"  {', '.join(missing)} absent from this panel — cannot separate.",
        )

    first, second = (units[c].to_numpy(dtype=float) for c in columns)
    lines = []
    for name, values in zip(columns, (first, second), strict=True):
        nonzero = int((values > 0).sum())
        lines.append(
            f"  {name:18s} {values.mean():5.2f}/km mean, {values.max():5.2f} max, "
            f"nonzero on {nonzero}/{len(values)} units"
        )

    if first.std() == 0 or second.std() == 0:
        constant = columns[0] if first.std() == 0 else columns[1]
        lines.append(
            f"  >>> {constant} is CONSTANT on this corridor. The two cannot be told "
            "apart here, and the column will be dropped before fitting."
        )
        return Separation(
            measured=True, report="\n".join(lines), near_constant=(constant,)
        )

    both = int(((first > 0) & (second > 0)).sum())
    first_only = int(((first > 0) & (second == 0)).sum())
    second_only = int(((first == 0) & (second > 0)).sum())
    lines.append(
        f"  >>> r = {float(np.corrcoef(first, second)[0, 1]):+.3f}   "
        f"{columns[0]} only: {first_only}, {columns[1]} only: {second_only}, "
        f"both: {both}"
    )

    thin = tuple(
        name
        for name, count in ((columns[0], first_only), (columns[1], second_only))
        if count < MIN_SINGLE_MECHANISM_UNITS
    )
    separates = not thin
    if separates:
        lines.append(
            "  >>> SEPARATES. Both single-mechanism cells are populated, so a fit given "
            "enough crashes could attribute the two effects independently."
        )
    else:
        lines.append(
            f"  >>> DOES NOT SEPARATE. Fewer than {MIN_SINGLE_MECHANISM_UNITS} units "
            f"carry {' and '.join(thin)} on its own, so nothing here distinguishes the "
            "two mechanisms — whatever a fit reports about them comes from the handful "
            "of units in the other cells."
        )
    return Separation(
        measured=True, report="\n".join(lines), separates=separates, near_constant=thin
    )


def run(candidate: Candidate, *, months: int, cache_dir: str | None) -> int:
    print(f"=== {candidate.name}  (ref={candidate.ref!r}, {candidate.region.value})")
    print(f"    {candidate.note}\n")

    started = time.time()
    try:
        fetched = fetch_corridor(candidate.ref, candidate.bbox)
    except Exception as exc:  # noqa: BLE001 - a validation script reports, never raises
        print(f"  corridor refused: {type(exc).__name__}: {exc}")
        return 1
    print(f"  resolved {len(fetched.points):,} vertices in {time.time() - started:.0f}s")

    periods = monthly_periods(months)
    crashes = synthetic_crashes(fetched.points, periods, n_crashes=600)

    built = build_corridor_panel(
        fetched.points,
        periods=periods,
        name=candidate.name,
        crashes=crashes,
        osm_client=HttpOverpassClient(timeout_s=240.0),
        ref=candidate.ref,
        cache=FileCache(directory=Path(cache_dir)) if cache_dir else None,
    )

    print(f"\n  {built.summary()}")
    if built.snap:
        print(
            f"  snapped {built.snap.n_snapped:,} of {built.snap.n_supplied:,} "
            f"({built.snap.snap_rate:.1%})"
        )
    print(f"  factors resolved: {len(built.factor_columns)}")
    print(f"    {', '.join(sorted(built.factor_columns))}")
    if built.skipped:
        print("  factors refused, with the reason:")
        for factor, adapter, reason in built.skipped:
            print(f"    {factor} ({adapter}): {reason}")

    separated = separation(built.panel)
    print(f"\n  Separation — the reason this corridor was chosen:\n{separated.report}")

    assessment = assess(
        built.panel,
        snap=built.snap,
        context=RunContext(
            facility_type=candidate.facility_type,
            region=candidate.region,
            severity=Severity.ALL,
        ),
    )
    print(f"\n  {assessment.banner}")
    print(f"  rung {assessment.rung.value}, {len(assessment.factor_names)} factors")
    print(f"    {', '.join(assessment.factor_names)}")

    vif = compute_vif(built.panel.drop_duplicates("unit_id")[list(SEPARATION)])
    print(
        "  VIF between the two, as measured on the corridor: "
        + ", ".join(f"{name} {value:.2f}" for name, value in vif.values.items())
        + (
            ""
            if separated.separates
            else "  — and read that as nothing. A column that barely varies is "
            "uncorrelated with everything; VIF near 1 here is absence of data, not "
            "independence."
        )
    )
    _report_ladder(assessment, built, separated)

    if assessment.sign_guard is not None:
        print(
            f"  sign guard: {'clean' if assessment.sign_guard.clean else 'contradictions'}"
            + (
                ""
                if assessment.sign_guard.clean
                else " on " + ", ".join(
                    f.factor for f in assessment.sign_guard.contradictions
                )
                + " — EXPECTED. The synthetic crashes carry no true effect, so every "
                "fitted sign is noise and roughly half of them point the wrong way. "
                "Nothing here is a finding about the road."
            )
        )

    print(
        "\n  Reminder: the crashes are synthetic. This validates the geometry and "
        "adapter path and the shape of the design matrix. It is not a finding about "
        "this road."
    )
    return 0


def _report_ladder(assessment, built, separated: Separation) -> None:
    """Say whether the two columns reached the fit, and why not when they did not."""
    reached = [c for c in SEPARATION if c in assessment.factor_names]
    if len(reached) == 2:
        print(
            "  Both columns reached the fit"
            + (
                ". With real crash data this corridor could diagnose the ramp/access "
                "inversion; on synthetic crashes it cannot, and does not claim to."
                if separated.separates
                else " — but the corridor does not separate them, so a fit here would "
                "be attributing two mechanisms it cannot tell apart."
            )
        )
        return

    absent = sorted(set(SEPARATION) - set(reached))
    print(f"\n  {', '.join(absent)} did NOT reach the fit, and the reason matters:")
    if assessment.descent_receipt:
        for line in assessment.descent_receipt.splitlines():
            print(f"    {line}")

    resolved = set(built.factor_columns)
    priorities = {
        factor.name: factor.drop_priority
        for factor in assessment.available_factors
        if factor.name in resolved
    }
    ranked = sorted(priorities.items(), key=lambda pair: -pair[1])
    for name in absent:
        if name not in priorities:
            continue
        position = [n for n, _ in ranked].index(name) + 1
        verdict = (
            "The corridor separated it cleanly and the ladder shed it anyway"
            if separated.separates
            else "This corridor could not have separated it in any case"
        )
        print(
            f"    '{name}' is {position} of {len(ranked)} by the registry's declared "
            f"drop_priority ({priorities[name]}). {verdict}. Separation in the data is "
            "necessary and not sufficient — the crash count has to buy enough terms to "
            "carry both, and the registry has to rank it inside them."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "corridor",
        nargs="?",
        default=None,
        help="Which corridor to run. Defaults to the chosen second corridor.",
    )
    parser.add_argument("--list", action="store_true", help="List the candidates.")
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument(
        "--cache", default=None, help="Cache directory, so a re-run is cheap."
    )
    args = parser.parse_args()

    if args.list:
        for candidate in CANDIDATES:
            marker = "*" if candidate.chosen else " "
            print(f" {marker} {candidate.name:6s} {candidate.region.value:12s} {candidate.note}")
        return 0

    if args.corridor is None:
        candidate = next(c for c in CANDIDATES if c.chosen)
    elif args.corridor.upper() in BY_NAME:
        candidate = BY_NAME[args.corridor.upper()]
    else:
        print(f"Unknown corridor {args.corridor!r}. Known: {', '.join(BY_NAME)}")
        return 2

    return run(candidate, months=args.months, cache_dir=args.cache)


if __name__ == "__main__":
    sys.exit(main())
