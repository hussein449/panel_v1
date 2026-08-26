"""What the client owes the people whose data this used.

Every value that reaches the report arrives with a licence attached, because
:class:`~roadrisk.core.registry.schema.Licence` travels on
:class:`~roadrisk.geo.adapters.base.FactorValues` rather than being assumed per
project. That is the raw material. This module turns it into the two sentences a
client actually needs:

* **Who must be credited in the report.** ODbL, CC-BY-SA and CC-BY-4.0 all require
  it. Nothing here is onerous — a line of text discharges it.
* **What happens if they redistribute the panel itself.** ODbL and CC-BY-SA impose
  share-alike on a derived *database*. A report is not a database; the panel CSV is.
  A client who publishes the panel inherits an obligation they will not have read
  about, and the only defensible moment to say so is before they do.

The distinction is the whole point. Collapsing both into "attribution required"
would understate the second, and treating every licence as share-alike would
overstate the first — CC-BY-4.0 is deliberately a separate rung for exactly that
reason.

Nothing here fetches, guesses or infers. A licence the registry did not declare
does not appear, and a licence this module does not recognise is reported as
unrecognised rather than quietly treated as permissive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roadrisk.core.registry.schema import LICENCE_POLICY, Licence, LicencePolicy

# The exact text an adapter is required to reproduce, when it has one. Written by
# the adapter as a note prefixed this way, so the credit line travels with the value
# instead of being reconstructed here from the adapter's name.
ATTRIBUTION_PREFIX = "ATTRIBUTION REQUIRED."

#: Per licence: must it be credited, does redistributing a derived database trigger
#: share-alike, and the sentence that says what the client actually has to do.
#:
#: The table itself moved down to :mod:`roadrisk.core.registry.schema` at step 5.1c,
#: beside the enum it is keyed by, because the API serves these obligations and
#: reaching into this module for them would have made shapely a dependency of
#: answering ``GET /registry``. It is re-exported here because this is where the
#: reasoning about what a client owes lives, and because nothing outside should have
#: to know which module holds the dictionary.
POLICY: dict[Licence, LicencePolicy] = LICENCE_POLICY


@dataclass(frozen=True)
class Obligation:
    """Everything owed under one licence, and to whom."""

    licence: str
    credit_required: bool
    share_alike_database: bool
    note: str
    factors: tuple[str, ...] = ()
    adapters: tuple[str, ...] = ()
    credits: tuple[str, ...] = ()
    recognised: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "licence": self.licence,
            "credit_required": self.credit_required,
            "share_alike_database": self.share_alike_database,
            "note": self.note,
            "factors": list(self.factors),
            "adapters": list(self.adapters),
            "credits": list(self.credits),
            "recognised": self.recognised,
        }


@dataclass(frozen=True)
class AttributionReport:
    """Every obligation this run incurred, grouped by licence."""

    obligations: tuple[Obligation, ...] = ()

    @property
    def credit_required(self) -> bool:
        return any(o.credit_required for o in self.obligations)

    @property
    def share_alike_database(self) -> bool:
        """True when redistributing the panel as a dataset carries share-alike."""
        return any(o.share_alike_database for o in self.obligations)

    @property
    def unrecognised(self) -> tuple[str, ...]:
        return tuple(o.licence for o in self.obligations if not o.recognised)

    def credit_lines(self) -> list[str]:
        """The lines that must appear in the report, deduplicated, in stable order."""
        lines: list[str] = []
        for obligation in self.obligations:
            if not obligation.credit_required:
                continue
            if obligation.credits:
                for credit in obligation.credits:
                    if credit not in lines:
                        lines.append(credit)
                continue
            for adapter in obligation.adapters:
                fallback = f"{adapter} — {obligation.licence}"
                if fallback not in lines:
                    lines.append(fallback)
        return lines

    def database_warning(self) -> str | None:
        """The sentence a client redistributing the panel needs to have read."""
        if not self.share_alike_database:
            return None
        licences = ", ".join(
            o.licence for o in self.obligations if o.share_alike_database
        )
        return (
            "This report may be shared freely with the credits above. The panel "
            "itself is a different matter: it is a database derived from "
            f"{licences} sources, so redistributing it as a dataset triggers "
            "share-alike and the dataset must carry the same licence. Reporting "
            "the numbers is not redistributing the database."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "credit_required": self.credit_required,
            "share_alike_database": self.share_alike_database,
            "credit_lines": self.credit_lines(),
            "database_warning": self.database_warning(),
            "unrecognised": list(self.unrecognised),
            "obligations": [o.as_dict() for o in self.obligations],
        }


def collect_attributions(fusion: Any) -> AttributionReport:
    """Group every fused factor's licence into the obligations it creates.

    Args:
        fusion: The :class:`~roadrisk.geo.adapters.fusion.FusionResult` for this run.
            Only the values that *won* fusion are counted — a rejected source did not
            reach the report, so nothing is owed for it.

    Returns:
        An :class:`AttributionReport`. Empty when no factor resolved, which is a
        legitimate outcome and not an error.
    """
    grouped: dict[str, dict[str, list[str]]] = {}
    for fused in getattr(fusion, "factors", []):
        chosen = fused.chosen
        licence = _licence_value(chosen.licence)
        bucket = grouped.setdefault(
            licence, {"factors": [], "adapters": [], "credits": []}
        )
        _append_unique(bucket["factors"], fused.factor)
        _append_unique(bucket["adapters"], chosen.adapter)
        for credit in _credits(chosen):
            _append_unique(bucket["credits"], credit)

    obligations = [
        _obligation(licence, bucket) for licence, bucket in sorted(grouped.items())
    ]
    return AttributionReport(obligations=tuple(obligations))


# ---- internals ---------------------------------------------------------------


def _obligation(licence: str, bucket: dict[str, list[str]]) -> Obligation:
    policy = _policy_for(licence)
    if policy is None:
        return Obligation(
            licence=licence,
            credit_required=True,
            share_alike_database=False,
            note=(
                "This licence is not one the tool knows how to advise on. Treat it as "
                "requiring credit and check its terms before the report is shared."
            ),
            factors=tuple(bucket["factors"]),
            adapters=tuple(bucket["adapters"]),
            credits=tuple(bucket["credits"]),
            recognised=False,
        )

    credit_required, share_alike, note = policy
    return Obligation(
        licence=licence,
        credit_required=credit_required,
        share_alike_database=share_alike,
        note=note,
        factors=tuple(bucket["factors"]),
        adapters=tuple(bucket["adapters"]),
        credits=tuple(bucket["credits"]),
    )


def _policy_for(licence: str) -> LicencePolicy | None:
    for known, policy in POLICY.items():
        if known.value == licence:
            return policy
    return None


def _credits(chosen: Any) -> list[str]:
    """The explicit credit text an adapter attached, if it attached any."""
    found: list[str] = []
    for note in getattr(chosen, "notes", ()) or ():
        text = " ".join(str(note).split())
        if text.startswith(ATTRIBUTION_PREFIX):
            stripped = text[len(ATTRIBUTION_PREFIX) :].strip()
            if stripped:
                found.append(stripped)
    return found


def _licence_value(licence: Any) -> str:
    return licence.value if isinstance(licence, Licence) else str(licence)


def _append_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)
