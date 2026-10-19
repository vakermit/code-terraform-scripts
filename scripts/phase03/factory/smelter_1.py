# =============================================================================
#  SMELTER  —  paste into the script slot of  smelter_1
#  Discretionary. Stops consuming when the kernel goes quiet.
# =============================================================================
#
#  FAIL_SAFE = "idle", the opposite of the oxygen generator's, and for the
#  same reason: only this script knows what kind of machine it is. A smelter
#  that keeps smelting through a crisis nobody is managing is spending power
#  and ore against a plan that no longer exists. Life support holds, factories
#  stand down, and neither decision belongs in the lease.
#
#  WHAT IDLE MEANS HERE.  Not "stop the script" — the script must stay alive,
#  because a stopped script drops its recipe selection and leaves the machine
#  inert even after the kernel returns. Idle means: finish nothing new, stop
#  pulling ore, and keep draining finished output so the machine is not found
#  blocked when permission comes back. Everything already in progress is left
#  to complete, because a flush destroys it.
#
#  WHY THE LEASE IS ONLY PERMISSION.  A smelter has no fluid to meter and its
#  draw is already inside the envelope safety measured, so the planner grants
#  it `run` rather than a quantity. The quantitative control over this machine
#  is safety's breaker, which outranks everything here.
# =============================================================================

from bus import lease
from capability import outpost_of
# Inherited from phase02/lib via the phase fallback chain: these helpers are
# not phase-specific and there was nothing to rewrite in them.
from store import ensure_ports, push, stock_of

FAIL_SAFE = "idle"           # kernel silent -> stop consuming
PASS_S = 2.0
BATCH = 10                   # units of ore to pull per feed

outpost_id = outpost_of(self)
said = ""


def say(msg):
    global said
    if msg != said:
        print(msg)
        said = msg


def permitted():
    """True when a fresh lease names this machine and allows it to run.

    Three outcomes collapse to False on purpose — no bus, no fresh
    allocation, and an allocation that does not mention this machine — because
    for a discretionary machine they mean the same thing: nobody is accounting
    for what I would consume, so I should not consume it.
    """
    held = lease(self.id, outpost_id)
    if held == None:
        return False
    if not held.has("run"):
        return False
    return held["run"]


def drain():
    """Move finished goods out, so a blocked output never masks an idle lease.

    `push` re-aims the port at a fresh sink after each partial send, because a
    stack larger than one bin needs more than one destination to land in.
    """
    moved = 0
    for stack in self.output.stacks():
        moved = moved + push(self.output, stack, "smelter")
    return moved


def feed():
    """Top up the input for the selected recipe. Returns units moved."""
    recipe = self.get_recipe()
    if recipe == None or recipe == "":
        return 0
    room = self.input.capacity() - self.input.count()
    if room <= 0:
        return 0
    want = min(BATCH, room)
    for ore in ["iron_ore", "silicon_ore", "lead_ore", "titanium_ore"]:
        have = stock_of(ore)
        if have <= 0:
            continue
        result = self.input.take(ore, min(want, have))
        if result != None and result.moved > 0:
            return result.moved
    return 0


while True:
    # Nothing moves until both ports are aimed, and a port can be moved out
    # from under us by hand, so this is checked every pass rather than once.
    if not ensure_ports(self, tag="smelter"):
        sleep(PASS_S)
        continue

    drain()                              # always: a full output helps no one

    if permitted():
        say("smelter: leased, running")
        feed()
    else:
        # FAIL_SAFE "idle". The recipe stays selected and work in progress
        # finishes; only the pulling stops. Nothing is flushed, because a
        # flush is permanent and a lease is not.
        say("smelter: no fresh lease, idle")

    sleep(PASS_S)
