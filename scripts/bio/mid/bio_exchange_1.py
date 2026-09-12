# =============================================================================
#  BIO EXCHANGE  (mid tier)  —  paste into the script slot of  bio_exchange_1
#  Step 4 of the biology loop, and the PLANNER for the other two machines.
# =============================================================================
#
#  The early scripts coordinated through game state alone, and one thing
#  could not be done that way: the Lab learns what each fragment costs, but
#  only the Exchange can pick the order, and neither could tell the other.
#  The Signal Bus closes that gap. This script is the planner.
#
#  CHANNEL CONTRACT — shared by all three mid scripts
#  ---------------------------------------------------------------------------
#    bio.prices   broadcast   Lab -> all
#                 {fragment_id: {"cost": n, "rarity": s, "name": s}}
#                 Credits of reagents per extracted sample, learned by
#                 analyze(). Persisted by the Lab in the Data Archive.
#
#    bio.plan     broadcast   Exchange -> all          (this script writes)
#                 {"order": id, "name": s, "reward": n, "margin": n,
#                  "remaining": {fragment_id: n}, "scout": bool}
#                 The active order and what it still needs, net of
#                 delivered and in_transit. scout=True asks the Collector to
#                 favour unknown dots because the plan has unpriced parts.
#
#    bio.jobs     queue       Exchange -> Collectors   (this script writes)
#                 {"fragment_id": s, "name": s, "order": id}
#                 One message per sample that still has to be COLLECTED:
#                 remaining minus what the store already holds. Consumed
#                 once each, so several Collectors share the work cleanly.
#
#    bio.status.exchange / .lab / .collector   broadcast   telemetry
#  ---------------------------------------------------------------------------
#
#  ORDER SELECTION. With bio.prices this is a real margin calculation:
#
#      cost   = sum over remaining samples of price[fragment].cost
#      margin = reward - cost
#
#  Fragments the Lab has not priced yet are estimated from rarity, using
#  the average cost-per-rarity-point of everything already priced. While an
#  order has unpriced parts its margin is an estimate and the plan raises
#  `scout` so the Collector goes and prices them — analyze() is free.
#
#  AFFORDABILITY. Rewards pay at the end, so the reagent bill for every
#  sample still to be made must be fronted from current credits. An order
#  whose bill exceeds the balance is not activated while a cheaper one is
#  workable; if every order is out of reach the cheapest is chosen so the
#  Lab can at least chip at it as credits come in from elsewhere.
# =============================================================================

STORE = "inventory"    # freight endpoint; at a remote outpost use a local bin
IDLE_SLEEP = 0.5
BUSY_SLEEP = 0.25

# Rarity -> effort points. Used only to estimate fragments nobody has priced.
RARITY_WEIGHT = {"common": 1, "uncommon": 2, "rare": 4, "legendary": 8}
UNPRICED_GUESS_PER_POINT = 60   # credits per point before anything is priced

inventory = get_component("inventory")
catalog = get_component("item_catalog")
commander = get_component("commander")
research = get_component("research")
comms = get_component("comms")

if comms == None:
    print("[exchange] Signal Bus not researched — this is the mid-tier script;")
    print("[exchange] use scripts/bio/early until comms unlock.")

if not research.is_unlocked("research_auto_feeders"):
    print("[exchange] Auto Feeders is not researched — self.input.take()")
    print("[exchange] cannot stage samples yet; deliver from the workbench.")


# ---------------------------------------------------------------- prices ----

def price_book():
    # The Lab's published prices, or an empty book before it has spoken.
    if comms == None:
        return {}
    book = comms.latest("bio.prices")
    if book == None:
        return {}
    return book


def rarity_points(fragment_id):
    info = catalog.lookup(fragment_id)
    if info == None or info.rarity == None:
        return 1
    return RARITY_WEIGHT.get(info.rarity, 1)


def guess_rate(book):
    # Average priced cost per rarity point, to extrapolate unpriced ones.
    total_cost = 0
    total_points = 0
    for frag in book.keys():
        entry = book[frag]
        total_cost = total_cost + entry["cost"]
        total_points = total_points + RARITY_WEIGHT.get(entry["rarity"], 1)
    if total_points == 0:
        return UNPRICED_GUESS_PER_POINT
    return total_cost / total_points


# --------------------------------------------------------------- scoring ----

def assess(order, book, rate):
    # Everything the ranking needs about one order, right now.
    #
    #   remaining  {frag: n}  still owed, net of delivered and in_transit
    #   to_make    n          samples the Lab still has to extract
    #   ready      n          samples in the store deliverable right now
    #   cost       n          reagent bill for to_make (estimates included)
    #   unpriced   n          samples in to_make with no real price yet
    #   margin     n          reward - cost
    remaining = {}
    to_make = 0
    ready = 0
    cost = 0
    unpriced = 0

    for frag in order.requires.keys():
        need = order.requires[frag]
        need = need - order.delivered.get(frag, 0)
        need = need - order.in_transit.get(frag, 0)
        if need <= 0:
            continue
        remaining[frag] = need

        held = inventory.count(frag)
        if held >= need:
            ready = ready + need
            continue
        ready = ready + held

        make = need - held
        to_make = to_make + make
        if book.has(frag):
            cost = cost + make * book[frag]["cost"]
        else:
            cost = cost + make * rarity_points(frag) * rate
            unpriced = unpriced + make

    result = {}
    result["order"] = order
    result["remaining"] = remaining
    result["to_make"] = to_make
    result["ready"] = ready
    result["cost"] = cost
    result["unpriced"] = unpriced
    result["margin"] = order.reward - cost
    result["affordable"] = cost <= commander.get_credits()
    return result


def better(a, b):
    # 1. deliverable now beats not — it frees the store and pays sooner
    # 2. affordable beats not
    # 3. higher margin
    # 4. fewer samples left
    if (a["ready"] > 0) != (b["ready"] > 0):
        return a["ready"] > 0
    if a["affordable"] != b["affordable"]:
        return a["affordable"]
    if a["margin"] != b["margin"]:
        return a["margin"] > b["margin"]
    return a["to_make"] < b["to_make"]


def choose(orders):
    book = price_book()
    rate = guess_rate(book)

    best = None
    cheapest = None
    for order in orders:
        if order.status == "complete":
            continue
        a = assess(order, book, rate)
        if len(a["remaining"]) == 0:
            continue
        if best == None or better(a, best):
            best = a
        if cheapest == None or a["cost"] < cheapest["cost"]:
            cheapest = a

    # Nothing affordable at all: take the cheapest and let credits build.
    if best != None and not best["affordable"] and cheapest != None:
        if cheapest["ready"] == 0 and best["ready"] == 0:
            best = cheapest
    return best


# ------------------------------------------------------------ publishing ----

def publish_plan(a):
    if comms == None:
        return
    order = a["order"]
    plan = {}
    plan["order"] = order.id
    plan["name"] = order.name
    plan["reward"] = order.reward
    plan["margin"] = a["margin"]
    plan["remaining"] = a["remaining"]
    plan["scout"] = a["unpriced"] > 0
    comms.broadcast("bio.plan", plan)


def reconcile_jobs(a):
    # Keep exactly (remaining - held) collection jobs queued per fragment.
    # A job vanishes from pending() the moment a Collector takes it, so a
    # trip in flight can briefly let one extra job through; the Lab discards
    # any sample the plan no longer needs, so the cost is one wasted trip.
    if comms == None:
        return

    queued = {}
    stale = []
    for msg in comms.pending("bio.jobs"):
        frag = msg.value["fragment_id"]
        if msg.value["order"] != a["order"].id:
            stale.append(msg.id)
            continue
        queued[frag] = queued.get(frag, 0) + 1

    # Jobs for a previous order are no longer wanted.
    for message_id in stale:
        comms.cancel("bio.jobs", message_id)

    remaining = a["remaining"]
    for frag in remaining.keys():
        want = remaining[frag] - inventory.count(frag)
        have = queued.get(frag, 0)

        while have < want:
            job = {}
            job["fragment_id"] = frag
            job["order"] = a["order"].id
            info = catalog.lookup(frag)
            if info != None:
                job["name"] = info.name
            else:
                job["name"] = frag
            sent = comms.send("bio.jobs", job)
            if sent.status != "ok":
                break
            have = have + 1

        if have > want:
            for msg in comms.pending("bio.jobs"):
                if have <= want:
                    break
                if msg.value["fragment_id"] == frag:
                    comms.cancel("bio.jobs", msg.id)
                    have = have - 1


def publish_status(state, detail):
    if comms == None:
        return
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["credits"] = commander.get_credits()
    status["lifetime"] = self.lifetime_credits()
    comms.broadcast("bio.status.exchange", status)


# ----------------------------------------------------------------- ports ----

def ensure_ports():
    if self.input.connected_id() != STORE:
        result = self.input.connect(STORE)
        if result.status != "ok":
            print("[exchange] input connect failed:", result.message)
            return False
    if self.output.connected_id() != STORE:
        result = self.output.connect(STORE)
        if result.status != "ok":
            print("[exchange] output connect failed:", result.message)
            return False
    return True


def drain_output():
    # A shared order finished elsewhere returns our committed sample here.
    for stack in self.output.stacks():
        result = self.output.send(stack.id, stack.count, stack.properties, "exact")
        if result.status != "ok":
            print("[exchange] could not return", stack.id, "-", result.message)


def stage_one(order):
    # Move one qualifying sample from the store into self.input.
    # matches_order() is the authority: coastal orders want an exact glow
    # and geothermal orders want exact genes, so the id alone is not enough.
    for stack in inventory.stacks():
        if order.requires.get(stack.id, 0) <= 0:
            continue
        if not self.matches_order(stack.id, stack.properties):
            continue
        result = self.input.take(stack.id, 1, stack.properties, "exact")
        if result.status == "ok" and result.moved > 0:
            return True
    return False


# ------------------------------------------------------------------ loop ----

announced = ""

while True:
    if not ensure_ports():
        sleep(IDLE_SLEEP)
        continue

    drain_output()

    a = choose(self.orders())
    if a == None:
        print("[exchange] every bio order is complete — stopping")
        if comms != None:
            comms.clear("bio.jobs")
            comms.broadcast("bio.plan", None)
        publish_status("done", "")
        break

    order = a["order"]

    if order.status != "active":
        result = self.set_order(order.id)
        if result.status != "ok":
            print("[exchange] cannot activate", order.name, "-", result.message)
            sleep(IDLE_SLEEP)
            continue

    publish_plan(a)
    reconcile_jobs(a)

    if announced != order.id:
        cost = a["cost"]
        margin = a["margin"]
        if a["unpriced"] > 0:
            print("[exchange] target:", order.name, "- pays", order.reward,
                  "cr, est. cost", floor(cost), "cr (", a["unpriced"],
                  "unpriced ) est. margin", floor(margin))
        else:
            print("[exchange] target:", order.name, "- pays", order.reward,
                  "cr, costs", floor(cost), "cr, margin", floor(margin))
        if not a["affordable"]:
            print("[exchange] bill exceeds credits — Lab will extract as it can afford")
        announced = order.id

    # Stage a qualifying sample, then hand it over.
    if self.input.count() == 0:
        if not stage_one(order):
            publish_status("waiting", order.name)
            sleep(IDLE_SLEEP)
            continue

    result = self.deliver()

    if result.status == "ok":
        print("[exchange] delivered toward", order.name)
        publish_status("delivering", order.name)
    elif result.status == "complete":
        print("[exchange] ORDER COMPLETE:", order.name, "- paid", order.reward, "cr")
        publish_status("complete", order.name)
        announced = ""
    elif result.status == "busy":
        sleep(BUSY_SLEEP)
    else:
        print("[exchange] deliver:", result.message)
        sleep(IDLE_SLEEP)
