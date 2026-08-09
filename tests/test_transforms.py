"""Every transform is guarded, and every failure names the factor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadrisk.core.errors import TransformError
from roadrisk.core.registry import Transform
from roadrisk.core.transforms import apply_transform, build_design


class TestApplyTransform:
    def test_identity(self) -> None:
        values = pd.Series([1.0, 2.0, 3.0])
        result = apply_transform(values, Transform.IDENTITY, factor="f")
        pd.testing.assert_series_equal(result, values)

    def test_ln(self) -> None:
        result = apply_transform(pd.Series([1.0, np.e]), Transform.LN, factor="f")
        assert result.tolist() == pytest.approx([0.0, 1.0])

    def test_ln1p_accepts_zero(self) -> None:
        result = apply_transform(pd.Series([0.0, 1.0]), Transform.LN1P, factor="f")
        assert result.iloc[0] == pytest.approx(0.0)

    def test_zscore(self) -> None:
        result = apply_transform(
            pd.Series([1.0, 2.0, 3.0]), Transform.ZSCORE, factor="f"
        )
        assert result.mean() == pytest.approx(0.0)
        assert result.std(ddof=0) == pytest.approx(1.0)


class TestGuards:
    def test_ln_rejects_zero_and_suggests_ln1p(self) -> None:
        with pytest.raises(TransformError, match="Use 'ln1p'"):
            apply_transform(pd.Series([0.0, 1.0]), Transform.LN, factor="speed_limit")

    def test_ln_rejects_negative(self) -> None:
        with pytest.raises(TransformError, match="speed_limit"):
            apply_transform(pd.Series([-1.0, 1.0]), Transform.LN, factor="speed_limit")

    def test_ln1p_rejects_negative(self) -> None:
        with pytest.raises(TransformError, match="negative"):
            apply_transform(pd.Series([-0.5]), Transform.LN1P, factor="curve_density")

    def test_zscore_rejects_constant(self) -> None:
        with pytest.raises(TransformError, match="constant"):
            apply_transform(pd.Series([2.0, 2.0]), Transform.ZSCORE, factor="lit")

    def test_rejects_nulls(self) -> None:
        with pytest.raises(TransformError, match="null or non-numeric"):
            apply_transform(
                pd.Series([1.0, None]), Transform.IDENTITY, factor="grade_pct"
            )

    def test_rejects_infinity_and_says_to_cap(self) -> None:
        """Curve radius on a tangent is the case this exists for."""
        with pytest.raises(TransformError, match="capped by"):
            apply_transform(
                pd.Series([1.0, np.inf]), Transform.LN, factor="curve_radius_min"
            )


class TestBuildDesign:
    def test_columns_are_named_by_factor_not_by_input_column(
        self, shipped_registry
    ) -> None:
        """Everything downstream must speak in registry terms."""
        panel = pd.DataFrame({"curve_density": [1.0, 2.0], "speed_limit": [50.0, 80.0]})
        factors = shipped_registry.available(panel.columns)
        design = build_design(panel, factors)
        assert set(design.columns) == {"curve_density", "speed_limit"}

    def test_applies_the_declared_transform(self, shipped_registry) -> None:
        panel = pd.DataFrame({"speed_limit": [50.0, 80.0]})
        factors = shipped_registry.available(panel.columns)
        design = build_design(panel, factors)
        assert design["speed_limit"].tolist() == pytest.approx(
            np.log([50.0, 80.0]).tolist()
        )

    def test_empty_factor_list_gives_empty_design(self) -> None:
        design = build_design(pd.DataFrame({"a": [1.0]}), [])
        assert design.shape[1] == 0
