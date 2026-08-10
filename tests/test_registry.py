"""The registry is the architectural core — a bad one must fail loudly, not quietly."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from roadrisk.core.errors import RegistryError
from roadrisk.core.registry import Registry, Sign, parse_registry

DERIVE_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "derive_weights.py"


def _load_derivation_module() -> ModuleType:
    """Import tools/derive_weights.py, which is a script rather than a package."""
    if "derive_weights" in sys.modules:
        return sys.modules["derive_weights"]
    spec = importlib.util.spec_from_file_location("derive_weights", DERIVE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["derive_weights"] = module
    spec.loader.exec_module(module)
    return module

MINIMAL = """
version: "test"
factors:
  - name: {name}
    label: A factor
    column: {column}
    transform: ln1p
    expected_sign: "{sign}"
    drop_priority: {priority}
    missing_behaviour: Something is lost.
    adapters:
      - name: osm
        tier: A
        licence: ODbL
"""


def _yaml(*entries: str) -> str:
    head, *rest = entries
    return head + "".join(entry.split("factors:", 1)[1] for entry in rest)


def factor_yaml(
    name: str,
    column: str,
    sign: str = "+",
    priority: int = 10,
    weights: str = "",
) -> str:
    return (
        MINIMAL.format(name=name, column=column, sign=sign, priority=priority) + weights
    )


def weight_yaml(
    value: float,
    *,
    family: str = "hsm",
    source: str = "AASHTO HSM Eq. 10-20",
    extra: str = "",
) -> str:
    return (
        "    weights:\n"
        f"      - value: {value}\n"
        f"        family: {family}\n"
        f'        source: "{source}"\n' + extra
    )


class TestShippedRegistry:
    def test_loads(self, shipped_registry: Registry) -> None:
        assert shipped_registry.version
        assert len(shipped_registry.factors) >= 10

    def test_some_weights_are_sourced_and_some_are_not(
        self, shipped_registry: Registry
    ) -> None:
        """Partial coverage is the expected state, not a defect."""
        sourced = [f for f in shipped_registry.factors if f.is_sourced]
        assert sourced, "expected at least one cited weight"
        assert shipped_registry.unsourced(), "expected some factors still uncited"

    def test_every_weight_carries_a_citation(self, shipped_registry: Registry) -> None:
        """The invariant that matters — a weight without a source must not exist."""
        for factor in shipped_registry.factors:
            for weight in factor.weights:
                assert weight.source.strip(), factor.name

    def test_citations_name_a_document_not_just_a_number(
        self, shipped_registry: Registry
    ) -> None:
        for factor in shipped_registry.factors:
            for weight in factor.weights:
                assert any(
                    token in weight.source
                    for token in ("HSM", "TOI", "FHWA", "Elvik", "iRAP")
                ), f"{factor.name} citation names no recognisable source"

    def test_registry_weights_match_the_derivation_script(
        self, shipped_registry: Registry
    ) -> None:
        """The registry must not drift from the arithmetic that produced it.

        Every weight is computed in tools/derive_weights.py from a published equation.
        Hand-editing one is a test failure, not a silent change.
        """
        derivations = _load_derivation_module()

        for derive in derivations.DERIVATIONS:
            result = derive()
            factor = shipped_registry.by_name(result.factor)
            match = [
                w
                for w in factor.weights
                if w.family.value == result.family
                and w.severity.value == result.severity
            ]
            assert match, (
                f"{result.factor}: derivation produces a {result.family}/"
                f"{result.severity} weight the registry does not declare"
            )
            assert abs(match[0].value - result.value) < 5e-5, (
                f"{result.key}: registry has {match[0].value}, "
                f"derivation gives {result.value:.6f}"
            )

    def test_every_registry_weight_comes_from_the_script(
        self, shipped_registry: Registry
    ) -> None:
        """The reverse direction — no weight may be introduced by hand."""
        derivations = _load_derivation_module()
        derived = {
            (d.factor, d.family, d.severity)
            for d in (derive() for derive in derivations.DERIVATIONS)
        }

        for factor in shipped_registry.factors:
            for weight in factor.weights:
                key = (factor.name, weight.family.value, weight.severity.value)
                assert key in derived, f"{key} is in the registry but not derived"

    def test_derived_weights_agree_with_their_declared_signs(
        self, shipped_registry: Registry
    ) -> None:
        derivations = _load_derivation_module()
        for derive in derivations.DERIVATIONS:
            result = derive()
            factor = shipped_registry.by_name(result.factor)
            expected = 1 if factor.expected_sign is Sign.POSITIVE else -1
            observed = 1 if result.value > 0 else -1
            assert observed == expected, result.factor

    def test_speed_is_split_into_posted_and_operating(
        self, shipped_registry: Registry
    ) -> None:
        """The Power Model applies to operating speed, so posted gets its own factor.

        Keeping them as one column is what made the caveat unavoidable.
        """
        posted = shipped_registry.by_name("speed_limit")
        operating = shipped_registry.by_name("operating_speed_85")

        assert posted.column != operating.column
        assert all(w.caveat for w in posted.weights), "posted weights must self-declare"
        assert not any(w.caveat for w in operating.weights)

    def test_speed_weights_are_severity_specific(
        self, shipped_registry: Registry
    ) -> None:
        severities = {
            w.severity.value for w in shipped_registry.by_name("speed_limit").weights
        }
        assert {"injury", "fatal"} <= severities

    def test_sources_that_disagree_are_both_kept(
        self, shipped_registry: Registry
    ) -> None:
        """grade_pct carries HSM and iRAP weights that differ four-fold.

        Keeping both, with their scopes declared, is the point. Averaging them would
        produce a number neither source supports.
        """
        families = {w.family.value for w in shipped_registry.by_name("grade_pct").weights}
        assert {"hsm", "irap"} <= families

    def test_carries_its_own_checksum(self, shipped_registry: Registry) -> None:
        assert shipped_registry.sha256
        assert len(shipped_registry.sha256) == 64

    def test_ramp_density_expects_positive(self, shipped_registry: Registry) -> None:
        """The M51 inversion is an open blocker, not a reason to flip the declaration."""
        assert shipped_registry.by_name("ramp_density").expected_sign is Sign.POSITIVE


class TestValidation:
    def test_rejects_duplicate_names(self) -> None:
        text = _yaml(factor_yaml("a", "col_a"), factor_yaml("a", "col_b", priority=20))
        with pytest.raises(RegistryError, match="duplicate factor name"):
            parse_registry(text)

    def test_rejects_duplicate_columns(self) -> None:
        text = _yaml(factor_yaml("a", "shared"), factor_yaml("b", "shared", priority=20))
        with pytest.raises(RegistryError, match="duplicate factor column"):
            parse_registry(text)

    def test_rejects_duplicate_drop_priority(self) -> None:
        """Ties would make descent arbitrary rather than declared."""
        text = _yaml(factor_yaml("a", "col_a"), factor_yaml("b", "col_b", priority=10))
        with pytest.raises(RegistryError, match="drop_priority must be unique"):
            parse_registry(text)

    def test_rejects_weight_without_citation(self) -> None:
        text = factor_yaml(
            "a",
            "col_a",
            weights="    weights:\n      - value: 0.3\n        family: hsm\n",
        )
        with pytest.raises(RegistryError, match="source"):
            parse_registry(text)

    def test_rejects_weight_with_empty_citation(self) -> None:
        text = factor_yaml("a", "col_a", weights=weight_yaml(0.3, source=""))
        with pytest.raises(RegistryError, match="source"):
            parse_registry(text)

    def test_rejects_weight_contradicting_expected_sign(self) -> None:
        """The registry must not ship a contradiction with itself."""
        text = factor_yaml("a", "col_a", sign="+", weights=weight_yaml(-0.3))
        with pytest.raises(RegistryError, match="must not ship a contradiction"):
            parse_registry(text)

    def test_checks_every_weight_not_just_the_first(self) -> None:
        """One bad source must not slip in behind a good one."""
        text = factor_yaml("a", "col_a", sign="+", weights=weight_yaml(0.3)) + (
            "      - value: -0.4\n"
            "        family: irap\n"
            '        source: "iRAP fact sheet"\n'
        )
        with pytest.raises(RegistryError, match="must not ship a contradiction"):
            parse_registry(text)

    def test_rejects_indistinguishable_weights(self) -> None:
        """Two weights matching the same context would make selection arbitrary."""
        text = factor_yaml("a", "col_a", weights=weight_yaml(0.3)) + (
            "      - value: 0.4\n"
            "        family: hsm\n"
            '        source: "AASHTO HSM Eq. 10-13"\n'
        )
        with pytest.raises(RegistryError, match="Selection would be"):
            parse_registry(text)

    def test_rejects_the_pre_0_2_schema_by_name(self) -> None:
        """A confusing `extra fields not permitted` would waste an afternoon."""
        text = factor_yaml("a", "col_a") + "    default_weight: 0.3\n"
        with pytest.raises(RegistryError, match="pre-0.2 single-weight schema"):
            parse_registry(text)

    def test_error_names_the_factor_not_its_index(self) -> None:
        text = _yaml(
            factor_yaml("good", "col_a"),
            factor_yaml("suspect", "col_b", sign="?", priority=20),
        )
        with pytest.raises(RegistryError) as excinfo:
            parse_registry(text)
        assert "factor 'suspect'" in str(excinfo.value)

    def test_rejects_unknown_field(self) -> None:
        text = factor_yaml("a", "col_a") + "    weight: 0.3\n"
        with pytest.raises(RegistryError):
            parse_registry(text)

    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(RegistryError, match="must contain a mapping"):
            parse_registry("- just\n- a\n- list\n")


class TestSelection:
    def test_available_and_missing_partition_the_registry(
        self, shipped_registry: Registry
    ) -> None:
        columns = ["curve_density", "speed_limit", "unrelated"]
        available = shipped_registry.available(columns)
        missing = shipped_registry.missing(columns)

        assert {f.name for f in available} == {"curve_density", "speed_limit"}
        assert len(available) + len(missing) == len(shipped_registry.factors)

    def test_available_comes_back_in_drop_order(
        self, shipped_registry: Registry
    ) -> None:
        available = shipped_registry.available(shipped_registry.columns)
        priorities = [f.drop_priority for f in available]
        assert priorities == sorted(priorities)

    def test_keep_order_is_the_reverse(self, shipped_registry: Registry) -> None:
        keep = Registry.in_keep_order(shipped_registry.factors)
        assert keep[0].drop_priority == max(f.drop_priority for f in keep)

    def test_by_name_raises_on_unknown(self, shipped_registry: Registry) -> None:
        with pytest.raises(KeyError):
            shipped_registry.by_name("no_such_factor")
