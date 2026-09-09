# ============================================================
#  PRESSURE GENERATOR - aims the sync pulse instead of polling
# ============================================================
#  Each cycle the gauge sweeps 0->100 and a ~4-unit window sits
#  somewhere inside it. sync() inside the window is +25%,
#  outside is -10%, and NOT firing at all is also -10%. So
#  every cycle is a forced bet: there is no safe "skip".
#
#  The trap the docs warn about is reading the window once and
#  looping on stale bounds. Every iteration here re-reads
#  next_window_low/high and gauge together, and nothing is
#  cached across a sleep.
#
#  The subtler trap is polling granularity. One sleep advances
#  the gauge by some fixed amount; if that is wider than the
#  window, a plain poll loop steps straight over it every time.
#  So the script MEASURES the advance per sleep, then aims:
#  one big jump to the window's leading edge, then single steps
#  in. Every sleep re-measures, so a drifting rate is tracked.
# ============================================================

SLEEP_MIN   = 1      # smallest sleep the runtime accepts
INT_SLEEP   = True   # runtime wants whole numbers; False if it takes floats
FINE_ZONE   = 0      # extra gauge units to stop short of the window edge
ALPHA       = 0.35   # how fast the rate estimate follows what we observe
RATE_SAFETY = 1.35   # plan each hop as if the gauge were this much faster than
                     # measured. Overshooting the window forfeits a whole cycle,
                     # so every hop deliberately falls short and we take another.
                     # Raise it if the sweep speed is noisy, at a cost of more
                     # hops per cycle.
MAX_ITERS   = 260    # step-limit guard: ~7000 of the 10000 steps
MAX_CYCLES  = 60     # stop after this many sweeps; just run it again
VERBOSE     = True


def say(msg):
    if VERBOSE:
        print(msg)


# Gauge advance between two reads, allowing for the wrap at 100.
def advance(before, after):
    d = after - before
    if d < 0:
        d = d + 100
    return d


# Turn a wanted gauge distance into a sleep amount, ALWAYS rounding down.
# Undershooting costs one extra small step; overshooting sails past the
# window and forfeits the whole cycle, so the bias is deliberate.
def nap_for(dist, rate):
    if dist <= 0:
        return SLEEP_MIN
    amt = dist / rate
    if INT_SLEEP:
        amt = int(amt)
    if amt < SLEEP_MIN:
        amt = SLEEP_MIN
    return amt


# ---------- calibrate: how far does one sleep move the gauge? ---------------

g_prev = self.gauge()
sleep(SLEEP_MIN)
rate = advance(g_prev, self.gauge()) / (SLEEP_MIN * 1.0)
if rate <= 0:
    rate = 1.0            # gauge did not move; assume slow and correct later

width = self.next_window_high() - self.next_window_low()
say("gauge moves " + str(rate) + " per sleep(" + str(SLEEP_MIN) +
    "), window " + str(width) + " wide")
if rate > width:
    say("WARNING: one sleep outruns the window - hits will be part luck. " +
        "Lower SLEEP_MIN if your sleep() accepts floats.")

# ---------- main -----------------------------------------------------------

synced = False           # already fired this cycle
hits = 0
misses = 0
cycles = 0
iters = 0

while iters < MAX_ITERS and cycles < MAX_CYCLES:
    iters = iters + 1

    # Re-read all three together, every iteration. The window shifts each
    # cycle AND after each sync(), so anything held across a sleep is stale.
    g = self.gauge()
    lo = self.next_window_low()
    hi = self.next_window_high()

    if not synced and g >= lo and g <= hi:
        self.sync()
        synced = True
        hits = hits + 1
        say("hit " + str(hits) + " at gauge " + str(g) + " in [" + str(lo) +
            "," + str(hi) + "] eff " + str(self.efficiency()) + "%")

    if synced:
        target = 99.0                 # done here; ride out the sweep
    elif g > hi:
        target = 99.0                 # window is behind us; wait for the wrap
    else:
        target = lo - FINE_ZONE       # leading edge, then step in

    amt = nap_for(target - g, rate * RATE_SAFETY)
    sleep(amt)
    g2 = self.gauge()

    # A sleep that did not wrap is a clean rate sample: gauge moved per
    # sleep unit. Wrapped sleeps are ambiguous (could be more than one
    # lap), so they are not used to update the estimate.
    if g2 > g and amt > 0:
        rate = rate * (1 - ALPHA) + (advance(g, g2) / (amt * 1.0)) * ALPHA
        if rate <= 0:
            rate = 0.1

    if g2 < g:                        # the sweep wrapped during that sleep
        cycles = cycles + 1
        if not synced:
            misses = misses + 1
            say("cycle " + str(cycles) + " MISSED (never fired)")
        synced = False

total = hits + misses
if total < 1:
    total = 1
say("stopping - " + str(hits) + " hits, " + str(misses) + " misses over " +
    str(cycles) + " cycles (" + str(100 * hits // total) + "%), eff " +
    str(self.efficiency()) + "%, output " + str(self.output()))
if self.is_degraded():
    say("DEGRADED - Mk III starved, running as tier " +
        str(self.effective_tier()) + "; check water_in level")
