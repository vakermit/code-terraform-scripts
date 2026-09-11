# ============================================================
#  HEAT GENERATOR - learns the state -> power table, then holds it
# ============================================================
#  The planet picks a thermal state once per day and keeps it.
#  Each state has its own optimal set_power() value, 1-10.
#
#  Efficiency is NOT a gradient here (docs: reference/components/
#  terraforming.md, .efficiency()): 100% at the optimum, about
#  31% one step away, then a flat 10% floor everywhere else.
#  So there is nothing to "solve" - far from the peak every
#  reading looks the same. What that shape DOES give us is a
#  proximity alarm: a reading well above the floor means the
#  answer is next door. The scan starts mid-range and, the
#  moment a probe reads warm, checks its neighbours first.
#
#  Runtime notes (docs/manual/37-loops, 03-yielding-and-status):
#  - `while True:` yields to the game every pass, one pass per
#    tick. Each probe is set on one pass and read on the next,
#    so the scan never depends on efficiency updating instantly.
#  - set_power() returns an ActionResult; it is not a number
#    and is not compared to one.
#  - Script variables die on game load. The learned table is
#    printed paste-ready every time it changes, and can also be
#    kept in the Data Archive once that is researched.
# ============================================================

# Paste discovered values here, e.g.
#   TABLE = {"clear": 5, "dust_storm": 8, "heat_bleed": 2, "dust_veil": 6}
TABLE = {}

ARCHIVE_KEY   = ""     # e.g. "heater.table" once the Data Archive (notebook)
                       # is researched. Empty = don't touch it. With a key set
                       # the table survives game loads without any pasting.
POWER_MIN     = 1      # 0 is "off" and always reads 0%, so never probe it
POWER_MAX     = 10
EFF_TARGET    = 100    # efficiency() that means "exactly right"
WARM          = 20     # above the 10% floor, below the 31% neighbour - a probe
                       # reading at least this means the answer is next door
RELEARN_BELOW = 99.0   # a pasted/archived entry scoring under this is re-scanned
CHECK_EVERY   = 50     # ticks between Mk III starvation checks
VERBOSE       = True

# Probe order: mid-range first. The optimum is as likely anywhere, but the
# warm-neighbour jump works in both directions from the middle.
ORDER = (5, 6, 4, 7, 3, 8, 2, 9, 1, 10)

clock = get_component("clock")
archive = None
if ARCHIVE_KEY != "":
    archive = get_component("notebook")
    saved = archive.get(ARCHIVE_KEY, None)
    if saved is not None:
        for k in saved:
            TABLE[k] = saved[k]


def say(msg):
    if VERBOSE:
        print(msg)


# Paste-ready, so a learned table survives into the next run even without
# the archive.
def report():
    s = ""
    for k in TABLE:
        if s != "":
            s = s + ", "
        s = s + '"' + k + '": ' + str(TABLE[k])
    print("TABLE = {" + s + "}      <-- paste this into the script")
    if archive is not None:
        archive.set(ARCHIVE_KEY, TABLE)


# Pick the next power to try. `last` and `e` are the previous probe and what
# it read. A warm reading sends us to an untested neighbour first; otherwise
# continue the mid-out order. None means everything has been tried.
def next_probe(tested, last, e):
    if last is not None and e >= WARM:
        for n in (last + 1, last - 1):
            if n >= POWER_MIN and n <= POWER_MAX and n not in tested:
                return n
    for n in ORDER:
        if n not in tested:
            return n
    return None


# Everything tried and nothing read 100%: take the best we saw rather than
# leave the heater on a random probe.
def best_of(tested):
    bw = POWER_MIN
    be = -1
    for w in tested:
        if tested[w] > be:
            be = tested[w]
            bw = w
    return bw


# ---------- main -----------------------------------------------------------

cur = ""             # thermal state we are currently set up for
power = POWER_MIN
tested = None        # dict of probe -> reading while a scan is running
verified = {}        # states whose table entry has been proven this run
flags = {"deg": False}
ticks = 0

say("heater online, day " + str(clock.get_day()) + ", known states: " +
    str(len(TABLE)))

while True:
    ticks = ticks + 1
    now = self.thermal_state()

    if now != cur:
        # New day, new state. Use the table if we have it; otherwise start
        # a scan. Either way the reading is checked on the next pass.
        cur = now
        tested = None
        if cur in TABLE:
            power = TABLE[cur]
            say("day " + str(clock.get_day()) + " " + cur + " -> " +
                str(power) + " from table")
        else:
            tested = {}
            power = next_probe(tested, None, 0)
            say("day " + str(clock.get_day()) + " " + cur +
                " unknown - scanning")

    elif tested is not None:
        # A scan is running: `power` was set last pass, read it now.
        e = self.efficiency()
        if e >= EFF_TARGET:
            TABLE[cur] = power
            verified[cur] = 1
            tested = None
            say(cur + " -> " + str(power) + " at " + str(e) + "% after " +
                str(len(TABLE)) + " states learned")
            report()
        else:
            tested[power] = e
            nxt = next_probe(tested, power, e)
            if nxt is None:
                power = best_of(tested)
                say(cur + ": nothing read 100%, holding best seen " +
                    str(power) + " at " + str(tested[power]) + "%")
                verified[cur] = 1
                tested = None
            else:
                power = nxt

    elif cur not in verified:
        # Table entry (pasted or archived) has had a tick to take effect.
        # Prove it once; a stale entry gets one scan to fix itself.
        e = self.efficiency()
        verified[cur] = 1
        if e < RELEARN_BELOW:
            say(cur + " table value " + str(power) + " only reads " + str(e) +
                "% - rescanning")
            tested = {}
            power = next_probe(tested, None, 0)

    self.set_power(power)

    # A starved Mk III silently drops to Mk II. That is a steam problem, not
    # a power problem - surface it so it is not mistaken for a bad table.
    if ticks % CHECK_EVERY == 0:
        d = self.is_degraded()
        if d != flags["deg"]:
            flags["deg"] = d
            if d:
                say("DEGRADED - Mk III starved, running as tier " +
                    str(self.effective_tier()) + "; check steam_in level")
            else:
                say("recovered - tier " + str(self.effective_tier()))
        if ticks % (CHECK_EVERY * 20) == 0:
            say("day " + str(clock.get_day()) + " " + cur + " power " +
                str(power) + " eff " + str(self.efficiency()) + "% output " +
                str(self.output()))
