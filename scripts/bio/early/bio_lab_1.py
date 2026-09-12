# =============================================================================
#  BIO LAB  —  paste into the script slot of  bio_lab_1
#  Steps 2 and 3 of the biology loop: specimen -> analyzed -> sample.
# =============================================================================
#
#  This is script 2 of 3, and it is the one that learns.
#
#  THE COST MODEL. Nothing in the API will tell you what a Bio Order costs
#  to fill. Prices are public — shop.get_catalogue() gives every reagent's
#  cost — but the recipe that turns a fragment into a sample is revealed
#  ONLY by analyze(), and only while that specimen sits in this chamber.
#  scan() hides recipes, journal.cataloged_fragments() has no recipe field,
#  and item_catalog.lookup() has no recipe field.
#
#  So the price list has to be built, one analysis at a time:
#
#      analyze()  ->  info.required_recipe  ->  recipes[fragment_id]
#      recipes[frag] x shop prices          ->  cost per sample
#      cost per sample x order remaining    ->  cost to finish the order
#
#  analyze() costs no reagents — only ~0.1 h — so learning a recipe is
#  nearly free. That is why the Collector's opening run samples unknown
#  dots: it is buying the price list, cheaply, before anything is spent.
#
#  The learned book lives in this script's variables, so it resets when the
#  script restarts. The journal keeps the fragments; it does not keep their
#  recipes. Re-analysing a known fragment reprices it in one cheap trip.
#
#  PORTS. The manual Biology buttons and the scripted ports are separate
#  paths. A script must take reagents into self.input, load() them into the
#  chamber, then send() the finished sample out of self.output. self.input
#  holds ONE reagent type at a time, so each reagent is taken and loaded in
#  turn rather than all staged at once.
# =============================================================================

STORE = "inventory"    # freight endpoint; at a remote outpost use a local bin
REAGENT_BUFFER = 5     # spare units to keep beyond the recipe's need
CREDIT_FLOOR = 200     # never spend below this on optional buffer stock
IDLE_SLEEP = 0.5
DEMAND_SLEEP = 5

# Leave as "" to auto-detect, or paste the exact ids from the machine cards.
COLLECTOR_ID = ""
EXCHANGE_ID = ""


def find_machine(kind, configured):
    # Instance ids are numbered per save — bio_collector_1, bio_collector_2,
    # ... — and a powered-down machine reads the same as a missing one.
    if configured != "":
        found = get_component(configured)
        if found != None:
            return found

    found = get_component(kind)
    if found != None:
        return found

    n = 1
    while n <= 8:
        found = get_component(kind + "_" + str(n))
        if found != None:
            return found
        n = n + 1
    return None


collector = find_machine("bio_collector", COLLECTOR_ID)
exchange = find_machine("bio_exchange", EXCHANGE_ID)
inventory = get_component("inventory")
shop = get_component("shop")
commander = get_component("commander")
research = get_component("research")

if collector == None:
    print("[lab] no Bio Collector found — is it powered on?")

# Scripted port transfers are gated behind research. Without it take() and
# send() fail and the Lab can only be driven by the manual workbench.
if not research.is_unlocked("research_auto_feeders"):
    print("[lab] Auto Feeders is not researched — self.input.take() and")
    print("[lab] self.output.send() will not move anything yet.")


# ------------------------------------------------------------ price list ----

# Reagent prices are static, so read the catalogue once.
prices = {}
for entry in shop.get_catalogue():
    prices[entry.id] = entry.cost

# fragment_id -> {reagent_id: qty}, learned from analyze().
recipes = {}


def recipe_cost(recipe):
    # Credits of reagents consumed by one extraction of this recipe.
    total = 0
    for reagent in recipe.keys():
        total = total + recipe[reagent] * prices.get(reagent, 0)
    return total


def order_estimate(order):
    # What finishing `order` would cost in reagents, from what we know.
    #
    # Returns {"cost": n, "known": n, "unknown": n} where cost covers only
    # the fragments whose recipe has been learned. `unknown` counts the
    # samples we cannot price yet — the estimate is a floor while it is > 0.
    cost = 0
    known = 0
    unknown = 0

    for frag in order.requires.keys():
        short = order.requires[frag]
        short = short - order.delivered.get(frag, 0)
        short = short - order.in_transit.get(frag, 0)
        if short <= 0:
            continue

        if recipes.has(frag):
            cost = cost + short * recipe_cost(recipes[frag])
            known = known + short
        else:
            unknown = unknown + short

    estimate = {}
    estimate["cost"] = cost
    estimate["known"] = known
    estimate["unknown"] = unknown
    return estimate


def report_order_economics():
    # One-line read on whether the active order is worth finishing.
    if exchange == None:
        return

    order = exchange.active_order()
    if order == None:
        return

    estimate = order_estimate(order)
    cost = estimate["cost"]
    unknown = estimate["unknown"]
    margin = order.reward - cost

    if unknown > 0:
        print("[lab]", order.name, "- at least", cost, "cr of reagents,")
        print("[lab]  ", unknown, "samples still unpriced — margin under", margin)
    else:
        print("[lab]", order.name, "- costs", cost, "cr, pays", order.reward,
              "cr, margin", margin)


# ---------------------------------------------------------------- demand ----

def active_remaining():
    # What the ACTIVE order still needs, net of committed samples.
    if exchange == None:
        return {}

    order = exchange.active_order()
    if order == None:
        return {}

    remaining = {}
    for frag in order.requires.keys():
        short = order.requires[frag]
        short = short - order.delivered.get(frag, 0)
        short = short - order.in_transit.get(frag, 0)
        if short > 0:
            remaining[frag] = short
    return remaining


# ----------------------------------------------------------------- ports ----

def ensure_ports():
    # Both ports must point at the store before anything can move.
    if self.input.connected_id() != STORE:
        result = self.input.connect(STORE)
        if result.status != "ok":
            print("[lab] input connect failed:", result.message)
            return False

    if self.output.connected_id() != STORE:
        result = self.output.connect(STORE)
        if result.status != "ok":
            print("[lab] output connect failed:", result.message)
            return False

    return True


def drain_output():
    # Push finished samples and recovered reagents back to the store.
    # extract() stages into output and does NOT forward automatically, so a
    # full output port stalls the next extraction.
    for stack in self.output.stacks():
        result = self.output.send(stack.id, stack.count, stack.properties, "exact")
        if result.status != "ok":
            print("[lab] could not drain", stack.id, "-", result.message)
            return False
    return True


def clear_input_except(reagent):
    # self.input latches to one reagent id. A leftover of a different type
    # blocks the next take(), so return it to the store first.
    for stack in self.input.stacks():
        if stack.id == reagent:
            continue
        result = self.input.eject(STORE, stack.id, stack.count)
        if result.status != "ok":
            print("[lab] input blocked by", stack.id, "-", result.message)
            return False
    return True


# ------------------------------------------------------------- reagents ----

def stock_reagent(reagent, units):
    # Make sure the store holds `units` of `reagent`, buying the shortfall
    # plus a buffer. Returns True when the required amount is covered.
    held = inventory.count(reagent)
    if held >= units:
        return True

    shortfall = units - held
    wanted = shortfall + REAGENT_BUFFER

    # The buffer is optional; the shortfall is not.
    if commander.get_credits() < CREDIT_FLOOR:
        wanted = shortfall

    price = prices.get(reagent, 0)
    if price * wanted > commander.get_credits():
        affordable = 0
        if price > 0:
            affordable = floor(commander.get_credits() / price)
        if affordable < shortfall:
            print("[lab] cannot afford", shortfall, "x", reagent,
                  "- need", price * shortfall, "cr")
            return False
        wanted = affordable

    result = shop.buy(reagent, wanted)
    if result.status != "ok":
        print("[lab] buy", reagent, "failed:", result.message)
        return inventory.count(reagent) >= units

    return inventory.count(reagent) >= units


def stage_recipe(recipe):
    # Take and load each reagent in turn. self.input holds one type at a
    # time, so this is take -> load -> take -> load, not a bulk staging.
    #
    # Subtract what is already in loaded_reagents on every pass: taking the
    # full recipe again would leave a surplus latched in the input port and
    # block the next reagent type.
    for reagent in recipe.keys():
        need = recipe[reagent] - self.loaded_reagents.get(reagent, 0)
        if need <= 0:
            continue

        if not stock_reagent(reagent, need):
            return False
        if not clear_input_except(reagent):
            return False

        staged = self.input.count()
        if staged < need:
            result = self.input.take(reagent, need - staged)
            if result.status != "ok":
                print("[lab] take", reagent, "failed:", result.message)
                return False

        result = self.load(reagent, need)
        if result.status != "ok":
            print("[lab] load", reagent, "failed:", result.message)
            return False

    return True


def bench_matches(recipe):
    # The chamber must equal the recipe exactly — no missing units, no
    # extras. extract() destroys the loaded reagents otherwise.
    bench = self.loaded_reagents
    for reagent in recipe.keys():
        if bench.get(reagent, 0) != recipe[reagent]:
            return False
    for reagent in bench.keys():
        if recipe.get(reagent, 0) != bench[reagent]:
            return False
    return True


# ------------------------------------------------------------------ loop ----

reported_for = ""

while True:
    if not ensure_ports():
        sleep(DEMAND_SLEEP)
        continue

    # Output first: a full output port stalls extract(), discard() and
    # unload_reagents(), all of which stage their results there.
    drain_output()

    specimen = self.specimen

    # --- empty chamber: pull a specimen from the collector's cargo ----------
    if not specimen:
        if collector == None:
            sleep(DEMAND_SLEEP)
            continue
        result = self.take_from(collector)
        if result.status != "ok":
            # source_empty is the normal case — the collector is still out.
            sleep(IDLE_SLEEP)
        continue

    # --- unidentified: analyze, and learn the recipe ------------------------
    if specimen.stage == "collected":
        result = self.analyze()
        if result.status != "ok":
            print("[lab] analyze:", result.message)
            sleep(IDLE_SLEEP)
            continue

        info = result.info
        recipes[info.fragment_id] = info.required_recipe
        per_sample = recipe_cost(info.required_recipe)
        print("[lab] analyzed", info.name, "-", info.rarity,
              "- costs", per_sample, "cr per sample")

        # A newly priced fragment can change the order's economics.
        report_order_economics()
        continue

    # --- analyzed: does the ACTIVE order still want this fragment? ----------
    fragment = specimen.fragment_id
    remaining = active_remaining()

    if not remaining.has(fragment):
        # analyze() already catalogued it and recorded its recipe, which was
        # the value of the trip. Extracting would spend reagents for nothing.
        result = self.discard()
        print("[lab] active order does not need", fragment, "- discarded")
        if result.status != "ok":
            print("[lab] discard:", result.message)
            sleep(IDLE_SLEEP)
        continue

    # --- affordability gate -------------------------------------------------
    recipe = specimen.recipe
    cost = recipe_cost(recipe)
    if cost > commander.get_credits():
        if reported_for != fragment:
            print("[lab] cannot afford", fragment, "-", cost, "cr needed,",
                  commander.get_credits(), "on hand")
            reported_for = fragment
        sleep(DEMAND_SLEEP)
        continue

    reported_for = ""

    # --- stage the recipe and extract ---------------------------------------
    if not stage_recipe(recipe):
        sleep(DEMAND_SLEEP)
        continue

    if not bench_matches(recipe):
        # Wrong or stale bench. unload_reagents() recovers them intact via
        # the output port; extracting now would destroy them.
        print("[lab] chamber does not match recipe — recovering reagents")
        self.unload_reagents()
        drain_output()
        continue

    result = self.extract()
    if result.status == "ok":
        left = remaining[fragment] - 1
        print("[lab] extracted", fragment, "for", cost, "cr -", left, "still needed")
        drain_output()
    else:
        print("[lab] extract:", result.message)
        sleep(IDLE_SLEEP)
