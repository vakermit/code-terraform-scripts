# =============================================================================
#  control  —  one place decides, every machine obeys
# =============================================================================
#
#  Hardware actions are self-only: no script can drive another machine's drill
#  or recipe. So central control is not central execution. The controller
#  decides and broadcasts a policy; machine scripts stay thin loops that read
#  it and act on their own `self`.
#
#  THE CONTRACT.  control.policy   broadcast   controller -> everything
#
#    {"mode": "normal" | "conserve" | "emergency",
#     "power_pct": 0-100,
#     "allow": {"production": bool, "bio": bool, "mining": bool,
#               "exploration": bool},
#     "mine": {ore_id: units},        # what the rover should favour
#     "hour": <world-clock hour the policy was written>}
#
#  EVERY HELPER DEGRADES.  With no controller running, `policy()` returns None
#  and `allows()` answers True. A machine must never stall because the
#  controller is stopped, so the absence of policy means "use your own
#  judgement", which is exactly what these scripts did before.
#
#  STALENESS.  A controller that dies leaves its last broadcast on the bus
#  forever. Policy older than STALE_HOURS is ignored rather than obeyed, so a
#  crashed controller cannot hold the base in conserve mode indefinitely.
# =============================================================================

from signals import latest

CHANNEL = "control.policy"
STALE_HOURS = 6
SUBSYSTEMS = ["production", "bio", "mining", "exploration"]


def now_hour():
    """Absolute world-clock hour, so staleness survives midnight."""
    clock = get_component("clock")
    if clock == None:
        return 0
    return clock.get_day() * 24 + clock.get_time()[0]


def policy():
    """The current policy, or None when there is no fresh one.

    None means no controller, a crashed controller, or one that has not
    published yet. Callers treat all three the same: decide locally.
    """
    p = latest(CHANNEL)
    if p == None:
        return None
    if not p.has("hour"):
        return p                        # no timestamp: trust it
    age = now_hour() - p["hour"]
    if age < 0 or age > STALE_HOURS:
        return None
    return p


def allows(subsystem, default=True):
    """May `subsystem` do discretionary work right now?

    True whenever there is no policy, so a stopped controller never stops the
    base. Only an explicit False in a fresh policy holds work back.
    """
    p = policy()
    if p == None or not p.has("allow"):
        return default
    allow = p["allow"]
    if not allow.has(subsystem):
        return default
    return allow[subsystem]


def mode(default="normal"):
    """Current operating mode: normal, conserve, or emergency."""
    p = policy()
    if p == None or not p.has("mode"):
        return default
    return p["mode"]


def mine_targets():
    """Ore the controller wants prioritised, as {ore_id: units}, or {}.

    Empty means "no central preference" — the rover falls back to reading the
    factory channels itself.
    """
    p = policy()
    if p == None or not p.has("mine"):
        return {}
    return p["mine"]


def publish(comms, mode_name, power_pct, allow, mine):
    """Write a policy to the bus. Only the controller should call this.

    Passing comms in rather than resolving it keeps the caller honest about
    owning the broadcast, and makes a dry-run controller trivial.
    """
    if comms == None:
        return False
    body = {}
    body["mode"] = mode_name
    body["power_pct"] = int(power_pct)
    body["allow"] = allow
    body["mine"] = mine
    body["hour"] = now_hour()
    comms.broadcast(CHANNEL, body)
    return True


def decide(power_pct, thresholds=None):
    """Map grid charge to a mode and per-subsystem permissions.

    Subsystems are shed in increasing order of how much the base needs them.
    Exploration is pure investment and goes first. Bio is a credit engine that
    can wait. Production is the order pipeline and goes last of the
    discretionary work. Mining survives into conserve because an empty ore
    store stalls everything once power returns.

    Atmosphere and sensors are never listed: they are life support and this
    never touches them.
    """
    if thresholds == None:
        thresholds = {"conserve": 60, "emergency": 35}
    allow = {}
    if power_pct < thresholds["emergency"]:
        name = "emergency"
        for s in SUBSYSTEMS:
            allow[s] = False
    elif power_pct < thresholds["conserve"]:
        name = "conserve"
        allow["production"] = True
        allow["mining"] = True
        allow["bio"] = False
        allow["exploration"] = False
    else:
        name = "normal"
        for s in SUBSYSTEMS:
            allow[s] = True
    return {"mode": name, "allow": allow}
