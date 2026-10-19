# =============================================================================
#  HEATER  —  paste into the script slot of  heater_1
#  Life support. Holds its setpoint when the kernel goes quiet.
# =============================================================================
#
#  FAIL_SAFE = "hold". Temperature is a terraforming pillar and a habitability
#  floor at the same time, so a heater that idles because nothing is talking
#  to it is a heater that undoes work while nobody is watching. It keeps its
#  last good power setting instead.
#
#  WHAT THE LEASE WOULD CONTROL. A Mk III heater draws 12 t/h of STEAM, not
#  water, through `steam_in`, and steam comes from a thermal vent that cycles
#  between active and dormant. So a heater's allowance is only meaningful at
#  Mk III and only once a vent is capped and tanked. Below that tier the
#  machine reads no lease at all, exactly as the oxygen generator does, and
#  the planner skips it rather than ranking and starving it.
#
#  POWER IS THE REAL CONSTRAINT TODAY. `safety.watts` learned this heater at
#  9 W, which is small, but heat is the pillar with the least to show for the
#  draw right now. If the base ever has to shed, this is a machine the
#  planner may well rank low — and it will be the breaker that stops it, not
#  this script, because a heater asked to stand down must still hold its
#  setpoint for the moment power returns.
# =============================================================================

from bus import allowance, lease
from capability import outpost_of

FAIL_SAFE = "hold"           # kernel silent -> keep the last good setpoint
FULL_STEAM = 12.0            # t/h a Mk III heater wants
NEEDS_TIER = 3               # below this, steam is not consumed at all
PASS_S = 2.0

POWER_MIN = 1
POWER_MAX = 10

outpost_id = outpost_of(self)
last_good = 0
said = ""


def say(msg):
    global said
    if msg != said:
        print(msg)
        said = msg


def share():
    """Fraction of full steam allowed, 1.0 below the tier that consumes it."""
    if self.tier() < NEEDS_TIER:
        return 1.0
    held = lease(self.id, outpost_id)
    if held == None:
        return None
    steam = allowance(self.id, outpost_id, "steam", 0.0)
    if FULL_STEAM <= 0:
        return 1.0
    return min(1.0, steam / FULL_STEAM)


while True:
    allowed = share()

    if allowed == None:
        target = last_good
        if target <= 0:
            target = POWER_MAX
        say("heater: no fresh lease, holding " + str(target))
    else:
        # Scale within the machine's own range rather than from zero: a
        # heater at power 0 is off, and partial steam should mean slower,
        # not stopped.
        span = POWER_MAX - POWER_MIN
        target = int(POWER_MIN + round(span * allowed))
        last_good = target
        if allowed < 1.0:
            say("heater: leased " + str(round(allowed * 100)) + "% of steam")
        else:
            say("heater: full power " + str(target))

    self.set_power(target)

    if self.is_degraded():
        where = "unknown"
        if self.steam_in != None:
            where = str(self.steam_in.level()) + " t"
        say("heater: degraded, steam_in " + where +
            ", tier " + str(self.effective_tier()))

    sleep(PASS_S)
