"""The registry is the architectural core — a bad one must fail loudly, not quietly."""

from __future__ import annotations

import pytest

from roadrisk.core.errors import RegistryError
from roadrisk.core.registry import Registry, Sign, parse_registry

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

    def test_every_weight_is_unsourced(self, shipped_registry: Registry) -> None:
        """Deliberate. Mode B must refuse until the weights carry citations."""
        assert len(shipped_registry.unsourced()) == len(shipped_registry.factors)

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
