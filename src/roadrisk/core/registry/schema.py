"""Declarative factor registry.

The generalisation the product rests on: *a factor is a declaration, not code*. Adding
"pavement friction" or "lighting" must never require touching the engine. The engine
reads this registry and builds the model specification from it.

Both modes read the same registry, which is what makes them comparable — Mode B applies
``default_weight``, Mode A estimates a coefficient for the same transformed column.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Transform(StrEnum):
    """How a raw column is mapped before it enters the model."""

    IDENTITY = "identity"
    LN = "ln"
    LN1P = "ln1p"
    ZSCORE = "zscore"


class Sign(StrEnum):
    """The direction a factor is expected to push risk. The guard rail."""

    POSITIVE = "+"
    NEGATIVE = "-"

    @property
    def as_int(self) -> int:
        return 1 if self is Sign.POSITIVE else -1


class Tier(StrEnum):
    """Who pays to obtain the value.

    A — open, global, scriptable, free.
    B — open, but needs vision models or graph compute.
    C — free-tier APIs, licence-limited, opt-in per project.
    D — cannot be derived; the client must measure and supply it.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Licence(StrEnum):
    """Licence attached to a value, carried through to the report.

    ODbL and CC-BY-SA both impose share-alike on a redistributed derived *database*.
    The report is fine with attribution; the dataset is not. Hence this travels with
    every value rather than being assumed per project.

    ``CC-BY-4.0`` is attribution without share-alike — a materially lighter obligation
    than the two above and a materially heavier one than public domain. It is separate
    because collapsing it into either would misstate what the client must do.
    """

    ODBL = "ODbL"
    CC_BY_SA = "CC-BY-SA"
    CC_BY = "CC-BY-4.0"
    PUBLIC_DOMAIN = "public-domain"
    PROPRIETARY = "proprietary"
    CLIENT = "client"


#: What each tier actually costs the client, in one line.
#:
#: Stated as data next to the enum rather than only in its docstring, because step
#: 5.1c serves it: a client reading ``"tier": "C"`` off the API needs to know that it
#: means a rate-limited free-tier key they have to obtain, and a letter does not say
#: that. A test asserts this covers every member — a tier nobody has described would
#: otherwise be published as a bare letter.
TIER_MEANING: dict[Tier, str] = {
    Tier.A: "Open, global, scriptable, free. Costs a network request.",
    Tier.B: "Open, but needs vision models or graph compute to derive. Costs machine time.",
    Tier.C: "Free-tier API, licence-limited. Needs a key, and is opt-in per project.",
    Tier.D: "Cannot be derived. The client measures it and supplies it.",
}


class LicencePolicy(NamedTuple):
    """What one licence obliges the client to do.

    Two booleans rather than one, deliberately, and the reason is in
    :mod:`roadrisk.geo.attribution`: crediting a source in the report and
    redistributing the panel as a dataset are different acts under different terms.
    ODbL and CC-BY-SA impose share-alike on the second and not the first, CC-BY-4.0 on
    neither, and collapsing them into "attribution required" understates what a client
    who publishes the panel has just agreed to.
    """

    credit_required: bool
    share_alike_database: bool
    note: str


#: Per licence: must it be credited, does redistributing a derived database trigger
#: share-alike, and the sentence that says what the client actually has to do.
#:
#: This lives beside the enum it is keyed by rather than in the geospatial layer that
#: first needed it, because it describes a licence and not a pipeline. Step 5.1c is
#: what forced the move: the API serves these obligations alongside every adapter it
#: lists, and reaching into ``roadrisk.geo`` for them would have made shapely a
#: dependency of answering ``GET /registry``. The alternative — a second copy of the
#: text in the API — is the drift step 5.1a exists to prevent.
LICENCE_POLICY: dict[Licence, LicencePolicy] = {
    Licence.ODBL: LicencePolicy(
        True,
        True,
        "Credit the source in the report. Publishing the panel itself as a dataset "
        "is redistributing a derived database, which triggers ODbL share-alike — "
        "the dataset would have to carry the same licence.",
    ),
    Licence.CC_BY_SA: LicencePolicy(
        True,
        True,
        "Credit the source in the report. Publishing the panel itself as a dataset "
        "triggers CC-BY-SA share-alike — the dataset would have to carry the same "
        "licence.",
    ),
    Licence.CC_BY: LicencePolicy(
        True,
        False,
        "Credit the source in the report. Attribution only: there is no share-alike "
        "obligation, so the panel may be redistributed under any licence provided "
        "the credit travels with it.",
    ),
    Licence.PUBLIC_DOMAIN: LicencePolicy(
        False,
        False,
        "No obligation. Credited anyway where the source asks for it.",
    ),
    Licence.PROPRIETARY: LicencePolicy(
        True,
        False,
        "Governed by the supplier's own terms, which this tool has not read. Check "
        "them before the report leaves the building.",
    ),
    Licence.CLIENT: LicencePolicy(
        False,
        False,
        "The client's own data. No third-party obligation.",
    ),
}


class WeightFamily(StrEnum):
    """Which body of evidence a weight comes from.

    Preference order for selection is declared in ``roadrisk.core.weights`` — iRAP
    first, because it is global and cross-sectional by construction, which is what
    Mode B actually does.
    """

    IRAP = "irap"
    HSM = "hsm"
    ELVIK = "elvik"


class FacilityType(StrEnum):
    """The road type a weight was estimated on, or that a corridor is.

    ``ANY`` on a weight means the source does not restrict by facility. ``ANY`` on a
    run means the corridor type was not declared, in which case only unrestricted
    weights are admissible — the engine will not guess.
    """

    RURAL_TWO_LANE = "rural_two_lane"
    RURAL_MULTILANE = "rural_multilane"
    URBAN_ARTERIAL = "urban_arterial"
    #: A grade-separated dual carriageway with no at-grade junctions — an
    #: *Αυτοκινητόδρομος*, an autoroute, an Interstate.
    #:
    #: **It exists so that a motorway can stop being declared as something else.** No
    #: weight in the registry is scoped to it today, so declaring it admits exactly the
    #: unrestricted weights and nothing more — the same evidence ``ANY`` gets. That is
    #: the point rather than a shortcoming: the option a reader reaches for instead is
    #: ``RURAL_TWO_LANE``, which is not a near miss but a different road, and it quietly
    #: admits the HSM's two-lane-two-way weights. ``access_density`` is HSM Eq. 10-17,
    #: *"rural two-lane two-way segments"* — and a motorway has no driveways at all, so
    #: the number would be admitted on a premise that is false rather than approximate.
    #: Found on the Cyprus A10, declared ``rural_two_lane`` because nothing better was
    #: offered.
    #:
    #: So this buys an honest and smaller answer. A motorway-scoped weight entering the
    #: registry later makes it buy more, with nothing here changing.
    MOTORWAY = "motorway"
    ANY = "any"


class Region(StrEnum):
    """Where a weight was estimated, or where a corridor is.

    Region granularity, not country, because published weights are estimated on
    regional or national datasets and never on "Cyprus" specifically. A Cyprus
    corridor declares ``europe`` and gets European evidence where it exists, global
    evidence otherwise, and North American evidence only as a last resort — with the
    reach reported.

    Stage 2 will resolve this from the corridor's admin boundary automatically; the
    GADM and OSM-relation adapters are already declared for that.
    """

    NORTH_AMERICA = "north_america"
    EUROPE = "europe"
    AUSTRALASIA = "australasia"
    ASIA = "asia"
    AFRICA = "africa"
    MIDDLE_EAST = "middle_east"
    LATIN_AMERICA = "latin_america"
    GLOBAL = "global"


class Severity(StrEnum):
    """Which crashes a weight predicts.

    This is not decoration. The Elvik Power Model exponent is 1.6 for injury crashes
    and 4.1 for fatal ones — applying the wrong one is a factor-of-two error, and
    before this existed the registry silently assumed injury.
    """

    ALL = "all"
    INJURY = "injury"
    FSI = "fsi"
    FATAL = "fatal"


class CrashScope(StrEnum):
    """Which crash types a weight covers.

    HSM CMFs are stated for *total* segment crashes. iRAP risk factors are stated per
    crash type — its curvature factor covers run-off and head-on only, and its street
    lighting factor covers intersection crashes only.

    Scope does two jobs. It stops the engine scoring a like-for-like agreement between
    weights measuring different quantities, and it decides which crash-type bucket a
    weight enters when Mode B decomposes the score
    (see :mod:`roadrisk.core.crashmix`).

    ``TOTAL`` is a marker, not a type: a total-scope weight enters *every* bucket.
    The remaining four partition all crashes exactly once, so shares over them sum
    to one and nothing is double-counted or lost.
    """

    TOTAL = "total"
    RUN_OFF_HEAD_ON = "run_off_head_on"
    INTERSECTION = "intersection"
    PEDESTRIAN = "pedestrian"
    OTHER = "other"


class Weight(BaseModel):
    """One published weight for one factor, with the context it is valid in.

    A weight used to be a bare number plus a citation. That was the root cause of
    every caveat in the first sourcing pass: nothing recorded the facility type, the
    region, the severity or the crash scope a number was estimated for, so the engine
    applied US rural two-lane injury-crash coefficients to any corridor anywhere and
    said nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    source: str = Field(min_length=1, description="Citation. Never optional.")
    family: WeightFamily

    facility_type: FacilityType = FacilityType.ANY
    region: Region = Region.GLOBAL
    severity: Severity = Severity.ALL
    scope: CrashScope = CrashScope.TOTAL

    fit_r2: float | None = Field(
        default=None,
        description="Linearisation quality where the weight was fitted; None if exact.",
    )
    assumes: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Run conditions this weight was derived under, checked against the actual "
            "run. e.g. {'segment_length_km': 0.5} or {'reference_aadt': 10000}."
        ),
    )
    caveat: str | None = Field(
        default=None,
        description=(
            "A limitation intrinsic to this weight, true on every run regardless of "
            "context. Always surfaced as a concern — this is how a known-imperfect "
            "weight stays usable without becoming quietly trusted."
        ),
    )
    notes: str | None = None

    @property
    def sign(self) -> int:
        if self.value > 0:
            return 1
        return -1 if self.value < 0 else 0

    @property
    def is_exact(self) -> bool:
        return self.fit_r2 is None


class Adapter(BaseModel):
    """One way of obtaining a factor.

    Adapters are ordered within a factor: the first that resolves wins. Client-supplied
    data is simply the highest-priority adapter — same code path, no special case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    tier: Tier
    licence: Licence
    notes: str | None = None


class Factor(BaseModel):
    """A single declared model term."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    column: str = Field(min_length=1)
    transform: Transform
    expected_sign: Sign
    missing_behaviour: str = Field(min_length=1)
    adapters: list[Adapter] = Field(min_length=1)

    drop_priority: int = Field(
        description="Descent order when the ladder must shed terms. Lower is dropped first."
    )
    weights: list[Weight] = Field(
        default_factory=list,
        description=(
            "Published weights for this factor, each carrying the context it is valid "
            "in. Empty means uncited, and an uncited factor never enters Mode B."
        ),
    )
    not_applicable_on: list[FacilityType] = Field(
        default_factory=list,
        description=(
            "Facility types on which this factor does not describe a real feature of "
            "the road, and must not be fitted. Empty — the usual case — means the "
            "factor applies everywhere. This is not a statement that the factor is "
            "weak on those roads; it is a statement that the quantity does not exist "
            "there, so a column claiming to measure it is measuring something else."
        ),
    )
    not_applicable_reason: str = Field(
        default="",
        description=(
            "Why the exclusion holds, in the registry rather than in code. Required "
            "whenever `not_applicable_on` is non-empty, because an exclusion nobody "
            "wrote an argument for is indistinguishable from one added to make a "
            "corridor look better."
        ),
    )

    notes: str | None = None

    @model_validator(mode="after")
    def _exclusions_carry_a_reason(self) -> Factor:
        if self.not_applicable_on and not self.not_applicable_reason.strip():
            raise ValueError(
                f"factor '{self.name}' is excluded on "
                f"{', '.join(f.value for f in self.not_applicable_on)} but states no "
                "reason. An exclusion is a claim about the road and has to be argued "
                "where the next reader will find it."
            )
        return self

    def applies_to(self, facility: FacilityType) -> bool:
        """Whether this factor describes a real feature of that kind of road.

        ``FacilityType.ANY`` means the caller declared nothing, and the engine does not
        guess: an undeclared corridor keeps every factor, because dropping a term on an
        assumption about the road would be the same class of error the exclusion exists
        to prevent.
        """
        if facility is FacilityType.ANY:
            return True
        return facility not in self.not_applicable_on

    @property
    def is_sourced(self) -> bool:
        """True when this factor carries at least one cited weight."""
        return bool(self.weights)

    def weights_from(self, family: WeightFamily) -> list[Weight]:
        return [w for w in self.weights if w.family is family]

    @model_validator(mode="after")
    def _weights_agree_with_expected_sign(self) -> Factor:
        """A weight contradicting its own declared sign is a registry bug, not a finding.

        This runs per weight, so one bad source cannot slip in behind a good one.
        """
        for weight in self.weights:
            if weight.sign == 0 or weight.sign == self.expected_sign.as_int:
                continue
            raise ValueError(
                f"factor '{self.name}' declares expected_sign "
                f"'{self.expected_sign.value}' but the weight from "
                f"{weight.family.value} is {weight.value}. Fix one of them — the "
                "registry must not ship a contradiction with itself."
            )
        return self

    @model_validator(mode="after")
    def _weights_are_distinguishable(self) -> Factor:
        """Two weights matching the same context would make selection arbitrary."""
        seen: set[tuple[str, str, str, str]] = set()
        for weight in self.weights:
            key = (
                weight.family.value,
                weight.facility_type.value,
                weight.region.value,
                weight.severity.value,
            )
            if key in seen:
                raise ValueError(
                    f"factor '{self.name}' has two weights with identical "
                    f"family/facility/region/severity {key}. Selection would be "
                    "arbitrary — differentiate them or remove one."
                )
            seen.add(key)
        return self


class Registry(BaseModel):
    """The complete set of declared factors, plus provenance of the file it came from."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    factors: list[Factor] = Field(min_length=1)

    # Populated by the loader, not by the YAML.
    source_path: str | None = None
    sha256: str | None = None

    @field_validator("factors")
    @classmethod
    def _unique_names_and_columns(cls, factors: list[Factor]) -> list[Factor]:
        for attr in ("name", "column"):
            seen: dict[str, int] = {}
            for f in factors:
                value = getattr(f, attr)
                seen[value] = seen.get(value, 0) + 1
            duplicates = sorted(v for v, n in seen.items() if n > 1)
            if duplicates:
                raise ValueError(f"duplicate factor {attr}(s): {', '.join(duplicates)}")
        return factors

    @field_validator("factors")
    @classmethod
    def _unique_drop_priority(cls, factors: list[Factor]) -> list[Factor]:
        """Descent must be deterministic — ties would make it arbitrary."""
        priorities = [f.drop_priority for f in factors]
        if len(set(priorities)) != len(priorities):
            clashing = sorted({p for p in priorities if priorities.count(p) > 1})
            raise ValueError(
                f"drop_priority must be unique so descent is deterministic; "
                f"repeated value(s): {clashing}"
            )
        return factors

    # ---- lookup -------------------------------------------------------------

    def by_name(self, name: str) -> Factor:
        for f in self.factors:
            if f.name == name:
                return f
        raise KeyError(f"no factor named '{name}' in registry {self.version}")

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.factors]

    @property
    def columns(self) -> list[str]:
        return [f.column for f in self.factors]

    def available(
        self,
        present_columns: object,
        *,
        facility_type: FacilityType = FacilityType.ANY,
    ) -> list[Factor]:
        """Factors whose input column is present and which apply to this road type.

        Returned in descent order, most-droppable first, so callers never have to
        re-sort and accidentally introduce a different order.

        ``facility_type`` defaults to ``ANY``, which excludes nothing — a caller that
        does not know the road type gets the behaviour it had before this argument
        existed, rather than a guess.
        """
        columns = set(present_columns)  # type: ignore[arg-type]
        return self.in_drop_order(
            [
                f
                for f in self.factors
                if f.column in columns and f.applies_to(facility_type)
            ]
        )

    def not_applicable(
        self,
        present_columns: object,
        *,
        facility_type: FacilityType = FacilityType.ANY,
    ) -> list[Factor]:
        """Factors held out because they do not describe this kind of road.

        Separate from :meth:`missing`, which is about a column nobody supplied. A
        factor here has its data and is set aside anyway, and the two are different
        things to tell a client.
        """
        columns = set(present_columns)  # type: ignore[arg-type]
        return self.in_drop_order(
            [
                f
                for f in self.factors
                if f.column in columns and not f.applies_to(facility_type)
            ]
        )

    def missing(self, present_columns: object) -> list[Factor]:
        """Factors whose column is absent. Each one drops exactly one term."""
        columns = set(present_columns)  # type: ignore[arg-type]
        return self.in_drop_order([f for f in self.factors if f.column not in columns])

    @staticmethod
    def in_drop_order(factors: list[Factor]) -> list[Factor]:
        """Least important first — the order the ladder sheds terms in."""
        return sorted(factors, key=lambda f: f.drop_priority)

    @staticmethod
    def in_keep_order(factors: list[Factor]) -> list[Factor]:
        """Most important first — the order the ladder retains terms in."""
        return sorted(factors, key=lambda f: f.drop_priority, reverse=True)

    def unsourced(self) -> list[Factor]:
        """Factors Mode B cannot legitimately use."""
        return [f for f in self.factors if not f.is_sourced]


__all__ = [
    "LICENCE_POLICY",
    "TIER_MEANING",
    "Adapter",
    "CrashScope",
    "FacilityType",
    "Factor",
    "Licence",
    "LicencePolicy",
    "Region",
    "Registry",
    "Severity",
    "Sign",
    "Tier",
    "Transform",
    "Weight",
    "WeightFamily",
]
