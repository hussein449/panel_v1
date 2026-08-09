"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from roadrisk.core.registry import Registry, load_registry
from roadrisk.demo import synthetic_panel

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def shipped_registry() -> Registry:
    """The registry that ships with the package. Every weight is unsourced."""
    return load_registry()


@pytest.fixture(scope="session")
def sourced_registry() -> Registry:
    """A registry with invented-but-cited weights, so Mode B can be exercised."""
    return load_registry(FIXTURES / "factors_sourced.yaml")


@pytest.fixture(scope="session")
def rich_panel() -> pd.DataFrame:
    """A panel with enough crashes for the top rung."""
    return synthetic_panel(n_units=120, n_periods=24, seed=7)


@pytest.fixture(scope="session")
def sparse_panel() -> pd.DataFrame:
    """A panel with enough crashes to fit, but not at A-full."""
    return synthetic_panel(n_units=120, n_periods=24, seed=11, intercept=-8.4)


@pytest.fixture(scope="session")
def starved_panel() -> pd.DataFrame:
    """A panel below the A-minimal floor. Mode B territory."""
    return synthetic_panel(n_units=60, n_periods=12, seed=13, intercept=-10.5)


@pytest.fixture(scope="session")
def crash_only_panel() -> pd.DataFrame:
    """Crash locations with no zero rows. Mode A must refuse this."""
    return synthetic_panel(n_units=120, n_periods=24, seed=7, crash_rows_only=True)
