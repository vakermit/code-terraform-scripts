# =============================================================================
#  capability  —  ask what exists before using it
# =============================================================================
#
#  Half of this platform's components are behind research. `comms` is None
#  before Signal Bus, `notebook` before Data Archive, `markers` before
#  Cartography, `terraforming` before the Index is readable. A kernel that
#  assumes any of them is a kernel that raises on a fresh save and takes the
#  whole base down with it.
#
#  So nothing calls get_component() directly. Every component has a named
#  accessor here that returns None when it is absent, and `report()` renders
#  the whole picture in one line for a loop's first print. Degrading is the
#  normal path, not the error path.
#
#  There is no caching. A handle goes stale when its module is unmounted and
#  a component can appear mid-save when its research lands, so each call asks
#  the game again. These are cheap reads.
# =============================================================================

# What the kernel needs, and what it loses without each one.
NEEDS = {
    "comms": "live coordination; without it every machine holds its fail-safe",
    "notebook": "durable memory; without it nothing is learned across a reload",
    "power_control": "the envelope and the breaker; without it there is no safety loop",
    "outpost_network": "machine discovery; without it nothing can be enumerated",
    "terraforming": "pillar gaps; without them the planner cannot rank",
    "clock": "world time; without it staleness cannot be measured",
}


def comp(name):
    """A component by id, or None. The one place get_component() is called."""
    return get_component(name)


def comms():
    return get_component("comms")


def notebook():
    return get_component("notebook")


def power():
    return get_component("power_control")


def runner():
    return get_component("run_control")


def network():
    return get_component("outpost_network")


def fleet():
    return get_component("fleet")


def terraforming():
    return get_component("terraforming")


def clock():
    return get_component("clock")


def missing():
    """The ids from NEEDS that are not available right now, in NEEDS order."""
    absent = []
    for name in NEEDS:
        if get_component(name) == None:
            absent.append(name)
    return absent


def report(loop_name):
    """One line naming what this loop is running without. True when all present."""
    absent = missing()
    if len(absent) == 0:
        print(f"{loop_name}: all components present")
        return True
    print(f"{loop_name}: running degraded, missing {', '.join(absent)}")
    for name in absent:
        print(f"  no {name} -> {NEEDS[name]}")
    return False


def outpost_of(machine):
    """The outpost id owning `machine`, or "" when it cannot be resolved.

    Pass `self` in: a library has no `self` of its own. Resolved by matching
    the machine's id against the buildings of its own type at each outpost,
    which uses nothing but ids — a stationary machine has no position() to
    ask, and a display name is renameable.
    """
    if machine == None:
        return ""
    net = get_component("outpost_network")
    if net == None:
        return ""
    for outpost in net.outposts():
        for ref in outpost.buildings(machine.type_id):
            if ref.id == machine.id:
                return outpost.id
    return ""


def now_hour():
    """Absolute world-clock hour, so an age survives midnight. 0 without a clock."""
    c = get_component("clock")
    if c == None:
        return 0
    return c.get_day() * 24 + c.get_time()[0]


def hours(h):
    """Sleep `h` world hours, falling back to a rough constant with no clock."""
    c = get_component("clock")
    if c == None:
        sleep(h * 25)
        return
    sleep(c.real_seconds_per_hour() * h)
