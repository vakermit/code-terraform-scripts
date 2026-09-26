# =============================================================================
#  SUPPLY DOCK  —  paste into the script slot of  supply_dock_1
#  Pick an Earth Order, load it from storage, ship it; tell the factory
#  what to make for the rest.
# =============================================================================
#
#  Three things must be true for anything to ship: an order is assigned,
#  its items are loaded, and dispatch is enabled. Completion or a weekly
#  board refresh clears the order AND disables dispatch, so the script
#  polls current_order() and starts the cycle again when it goes None.
#
#  CHANNEL CONTRACT — see fabricator_1.py for the factory table.
#    writes   dock.needs   {item_id: units}   what the active order still
#             needs that storage does not hold. The Fabricator merges this
#             with factory.targets, so an Earth Order pulls production.
#    writes   factory.status.dock
#
#  CHOOSING. Campaign orders never expire; weekly ones do, and their
#  shipped progress is lost at refresh. Score = reward × fillable fraction,
#  where fillable is what storage can cover right now. A weekly order that
#  cannot be finished before its board refreshes is skipped unless nothing
#  else is available. ORDER_ID pins one order and bypasses the scoring.
#
#  LOADING. The input port is order-aware and refuses overshoot, so the
#  script simply pulls what is still owed. Pull order is Inventory first,
#  then bins. Leftover cargo after a completion or expiry is ejected back
#  to storage, since set_order() answers "cargo_present" until it is.
# =============================================================================

from power import wait_for_policy
from store import aim, bins, sink_for, source_for, stock_of

STORE = "inventory"        # last-resort sink for leftovers
ORDER_ID = ""              # pin an order id; "" = choose by score
ALLOW_WEEKLY = True
POLL = 5

orders = get_component("orders")
inventory = get_component("inventory")
clock = get_component("clock")
research = get_component("research")
comms = get_component("comms")
home = get_component("outpost_network").home()

if comms == None:
    print("[dock] DEGRADED: no Signal Bus — the factory will not hear this order's needs")
if not research.is_unlocked("research_auto_feeders"):
    print("[dock] Auto Feeders is not researched — loading will not move anything")


# ---------------------------------------------------------------- stores ----

def pull(item, count):
    moved = 0
    while moved < count:
        src = source_for(item)
        if src == "" or not aim(self.input, src, "dock"):
            break
        result = self.input.take(item, count - moved)
        if result.status != "ok" or result.moved == 0:
            if result.status != "ok":
                print("[dock] take", item, ":", result.message)
            break
        moved = moved + result.moved
    return moved


def eject_leftovers():
    # After completion or expiry the slots may still hold cargo; the next
    # set_order() refuses until they are empty.
    for slot in self.slots():
        if slot.item_id == None or slot.count == 0:
            continue
        result = self.input.eject(sink_for(slot.item_id), slot.item_id, slot.count)
        if result.status == "ok":
            print("[dock] returned", slot.count, "x", slot.item_id, "to storage")
        else:
            print("[dock] eject", slot.item_id, ":", result.message)
            return False
    return True


# ---------------------------------------------------------------- orders ----

def owed(order):
    # {item: units still to ship}, net of shipped and what is loaded here.
    out = {}
    for item in order.requires.keys():
        left = order.requires[item] - order.shipped.get(item, 0) - self.count(item)
        if left > 0:
            out[item] = left
    return out


def assess(order):
    need = owed(order)
    total = 0
    fillable = 0
    for item in need.keys():
        total = total + need[item]
        fillable = fillable + min(need[item], stock_of(item))

    a = {}
    a["order"] = order
    a["need"] = need
    a["total"] = total
    a["fillable"] = fillable
    a["finishable"] = True
    if order.kind == "weekly" and order.expires_day != None:
        hours_left = (order.expires_day - clock.get_day()) * 24
        a["finishable"] = total <= self.dispatch_rate() * hours_left
    if total > 0:
        a["score"] = order.reward_credits * fillable / total
    else:
        a["score"] = 0
    return a


def candidates():
    out = []
    for order in orders.list_orders():
        out.append(order)
    if ALLOW_WEEKLY:
        for order in orders.list_weekly_orders():
            if order.status == "active":
                out.append(order)
    return out


def choose():
    if ORDER_ID != "":
        pinned = orders.get_order(ORDER_ID)
        if pinned != None and pinned.status != "completed":
            return assess(pinned)
        print("[dock] ORDER_ID", ORDER_ID, "is not an open order — choosing by score")

    best = None
    fallback = None
    for order in candidates():
        a = assess(order)
        if a["total"] == 0:
            continue
        if fallback == None or a["score"] > fallback["score"]:
            fallback = a
        if not a["finishable"]:
            continue
        if best == None or a["score"] > best["score"]:
            best = a
    if best == None:
        return fallback
    return best


def publish(a, state):
    if comms == None:
        return
    needs = {}
    if a != None:
        for item in a["need"].keys():
            short = a["need"][item] - stock_of(item)
            if short > 0:
                needs[item] = short
    comms.broadcast("dock.needs", needs)

    status = {}
    status["state"] = state
    status["dispatching"] = self.current_dispatch()
    status["loaded"] = self.total()
    status["owed"] = self.capacity()
    if a != None:
        status["order"] = a["order"].name
    comms.broadcast("factory.status.dock", status)


# ------------------------------------------------------------------ loop ----

print("[dock]", len(bins()), "storage bins at", home.name, "- rate",
      self.dispatch_rate(), "units/h")
announced = ""

while True:
    # Hold off starting work the grid cannot carry. Hysteretic: a job
    # already running continues down to PAUSE_PCT, a new one waits for
    # RESUME_PCT, so this does not flap around a single threshold.
    wait_for_policy(self.id, "production", "dock")

    order = self.current_order()

    # --- nothing assigned: clear the slots and pick ---------------------------
    if order == None:
        if self.total() > 0:
            if not eject_leftovers():
                sleep(POLL)
                continue

        a = choose()
        if a == None:
            if announced != "none":
                print("[dock] no open Earth Order to ship — idle")
                announced = "none"
            publish(None, "idle")
            sleep(POLL * 6)
            continue

        result = self.set_order(a["order"].id)
        if result.status != "ok":
            print("[dock] set_order", a["order"].name, ":", result.message)
            sleep(POLL)
            continue
        announced = ""
        continue

    # --- assigned: load what is owed, keep dispatch on ------------------------
    a = assess(order)
    if announced != order.id:
        print("[dock] shipping", order.name, "- pays", order.reward_credits,
              "cr;", a["total"], "units owed,", a["fillable"], "in storage")
        if order.kind == "weekly" and not a["finishable"]:
            print("[dock] warning: cannot finish this weekly order before its board refreshes")
        announced = order.id

    loaded_any = False
    for item in a["need"].keys():
        moved = pull(item, a["need"][item])
        if moved > 0:
            loaded_any = True
            print("[dock] loaded", moved, "x", item)

    if not self.is_enabled():
        result = self.set_enabled(True)
        if result.status != "ok":
            print("[dock] enable:", result.message)

    if loaded_any:
        publish(a, "loading")
    elif self.current_dispatch() != None:
        publish(a, "dispatching")
    else:
        publish(a, "waiting")
    sleep(POLL)
