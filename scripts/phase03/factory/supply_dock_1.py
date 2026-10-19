# =============================================================================
#  SUPPLY DOCK  —  paste into the script slot of  supply_dock_1
#  Ships to Earth, but only with the ingots it was allotted.
# =============================================================================
#
#  FAIL_SAFE = "idle". A dock turns material into credits, which is valuable
#  and entirely discretionary: nothing breaks if it waits. With no fresh
#  lease it keeps its order and stops loading, so the ingots stay available
#  to whatever the kernel decides matters more once it is talking again.
#
#  WHY THIS MACHINE IS INTERESTING.  It is one half of the only contention
#  this base actually has. An iron ingot can become an upgrade pack, which
#  raises a tier and so raises terraforming rate for the rest of the game, or
#  it can be shipped for credits that buy something now. The planner ranks
#  those two outcomes and hands each machine a number of ingots; this script
#  spends no more than its number.
#
#  LOADED CARGO IS NOT RECOVERABLE through the lease. Units taken into the
#  dock stay physical cargo in the dock: `clear_order()` releases the
#  assignment and leaves them there, and a different order is refused with
#  `cargo_present` until something drains them. So the lease is consulted
#  BEFORE taking anything, never after — an over-eager load cannot be undone
#  by a later reallocation.
# =============================================================================

from bus import lease
from capability import outpost_of

FAIL_SAFE = "idle"           # kernel silent -> stop loading
RESOURCE = "iron_ingot"
PASS_S = 2.0

outpost_id = outpost_of(self)
orders = get_component("orders")
said = ""


def say(msg):
    global said
    if msg != said:
        print(msg)
        said = msg


def allotted():
    """Ingots this dock may load this pass, or None when nothing is leased."""
    held = lease(self.id, outpost_id)
    if held == None:
        return None
    if not held.has(RESOURCE):
        return 0
    return held[RESOURCE]


def pick_order():
    """Assign an order when the dock has none. True when one is assigned.

    Campaign orders first, since they never expire and can carry technology
    or recipe rewards; weekly boards are credits only and expire whole.
    """
    if self.current_order() != None:
        return True
    if orders == None:
        return False
    for listing in (orders.list_orders(), orders.list_weekly_orders()):
        if listing == None:
            continue
        for order in listing:
            result = self.set_order(order.id)
            if result == None or result.status == "ok":
                say(f"dock: took order {order.id}")
                return True
            if result.status == "cargo_present":
                # Someone loaded for a previous order and it never shipped.
                # Nothing here can drain it, so say so once and wait.
                say("dock: cargo from an old order is blocking reassignment")
                return False
    return False


def load(budget):
    """Take up to `budget` units toward the current order. Returns units moved."""
    order = self.current_order()
    if order == None or budget <= 0:
        return 0
    moved = 0
    for item in order.requires:
        if item != RESOURCE:
            continue                      # only the leased resource is metered
        still = order.requires[item]
        if order.shipped.has(item):
            still = still - order.shipped[item]
        if still <= 0:
            continue
        result = self.input.take(item, min(budget, still))
        if result != None:
            moved = moved + result.moved
    return moved


while True:
    if not pick_order():
        sleep(PASS_S)
        continue

    budget = allotted()
    if budget == None:
        # FAIL_SAFE "idle". Keep the order and the dispatch setting, load
        # nothing. Anything already loaded ships, because stopping that would
        # strand cargo the dock cannot give back.
        say("dock: no fresh lease, loading nothing")
    elif budget <= 0:
        say("dock: leased nothing this pass")
    else:
        moved = load(budget)
        if moved > 0:
            say(f"dock: loaded {moved} toward {self.current_order().id}")
        if not self.is_enabled():
            self.set_enabled(True)

    sleep(PASS_S)
