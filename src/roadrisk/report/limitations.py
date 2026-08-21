"""Step 4.6 — the limitations page, assembled from what the run actually did.

**It is data, not prose.** Written as paragraphs inside the layout it would be a thing
somebody could quietly edit out, and it would go stale the moment the engine changed.
Built from the payload it cannot be removed without a code change, it cannot describe a
run other than the one it came from, and a new failure mode reaches the page the day it
is implemented rather than the day someone remembers to write it down.

Almost all of it is already on the assessment: the checks that failed, the terms that
were dropped, the factors that were missing, the receipts, the validation outcome, the
crash mix. This module reads those and says what each one costs the reader.

**There is no way to switch it off.** `collect_limitations` takes no flag, returns a
non-empty list for every run — a corridor with nothing else wrong still carries the
standing caveats that apply to every assessment this tool produces — and the page
renders it unconditionally.

Severity is about what a limitation costs you, not how bad it sounds:

* ``material`` — changes what you may conclude. Read these before the numbers.
* ``caveat`` — qualifies a number without invalidating it.
* ``context`` — worth knowing, changes nothing on its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MATERIAL = "material"
CAVEAT = "caveat"
CONTEXT = "context"

#: Cache entries older than this are called out by age rather than merely counted.
STALE_CACHE_DAYS = 180.0

#: Below this share of crashes landing on the corridor, the panel is describing a
#: different road from the one the crashes happened on.
LOW_SNAP_RATE = 0.9


@dataclass(frozen=True)
class Limitation:
    """One thing this assessment cannot tell you, and why."""

    code: str
    severity: str
    title: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
        }


def collect_limitations(
    assessment: Mapping[str, Any],
    corridor: Mapping[str, Any] | None = None,
) -> list[Limitation]:
    """Everything this run cannot support, read off the run itself.

    Args:
        assessment: The payload from :meth:`roadrisk.core.Assessment.as_dict`.
        corridor: The payload from :meth:`roadrisk.geo.CorridorPanel.as_dict`, when the
            panel came from geography.

    Returns:
        Limitations, most material first. Never empty — the standing caveats apply to
        every assessment this tool produces, so a clean run still carries them.
    """
    found: list[Limitation] = []
    for collect in (
        _mode,
        _receipts,
        _checks,
        _factors,
        _sign_guard,
        _validation,
        _evidence,
    ):
        found.extend(collect(assessment))

    if corridor is not None:
        found.extend(_geography(corridor))
        found.extend(_tiers(corridor))

    found.extend(_standing(assessment, corridor))

    order = {MATERIAL: 0, CAVEAT: 1, CONTEXT: 2}
    return sorted(found, key=lambda item: order.get(item.severity, 3))


def as_dicts(limitations: Sequence[Limitation]) -> list[dict[str, str]]:
    return [item.as_dict() for item in limitations]


# ---- what the mode itself costs ----------------------------------------------


def _mode(assessment: Mapping[str, Any]) -> list[Limitation]:
    if assessment.get("mode") != "B":
        return []
    return [
        Limitation(
            code="mode_b_is_a_ranking",
            severity=MATERIAL,
            title="These scores are a ranking, not a prediction",
            detail=(
                "This assessment ran in Mode B, which scores each segment from weights "
                "published in the road safety literature rather than from crashes on "
                "this road. It says which segments are worse than which. It does not "
                "estimate how many crashes any of them will have, and no number here "
                "may be read as one — the scores have no units and do not compare "
                "across corridors."
            ),
        )
    ]


def _receipts(assessment: Mapping[str, Any]) -> list[Limitation]:
    receipts = assessment.get("receipts") or {}
    found: list[Limitation] = []

    if receipts.get("refusal"):
        found.append(
            Limitation(
                code="mode_a_refused",
                severity=MATERIAL,
                title="A crash model could not be fitted to this data",
                detail=str(receipts["refusal"]),
            )
        )
    if receipts.get("descent"):
        found.append(
            Limitation(
                code="specification_reduced",
                severity=MATERIAL,
                title="The model was fitted with fewer factors than were available",
                detail=(
                    f"{receipts['descent']} Every dropped factor is one whose effect "
                    "this assessment cannot separate from the others, so its absence "
                    "does not mean it does not matter."
                ),
            )
        )
    if receipts.get("index_refusal"):
        found.append(
            Limitation(
                code="index_refused",
                severity=MATERIAL,
                title="The fallback score could not be produced either",
                detail=str(receipts["index_refusal"]),
            )
        )
    return found


# ---- what the gates said ------------------------------------------------------


def _checks(assessment: Mapping[str, Any]) -> list[Limitation]:
    found: list[Limitation] = []
    for check in assessment.get("checks") or []:
        status = check.get("status")
        if status == "failed":
            found.append(
                Limitation(
                    code=f"check_failed_{check.get('number')}",
                    severity=MATERIAL if check.get("failure_type") == "hard" else CAVEAT,
                    title=f"Check {check.get('number')} failed — {check.get('name')}",
                    detail=str(check.get("message", "")),
                )
            )
        elif status == "skipped":
            found.append(
                Limitation(
                    code=f"check_skipped_{check.get('number')}",
                    severity=CONTEXT,
                    title=f"Check {check.get('number')} could not be run — "
                    f"{check.get('name')}",
                    detail=(
                        f"{check.get('message', '')} A check that did not run is not a "
                        "check that passed."
                    ),
                )
            )
    return found


# ---- what was left out of the model -------------------------------------------


def _factors(assessment: Mapping[str, Any]) -> list[Limitation]:
    factors = assessment.get("factors") or {}
    found: list[Limitation] = []

    missing = factors.get("missing") or []
    if missing:
        names = ", ".join(sorted(str(item.get("name")) for item in missing))
        found.append(
            Limitation(
                code="factors_absent",
                severity=CAVEAT,
                title=f"{len(missing)} factor(s) were not in the data at all",
                detail=(
                    f"No column was supplied for: {names}. Each is a term the model "
                    "could not carry, so its effect is either absent from the result or "
                    "absorbed by whichever factor it correlates with. The registry's "
                    "note on what each absence costs travels in the run record."
                ),
            )
        )

    dropped = factors.get("dropped_for_collinearity") or []
    if dropped:
        found.append(
            Limitation(
                code="factors_collinear",
                severity=CAVEAT,
                title="Some factors were too alike to separate",
                detail=(
                    f"{', '.join(dropped)} moved together closely enough that the model "
                    "could not tell their effects apart, so one of each pair was "
                    "dropped. The one that stayed is carrying the effect of both."
                ),
            )
        )

    constant = factors.get("constant") or []
    if constant:
        found.append(
            Limitation(
                code="factors_constant",
                severity=CONTEXT,
                title="Some factors were the same everywhere on this corridor",
                detail=(
                    f"{', '.join(constant)} did not vary along the corridor, so nothing "
                    "can be learned about them here. That is a property of this road, "
                    "not evidence that they do not matter."
                ),
            )
        )
    return found


def _sign_guard(assessment: Mapping[str, Any]) -> list[Limitation]:
    guard = assessment.get("sign_guard") or {}
    findings = [f for f in guard.get("findings") or [] if f.get("contradicts")]
    if not findings:
        return []

    names = ", ".join(str(f.get("factor")) for f in findings)
    return [
        Limitation(
            code="sign_contradiction",
            severity=MATERIAL,
            title="A factor's effect came out opposite to what the evidence expects",
            detail=(
                f"{names} fitted with the opposite sign to the one the literature "
                "predicts. That usually means it is standing in for something else on "
                "this corridor rather than causing anything, and it is not "
                "interpretable as a cause. It is reported rather than removed, because "
                "hiding it would hide the finding."
            ),
        )
    ]


# ---- whether it predicts anything ---------------------------------------------


def _validation(assessment: Mapping[str, Any]) -> list[Limitation]:
    validation = assessment.get("validation")
    if not validation:
        return []

    if not validation.get("available"):
        return [
            Limitation(
                code="not_validated",
                severity=MATERIAL,
                title="The model was never tested on road it had not seen",
                detail=(
                    str(validation.get("refusal") or "")
                    + " Without a held-out test there is no evidence that this model "
                    "predicts anything beyond the data it was fitted to."
                ).strip(),
            )
        ]

    found: list[Limitation] = []
    if not validation.get("passed"):
        found.append(
            Limitation(
                code="validation_failed",
                severity=MATERIAL,
                title="The model did not predict held-out road well",
                detail=(
                    "Refitted with stretches of the corridor held back, the model did "
                    "not reproduce what happened on them. Treat the ranking as "
                    "indicative and the predicted counts as weak."
                ),
            )
        )
    notes = [str(note) for note in validation.get("notes") or []]
    if notes:
        found.append(
            Limitation(
                code="validation_note",
                severity=CAVEAT,
                title="How the validation was set up",
                detail=" ".join(notes),
            )
        )
    return found


def _evidence(assessment: Mapping[str, Any]) -> list[Limitation]:
    """Caveats that come from the body of evidence rather than from this corridor."""
    found: list[Limitation] = []

    context = assessment.get("context") or {}
    if context.get("crash_mix_is_default"):
        found.append(
            Limitation(
                code="default_crash_mix",
                severity=CAVEAT,
                title="The split of crashes by type was assumed, not measured",
                detail=(
                    "No local breakdown of crashes by type was supplied, so a published "
                    "distribution was used. It carries the same transfer problem as any "
                    "figure borrowed from another country's roads. Supplying a local "
                    "split is a cheap improvement."
                ),
            )
        )
    if not context.get("declared"):
        found.append(
            Limitation(
                code="context_undeclared",
                severity=CONTEXT,
                title="The corridor type, region and crash severity were not declared",
                detail=(
                    "Only evidence with no stated scope could be used. Declaring what "
                    "kind of road this is, where it is and which crashes were counted "
                    "would admit better-matched published weights."
                ),
            )
        )

    posterior = assessment.get("posterior")
    if posterior and not posterior.get("converged"):
        found.append(
            Limitation(
                code="posterior_refused",
                severity=CAVEAT,
                title="A Bayesian fit was attempted and could not be believed",
                detail=(
                    "The approximation was refused and the sampler that replaced it did "
                    "not converge, so nothing from it is reported and the intervals in "
                    "this report are the frequentist ones. They are narrower than a "
                    "credible interval would have been, because they do not carry the "
                    "uncertainty in how much segments differ from one another."
                ),
            )
        )

    index = assessment.get("index") or {}
    families = {str(term.get("family")) for term in index.get("terms") or []}
    factors_used = set(assessment.get("factors", {}).get("in_model") or [])
    factors_used |= {str(term.get("factor")) for term in index.get("terms") or []}

    if "hsm" in families:
        found.append(
            Limitation(
                code="hsm_edition_unpinned",
                severity=CAVEAT,
                title="The American evidence is not pinned to a verifiable edition",
                detail=(
                    "Some weights come from the AASHTO Highway Safety Manual. They were "
                    "read from the draft text of the 2nd edition and are checked against "
                    "its published worked examples, but the 2024 edition changed the "
                    "relevant parts and nothing here is tied to a licensed copy. The "
                    "values are defensible; the citation is not yet closed."
                ),
            )
        )
    if "speed_limit" in factors_used:
        found.append(
            Limitation(
                code="posted_speed_stands_in",
                severity=CAVEAT,
                title="Posted speed is standing in for the speed people drive",
                detail=(
                    "The published relationship between speed and crashes is defined on "
                    "operating speed — what traffic actually does — and the value used "
                    "here is the posted limit. Where the two differ, and they routinely "
                    "do, this factor's contribution is wrong by an unknown amount. One "
                    "speed survey on this corridor would remove the largest known "
                    "weakness in the score."
                ),
            )
        )
    return found


# ---- what the geography could and could not supply -----------------------------


def _geography(corridor: Mapping[str, Any]) -> list[Limitation]:
    found: list[Limitation] = []

    snap = corridor.get("snap")
    if snap and snap.get("n_supplied"):
        rate = float(snap.get("snap_rate") or 0.0)
        if rate < LOW_SNAP_RATE:
            reasons = ", ".join(
                f"{reason.replace('_', ' ')} ({n})"
                for reason, n in (snap.get("dropped_reasons") or {}).items()
            )
            found.append(
                Limitation(
                    code="crashes_dropped",
                    severity=MATERIAL if rate < 0.8 else CAVEAT,
                    title=(
                        f"{snap.get('n_dropped')} of {snap.get('n_supplied')} crashes "
                        "did not land on this corridor"
                    ),
                    detail=(
                        f"Only {rate:.0%} of the supplied crashes could be placed on the "
                        f"road. Dropped for: {reasons}. Every count below is of the "
                        "crashes that were placed, not of the crashes that happened."
                    ),
                )
            )

    geometry = [
        str(warning) for warning in corridor.get("corridor", {}).get("warnings") or []
    ]
    if geometry:
        found.append(
            Limitation(
                code="corridor_geometry",
                severity=CAVEAT,
                title="The centreline has a structural problem",
                detail=" ".join(geometry),
            )
        )

    warnings = [str(warning) for warning in corridor.get("warnings") or []]
    if warnings:
        found.append(
            Limitation(
                code="pipeline_warning",
                severity=CONTEXT,
                title="Notes from building the panel",
                detail=" ".join(warnings),
            )
        )

    cache = corridor.get("cache") or {}
    if cache.get("used") and float(cache.get("oldest_days") or 0.0) >= STALE_CACHE_DAYS:
        found.append(
            Limitation(
                code="stale_cache",
                severity=CAVEAT,
                title="Some source data was served from a cache and is old",
                detail=(
                    f"The oldest cached answer used here is "
                    f"{float(cache['oldest_days']):.0f} days old. The road may have "
                    "changed since it was fetched."
                ),
            )
        )
    return found


def _tiers(corridor: Mapping[str, Any]) -> list[Limitation]:
    """Tier B and below are inferred, and the report should not blur that."""
    provenance = corridor.get("provenance") or []
    inferred = [row for row in provenance if str(row.get("tier")) in {"B", "C", "D"}]
    thin = [
        row
        for row in provenance
        if float(row.get("confidence_high") or 0.0) < 0.5
        and float(row.get("coverage") or 0.0) > 0
    ]
    found: list[Limitation] = []

    if inferred:
        names = ", ".join(str(row.get("factor")) for row in inferred)
        found.append(
            Limitation(
                code="inferred_factors",
                severity=CAVEAT,
                title="Some factors were inferred rather than measured",
                detail=(
                    f"{names} came from Tier B or lower sources — estimated from other "
                    "data rather than observed on the road. They are usable and they "
                    "are not measurements."
                ),
            )
        )
    if thin:
        names = ", ".join(str(row.get("factor")) for row in thin)
        found.append(
            Limitation(
                code="low_confidence_factors",
                severity=CAVEAT,
                title="Some factors were carried rather than measured on most segments",
                detail=(
                    f"On more than half the corridor, {names} was filled in from a "
                    "neighbouring value rather than resolved for that segment."
                ),
            )
        )
    return found


# ---- the ones that apply to every run this tool produces ----------------------


def _standing(
    assessment: Mapping[str, Any], corridor: Mapping[str, Any] | None
) -> list[Limitation]:
    """Caveats that are true of the method, not of this corridor.

    These are why the list is never empty. A run with nothing wrong with it is still a
    statistical association on one road, and a report that said nothing at all under
    "limitations" would be making a claim it cannot support.
    """
    found = [
        Limitation(
            code="association_not_cause",
            severity=CONTEXT,
            title="This is an association, not a cause",
            detail=(
                "Segments with a given feature had more crashes than segments without "
                "it. That is not the same as the feature causing them, and it is not a "
                "forecast of what changing it would do. Treat the ranking as where to "
                "look, and a site inspection as what to do about it."
            ),
        ),
        Limitation(
            code="one_corridor",
            severity=CONTEXT,
            title="Everything here comes from one road",
            detail=(
                "The model was fitted on this corridor alone. Nothing in it transfers "
                "to another road without being refitted there, and a factor that "
                "matters elsewhere may be invisible here simply because this road does "
                "not vary in it."
            ),
        ),
    ]

    if corridor is None:
        found.append(
            Limitation(
                code="panel_supplied",
                severity=CONTEXT,
                title="The panel was supplied rather than built from the road",
                detail=(
                    "This assessment did not build the panel from geography, so it "
                    "cannot vouch for how the segments were cut, how the crashes were "
                    "placed on them, or where the factor values came from. Provenance "
                    "and licensing are unknown to it."
                ),
            )
        )
    return found


__all__ = [
    "CAVEAT",
    "CONTEXT",
    "MATERIAL",
    "Limitation",
    "as_dicts",
    "collect_limitations",
]
