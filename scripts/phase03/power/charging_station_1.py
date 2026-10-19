# =============================================================================
#  VEHICLE CHARGING STATION  —  paste into the script slot of  charging_station_1
#  Rescue is never gated. Nothing in the kernel can stop it.
# =============================================================================
#
#  FAIL_SAFE = "hold", and one behaviour sits above the lease entirely: a
#  stranded vehicle is recovered whatever the kernel says, including when the
#  kernel says nothing. A rover out of battery in the field is not a
#  throttleable load, it is a vehicle that stops existing as an asset until
#  someone fetches it — and the station only needs power at launch, so the
#  mission survives an outage that starts after the drone is away.
#
#  This is the clearest case in the base for why fail-safe direction belongs
#  in the machine. A kernel ranking machines by marginal terraforming value
#  would rank a charging station low: it produces nothing. It would be right
#  about the production and catastrophically wrong about the consequence.
#
#  WHAT THE LEASE DOES CONTROL: topping up docked vehicles that are not in
#  trouble. That is discretionary, it is the larger share of the station's
#  draw over time, and it can wait for headroom.
#
#  ONE RESCUE AT A TIME is a hard game limit, so every dispatch is guarded on
#  is_rescuing() rather than hoped about.
# =============================================================================

from bus import lease
from capability import fleet, outpost_of

FAIL_SAFE = "hold"
PASS_S = 3.0

RESCUE_BELOW = 0.12         # battery fraction that counts as stranded
RESCUE_TO = 0.6             # charge the rescued vehicle to this
TOP_UP_BELOW = 0.85         # docked vehicles below this are worth topping up
TOP_UP_TO = 0.95

outpost_id = outpost_of(self)
said = ""


def say(msg):
    global said
    if msg != said:
        print(msg)
        said = msg


def permitted():
    """True when a fresh lease allows discretionary top-ups."""
    held = lease(self.id, outpost_id)
    if held == None:
        return False
    if not held.has("run"):
        return True                      # named but unmetered: permission enough
    return held["run"]


def stranded():
    """Vehicles low enough to need fetching, worst first.

    Read from the fleet rather than from what is docked: the whole point is
    the ones that did not make it back.
    """
    f = fleet()
    if f == None:
        return []
    low = []
    for v in f.vehicles():
        if v.is_docked:
            continue
        if v.battery_level == None or v.battery_level > RESCUE_BELOW:
            continue
        if v.rescue_status != None and v.rescue_status != "none":
            continue                     # already being fetched
        low.append(v)
    return sorted(low, key=lambda v: v.battery_level)


while True:
    # -- rescue, above the lease ------------------------------------------
    if not self.is_rescuing():
        waiting = stranded()
        if len(waiting) > 0:
            target = waiting[0]
            result = self.dispatch_rescue(target.name, RESCUE_TO)
            if result == None or result.status == "ok":
                print("station: rescuing " + target.name + " at " +
                      str(round(target.battery_level * 100)) + "%")
            else:
                say("station: rescue refused, " + result.message)
    else:
        say("station: rescue in progress")

    # -- top-ups, below the lease -----------------------------------------
    if not permitted():
        say("station: no fresh lease, top-ups held (rescue still armed)")
    else:
        docked = self.get_docked()
        if docked != None:
            for v in docked:
                if v.battery_level != None and v.battery_level < TOP_UP_BELOW:
                    self.charge(v.id, TOP_UP_TO)

    sleep(PASS_S)
