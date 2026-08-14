"""Are the intervals honest? Measure coverage against known planted truth.

A 95% confidence interval makes a testable promise: across many datasets drawn from the
same truth, the true value lands inside it 95% of the time. Under that, the model is
overconfident — and by exactly how much is measurable, because the synthetic panel's
coefficients are planted rather than estimated.

    python tools/validate_coverage.py

This is the experiment that answers "did the standard errors widen because the data says
so, or because we broke something". It needs no network and takes a few seconds.
"""

from __future__ import annotations

import sys
import time

import numpy as np

from roadrisk.core.contract import (
    CRASH_COLUMN,
    LOG_EXPOSURE_COLUMN,
    UNIT_COLUMN,
    prepare_panel,
)
from roadrisk.core.models.glm import fit_negative_binomial, fit_negative_binomial_panel
from roadrisk.core.registry import load_registry
from roadrisk.core.transforms import build_design
from roadrisk.demo import TRUE_EFFECTS, synthetic_panel

REPLICATES = 60
N_UNITS, N_PERIODS = 80, 12
NOMINAL = 0.95


def coverage(unit_dispersion: float, replicates: int = REPLICATES):
    """How often each model's 95% interval actually contains the planted truth."""
    registry = load_registry()
    naive_hits: dict[str, int] = {}
    clustered_hits: dict[str, int] = {}
    widths: dict[str, list[float]] = {}

    for seed in range(replicates):
        panel = synthetic_panel(
            n_units=N_UNITS,
            n_periods=N_PERIODS,
            seed=1000 + seed,
            unit_dispersion=unit_dispersion,
        )
        prepared, _ = prepare_panel(panel)
        design = build_design(prepared, registry.available(prepared.columns))
        counts = prepared[CRASH_COLUMN]
        offset = prepared[LOG_EXPOSURE_COLUMN]

        naive = fit_negative_binomial(counts, design, offset)
        clustered = fit_negative_binomial_panel(
            counts, design, offset, prepared[UNIT_COLUMN]
        )
        if not (naive.converged and clustered.converged):
            continue

        for name, truth in TRUE_EFFECTS.items():
            a, b = naive.coefficient(name), clustered.coefficient(name)
            if a is None or b is None:
                continue
            naive_hits[name] = naive_hits.get(name, 0) + (a.ci_low <= truth <= a.ci_high)
            clustered_hits[name] = clustered_hits.get(name, 0) + (
                b.ci_low <= truth <= b.ci_high
            )
            widths.setdefault(name, []).append(
                (b.ci_high - b.ci_low) / (a.ci_high - a.ci_low)
            )

    return naive_hits, clustered_hits, widths


def report(label: str, unit_dispersion: float) -> None:
    started = time.time()
    naive, clustered, widths = coverage(unit_dispersion)

    print(f"\n=== {label}  (unit_dispersion={unit_dispersion})")
    print(f"{'factor':18s} {'planted':>8s} {'rung 1':>8s} {'rung 2':>8s} {'wider':>7s}")
    for name, truth in TRUE_EFFECTS.items():
        if name not in widths:
            continue
        n = len(widths[name])
        print(
            f"{name:18s} {truth:+8.2f} {naive[name] / n:7.0%} "
            f"{clustered[name] / n:8.0%} {np.mean(widths[name]):6.2f}x"
        )

    total = sum(len(v) for v in widths.values())
    naive_rate = sum(naive.values()) / total
    clustered_rate = sum(clustered.values()) / total
    print(
        f"{'OVERALL':18s} {'':8s} {naive_rate:7.0%} {clustered_rate:8.0%}"
        f"          [{time.time() - started:.0f}s]"
    )
    print(
        f"   both claim {NOMINAL:.0%}. rung 1 is wrong "
        f"{1 - naive_rate:.0%} of the time while promising {1 - NOMINAL:.0%}; "
        f"rung 2 is wrong {1 - clustered_rate:.0%} of the time."
    )


def main() -> int:
    print(
        f"{REPLICATES} panels per condition, {N_UNITS} segments x {N_PERIODS} periods.\n"
        "A 95% interval should contain the planted truth 95% of the time."
    )
    report("segments all alike — nothing to correct", 0.0)
    report("segments have persistent character — as real ones do", 0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
