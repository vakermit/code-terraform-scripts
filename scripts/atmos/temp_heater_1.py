# ============================================================
#  HEAT GENERATOR - learns the state -> power table, then holds it
# ============================================================
#  The planet picks a thermal state once per day and keeps it.
#  Each state has its own optimal set_power() value, and
#  efficiency() falls off LINEARLY with distance from it. That
#  makes efficiency a gradient, not just a pass/fail light:
#  a full sweep tells us the peak in one pass, and reading it
#  back afterwards proves the table entry is still right.
#
#  Once a state is learned it is never searched again, so the
#  cost is at most four searches for the life of the run.
#
#  >>> The script PRINTS a paste-ready TABLE line whenever it
#  >>> learns something. Paste it into TABLE below and future
#  >>> runs hit 100% instantly with no searching at all.
# ============================================================

# Paste discovered values here, e.g.
#   TABLE = {"clear": 5, "dust_storm": 8, "heat_bleed": 2, "dust_veil": 6}
TABLE = {}

POWER_MIN     = 0      # set_power() range per the machine docs
POWER_MAX     = 10
COARSE_STEP   = 1      # optima are very likely whole watts
FINE_STEP     = 0.25   # only used if no whole watt reaches 100%
EFF_TARGET    = 100    # efficiency() that means "exactly right"
RELEARN_BELOW = 99.0   # a hardcoded entry scoring under this gets re-searched
TICK_SLEEP    = 1      # game-hours between checks. The state only changes at
                       # midnight, so this is purely how long we can be caught
                       # holding yesterday's power - a loss of TICK_SLEEP/24.
MAX_TICKS     = 900    # Sized to the step limit, NOT to taste. At ~8 steps a
                       # tick, 900 uses 7354 of 10000; 1200 uses 9736, too
                       # close. Raising TICK_SLEEP also raises step cost, so
                       # drop MAX_TICKS if you raise it.
                       #
                       # Measured, table pre-pasted:
                       #   TS=1 ->  37.5 days/run, 95.9% of time at 100%
                       #   TS=2 ->  75.0 days/run, 91.7%
                       #   TS=3 -> 112.5 days/run, 87.6%
                       #   TS=4 -> 150.0 days/run, 83.3%   (9135 steps)
                       #
                       # output() is 0 while no script runs, so a run that
                       # ends is worse than one that is slightly off-optimal.
                       # Effective output including the stopped time:
                       #        restart same day   after 5d   after 20d
                       #   TS=1        95.9%         84.6%      62.5%
                       #   TS=2        91.7%         85.9%      72.4%
                       #   TS=3        87.6%         83.8%      74.3%
                       # Restart promptly -> keep TS=1. If it sits idle for
                       # days between runs, TS=2 or 3 nets you more heat.
CHECK_EVERY   = 24     # ticks between health checks; the state cannot change
                       # mid-day, so verifying every tick just burns steps
VERBOSE       = True

clock = get_component("clock")


def say(msg):
    if VERBOSE:
        print(msg)


# Paste-ready, so a learned table survives into the next run.
def report():
    s = ""
    for k in TABLE:
        if s != "":
            s = s + ", "
        s = s + '"' + k + '": ' + str(TABLE[k])
    print("TABLE = {" + s + "}      <-- paste this into the script")


def probe(w):
    self.set_power(w)
    return self.efficiency()


# Snap float drift so the printed table pastes back as 8, not 8.000000001.
# Only moves a value that is already within a rounding error of a clean one.
def tidy(w):
    n = int(w / FINE_STEP + 0.5) * FINE_STEP
    if w - n < 0.000001 and n - w < 0.000001:
        w = n
    n = int(w + 0.5)
    if w - n < 0.000001 and n - w < 0.000001:
        return n
    return w


# Efficiency falls off LINEARLY, so two probes give the slope and the slope
# points straight at the peak - no sweep needed. Probe the middle of the
# range, step one watt, and read how much efficiency moved: that is the cost
# per watt of error, so the remaining error is (100 - eff) / slope.
#
# Two things can fool it: a peak sitting between the two probes (the readings
# straddle it, so the slope is wrong) and a falloff steep enough to clamp a
# reading at 0 (no gradient to read). Both are caught by verifying the answer
# with a third probe, and both fall back to the sweep, so the fast path can
# never return a wrong value - only fail to find one.
def solve(state):
    a = 5
    b = 6
    ea = probe(a)
    if ea >= EFF_TARGET:
        return a, ea
    eb = probe(b)
    if eb >= EFF_TARGET:
        return b, eb
    if ea > 0 and eb > 0 and ea != eb:
        slope = eb - ea
        if slope < 0:
            slope = -slope
        if eb > ea:
            w = b + (EFF_TARGET - eb) / slope      # peak is above b
        else:
            w = a - (EFF_TARGET - ea) / slope      # peak is below a
        w = tidy(w)
        if w >= POWER_MIN and w <= POWER_MAX:
            e = probe(w)
            if e >= EFF_TARGET:
                return w, e
    return find_best(state)


# Sweep whole watts first and stop the moment we hit 100% - every probe spent
# is a tick running off-optimal, which the docs say wastes energy AND cuts
# output, so the early exit is worth having.
#
# If no whole watt is perfect the optimum sits between them, so we re-sweep
# the winning watt's neighbourhood at FINE_STEP. And if the whole sweep came
# back flat zero, the falloff is steep enough to clamp every probe at 0 and
# the coarse winner is meaningless - so sweep the entire range fine instead.
def find_best(state):
    best_w = POWER_MIN
    best_e = -1
    w = POWER_MIN
    while w <= POWER_MAX:
        e = probe(w)
        if e > best_e:
            best_e = e
            best_w = w
        if e >= EFF_TARGET:
            return best_w, best_e
        w = w + COARSE_STEP

    if best_e <= 0:
        lo = POWER_MIN            # everything clamped; nothing to zoom in on
        hi = POWER_MAX
    else:
        lo = best_w - COARSE_STEP
        hi = best_w + COARSE_STEP
        if lo < POWER_MIN:
            lo = POWER_MIN
        if hi > POWER_MAX:
            hi = POWER_MAX

    w = lo
    while w <= hi:
        e = probe(w)
        if e > best_e:
            best_e = e
            best_w = w
        if e >= EFF_TARGET:
            return tidy(best_w), best_e
        w = w + FINE_STEP
    return tidy(best_w), best_e


# ---------- per-state logic ------------------------------------------------

# Look up or learn the power for a state, and prove it against the live
# reading before trusting it.
def pick(state):
    if state in TABLE:
        w = TABLE[state]
        self.set_power(w)
        e = self.efficiency()
        if e >= RELEARN_BELOW:
            say("day " + str(clock.get_day()) + " " + state + " -> " + str(w) +
                " (" + str(e) + "%)")
            return w
        if state in searched:
            return w                  # already tried; nothing better to find
        say(state + " only " + str(e) + "% at " + str(w) + " - re-searching")
    searched[state] = 1
    w, e = solve(state)
    TABLE[state] = w
    say("day " + str(clock.get_day()) + " " + state + " -> " + str(w) +
        " at " + str(e) + "%")
    report()
    return w


# Periodic health check. Kept out of the per-tick path: the state cannot
# change mid-day, so re-verifying every single tick buys nothing and the
# steps it costs are steps the run cannot spend staying alive.
def audit(state, power):
    e = self.efficiency()
    if e < RELEARN_BELOW and state not in searched:
        searched[state] = 1
        say(state + " drifted to " + str(e) + "% - re-searching")
        power, e = solve(state)
        TABLE[state] = power
        self.set_power(power)
        report()
    d = self.is_degraded()
    if d != flags["deg"]:
        flags["deg"] = d
        if d:
            say("DEGRADED - Mk III starved, running as tier " +
                str(self.effective_tier()) + "; check steam_in level")
        else:
            say("recovered - tier " + str(self.effective_tier()))
    return power


# ---------- main -----------------------------------------------------------
while True:
    state = ""
    power = -1
    searched = {}          # states already searched this run - at most once each
    flags = {"deg": False}
    ticks = 0
    
    say("heater online, day " + str(clock.get_day()) + ", known states: " +
        str(len(TABLE)))
    
    while ticks < MAX_TICKS:
        ticks = ticks + 1
        now = self.thermal_state()
        if now != state:
            state = now
            power = pick(state)
        self.set_power(power)
        if ticks % CHECK_EVERY == 0:
            power = audit(state, power)
        sleep(TICK_SLEEP)
    
    say("stopping after " + str(ticks) + " ticks (day " + str(clock.get_day()) +
        ") at " + str(self.efficiency()) + "%, output " + str(self.output()) +
        " - RUN IT AGAIN, output is 0 while no script runs")
    report()
