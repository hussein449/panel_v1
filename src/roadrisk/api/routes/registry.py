"""The factor registry, served — and this is step 5.1c's done-when.

*"OpenAPI generated, with factors, tiers and licences read from `factors.yaml`."*

Read, not copied. There is no list of factor names in this package, no table of tiers,
no set of licence strings: the response is projected from the `Registry` the loader
validated at startup, and the `tier` and `licence` fields are typed with the registry's
own enums, so the published OpenAPI document cannot describe a licence the registry is
incapable of holding. A test asserts both halves — that the factors served are exactly
the factors declared, and that no factor name appears anywhere in `roadrisk/api/`.

**Why the obligations travel with the adapters.** A client reading `"licence": "ODbL"`
off a JSON response has been told nothing they can act on. What they need to know is
that crediting the source in a report discharges it and republishing the panel as a
dataset does not — which is the distinction
:mod:`roadrisk.geo.attribution` exists to make, and the reason the policy table moved
down beside the enum at this step rather than being written out a second time here.
"""

from __future__ import annotations

from fastapi import APIRouter

from roadrisk.api.deps import RegistryDep
from roadrisk.api.schemas import (
    AdapterOut,
    FactorOut,
    LicenceOut,
    RegistryOut,
    TierOut,
)
from roadrisk.core.registry import (
    LICENCE_POLICY,
    TIER_MEANING,
    Adapter,
    Factor,
    Licence,
    Registry,
    Tier,
)

router = APIRouter(tags=["registry"])


@router.get(
    "/registry",
    response_model=RegistryOut,
    summary="Every declared factor, with the tier and licence of each way to obtain it",
)
def read_registry(registry: RegistryDep) -> RegistryOut:
    """Serve `factors.yaml`, in the order the ladder would shed terms.

    Descent order — least important first — rather than file order, because that is the
    order that means something: it is what the engine drops when the panel cannot
    support the full specification, and a client planning which data to buy is reading
    the list backwards from the bottom.
    """
    factors = Registry.in_keep_order(list(registry.factors))
    return RegistryOut(
        version=registry.version,
        sha256=registry.sha256,
        source=_basename(registry.source_path),
        factor_count=len(registry.factors),
        sourced_count=sum(1 for factor in registry.factors if factor.is_sourced),
        tiers=[TierOut(code=tier, meaning=TIER_MEANING[tier]) for tier in Tier],
        licences=[_licence(licence) for licence in Licence],
        factors=[_factor(factor) for factor in factors],
    )


def _factor(factor: Factor) -> FactorOut:
    return FactorOut(
        name=factor.name,
        label=factor.label,
        column=factor.column,
        transform=factor.transform,
        expected_sign=factor.expected_sign,
        drop_priority=factor.drop_priority,
        sourced=factor.is_sourced,
        weight_count=len(factor.weights),
        missing_behaviour=_tidy(factor.missing_behaviour),
        adapters=[_adapter(adapter) for adapter in factor.adapters],
        notes=_tidy(factor.notes) if factor.notes else None,
    )


def _adapter(adapter: Adapter) -> AdapterOut:
    policy = LICENCE_POLICY[adapter.licence]
    return AdapterOut(
        name=adapter.name,
        tier=adapter.tier,
        licence=adapter.licence,
        credit_required=policy.credit_required,
        share_alike_database=policy.share_alike_database,
        obligation=policy.note,
        notes=_tidy(adapter.notes) if adapter.notes else None,
    )


def _licence(licence: Licence) -> LicenceOut:
    policy = LICENCE_POLICY[licence]
    return LicenceOut(
        code=licence,
        credit_required=policy.credit_required,
        share_alike_database=policy.share_alike_database,
        obligation=policy.note,
    )


def _tidy(text: str) -> str:
    """Collapse the YAML block scalars' line breaks into one paragraph.

    `factors.yaml` folds its prose to fit a text editor. Those line breaks are an
    artefact of the file, not of the sentence, and a client rendering them verbatim
    gets a ragged paragraph for no reason.
    """
    return " ".join(text.split())


def _basename(path: str | None) -> str:
    """The file's name, never the server's directory layout."""
    if not path:
        return "factors.yaml"
    return path.replace("\\", "/").rsplit("/", 1)[-1]
