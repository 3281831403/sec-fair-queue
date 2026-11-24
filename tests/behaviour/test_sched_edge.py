"""Five behaviour tests for weighted fairness, burst limits and isolation."""

import pytest

from fairq import sched


def make_state(burst_limit=100.0, now=0.0):
    return {"now": float(now), "burst_limit": float(burst_limit), "tenants": {}}


def test_two_tenants_receive_quota_in_weight_proportion():
    state = make_state()
    sched.add_tenant(state, "alpha", 1.0)
    sched.add_tenant(state, "beta", 3.0)

    grants = {"alpha": 0, "beta": 0}
    for _ in range(40):
        tenant = sched.pick_next(state)
        grants[tenant] += 1
        sched.charge(state, tenant, 1.0)

    assert grants == {"alpha": 10, "beta": 30}


def test_single_tenant_cannot_exceed_burst_limit():
    state = make_state(burst_limit=5.0)
    sched.add_tenant(state, "alpha", 1.0)

    sched.charge(state, "alpha", 5.0)
    with pytest.raises(ValueError):
        sched.charge(state, "alpha", 1.0)

    assert sched.virtual_time(state, "alpha") == pytest.approx(5.0)


def test_pick_next_is_stable_for_equal_virtual_time():
    state = make_state()
    sched.add_tenant(state, "gamma", 1.0)
    sched.add_tenant(state, "beta", 1.0)
    sched.add_tenant(state, "alpha", 1.0)

    assert sched.pick_next(state) == "alpha"
    sched.charge(state, "alpha", 1.0)
    assert sched.pick_next(state) == "beta"
    sched.charge(state, "beta", 1.0)
    assert sched.pick_next(state) == "gamma"


def test_long_waiting_tenant_is_prioritized():
    state = make_state(now=0.0)
    sched.add_tenant(state, "starved", 1.0)

    sched.refill(state, 100.0, 1.0)
    sched.add_tenant(state, "busy", 1.0)
    sched.charge(state, "busy", 30.0)

    assert sched.starvation_check(state, 50.0) == ["starved"]
    assert sched.pick_next(state) == "starved"


def test_two_batches_match_separate_runs():
    config = {
        "tie_break": "name",
        "tenants": {
            "alpha": {"weight": 1.0, "burst_limit": 100.0},
            "beta": {"weight": 1.0, "burst_limit": 100.0},
        },
    }
    requests = [
        {"queue": "first", "cost": 1.0},
        {"queue": "second", "cost": 1.0},
        {"queue": "first", "cost": 1.0},
        {"queue": "second", "cost": 1.0},
        {"queue": "first", "cost": 1.0},
        {"queue": "second", "cost": 1.0},
    ]

    mixed = sched.queue_batch(requests, config)
    for queue in ("first", "second"):
        only_this_queue = [item for item in requests if item["queue"] == queue]
        solo = sched.queue_batch(only_this_queue, config)
        assert (
            mixed["queues"][queue]["grants"]
            == solo["queues"][queue]["grants"]
        )