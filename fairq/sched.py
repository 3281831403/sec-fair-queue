"""Weighted fair queue scheduling contracts.

The scheduler state is a plain dictionary so the tests can build small,
inspectable scenarios:

    {
        "now": 0.0,
        "burst_limit": 10.0,
        "tenants": {
            "alpha": {
                "weight": 1.0,
                "served": 0.0,
                "credit": 10.0,
                "last_refill": 0.0,
                "last_grant": 0.0,
            },
        },
    }

The eight public functions below are the complete implementation surface.
"""


def _tenant_entry(state: dict, tenant: str) -> dict:
    """Return a tenant's entry, raising KeyError when it is unknown."""
    try:
        return state["tenants"][tenant]
    except KeyError:
        raise KeyError(f"unknown tenant: {tenant!r}") from None


def _tenant_burst_limit(state: dict, entry: dict) -> float:
    """Return the burst limit that applies to one tenant.

    Tenants may carry their own ``burst_limit`` (used by ``queue_batch`` to
    honour per-tenant configuration); otherwise the state-wide limit applies.
    """
    if "burst_limit" in entry:
        return float(entry["burst_limit"])
    return float(state["burst_limit"])


def add_tenant(state: dict, tenant: str, weight: float) -> dict:
    """Add a tenant whose positive weight determines its share of service.

    The tenant starts with zero served work, one burst-limit worth of credit,
    and both timestamps equal to state["now"]. A non-positive weight is
    rejected with ValueError. Returns the same state dictionary.
    """
    weight = float(weight)
    if weight <= 0:
        raise ValueError(f"tenant {tenant!r} weight must be positive, got {weight!r}")

    burst_limit = float(state["burst_limit"])
    state["tenants"][tenant] = {
        "weight": weight,
        "served": 0.0,
        "credit": burst_limit,
        "last_refill": float(state["now"]),
        "last_grant": float(state["now"]),
    }
    return state


def virtual_time(state: dict, tenant: str) -> float:
    """Return the tenant virtual time, defined as served divided by weight."""
    entry = _tenant_entry(state, tenant)
    return float(entry["served"]) / float(entry["weight"])


def pick_next(state: dict) -> str:
    """Return the tenant with the smallest virtual time.

    Equal virtual times are resolved by ascending tenant name so insertion
    order can never change the result. The state is not modified.
    """
    tenants = state["tenants"]
    if not tenants:
        raise ValueError("cannot pick from an empty tenant set")

    # Virtual time is service volume / weight, so the comparison is valid
    # across tenants of different weights.
    return min(
        tenants,
        key=lambda name: (virtual_time(state, name), name),
    )


def charge(state: dict, tenant: str, cost: float) -> dict:
    """Charge cost units to a tenant and advance its virtual time.

    Reject a cost above the burst limit, or above the tenant's available
    credit, with ValueError before changing any state. A successful charge
    reduces credit, increases served work, and records the grant time as
    state["now"]. Returns the same state dictionary.
    """
    entry = _tenant_entry(state, tenant)
    cost = float(cost)

    if cost < 0:
        raise ValueError(f"charge cost must not be negative, got {cost!r}")

    # Validate everything before mutating anything, so a rejected charge
    # leaves served/credit/last_grant untouched.
    burst_limit = _tenant_burst_limit(state, entry)
    if cost > burst_limit:
        raise ValueError(
            f"charge cost {cost!r} exceeds burst limit {burst_limit!r} "
            f"for tenant {tenant!r}"
        )
    if cost > float(entry["credit"]):
        raise ValueError(
            f"charge cost {cost!r} exceeds available credit "
            f"{float(entry['credit'])!r} for tenant {tenant!r}"
        )

    entry["credit"] = float(entry["credit"]) - cost
    # Virtual time accumulates service volume, not call count.
    entry["served"] = float(entry["served"]) + cost
    entry["last_grant"] = float(state["now"])
    return state


def refill(state: dict, now: float, rate: float) -> dict:
    """Refill tenant credit from elapsed time and clip it to the burst limit.

    Each tenant receives (now - last_refill) * rate credit, capped at the
    configured burst limit, then state["now"] and last_refill are set to now.
    Calling twice with the same now therefore adds nothing. Returns the same
    state dictionary.
    """
    now = float(now)
    rate = float(rate)

    for tenant, entry in state["tenants"].items():
        last_refill = float(entry["last_refill"])
        # Credit accrues from real elapsed time, never from how often this
        # function is called. A backwards clock grants nothing.
        elapsed = now - last_refill
        if elapsed < 0:
            elapsed = 0.0

        credit = float(entry["credit"]) + elapsed * rate
        burst_limit = _tenant_burst_limit(state, entry)
        # Banked credit may never exceed the burst allowance.
        if credit > burst_limit:
            credit = burst_limit
        if credit < 0:
            credit = 0.0

        entry["credit"] = credit
        entry["last_refill"] = now

    state["now"] = now
    return state


def starvation_check(state: dict, threshold: float) -> list:
    """Return tenants whose actual wait since their last grant is enough.

    Wait is state["now"] minus last_grant, never a virtual-time difference.
    Eligible tenants are sorted by descending wait, with tenant name as the
    stable tie-breaker. Returns a list of tenant names.
    """
    now = float(state["now"])
    threshold = float(threshold)

    waiting = []
    for tenant, entry in state["tenants"].items():
        wait = now - float(entry["last_grant"])
        if wait >= threshold:
            waiting.append((tenant, wait))

    # Longest-waiting tenant first; names keep equal waits deterministic.
    waiting.sort(key=lambda item: (-item[1], item[0]))
    return [tenant for tenant, _wait in waiting]


def validate_config(config: dict) -> list[str]:
    """Return human-readable configuration problems, empty when valid.

    The expected shape is:

        {
            "tie_break": "name",
            "tenants": {
                "alpha": {"weight": 1.0, "burst_limit": 10.0},
            },
        }

    Issue strings must mention weight for a non-positive weight, burst_limit
    for a missing or non-positive burst limit, and tie_break when the rule is
    not name.
    """
    issues: list[str] = []

    if not isinstance(config, dict):
        return ["config must be a dictionary"]

    if config.get("tie_break") != "name":
        issues.append(
            f"tie_break must be 'name', got {config.get('tie_break')!r}"
        )

    tenants = config.get("tenants")
    if not isinstance(tenants, dict) or not tenants:
        issues.append("tenants must be a non-empty mapping")
        return issues

    for tenant, settings in tenants.items():
        if not isinstance(settings, dict):
            issues.append(f"tenant {tenant!r} settings must be a dictionary")
            continue

        weight = settings.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or float(weight) <= 0
        ):
            issues.append(
                f"tenant {tenant!r} weight must be a positive number, "
                f"got {weight!r}"
            )

        burst_limit = settings.get("burst_limit")
        if (
            isinstance(burst_limit, bool)
            or not isinstance(burst_limit, (int, float))
            or float(burst_limit) <= 0
        ):
            issues.append(
                f"tenant {tenant!r} burst_limit must be a positive number, "
                f"got {burst_limit!r}"
            )

    return issues


def queue_batch(requests: list[dict], config: dict) -> dict:
    """Schedule batches while giving every queue an independent state.

    Each request supplies a queue and a cost. Queues are discovered from the
    requests and each one is initialized separately from config, so work in
    one queue can never alter another queue's virtual times. Every request
    picks the next tenant and charges the requested cost.

    Returns:

        {
            "queues": {
                "queue-name": {
                    "grants": ["tenant", ...],
                    "state": {...},
                },
            },
        }
    """
    tenants_config = config.get("tenants", {})

    def new_state() -> dict:
        """Build a fresh state so queues never share virtual times."""
        burst_limits = [
            float(settings.get("burst_limit", 0.0))
            for settings in tenants_config.values()
            if isinstance(settings, dict)
        ]
        state = {
            "now": 0.0,
            "burst_limit": max(burst_limits) if burst_limits else 0.0,
            "tenants": {},
        }
        for tenant, settings in tenants_config.items():
            weight = float(settings.get("weight", 1.0))
            add_tenant(state, tenant, weight)
            if "burst_limit" in settings:
                # Honour per-tenant burst configuration inside this queue.
                limit = float(settings["burst_limit"])
                state["tenants"][tenant]["burst_limit"] = limit
                state["tenants"][tenant]["credit"] = limit
        return state

    queues: dict[str, dict] = {}

    for request in requests:
        queue = request["queue"]
        if queue not in queues:
            # One independent state per queue.
            queues[queue] = {"grants": [], "state": new_state()}

        state = queues[queue]["state"]
        tenant = pick_next(state)
        charge(state, tenant, float(request["cost"]))
        queues[queue]["grants"].append(tenant)

    return {"queues": queues}
