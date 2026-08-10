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


def factor_yaml(name: str, column: str, sign: str = "+", priority: int = 10) -> str:
    return MINIMAL.format(name=name, column=column, sign=sign, priority=priority)


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
            if factor.default_weight is not None:
                assert factor.weight_source, factor.name

    def test_citations_name_a_document_not_just_a_number(
        self, shipped_registry: Registry
    ) -> None:
        for factor in shipped_registry.factors:
            if not factor.is_sourced:
                continue
            source = str(factor.weight_source)
            assert any(
                token in source for token in ("HSM", "TOI", "FHWA", "Elvik")
            ), f"{factor.name} citation names no recognisable source: {source!r}"

    def test_registry_weights_match_the_derivation_script(
        self, shipped_registry: Registry
    ) -> None:
        """The registry must not drift from the arithmetic that produced it.

        Every sourced weight is computed in tools/derive_weights.py from a published
        equation. If someone hand-edits a weight, this fails.
        """
        derivations = _load_derivation_module()
        computed = {
            derive().factor: derive().weight for derive in derivations.DERIVATIONS
        }

        for name, weight in computed.items():
            declared = shipped_registry.by_name(name).default_weight
            assert declared is not None, f"{name} is derived but not set in the registry"
            assert abs(declared - weight) < 5e-5, (
                f"{name}: registry has {declared}, derivation gives {weight:.6f}"
            )

    def test_derived_weights_agree_with_their_declared_signs(
        self, shipped_registry: Registry
    ) -> None:
        derivations = _load_derivation_module()
        for derive in derivations.DERIVATIONS:
            result = derive()
            factor = shipped_registry.by_name(result.factor)
            expected = 1 if factor.expected_sign is Sign.POSITIVE else -1
            observed = 1 if result.weight > 0 else -1
            assert observed == expected, result.factor

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
        text = factor_yaml("a", "col_a") + "    default_weight: 0.3\n"
        with pytest.raises(RegistryError, match="must carry a citation"):
            parse_registry(text)

    def test_rejects_citation_without_weight(self) -> None:
        text = factor_yaml("a", "col_a") + '    weight_source: "HSM"\n'
        with pytest.raises(RegistryError, match="no default_weight"):
            parse_registry(text)

    def test_rejects_weight_contradicting_expected_sign(self) -> None:
        """The registry must not ship a contradiction with itself."""
        text = (
            factor_yaml("a", "col_a", sign="+")
            + "    default_weight: -0.3\n"
            + '    weight_source: "HSM"\n'
        )
        with pytest.raises(RegistryError, match="must not ship a contradiction"):
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
