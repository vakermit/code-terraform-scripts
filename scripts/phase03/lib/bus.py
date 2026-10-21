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

# Fallback only, for an allocation that declares no horizon of its own.
#
# A fixed number here was a bug. 900 seconds looked conservative and is in
# fact 145 planner passes: a world hour is about 25 simulation seconds at
# normal speed, so the planner's quarter-hour cadence comes round every six.
# A dead planner would have held the whole base on a stale lease for 145
# missed passes, and a kernel-silent test ran 41 passes without the lease
# ever going stale — the fail-safe branch was simply unreachable.
#
# So the publisher declares its own horizon in the allocation and readers
# honour it. This value applies only when one does not, and is deliberately
# tight: better a machine on its fail-safe than a machine obeying a ghost.
LEASE_STALE_S = 45

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
# The envelope is written by the safety loop, which builds the dict itself and
# publishes it through `publish`. There is deliberately no writer helper here:
# a library's registered copy inside the save can lag the file on disk, and a
# helper whose signature grows would then raise on every pass. Only the reader
# lives in the library, because every machine needs it and none of them write.
#
# ENVELOPE SHAPE
#   watts_free   W the planner may commit beyond the reserve
#   reserve_w    W held back and never offered
#   tonnes       {fluid_id: t/h}; a fluid ABSENT means unmeasured, not zero
#   autonomy_h   hours storage covers the deficit, or -1 when not drawing down
#   stored_wh    conventional battery energy, Lightning reserve excluded
#   hour         world-clock hour it was written
def envelope():
    """The current envelope, or None when safety is silent or stale."""
    return fresh(ENV, ENV_STALE_S)


# -------------------------------------------------------------------- leases
# NO WRITER HELPERS LIVE HERE, and that is a rule rather than an omission.
#
# The game runs the library copy recorded in the save, not the file on disk.
# That is proven, not suspected: the planner died on `publish_allocation()
# takes 2 positional arguments but 3 were given` while the file on disk had
# taken three for some time. Syncing the file does not update the running
# library, so any helper whose signature grows breaks every caller until the
# registration is rewritten.
#
# So writers depend only on `publish(channel, value)`, which is two arguments
# and always will be, and each loop builds its own payload. Readers are safe
# to share because their shape is fixed by the publisher.
#
# ALLOCATION SHAPE, written by the planner to ALLOC + outpost_id
#   ttl_s      simulation seconds this allocation should be believed for,
#              computed by the planner from its own cadence and the clock
#   machines   {machine_id: {resource: amount, "rank": n, "hour": h}}, or
#              {"run": True} for a machine that needs permission, not a
#              quantity
def lease(machine_id, outpost_id):
    """This machine's lease, or None when there is no fresh allowance for it.

    Four outcomes collapse to None, and callers must not tell them apart: no
    bus, nothing broadcast, an age past the payload's own horizon, and an
    allocation that simply does not name this machine. Every one of them
    means nobody is accounting for this machine right now, which is exactly
    what a fail-safe is for.
    """
    bus = _bus()
    if bus == None:
        return None
    info = bus.latest_info(ALLOC + outpost_id)
    if info == None or info.age_seconds == None:
        return None                        # see the None-age trap above
    payload = info.value
    if payload == None or not payload.has("machines"):
        return None
    limit = LEASE_STALE_S
    if payload.has("ttl_s") and payload["ttl_s"] > 0:
        limit = payload["ttl_s"]
    if info.age_seconds > limit:
        return None
    machines = payload["machines"]
    if not machines.has(machine_id):
        return None
    return machines[machine_id]


def allowance(machine_id, outpost_id, field, default=0):
    """One figure from this machine's lease, or `default` when there is none."""
    held = lease(machine_id, outpost_id)
    if held == None:
        return default
    if not held.has(field):
        return default
    return held[field]


# ---------------------------------------------------------------- shed order
# The shed order is written straight to SHED by the planner, for the same
# reason as the allocation: a list of machine ids worst-value first, which
# safety walks and never re-ranks.


def shed_order():
    """The planner's ranking, or an empty list when it is silent.

    Empty is meaningful: safety then falls back to its own conservative order
    rather than guessing at marginal value it has no model for.
    """
    ranked = fresh(SHED, LEASE_STALE_S)
    if ranked == None:
        return []
    return ranked
