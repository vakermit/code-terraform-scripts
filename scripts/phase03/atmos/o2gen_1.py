# =============================================================================
#  OXYGEN GENERATOR  —  paste into the script slot of  oxygen_generator_1
#  Life support. Holds its setpoint when the kernel goes quiet.
# =============================================================================
#
#  FAIL_SAFE = "hold", and that constant is the most important line in this
#  file. The kernel going silent is a normal event — a save, a reload, a
#  stopped automation, a crash all look identical from here — and for a
#  discretionary machine the right answer is to stop consuming. For life
#  support it is the opposite: idling the oxygen supply because the
#  controller died would make the controller's failure fatal rather than
#  inconvenient. Only this script knows which kind of machine it is, which is
#  why the direction lives here and not in the lease.
#
#  WHAT THE LEASE CONTROLS.  A Mk III pack buys a two-hundredfold multiplier
#  while its water holds and five times nothing when it starves, and the
#  degraded state flips per tick when input falls short of a tick's draw. So a
#  machine that demands full Mk III throughput on a partial allowance does not
#  get partial output, it gets a thrashing tier. Instead intake scales with
#  the allowance: run proportionally to what you were actually given.
#
#  INTAKE IS NOT A THROTTLE.  Peak efficiency is exactly one tenth of ambient
#  CO2, and both sides of that point lose efficiency smoothly. So the sweet
#  spot is recomputed every pass from live CO2 and then scaled by the lease,
#  rather than being treated as a dial from 0 to 1.
#
#  The setpoint returns to 0 when this script stops, which is the whole reason
#  a central kernel cannot replace this loop.
# =============================================================================

from bus import allowance, lease
from capability import outpost_of

FAIL_SAFE = "hold"           # kernel silent -> keep the last good setpoint
FULL_WATER = 8.0             # t/h a Mk III oxygen generator wants
PASS_S = 2.0

DUMP_AT = 55                 # inside the penalty-free 50-60 window
WASTE_STALL = 100

atmosphere = get_component("atmosphere")
outpost_id = outpost_of(self)

last_good = 0.0              # the setpoint to hold when nothing is talking
said = ""


def say(msg):
    """Print only when the message changes, so the console stays readable."""
    global said
    if msg != said:
        print(msg)
        said = msg


def sweet_spot():
    """Peak-efficiency CO2 intake: exactly a tenth of ambient."""
    if atmosphere == None:
        return last_good
    return atmosphere.get_co2() / 10


def share():
    """Fraction of full water this machine has been allowed, 0..1.

    A missing lease answers None rather than 0, because "nobody told me" and
    "you get nothing" must land in different branches: the first holds, the
    second obeys.

    Below Mk III the answer is always 1.0 whatever the lease says. Water is
    installed by the Mk III pack, so a Mk I or Mk II generator consumes none
    of it and throttling one against a water allowance would starve a machine
    for a resource it does not use. The planner allocates by type and cannot
    see the installed tier; the machine can, so the machine decides.
    """
    if self.tier() < 3:
        return 1.0
    held = lease(self.id, outpost_id)
    if held == None:
        return None
    water = allowance(self.id, outpost_id, "water", 0.0)
    if FULL_WATER <= 0:
        return 1.0
    fraction = water / FULL_WATER
    if fraction > 1.0:
        return 1.0
    return fraction


def manage_waste():
    """Dump inside the penalty-free window; never let the chamber stall."""
    w = self.waste()
    if w >= WASTE_STALL or w >= DUMP_AT:
        result = self.dump_waste()
        if result != None and result.status != "ok":
            say(f"oxygen: dump refused, {result.message}")


while True:
    manage_waste()

    allowed = share()
    if allowed == None:
        # FAIL_SAFE "hold". Keep the last setpoint the kernel agreed to, or
        # the unscaled sweet spot if it never said anything at all.
        target = last_good
        if target <= 0:
            target = sweet_spot()
        say("oxygen: no fresh lease, holding " + str(round(target, 2)))
    else:
        target = sweet_spot() * allowed
        last_good = target
        if allowed < 1.0:
            say("oxygen: leased " + str(round(allowed * 100)) + "% of water")
        else:
            say("oxygen: fully supplied")

    self.set_intake(target)

    if self.is_degraded():
        # water_in is installed by the Mk III pack, so a lower-tier machine
        # may not have the port at all. is_degraded() should be False there,
        # but this is life support and a guess is not worth an exception.
        where = "unknown"
        if self.water_in != None:
            where = str(self.water_in.level()) + " t"
        say("oxygen: degraded, water_in " + where +
            ", tier " + str(self.effective_tier()))

    sleep(PASS_S)
