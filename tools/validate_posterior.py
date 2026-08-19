"""Check the fast Bayesian rung against a slow one that cannot be wrong in the same way.

    python tools/validate_posterior.py

The shipped path is a Laplace approximation with an importance correction. It takes
seconds, and its own k-hat statistic polices it on every run. But k-hat is a *good*
meter, not a perfect one: it can pass an approximation that is mildly wrong, because it
measures whether the importance weights behave, not whether the answer is right.

So this runs both rungs on the same planted panel and puts them side by side. The MCMC
rung is slow — minutes — and wrong in completely different ways from a Gaussian
approximation, which is exactly what makes it worth waiting for. If the two agree, the
fast one can be trusted for the same reason `tools/validate_coverage.py` let step 3.1
claim its intervals were honest: it was measured, not asserted.

Both are then checked against the planted truth, which neither of them has seen.
"""

from __future__ import annotations

import argparse
import sys
import time

import statsmodels.api as sm

from roadrisk.core.contract import prepare_panel
from roadrisk.core.models.bayes import Method, fit_bayesian_glmm, fit_mcmc_reference
from roadrisk.core.registry import load_registry
from roadrisk.core.transforms import build_design
from roadrisk.demo import TRUE_EFFECTS, synthetic_panel

PLANTED_SIGMA = 0.5
PLANTED_ALPHA = 0.6

#: Three factors, which keeps the MCMC reference to a few minutes rather than a quarter
#: of an hour. Width is not the constraint on the fast rung — quadrature accuracy was,
#: and the node ladder handles it — but the sampler this checks against is slow in the
#: ordinary way, and it is the thing being waited for.
NARROW = (
    "unit_id",
    "period",
    "time_slot",
    "n_crashes",
    "length_km",
    "duration_hours",
    "curve_density",
    "junction_density",
    "speed_limit",
)


def build(units: int, periods: int):
    panel = synthetic_panel(
        n_units=units,
        n_periods=periods,
        seed=7,
        unit_dispersion=PLANTED_SIGMA,
        alpha=PLANTED_ALPHA,
    )[list(NARROW)]
    frame, _ = prepare_panel(panel)
    design = build_design(frame, load_registry().available(frame.columns))

    exog = sm.add_constant(design.astype(float))
    nb = sm.NegativeBinomialP(
        frame["n_crashes"].to_numpy(float),
        exog,
        p=2,
        offset=frame["log_exposure"].to_numpy(float),
    ).fit(disp=0, maxiter=200)
    start = {"intercept": float(nb.params["const"]), "alpha": float(nb.params["alpha"])}
    start.update({c: float(nb.params[c]) for c in design.columns})
    return frame, design, start


def run(frame, design, start, *, reference: bool, draws: int, nodes: int | None = None):
    """The shipped path, or the slow sampler it has to agree with.

    ``nodes`` matters more than it looks. Quadrature accuracy defines *which* marginal
    posterior is being approximated, so a reference run at a different node count is
    answering a slightly different question and any disagreement is partly its own
    doing. The reference is therefore pinned to whatever the fast rung settled on.
    """
    started = time.time()
    fitter = fit_mcmc_reference if reference else fit_bayesian_glmm
    extra = (
        {"draws": draws, "n_nodes": nodes} if reference else {"allow_mcmc": False}
    )
    fit = fitter(
        frame["n_crashes"],
        design,
        frame["log_exposure"],
        frame["unit_id"],
        start=start,
        seed=3,
        **extra,
    )
    return fit, time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", type=int, default=60)
    parser.add_argument("--periods", type=int, default=18)
    parser.add_argument("--draws", type=int, default=16000)
    args = parser.parse_args()

    frame, design, start = build(args.units, args.periods)
    print(
        f"{len(frame):,} rows, {frame['unit_id'].nunique()} units, "
        f"{len(design.columns)} factors\n"
    )

    fast, fast_seconds = run(frame, design, start, reference=False, draws=args.draws)
    print(f"Laplace + importance sampling: {fast_seconds:.1f}s")
    for line in fast.descent:
        print(f"  {line}")
    if not fast.converged:
        print(
            "\nThe fast rung refused on this panel, which is a legitimate outcome and "
            "not something to work around. Try fewer factors or more units."
        )
        return 1

    print(f"\nMCMC reference, {args.draws:,} draws — this is the slow part…")
    slow, slow_seconds = run(
        frame, design, start, reference=True, draws=args.draws, nodes=fast.n_nodes
    )
    print(f"  {slow_seconds:.0f}s, method={slow.method.value}")
    for line in slow.descent:
        print(f"  {line}")
    if not slow.converged or slow.method is not Method.MCMC:
        print("\nThe reference did not converge, so there is nothing to compare against.")
        return 1

    print(
        f"\n{'term':16s} {'planted':>8s} {'MCMC':>9s} {'Laplace':>9s} {'diff':>7s}  "
        f"{'Laplace 95%':>20s}  truth"
    )
    worst = 0.0
    missed = 0
    pairs = [
        (c.name, c, slow.coefficient(c.name)) for c in fast.coefficients
    ] + [
        ("sigma_u", fast.sigma_u, slow.sigma_u),
        ("alpha", fast.alpha, slow.alpha),
    ]
    for name, quick, reference in pairs:
        if quick is None or reference is None:
            continue
        planted = TRUE_EFFECTS.get(
            name, PLANTED_SIGMA if name == "sigma_u" else PLANTED_ALPHA
        )
        difference = quick.mean - reference.mean
        worst = max(worst, abs(difference))
        inside = quick.hdi_low <= planted <= quick.hdi_high
        missed += 0 if inside else 1
        print(
            f"{name:16s} {planted:+8.3f} {reference.mean:+9.4f} {quick.mean:+9.4f} "
            f"{difference:+7.3f}  [{quick.hdi_low:+.3f}, {quick.hdi_high:+.3f}]  "
            f"{'IN ' if inside else 'OUT'}"
        )

    speedup = slow_seconds / fast_seconds if fast_seconds else float("nan")
    print(
        f"\nLargest disagreement between the two rungs: {worst:.4f}\n"
        f"Planted values outside the fast rung's 95% interval: {missed} of {len(pairs)}\n"
        f"The fast rung was {speedup:.0f}x quicker "
        f"({fast_seconds:.1f}s against {slow_seconds:.0f}s)."
    )
    if worst > 0.05:
        print(
            "\nThat disagreement is large enough to care about. The fast rung's k-hat "
            "passed, so this would be a case k-hat did not catch — worth recording."
        )
        return 1
    print(
        "\nThe two agree. The fast rung's credible intervals can be read as the slow "
        "one's, which is what makes shipping the approximation defensible."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
