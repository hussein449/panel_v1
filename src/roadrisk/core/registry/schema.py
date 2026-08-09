"""Declarative factor registry.

The generalisation the product rests on: *a factor is a declaration, not code*. Adding
"pavement friction" or "lighting" must never require touching the engine. The engine
reads this registry and builds the model specification from it.

Both modes read the same registry, which is what makes them comparable — Mode B applies
``default_weight``, Mode A estimates a coefficient for the same transformed column.
"""

from __future__ import annotations

from enum import StrEnum

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
    """

    ODBL = "ODbL"
    CC_BY_SA = "CC-BY-SA"
    PUBLIC_DOMAIN = "public-domain"
    PROPRIETARY = "proprietary"
    CLIENT = "client"


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
    default_weight: float | None = Field(
        default=None,
        description="Mode B weight, on the transformed scale. None means unsourced.",
    )
    weight_source: str | None = Field(
        default=None,
        description="Citation for default_weight. Required whenever a weight is set.",
    )
    notes: str | None = None

    @property
    def is_sourced(self) -> bool:
        """True when this factor can legitimately be used by Mode B."""
        return self.default_weight is not None and bool(self.weight_source)

    @model_validator(mode="after")
    def _weight_requires_citation(self) -> Factor:
        if self.default_weight is not None and not self.weight_source:
            raise ValueError(
                f"factor '{self.name}' sets default_weight={self.default_weight} but no "
                "weight_source. Every published weight must carry a citation."
            )
        if self.weight_source and self.default_weight is None:
            raise ValueError(
                f"factor '{self.name}' has a weight_source but no default_weight."
            )
        return self

    @model_validator(mode="after")
    def _weight_agrees_with_expected_sign(self) -> Factor:
        """A weight that contradicts its own declared sign is a registry bug, not a finding."""
        if self.default_weight is None or self.default_weight == 0:
            return self
        observed = 1 if self.default_weight > 0 else -1
        if observed != self.expected_sign.as_int:
            raise ValueError(
                f"factor '{self.name}' declares expected_sign '{self.expected_sign.value}' "
                f"but default_weight is {self.default_weight}. Fix one of them — the "
                "registry must not ship a contradiction."
            )
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

    def available(self, present_columns: object) -> list[Factor]:
        """Factors whose input column is present in the supplied panel.

        Returned in descent order, most-droppable first, so callers never have to
        re-sort and accidentally introduce a different order.
        """
        columns = set(present_columns)  # type: ignore[arg-type]
        return self.in_drop_order([f for f in self.factors if f.column in columns])

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
    "Adapter",
    "Factor",
    "Licence",
    "Registry",
    "Sign",
    "Tier",
    "Transform",
]
