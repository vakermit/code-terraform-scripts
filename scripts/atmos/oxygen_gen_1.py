# ============================================================
#  OXYGEN GENERATOR - steers waste into the clean-dump window
# ============================================================
#  Base loop: intake = co2/10 every tick, dump when waste is
#  in 50-60. That is the whole job when waste climbs slowly.
#
#  The failure mode is when it does not. Waste rises with
#  intake, so on a rich atmosphere one tick can carry waste
#  from 48 straight to 64 - over the clean window without ever
#  landing in it. Then every dump is a penalised dump, and the
#  penalty lingers until the NEXT dump, so it is not a one-off
#  cost: it taxes the whole cycle that follows.
#
#  Unlike a gauge we can only watch, we own the throttle here.
#  So the script measures how much waste one unit of intake
#  produces, and when a full-rate tick would overshoot the
#  window it trims intake just for that tick to land on 55.
#  One tick at reduced intake costs a slice of one tick's
#  output; a bad dump costs a slice of every tick until the
#  next one. That trade is why the throttle exists.
# ============================================================

INTAKE_DIV  = 10     # chamber sweet spot is 1/10th of ambient CO2
DUMP_LOW    = 50     # clean-dump window, per the machine docs
DUMP_HIGH   = 60
DUMP_AIM    = 55     # steer for the middle - most room for rate error
THROTTLE    = True   # trim intake to land inside the window
ALPHA       = 0.35   # how fast the waste-per-intake estimate follows reality
CHECK_EVERY = 24     # ticks between health checks
SLEEP_STEP  = 1      # sleep per iteration
MAX_TICKS   = 900    # sized to the step limit; see the heater notes
VERBOSE     = True

atm = get_component("atmosphere")


def say(msg):
    if VERBOSE:
        print(msg)


# ---------- state ----------------------------------------------------------

while True:

    wpi = 0.0            # waste produced per unit of intake, learned live
    have_wpi = False
    ticks = 0
    dumps = 0
    dirty = 0            # dumps that cost us a penalty
    throttled = 0
    flags = {"deg": False}
    
    say("oxygen online, waste " + str(self.waste()) + ", co2 " +
        str(atm.get_co2()))
    
    while ticks < MAX_TICKS:
        ticks = ticks + 1
        co2 = atm.get_co2()
        base = co2 / INTAKE_DIV
        w = self.waste()
        dumped = False
    
        # Dump first: the window is where we want to be caught, and clearing
        # early frees the whole next cycle to run clean.
        if w >= DUMP_LOW:
            p = self.dump_waste()
            dumps = dumps + 1
            dumped = True
            if p > 0:
                dirty = dirty + 1
                say("dirty dump at waste " + str(w) + " penalty " + str(p))
    
        # Intake for this tick. Full rate unless a full-rate tick would carry
        # waste over the window - then trim to land on DUMP_AIM instead.
        intake = base
        if THROTTLE and have_wpi and not dumped and wpi > 0:
            if w + wpi * base > DUMP_HIGH:
                want = DUMP_AIM - w
                if want < 0:
                    want = 0
                intake = want / wpi
                if intake > base:
                    intake = base
                if intake < base:
                    throttled = throttled + 1
        if intake < 0:
            intake = 0
        self.set_intake(intake)
    
        sleep(SLEEP_STEP)
    
        # A tick with no dump is a clean sample of how much waste that intake
        # made. Dump ticks reset waste, so they tell us nothing.
        w2 = self.waste()
        if not dumped and intake > 0 and w2 > w:
            obs = (w2 - w) / intake
            if have_wpi:
                wpi = wpi * (1 - ALPHA) + obs * ALPHA
            else:
                wpi = obs
                have_wpi = True
    
        if ticks % CHECK_EVERY == 0:
            d = self.is_degraded()
            if d != flags["deg"]:
                flags["deg"] = d
                if d:
                    say("DEGRADED - Mk III starved, running as tier " +
                        str(self.effective_tier()) + "; check water_in level")
                else:
                    say("recovered - tier " + str(self.effective_tier()))
    
    say("stopping after " + str(ticks) + " ticks - " + str(dumps) + " dumps, " +
        str(dirty) + " dirty, " + str(throttled) + " throttled ticks, eff " +
        str(self.efficiency()) + "%, output " + str(self.output()) +
        " - RUN IT AGAIN, output is 0 while no script runs")
