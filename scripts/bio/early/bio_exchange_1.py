# =============================================================================
#  BIO EXCHANGE  —  paste into the script slot of  bio_exchange_1
#  Step 4 of the biology loop: sample -> order -> credits.
# =============================================================================
#
#  This is script 3 of 3. It owns one decision — which Bio Order is active —
#  and the other two scripts follow it. The Collector targets the active
#  order's requirements; the Lab spends reagents only on fragments the
#  active order still needs. Choose badly here and both of them work for
#  nothing, so the choice is scored rather than taken in list order.
#
#  THE COST PROBLEM. Picking the most profitable order really means picking
#  the best reward MINUS reagent cost, and this script cannot see reagent
#  cost. Recipes are revealed only by bio_lab.analyze(), in the Lab's own
#  chamber, and set_order() is self-only so the Lab cannot make the choice
#  on our behalf. Until the machines can message each other, the price book
#  and the order selector live in different scripts.
#
#  THE PROXY. What IS available here is rarity: item_catalog.lookup() gives
#  .rarity for any fragment id, with no analysis and no field trip. Rarity
#  drives recipe expense, so weighting each required sample by rarity gives
#  a usable stand-in for cost:
#
#      score = reward / weighted samples still required
#
#  That is reward per unit of effort — high-reward orders full of rare
#  fragments stop outranking modest orders full of commons. It is a
#  heuristic, not a price. The Lab still holds the real credit gate and
#  refuses any extraction it cannot afford, so a mis-ranked order here
#  costs a little routing, never an overdraft.
#
#  When the machines can talk, replace RARITY_WEIGHT with the Lab's actual
#  per-sample costs and this becomes a true margin calculation.
# =============================================================================

STORE = "inventory"    # freight endpoint; at a remote outpost use a local bin
IDLE_SLEEP = 0.5       # waiting on the Lab to extract something deliverable
BUSY_SLEEP = 0.25      # a delivery is already mid-flight

# Cost proxy. Rarer fragments need more and pricier reagents per sample.
RARITY_WEIGHT = {
    "common": 1,
    "uncommon": 2,
    "rare": 4,
    "legendary": 8,
}

inventory = get_component("inventory")
catalog = get_component("item_catalog")
research = get_component("research")

if not research.is_unlocked("research_auto_feeders"):
    print("[exchange] Auto Feeders is not researched — self.input.take()")
    print("[exchange] cannot stage samples yet; deliver from the workbench.")

# fragment_id -> weight, so item_catalog is asked once per fragment.
weights = {}


def weight_of(fragment_id):
    # Rarity weight for one fragment, defaulting to common for anything the
    # catalog cannot classify.
    if weights.has(fragment_id):
        return weights[fragment_id]

    weight = 1
    info = catalog.lookup(fragment_id)
    if info != None and info.rarity != None:
        weight = RARITY_WEIGHT.get(info.rarity, 1)

    weights[fragment_id] = weight
    return weight


def score_order(order):
    # How this order stands right now.
    #
    # Returns a dict with:
    #   ready     — samples held in the store that it can accept now
    #   remaining — samples still required, net of delivered and in_transit
    #   effort    — those samples weighted by rarity, the cost proxy
    #   score     — reward per unit of effort
    ready = 0
    remaining = 0
    effort = 0

    for frag in order.requires.keys():
        needed = order.requires[frag]
        needed = needed - order.delivered.get(frag, 0)
        needed = needed - order.in_transit.get(frag, 0)
        if needed <= 0:
            continue

        remaining = remaining + needed
        effort = effort + needed * weight_of(frag)

        held = inventory.count(frag)
        if held < needed:
            ready = ready + held
        else:
            ready = ready + needed

    score = 0
    if effort > 0:
        score = order.reward / effort

    result = {}
    result["ready"] = ready
    result["remaining"] = remaining
    result["effort"] = effort
    result["score"] = score
    return result


def better(candidate, champion):
    # An order we can act on now always beats one we cannot: it frees store
    # space and pays sooner. Past that, best reward per unit of effort.
    candidate_live = candidate["ready"] > 0
    champion_live = champion["ready"] > 0
    if candidate_live != champion_live:
        return candidate_live

    if candidate["score"] != champion["score"]:
        return candidate["score"] > champion["score"]

    # Tie: finish whichever is closest to done.
    return candidate["remaining"] < champion["remaining"]


def pick_order(orders):
    # Best unfinished order, or None when every order is complete.
    champion = None
    for order in orders:
        if order.status == "complete":
            continue

        candidate = score_order(order)
        if candidate["remaining"] <= 0:
            # Fully delivered or fully committed — nothing left to do here.
            continue
        candidate["order"] = order

        if champion == None:
            champion = candidate
        elif better(candidate, champion):
            champion = candidate
    return champion


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
    # A shared order finished by another Exchange returns our committed
    # sample here. Put it back in the store so it can serve another order.
    for stack in self.output.stacks():
        result = self.output.send(stack.id, stack.count, stack.properties, "exact")
        if result.status != "ok":
            print("[exchange] could not return", stack.id, "-", result.message)


def stage_one(order):
    # Move one qualifying sample from the store into self.input.
    #
    # matches_order() is the authority, not the fragment id: coastal orders
    # want an exact glow and geothermal orders want exact genes, so two
    # stacks with the same id can differ on whether they qualify.
    for stack in inventory.stacks():
        needed = order.requires.get(stack.id, 0)
        if needed <= 0:
            continue
        if not self.matches_order(stack.id, stack.properties):
            continue

        result = self.input.take(stack.id, 1, stack.properties, "exact")
        if result.status == "ok" and result.moved > 0:
            return True

    return False


last_active = ""

while True:
    if not ensure_ports():
        sleep(IDLE_SLEEP)
        continue

    drain_output()

    choice = pick_order(self.orders())
    if choice == None:
        print("[exchange] every bio order is complete — stopping")
        break

    order = choice["order"]

    if order.status != "active":
        result = self.set_order(order.id)
        if result.status != "ok":
            print("[exchange] cannot activate", order.name, "-", result.message)
            sleep(IDLE_SLEEP)
            continue

    if last_active != order.id:
        print("[exchange] target:", order.name, "- pays", order.reward, "cr for",
              choice["remaining"], "samples (effort", choice["effort"], ")")
        last_active = order.id

    # Stage a qualifying sample, then hand it over.
    if self.input.count() == 0:
        if not stage_one(order):
            # Nothing in the store qualifies yet — the Lab is upstream.
            sleep(IDLE_SLEEP)
            continue

    result = self.deliver()

    if result.status == "ok":
        print("[exchange] delivered toward", order.name)
    elif result.status == "complete":
        print("[exchange] ORDER COMPLETE:", order.name, "- paid", order.reward, "cr")
        last_active = ""
    elif result.status == "busy":
        sleep(BUSY_SLEEP)
    elif result.status == "no_input":
        # The staged sample stopped qualifying — return it and re-pick.
        sleep(IDLE_SLEEP)
    else:
        print("[exchange] deliver:", result.message)
        sleep(IDLE_SLEEP)
