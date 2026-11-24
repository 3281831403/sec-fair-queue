"""Ten contract tests for the weighted fair queue scheduler.

Each test exercises one of the ten defects in the task statement. A correct
implementation must satisfy all ten contracts.
"""

import pytest

from fairq import sched


def make_state(burst_limit=100.0, now=0.0):
    """Create the minimal scheduler state used by the contract tests."""
    return {"now": float(now), "burst_limit": float(burst_limit), "tenants": {}}


def test_virtual_time_tracks_service_volume_not_call_count():
    state = make_state()
    sched.add_tenant(state, "alpha", 1.0)
    sched.add_tenant(state, "beta", 1.0)

    sched.charge(state, "alpha", 9.0)
    sched.charge(state, "beta", 3.0)

    assert sched.virtual_time(state, "alpha") == pytest.approx(9.0)
    assert sched.virtual_time(state, "beta") == pytest.approx(3.0)
    assert sched.virtual_time(state, "alpha") > sched.virtual_time(state, "beta")


def test_virtual_time_is_normalized_by_weight():
    state = make_state()
    sched.add_tenant(state, "alpha", 1.0)
    sched.add_tenant(state, "beta", 4.0)

    sched.charge(state, "alpha", 8.0)
    sched.charge(state, "beta", 8.0)

    assert sched.virtual_time(state, "alpha") == pytest.approx(8.0)
    assert sched.virtual_time(state, "beta") == pytest.approx(2.0)
    assert sched.virtual_time(state, "beta") < sched.virtual_time(state, "alpha")


def test_pick_next_breaks_ties_by_name_not_insertion_order():
    state = make_state()
    sched.add_tenant(state, "zeta", 1.0)
    sched.add_tenant(state, "alpha", 1.0)

    assert sched.pick_next(state) == "alpha"
    assert sched.pick_next(state) == "alpha"

    sched.charge(state, "alpha", 1.0)
    assert sched.pick_next(state) == "zeta"


def test_charge_rejects_above_burst_limit_before_deducting():
    state = make_state(burst_limit=5.0)
    sched.add_tenant(state, "alpha", 1.0)
    state["tenants"]["alpha"]["credit"] = 100.0

    with pytest.raises(ValueError):
        sched.charge(state, "alpha", 6.0)

    assert sched.virtual_time(state, "alpha") == pytest.approx(0.0)
    sched.charge(state, "alpha", 5.0)
    assert sched.virtual_time(state, "alpha") == pytest.approx(5.0)


def test_refill_uses_elapsed_time_not_call_count():
    state = make_state(burst_limit=10.0)
    sched.add_tenant(state, "alpha", 1.0)
    sched.charge(state, "alpha", 10.0)

    sched.refill(state, 1.0, 3.0)
    sched.refill(state, 1.0, 3.0)

    with pytest.raises(ValueError):
        sched.charge(state, "alpha", 4.0)
    sched.charge(state, "alpha", 3.0)


def test_refill_clips_credit_to_burst_limit():
    state = make_state(burst_limit=5.0)
    sched.add_tenant(state, "alpha", 1.0)
    sched.charge(state, "alpha", 5.0)

    sched.refill(state, 100.0, 100.0)

    sched.charge(state, "alpha", 5.0)
    with pytest.raises(ValueError):
        sched.charge(state, "alpha", 1.0)


def test_starvation_check_uses_actual_wait_not_virtual_time():
    state = make_state(now=0.0)
    sched.add_tenant(state, "old", 1.0)

    sched.refill(state, 100.0, 1.0)
    sched.add_tenant(state, "new", 1.0)

    assert sched.starvation_check(state, 50.0) == ["old"]


def test_starvation_list_is_sorted_by_wait_descending():
    state = make_state()
    sched.add_tenant(state, "a", 1.0)
    sched.add_tenant(state, "b", 1.0)
    sched.add_tenant(state, "c", 1.0)

    sched.refill(state, 20.0, 1.0)
    sched.charge(state, "c", 1.0)

    sched.refill(state, 50.0, 1.0)
    sched.charge(state, "b", 1.0)

    sched.refill(state, 100.0, 1.0)

    assert sched.starvation_check(state, 40.0) == ["a", "c", "b"]


def test_validate_config_flags_zero_weight_missing_burst_and_tie_rule():
    config = {
        "tie_break": "",
        "tenants": {
            "zero": {"weight": 0.0, "burst_limit": 5.0},
            "noburst": {"weight": 1.0},
        },
    }

    issues = sched.validate_config(config)
    report = " ".join(issues).lower()

    assert issues
    assert "weight" in report
    assert "burst" in report
    assert "tie" in report


def test_queue_batch_keeps_per_queue_state_independent():
    config = {
        "tie_break": "name",
        "tenants": {
            "alpha": {"weight": 1.0, "burst_limit": 100.0},
            "beta": {"weight": 1.0, "burst_limit": 100.0},
        },
    }

    standalone = sched.queue_batch(
        [{"queue": "second", "cost": 1.0}],
        config,
    )
    mixed = sched.queue_batch(
        [
            {"queue": "first", "cost": 1.0},
            {"queue": "second", "cost": 1.0},
        ],
        config,
    )

    assert standalone["queues"]["second"]["grants"] == ["alpha"]
    assert mixed["queues"]["second"]["grants"] == ["alpha"]