"""Run log and manifest — the reproducibility guarantees."""

from __future__ import annotations

import pandas as pd

from roadrisk.core.runlog import Level, RunLog, build_manifest, hash_frame


def frame() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": [0.5, 0.5, 0.5]})


class TestRunLog:
    def test_events_are_sequenced_in_order(self) -> None:
        log = RunLog()
        log.info("stage", "one", "first")
        log.warning("stage", "two", "second")

        assert [e.sequence for e in log] == [1, 2]
        assert len(log) == 2

    def test_levels_are_queryable(self) -> None:
        log = RunLog()
        log.info("s", "a", "m")
        log.refusal("s", "b", "m")
        log.flag("s", "c", "m")

        assert len(log.of_level(Level.REFUSAL)) == 1
        assert len(log.of_level(Level.FLAG)) == 1

    def test_data_is_carried_through_to_records(self) -> None:
        log = RunLog()
        log.descent("mode_selection", "insufficient_crashes", "stepped down", rung="A-full")

        record = log.as_records()[0]
        assert record["level"] == "descent"
        assert record["data"]["rung"] == "A-full"
        assert record["timestamp"]

    def test_events_property_returns_a_copy(self) -> None:
        log = RunLog()
        log.info("s", "a", "m")
        log.events.clear()
        assert len(log) == 1


class TestHashFrame:
    def test_is_stable(self) -> None:
        assert hash_frame(frame()) == hash_frame(frame())

    def test_changes_with_values(self) -> None:
        altered = frame()
        altered.loc[0, "a"] = 99
        assert hash_frame(frame()) != hash_frame(altered)

    def test_changes_with_column_names(self) -> None:
        renamed = frame().rename(columns={"a": "z"})
        assert hash_frame(frame()) != hash_frame(renamed)


class TestManifest:
    def test_fingerprint_ignores_creation_time(self) -> None:
        first = build_manifest(frame(), registry_version="1", registry_sha256="abc")
        second = build_manifest(frame(), registry_version="1", registry_sha256="abc")

        assert first.fingerprint == second.fingerprint

    def test_fingerprint_tracks_the_registry(self) -> None:
        first = build_manifest(frame(), registry_version="1", registry_sha256="abc")
        second = build_manifest(frame(), registry_version="2", registry_sha256="def")

        assert first.fingerprint != second.fingerprint

    def test_fingerprint_tracks_the_settings(self) -> None:
        first = build_manifest(
            frame(), registry_version="1", registry_sha256="a", settings={"cap": 25}
        )
        second = build_manifest(
            frame(), registry_version="1", registry_sha256="a", settings={"cap": 50}
        )

        assert first.fingerprint != second.fingerprint

    def test_records_the_environment(self) -> None:
        manifest = build_manifest(frame(), registry_version="1", registry_sha256="a")

        assert manifest.engine_version
        assert manifest.python_version
        assert "pandas" in manifest.package_versions
        assert manifest.panel_shape == (3, 2)

    def test_serialises_with_the_fingerprint_included(self) -> None:
        payload = build_manifest(
            frame(), registry_version="1", registry_sha256="a"
        ).as_dict()

        assert payload["fingerprint"]
        assert payload["panel_shape"] == [3, 2]
