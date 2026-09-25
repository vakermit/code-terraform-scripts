# =============================================================================
#  power  —  don't start work the grid cannot finish
# =============================================================================
#
#  Production and shipping draw hard and run for a long time. On a bad night
#  that empties the batteries, browns out the grid, and stops every script on
#  it — including the ones that would have refilled the store.
#
#  The grid reports everything needed to avoid that, so nothing here samples or
#  smooths: `power.grid(id)` gives generation, draw, net watts and stored Wh in
#  one snapshot. Hours-to-empty is just stored / -net.
#
#  POLICY. A hysteresis band, not a single threshold: hold below RESUME_PCT
#  once stopped, and only stop below PAUSE_PCT. One threshold makes scripts
#  flap on and off around the line, which is worse than either state.
#
#  This deliberately does NOT use breakers (power.set_powered). Switching a
#  machine off pauses its script and resumes it later, which is a second
#  control path to get wrong. Waiting inside the script keeps one owner.
# =============================================================================

PAUSE_PCT = 25       # stop starting new work below this
RESUME_PCT = 60      # ...and don't start again until back above this
POLL_HOURS = 0.5     # world-clock hours between checks while waiting


def control():
    """The power_control component, or None when it is unavailable."""
    return get_component("power_control")


def grid(target_id):
    """PowerGrid snapshot containing `target_id`, or None.

    `target_id` may be an outpost, building or field power-structure id. Returns
    None for a mobile unit, something under construction, or an unknown id, so
    every caller must handle None rather than assume a grid exists.
    """
    power = get_component("power_control")
    if power == None:
        return None
    return power.grid(target_id)


def state(target_id):
    """Everything a policy decision needs, as a plain dict.

    Keys: ok, pct, stored, capacity, net, generated, consumed, hours_left,
    daylight. `ok` is False when the grid could not be read, and then the
    numbers are zeros and callers should fall back to running normally rather
    than stalling forever on a missing component.

    `hours_left` is None while the grid is break-even or charging.
    """
    g = grid(target_id)
    if g == None:
        return {"ok": False, "pct": 0, "stored": 0, "capacity": 0, "net": 0,
                "generated": 0, "consumed": 0, "hours_left": None,
                "daylight": is_daylight()}
    pct = 0
    if g.capacity > 0:
        pct = g.stored * 100 / g.capacity
    return {"ok": True, "pct": pct, "stored": g.stored, "capacity": g.capacity,
            "net": g.net, "generated": g.generated, "consumed": g.consumed,
            "hours_left": hours_to_empty(g), "daylight": is_daylight()}


def hours_to_empty(g):
    """World-clock hours until this grid's batteries are flat, or None.

    None means the grid is break-even or charging. Uses conventional storage
    only: Lightning Rod reserve is spent last and is not a working buffer.
    """
    if g == None or g.net >= 0:
        return None
    return g.stored / -g.net


def hours_to_full(g):
    """World-clock hours until the batteries are full, or None when draining."""
    if g == None or g.net <= 0:
        return None
    room = g.capacity - g.stored
    if room <= 0:
        return 0
    return room / g.net


# ------------------------------------------------------------------ daylight
def is_daylight():
    """True while the sun is up. False when there is no clock."""
    clock = get_component("clock")
    if clock == None:
        return True
    return clock.get_elevation() > 0


def hours_until_dawn():
    """World-clock hours until sunrise, or 0 when the sun is already up.

    Dawn is not published directly, so this walks forward from the current hour
    to the next 06:00, which is when elevation crosses zero on Nocturna.
    """
    clock = get_component("clock")
    if clock == None:
        return 0
    if clock.get_elevation() > 0:
        return 0
    now = clock.get_time()[0]
    if now < 6:
        return 6 - now
    return 24 - now + 6


def sleep_hours(hours):
    """Sleep for world-clock `hours`, whatever the day-length pacing is."""
    clock = get_component("clock")
    if clock == None:
        sleep(hours * 25)            # default pacing fallback
        return
    sleep(clock.real_seconds_per_hour() * hours)


def sleep_until_dawn(max_hours=12):
    """One long sleep to sunrise rather than a poll loop. Returns hours slept."""
    hours = hours_until_dawn()
    if hours > max_hours:
        hours = max_hours
    if hours > 0:
        sleep_hours(hours)
    return hours


# -------------------------------------------------------------------- policy
def can_run(target_id, running, pause_pct=PAUSE_PCT, resume_pct=RESUME_PCT):
    """Should work continue right now?

    `running` is the caller's current state: pass True when mid-job, False when
    deciding whether to start. That is what makes the band hysteretic — a job
    already under way keeps going down to `pause_pct`, but a new one waits for
    `resume_pct`.

    Returns True when the grid cannot be read, so a missing power_control
    degrades to normal operation instead of a permanent stall.
    """
    s = state(target_id)
    if not s["ok"]:
        return True
    if running:
        return s["pct"] > pause_pct
    return s["pct"] >= resume_pct


def wait_for_charge(target_id, tag="", pause_pct=PAUSE_PCT, resume_pct=RESUME_PCT,
                    poll_hours=POLL_HOURS):
    """Block until the grid is back above `resume_pct`. Returns hours waited.

    Returns 0 immediately when there is charge to spare, so this is cheap to
    call at the top of every loop. While waiting at night with nothing coming
    in, it sleeps to dawn in one step instead of polling in the dark.
    """
    s = state(target_id)
    if not s["ok"] or s["pct"] >= resume_pct:
        return 0
    waited = 0
    print("[" + tag + "] power " + str(int(s["pct"])) + "%, holding until "
          + str(resume_pct) + "%")
    while True:
        s = state(target_id)
        if not s["ok"] or s["pct"] >= resume_pct:
            break
        if not s["daylight"] and s["net"] <= 0:
            waited = waited + sleep_until_dawn()
        else:
            sleep_hours(poll_hours)
            waited = waited + poll_hours
    print("[" + tag + "] power " + str(int(s["pct"])) + "%, resuming after "
          + str(round(waited, 1)) + "h")
    return waited


def report(target_id):
    """One-line grid summary for the console or a status broadcast."""
    s = state(target_id)
    if not s["ok"]:
        return "power: unknown"
    line = ("power " + str(int(s["pct"])) + "% (" + str(int(s["stored"])) + "/"
            + str(int(s["capacity"])) + " Wh) net " + str(int(s["net"])) + " W")
    if s["hours_left"] != None:
        line = line + ", " + str(round(s["hours_left"], 1)) + "h left"
    return line
