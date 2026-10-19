# =============================================================================
#  FABRICATOR  —  paste into the script slot of  fabricator_1
#  Turns ingots into upgrade packs, within its allowance.
# =============================================================================
#
#  FAIL_SAFE = "idle". The other half of the ingot contention, and the half
#  with the long payoff: a pack raises a machine's tier, and a tier raises
#  terraforming rate for the rest of the game. Valuable, and in no hurry —
#  so with no fresh lease it stops consuming and lets the dock or a future
#  decision have the material.
#
#  WHY IT RANKS ABOVE THE DOCK TODAY.  It does not, inherently. The planner
#  scores `tier` against `credits` from a seeded table where both are 1.0, so
#  the ranking is currently arbitrary and the fabricator wins on list order.
#  That is honest rather than clever: nothing has measured what a pack is
#  worth against the credits the same ingots would fetch, and an order's
#  reward divided by its requirement will price the credits side properly
#  once one is observed end to end.
#
#  PACKS CANNOT BE BOUGHT, only fabricated, so this machine is the only route
#  to a tier rise. That is the argument for it eventually outranking the dock,
#  and it is an argument the planner should be told rather than one this
#  script should act on by itself.
# =============================================================================

from bus import lease
from capability import outpost_of
from store import ensure_ports, push, stock_of   # inherited from phase02/lib

FAIL_SAFE = "idle"           # kernel silent -> stop consuming
RESOURCE = "iron_ingot"
PASS_S = 2.0

outpost_id = outpost_of(self)
said = ""


def say(msg):
    global said
    if msg != said:
        print(msg)
        said = msg


def allotted():
    """Ingots this fabricator may pull this pass, or None when unleased."""
    held = lease(self.id, outpost_id)
    if held == None:
        return None
    if not held.has(RESOURCE):
        return 0
    return held[RESOURCE]


def drain():
    """Clear finished packs out, so a full output never looks like an idle lease."""
    moved = 0
    for stack in self.output.stacks():
        moved = moved + push(self.output, stack, "fab")
    return moved


def feed(budget):
    """Pull up to `budget` ingots for the selected recipe."""
    recipe = self.get_recipe()
    if recipe == None or recipe == "":
        say("fab: no recipe selected")
        return 0
    room = self.input.capacity() - self.input.count()
    if room <= 0:
        return 0
    have = stock_of(RESOURCE)
    want = min(budget, room, have)
    if want <= 0:
        return 0
    result = self.input.take(RESOURCE, want)
    if result == None:
        return 0
    return result.moved


while True:
    if not ensure_ports(self, tag="fab"):
        sleep(PASS_S)
        continue

    drain()                              # always: a blocked output helps no one

    budget = allotted()
    if budget == None:
        # FAIL_SAFE "idle". The recipe stays selected and work in progress
        # finishes; only the pulling stops. Nothing is flushed, because a
        # flush is permanent and a missing lease is not.
        say("fab: no fresh lease, idle")
    elif budget <= 0:
        say("fab: leased nothing this pass")
    else:
        moved = feed(budget)
        if moved > 0:
            say(f"fab: pulled {moved} of {budget} leased")
        else:
            say(f"fab: leased {budget}, nothing to pull")

    sleep(PASS_S)
