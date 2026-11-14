from dataclasses import replace
from datetime import timedelta

import pytest

from rateguard.analytics import bps, evaluate

from .conftest import DAY


def changed(rows, provider="fred", tenor=10, **changes):
    return [
        replace(row, **changes) if row.provider == provider and row.tenor_years == tenor else row
        for row in rows
    ]


@pytest.mark.parametrize(
    ("fred", "delta", "status"),
    [
        (5.15, 0, "OK"),
        (5.13, 2, "OK"),
        (5.1299, 2.01, "WARNING"),
        (5.10, 5, "WARNING"),
        (5.0999, 5.01, "CRITICAL"),
        (5.17, 2, "OK"),
    ],
)
def test_reconciliation_boundaries(observations, settings, fred, delta, status):
    report = evaluate(changed(observations, yield_pct=fred), DAY, settings)
    result = next(r for r in report["reconciliation"] if r["tenor_years"] == 10)
    assert result["absolute_difference_bps"] == delta
    assert result["status"] == status


def test_percent_to_bps():
    assert bps(5.15, 5.13) == 2
    assert bps(5.13, 5.15) == -2


@pytest.mark.parametrize("value", [None, 30, -6])
def test_invalid_value_blocks_curve_and_reconciliation(observations, settings, value):
    report = evaluate(changed(observations, yield_pct=value), DAY, settings)
    assert report["status"] == "CRITICAL"
    assert report["curves"][1]["shape"] == "INCOMPLETE"
    assert report["curves"][1]["spreads_bps"] == {}
    assert report["reconciliation"][2]["absolute_difference_bps"] is None


def test_duplicate_even_if_same_value_is_critical(observations, settings):
    report = evaluate(observations + [observations[-1]], DAY, settings)
    assert report["status"] == "CRITICAL"
    assert report["points"][-1]["issues"][0]["code"] == "duplicate"


def test_no_forward_fill_or_cross_date_comparison(observations, settings):
    report = evaluate(
        changed(observations, observation_date=DAY - timedelta(days=1)), DAY, settings
    )
    point = report["points"][6]
    assert point["yield_pct"] is None
    assert point["last_valid_date"] == "2025-01-07"
    assert point["issues"][0]["code"] == "missing_date"
    assert report["reconciliation"][2]["absolute_difference_bps"] is None


def test_stale_and_empty(observations, settings):
    rows = [replace(row, observation_date=DAY - timedelta(days=10)) for row in observations]
    for report in (evaluate(rows, DAY, settings), evaluate([], DAY, settings)):
        assert report["status"] == "CRITICAL"
        assert all(any(i["code"] == "stale" for i in p["issues"]) for p in report["points"])


@pytest.mark.parametrize(
    ("slope", "shape"),
    [
        (0.06, "NORMAL"),
        (0.05, "FLAT"),
        (0, "FLAT"),
        (-0.05, "FLAT"),
        (-0.06, "INVERTED"),
    ],
)
def test_curve_classification_boundaries(observations, settings, slope, shape):
    rows = changed(observations, "treasury", 10, yield_pct=round(4.8 + slope, 2))
    report = evaluate(rows, DAY, settings)
    assert report["curves"][0]["shape"] == shape
    assert report["curves"][0]["spreads_bps"]["10Y-2Y"] == round(slope * 100, 2)


def test_normal_slope_can_have_local_inversion(observations, settings):
    report = evaluate(changed(observations, "treasury", 5, yield_pct=5.2), DAY, settings)
    assert report["curves"][0]["shape"] == "NORMAL"
    assert report["curves"][0]["has_local_inversion"] is True


def test_jump_warning(observations, settings):
    past = replace(observations[0], observation_date=DAY - timedelta(days=1), yield_pct=2)
    report = evaluate([past, *observations], DAY, settings)
    assert report["points"][0]["status"] == "WARNING"
    assert report["reconciliation"][0]["status"] == "WARNING"


def test_revision_observed_between_runs(observations, settings):
    previous = evaluate(observations, DAY, settings)
    report = evaluate(changed(observations, yield_pct=5.14), DAY, settings, previous)
    assert report["reconciliation"][2]["absolute_difference_bps"] == 1
    assert report["reconciliation"][2]["status"] == "WARNING"
    assert report["points"][6]["issues"][0]["code"] == "observed_revision"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ok_bps": 5, "warning_bps": 2},
        {"flat_bps": -1},
        {"jump_bps": float("nan")},
    ],
)
def test_invalid_configuration(settings, kwargs):
    with pytest.raises(ValueError):
        replace(settings, **kwargs)
