# ============================================================
#  PRESSURE GENERATOR - fires the sync pulse inside the window
# ============================================================
#  Each sweep the gauge climbs 0->100 and a ~4-unit window sits
#  somewhere inside it. sync() inside the window is +25%,
#  outside is -10%, and NOT firing at all is also -10%. So
#  every sweep is a forced bet: there is no safe "skip", and
#  the only way to lose is to never be inside the window on a
#  pass.
#
#  The trap the docs warn about is reading the window once and
#  looping on stale bounds. Every pass here re-reads the window
#  and the gauge together; nothing is remembered across passes
#  except bookkeeping.
#
#  Runtime notes (docs/manual/37-loops, builtins.md sleep()):
#  - `while True:` yields to the game every pass, one pass per
#    tick, and the gauge "rises each tick". So checking every
#    pass IS the finest polling the game offers. There is no
#    sleep() here - it is in real seconds and would skip ticks,
#    which is exactly how a 4-wide window gets stepped over.
#  - The gauge's advance per tick is measured and compared to
#    the window width. If a single tick can outrun the window,
#    no script can hit it reliably; that gets said out loud
#    rather than silently returning misses.
#  - sync() returns an ActionResult and is not compared to a
#    number.
# ============================================================

ALPHA       = 0.35   # how fast the measured gauge rate follows reality
CHECK_EVERY = 100    # ticks between status lines
VERBOSE     = True


def say(msg):
    if VERBOSE:
        print(msg)


# ---------- main -----------------------------------------------------------

last_g = -1.0        # gauge on the previous pass (-1 = none yet)
rate = 0.0           # gauge units per tick, learned live
synced = False       # fired already this sweep
hits = 0
misses = 0
sweeps = 0
ticks = 0
warned = False

say("pressure online, gauge " + str(self.gauge()) + " window [" +
    str(self.next_window_low()) + "," + str(self.next_window_high()) + "]")

while True:
    ticks = ticks + 1
    g = self.gauge()
    lo = self.next_window_low()
    hi = self.next_window_high()

    if last_g >= 0:
        if g < last_g:
            # The sweep wrapped since last pass: score it and reset.
            sweeps = sweeps + 1
            if not synced:
                misses = misses + 1
                say("sweep " + str(sweeps) + " MISSED - never inside the window")
            synced = False
        elif g > last_g:
            step = g - last_g
            if rate > 0:
                rate = rate + ALPHA * (step - rate)
            else:
                rate = step
    last_g = g

    if not synced and g >= lo and g <= hi:
        self.sync()
        synced = True
        hits = hits + 1
        say("hit " + str(hits) + " at gauge " + str(g) + " in [" + str(lo) +
            "," + str(hi) + "] eff " + str(self.efficiency()) + "%")

    if ticks % CHECK_EVERY == 0:
        if rate > (hi - lo) and not warned:
            warned = True
            say("WARNING: gauge moves " + str(rate) + " per tick but the " +
                "window is only " + str(hi - lo) + " wide - some sweeps " +
                "cannot be hit by any script")
        if ticks % (CHECK_EVERY * 10) == 0:
            total = hits + misses
            if total < 1:
                total = 1
            say("tick " + str(ticks) + ": " + str(hits) + " hits / " +
                str(misses) + " misses (" + str(100 * hits // total) +
                "%), gauge " + str(rate) + "/tick, eff " +
                str(self.efficiency()) + "%")
        if self.is_degraded():
            say("DEGRADED - Mk III starved, running as tier " +
                str(self.effective_tier()) + "; check water_in level")
