# =============================================================================
#  PRESSURE GENERATOR  —  paste into the script slot of  pressure_1
#  A forced bet every sweep. Takes no quantitative lease, by design.
# =============================================================================
#
#  FAIL_SAFE = "hold", and more than that: THIS MACHINE IGNORES THE SIZE OF
#  ITS ALLOWANCE ENTIRELY.
#
#  Every sweep the gauge climbs 0 to 100 with a roughly 4-unit window
#  somewhere inside it. Firing sync() inside the window is +25%; firing
#  outside is -10%; and not firing at all is ALSO -10%. There is no safe skip
#  and no partial output. A machine like this cannot be throttled, because
#  throttling it does not mean "produce less" — it means "lose 10% per sweep
#  instead of gaining 25%", which is worse than switching the machine off.
#
#  So the only honest lever over a pressure generator is the breaker, and
#  that belongs to the safety loop. A lease is read here for one purpose: to
#  SAY whether the kernel is accounting for this machine, so the trace and
#  the card are not silently missing it. The gauge logic never consults it.
#
#  NO sleep() ANYWHERE. sleep() counts real seconds and would skip ticks, and
#  a 4-wide window is exactly what gets stepped over when ticks are skipped.
#  A bare `while True:` yields once per tick, which is the finest polling the
#  game offers. The window and the gauge are re-read together every pass,
#  because reading the window once and looping on stale bounds is the trap
#  the manual warns about.
# =============================================================================

from bus import lease
from capability import outpost_of

FAIL_SAFE = "hold"           # and the allowance size is ignored: see above
REPORT_EVERY = 200           # ticks between status lines
NEEDS_TIER = 3               # water is installed by the Mk III pack

outpost_id = outpost_of(self)

ticks = 0
hits = 0
misses = 0
last_gauge = -1.0
fired_this_sweep = False
said_lease = ""


def say_once(msg):
    """Report a change in whether the kernel is accounting for this machine."""
    global said_lease
    if msg != said_lease:
        print(msg)
        said_lease = msg


while True:
    ticks = ticks + 1

    # Re-read both together. The window moves; a cached bound is a missed
    # sweep, and a missed sweep is a loss rather than a pause.
    gauge = self.gauge()
    low = self.next_window_low()
    high = self.next_window_high()

    if gauge < last_gauge:
        # The sweep wrapped. Score the one that just ended before resetting:
        # not firing is a loss, so a sweep with no hit is worth saying.
        if not fired_this_sweep:
            misses = misses + 1
        fired_this_sweep = False
    last_gauge = gauge

    if not fired_this_sweep and gauge >= low and gauge <= high:
        self.sync()
        fired_this_sweep = True
        hits = hits + 1

    if ticks % REPORT_EVERY == 0:
        held = lease(self.id, outpost_id)
        if held == None:
            say_once("pressure: unled, firing anyway — a skipped sweep is a loss")
        else:
            say_once("pressure: kernel accounting for this machine")
        print("pressure: " + str(hits) + " hits, " + str(misses) +
              " missed sweeps, efficiency " + str(self.efficiency()) + "%")
        if self.is_degraded():
            print("pressure: degraded, tier " + str(self.effective_tier()))
