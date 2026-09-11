# ============================================================
#  OXYGEN GENERATOR - steers waste into the clean-dump window
# ============================================================
#  Base loop: intake = co2/10 every tick, dump when waste is
#  in 50-60. That is the whole job when waste climbs slowly.
#
#  The failure mode is when it does not. Waste rises with
#  intake, so on a rich atmosphere one tick can carry waste
#  from 48 straight to 63 - over the clean window without ever
#  landing in it. Then every dump is a penalised dump, and the
#  penalty lingers until the NEXT dump, so it is not a one-off
#  cost: it taxes the whole cycle that follows.
#
#  Unlike a gauge we can only watch, we own the throttle here.
#  So the script measures how much waste one unit of intake
#  produces, and when a full-rate tick would overshoot the
#  window it can trim intake for that tick to land on 55.
#
#  But trimming is not always worth it, and the docs never say
#  how big a bad dump costs. Measured against a mild penalty
#  trimming LOSES ground; against a harsh one it wins. So the
#  script prices it instead of assuming: it lets the first
#  overshoot through, reads the real penalty off the dump
#  result, and from then on trims only when the arithmetic
#  says to. One bad cycle buys the answer for every cycle after.
#
#  Runtime notes (docs/manual/37-loops, 03-yielding-and-status):
#  - `while True:` yields to the game every pass, one pass per
#    tick. No sleep() - that is in seconds and would skip ticks.
#  - dump_waste() returns a WasteDumpResult; the number we want
#    is its .penalty field. Comparing the result itself crashes.
#  - Every variable here is relearned in a few ticks after a
#    game load, so nothing needs the Data Archive.
# ============================================================

INTAKE_DIV  = 10     # chamber sweet spot is 1/10th of ambient CO2
DUMP_LOW    = 50     # clean-dump window, per the machine docs
DUMP_HIGH   = 60
DUMP_AIM    = 55     # steer for the middle - most room for rate error
THROTTLE    = True   # trim intake to land inside the window when it pays
ALPHA       = 0.35   # how fast the learned rates follow what we observe
CHECK_EVERY = 50     # ticks between Mk III starvation checks
VERBOSE     = True

atm = get_component("atmosphere")


def say(msg):
    if VERBOSE:
        print(msg)


# ---------- learned state --------------------------------------------------

wpi = 0.0            # waste produced per unit of intake (0 = not measured yet)
ppu = 0.0            # dump penalty per unit of overshoot past DUMP_HIGH,
                     # priced from the first overshoot we let through
prev_w = -1.0        # waste the chamber held at the end of the last pass
prev_in = 0.0        # intake we set on the last pass
ticks = 0
dumps = 0
dirty = 0            # dumps that cost us a penalty
throttled = 0
flags = {"deg": False}


# Is trimming this tick cheaper than the dump penalty it avoids?
#
# Trimming costs the fraction of ONE tick's intake we give up. A dirty dump
# costs its penalty on every tick until the next dump, so both sides are put
# on the same footing: average loss per tick over the cycle. While ppu is
# still 0 this always returns base - that is the deliberate one-off probe
# that prices the penalty.
def trim_to(w, base):
    cut = (DUMP_AIM - w) / wpi
    if cut >= base or cut < 0:
        return base
    over = w + wpi * base - DUMP_HIGH
    # Ticks per cycle, rounded UP: ticks are discrete, and a cycle that takes
    # "1.6 ticks" really takes 2. Using the fraction here understates the
    # cycle and talks us out of trims that are actually worth making.
    c = DUMP_AIM / (wpi * base)
    cycle = int(c)
    if cycle < c:
        cycle = cycle + 1
    if cycle < 1:
        cycle = 1
    if ppu * over > ((base - cut) / base) / cycle:
        return cut
    return base


say("oxygen online, waste " + str(self.waste()) + ", co2 " +
    str(atm.get_co2()))

while True:
    ticks = ticks + 1
    base = atm.get_co2() / INTAKE_DIV
    w = self.waste()

    # Learn the fill rate: the last pass left the chamber at prev_w with
    # intake prev_in, and one tick has grown it to w. Passes where waste did
    # not move (no tick elapsed) are skipped rather than counted as zero.
    if prev_w >= 0 and prev_in > 0 and w > prev_w:
        obs = (w - prev_w) / prev_in
        if wpi > 0:
            wpi = wpi + ALPHA * (obs - wpi)
        else:
            wpi = obs
            say("chamber makes " + str(obs) + " waste per unit intake")

    # Dump first: the window is where we want to be caught, and clearing
    # early frees the whole next cycle to run clean. Above DUMP_HIGH we dump
    # anyway - the penalty only grows the longer we carry it, and waste at
    # 100 stalls the machine outright.
    if w >= DUMP_LOW:
        res = self.dump_waste()
        p = res.penalty
        dumps = dumps + 1
        if p > 0:
            dirty = dirty + 1
            over = w - DUMP_HIGH
            if over > 0:
                if ppu > 0:
                    ppu = ppu + ALPHA * (p / over - ppu)
                else:
                    ppu = p / over
                    say("priced a bad dump: " + str(p) + " for " + str(over) +
                        " over the window - " + str(res.message))
        w = self.waste()          # what the chamber holds now that it is dumped

    # Intake for this tick: full rate, unless a full-rate tick would carry
    # waste straight over the window and trimming is priced as worth it.
    intake = base
    if THROTTLE and wpi > 0 and w + wpi * base > DUMP_HIGH:
        intake = trim_to(w, base)
        if intake < base:
            throttled = throttled + 1
    self.set_intake(intake)

    prev_w = w
    prev_in = intake

    # A starved Mk III silently drops to Mk II. That is a water problem, not
    # an intake problem - surface it so it is not mistaken for a bad script.
    if ticks % CHECK_EVERY == 0:
        d = self.is_degraded()
        if d != flags["deg"]:
            flags["deg"] = d
            if d:
                say("DEGRADED - Mk III starved, running as tier " +
                    str(self.effective_tier()) + "; check water_in level")
            else:
                say("recovered - tier " + str(self.effective_tier()))
        if ticks % (CHECK_EVERY * 20) == 0:
            say("tick " + str(ticks) + ": " + str(dumps) + " dumps, " +
                str(dirty) + " dirty, " + str(throttled) + " trimmed, eff " +
                str(self.efficiency()) + "%, output " + str(self.output()))
