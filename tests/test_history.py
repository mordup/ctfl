from __future__ import annotations

import json
from datetime import date

import pytest

from ctfl.providers import history
from ctfl.providers.history import DayRecord, history_start


def _record() -> DayRecord:
    return DayRecord(
        messages=3,
        sessions=1,
        tokens={("claude-opus-5", "standard"): (100, 50, 10, 6, 4, 2)},
        projects={"-home-me-ctfl": ("Ctfl", 166, 3)},
    )


@pytest.mark.parametrize(("today", "start"), [
    (date(2026, 10, 2), date(2026, 9, 1)),
    (date(2026, 8, 31), date(2026, 7, 1)),
    (date(2026, 3, 1), date(2026, 2, 1)),
    (date(2026, 1, 15), date(2025, 12, 1)),
])
def test_history_start_is_first_of_previous_month(today, start):
    assert history_start(today) == start


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "h.json"
    history.save(path, {"2026-09-30": _record()})
    assert history.load(path) == {"2026-09-30": _record()}


def test_load_missing_or_corrupt_file_is_empty(tmp_path):
    path = tmp_path / "h.json"
    assert history.load(path) == {}
    path.write_text("{not json")
    assert history.load(path) == {}


def test_load_skips_malformed_days(tmp_path):
    path = tmp_path / "h.json"
    history.save(path, {"2026-09-30": _record(), "2026-09-29": _record()})
    raw = json.loads(path.read_text())
    raw["days"]["2026-09-29"]["tokens"][0][2] = -5
    raw["days"]["not-a-date"] = raw["days"]["2026-09-30"]
    path.write_text(json.dumps(raw))
    assert list(history.load(path)) == ["2026-09-30"]


def test_load_from_newer_version_is_refused(tmp_path):
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"version": 99, "days": {}}))
    assert history.load(path) is None


def test_saved_file_is_private(tmp_path):
    path = tmp_path / "h.json"
    history.save(path, {})
    assert path.stat().st_mode & 0o777 == 0o600


def test_unreadable_file_is_left_alone(tmp_path):
    path = tmp_path / "h.json"
    history.save(path, {"2026-09-30": _record()})
    path.chmod(0)
    try:
        assert history.load(path) is None
    finally:
        path.chmod(0o600)
