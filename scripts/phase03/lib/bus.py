# =============================================================================
#  bus  —  the envelope, the leases, the shed order
# =============================================================================
#
#  Three broadcasts carry the whole control plane, and they flow one way:
#
#    env                 safety  -> everyone     what is available to spend
#    alloc.<outpost_id>  planner -> machines     who gets how much of it
#    shed                planner -> safety       what to cut first, ranked
#
#  A broadcast rather than a queue, because a lease is a current value many
#  readers need, not work for one consumer to take. And on the bus rather
#  than in the Data Archive, because a machine must know how OLD its lease is
#  and the Archive records no age.
#
#  THE NONE-AGE TRAP.  latest_info() reports age_seconds as None for a
#  broadcast restored from a save without usable timestamp information. The
#  obvious freshness check, `info.age_seconds > limit`, is then a comparison
#  against None: the machine either raises or decides the lease is fine, and
#  a fail-safe that never fires after a reload is worse than no fail-safe at
#  all. `fresh()` is the only place that comparison is written, and it treats
#  an unknown age as stale.
#
#  Payload budget: a channel allows 1,024 values at 8 levels. An allocation
#  is one broadcast per outpost holding {machine_id: {...}}, so fifty
#  machines of four fields each is 200 values with room to spare. One channel
#  per outpost rather than one per machine, because the save allows 512
#  channels in total and a late base would spend them all on leases.
# =============================================================================

ENV = "env"
SHED = "shed"
ALLOC = "alloc."          # + outpost id

# A lease older than this is no lease. Generous against the planner's slow
# cadence, tight enough that a dead planner is noticed within a work cycle.
LEASE_STALE_S = 900

# The safety loop republishes far more often than the planner, so its own
# envelope is held to a much shorter life.
ENV_STALE_S = 120


def _bus():
    return get_component("comms")


def fresh(channel, limit_s):
    """The broadcast value on `channel` when it is fresh, else None.

    An absent bus, a channel never broadcast, an unknown age and an age past
    `limit_s` all answer None. Callers cannot tell those apart and must not:
    every one of them means "nobody is telling me what to do right now".
    """
    bus = _bus()
    if bus == None:
        return None
    info = bus.latest_info(channel)
    if info == None:
        return None
    if info.age_seconds == None:          # restored from a save; see the banner
        return None
    if info.age_seconds > limit_s:
        return None
    return info.value


def publish(channel, value):
    """Broadcast `value`. True when the bus accepted it."""
    bus = _bus()
    if bus == None:
        return False
    result = bus.broadcast(channel, value)
    if result.status != "ok":
        print(f"bus: {channel} rejected, {result.message}")
        return False
    return True


# ------------------------------------------------------------------ envelope
def publish_envelope(watts_free, reserve_w, tonnes, hour):
    """Safety's view of what is spendable. `tonnes` is {fluid_id: t/h free}."""
    return publish(ENV, {
        "watts_free": watts_free,
        "reserve_w": reserve_w,
        "tonnes": tonnes,
        "hour": hour,
    })


def envelope():
    """The current envelope, or None when safety is silent or stale."""
    return fresh(ENV, ENV_STALE_S)


# -------------------------------------------------------------------- leases
def publish_allocation(outpost_id, machines):
    """The planner's allocation for one outpost: {machine_id: {field: value}}."""
    return publish(ALLOC + outpost_id, machines)


def lease(machine_id, outpost_id):
    """This machine's lease, or None when there is no fresh allocation for it.

    An allocation that is fresh but does not name this machine is still None:
    a machine the planner did not mention has no allowance, which is a
    different thing from the planner being silent only in its consequences —
    both land the machine on its own fail-safe.
    """
    allocation = fresh(ALLOC + outpost_id, LEASE_STALE_S)
    if allocation == None:
        return None
    if not allocation.has(machine_id):
        return None
    return allocation[machine_id]


def allowance(machine_id, outpost_id, field, default=0):
    """One figure from this machine's lease, or `default` when there is none."""
    held = lease(machine_id, outpost_id)
    if held == None:
        return default
    if not held.has(field):
        return default
    return held[field]


# ---------------------------------------------------------------- shed order
def publish_shed(ranked):
    """Machine ids worst-value first. Safety walks this; it never re-ranks."""
    return publish(SHED, ranked)


def shed_order():
    """The planner's ranking, or an empty list when it is silent.

    Empty is meaningful: safety then falls back to its own conservative order
    rather than guessing at marginal value it has no model for.
    """
    ranked = fresh(SHED, LEASE_STALE_S)
    if ranked == None:
        return []
    return ranked
