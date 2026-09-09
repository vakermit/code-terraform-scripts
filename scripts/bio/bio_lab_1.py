# =============================================================================
#  BIO LAB  —  paste into the script slot of  bio_lab_1
#  Steps 2 and 3 of the biology loop: specimen -> analyzed -> sample.
# =============================================================================
#
#  This is script 2 of 3, and the one that does the real thinking.
#
#  A specimen is worthless until it becomes a sample, and a sample costs
#  reagents. Reagents cost credits and occupy inventory slots. So every
#  extraction here is planned before it is run:
#
#      analyze()  ->  recipe {reagent_id: qty}
#      recipe + inventory + credits  ->  BUILD A PROCEDURE (ordered steps)
#      run the procedure  ->  buy / load / extract
#
#  build_procedure() is the point of the split. It reads inventory and turns
#  "this specimen needs 3 cryo_solvent" into "buy 6 (3 for the bench, 3 for
#  the buffer), then load 3". Nothing is bought or loaded until the whole
#  plan is known, so a plan that cannot be afforded is abandoned before a
#  single credit is spent, and the plan is printed before it runs.
#
#  Two hazards drive the guards below:
#    * extract() with a mismatched bench DESTROYS the loaded reagents.
#      loaded_matches() refuses to extract unless the bench is exact.
#    * extract() into a full inventory stalls the whole pipeline.
#      make_room() sells surplus reagents — never samples, which sell for 0
#      on purpose; samples are worth credits only through the Bio Exchange.
# =============================================================================

REAGENT_BUFFER = 5     # units of each recipe reagent to keep beyond the bench need
CREDIT_FLOOR = 200     # never spend the last credits on optional buffer stock
IDLE_SLEEP = 0.5       # waiting on the collector / an action in flight
DEMAND_SLEEP = 5       # a required machine is missing — long wait

# Leave as "" to auto-detect, or paste the exact ids from the machine cards.
COLLECTOR_ID = ""
EXCHANGE_ID = ""


def find_machine(kind, configured):
    # Instance ids are numbered per save — bio_collector_1, bio_collector_2,
    # ... — so the id that works in one save may not exist in another.
    # get_component() returns None for an unknown id rather than raising,
    # so probing is safe: configured id, then bare type, then suffixes.
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

# A Bio Collector is not optional — it is the only source of specimens.
if collector == None:
    print("[lab] no Bio Collector found — set COLLECTOR_ID to the id on its machine card")

# A Bio Exchange is optional. Without one there is no order list, so there is
# no way to know which species are worth reagents. Fall back to catalog mode:
# analyze every specimen (analysis is what writes the catalog and the journal
# coords) and then discard it, so the run costs no reagents and no credits.
CATALOG_MODE = exchange == None
if CATALOG_MODE:
    print("[lab] no Bio Exchange found — catalog mode: analyze and discard, no extraction")
    print("[lab] set EXCHANGE_ID to the id on its machine card to extract toward orders")

# Every reagent id this lab has seen in a recipe. Seeded with the starter
# set, then grown from real recipes — so make_room() only ever sells things
# it knows to be reagents. A list, not a set, because the interpreter's for
# loop iterates lists, tuples and ranges.
known_reagents = [
    "alkaline_buffer", "cryo_solvent", "protein_marker",
    "chelating_agent", "enzyme_solution"
]


def remember_reagent(reagent):
    if reagent not in known_reagents:
        known_reagents.append(reagent)


# ---------------------------------------------------------------- demand ----

def outstanding_demand():
    # Same calculation the Collector and Exchange run: what unfinished
    # orders still need, minus samples already sitting in inventory.
    if CATALOG_MODE:
        return {}

    demand = {}
    for order in exchange.orders():
        if order.status == "complete":
            continue
        for frag in order.requires.keys():
            missing = order.requires[frag] - order.delivered.get(frag, 0)
            if missing > 0:
                demand[frag] = demand.get(frag, 0) + missing

    short = {}
    for frag in demand.keys():
        gap = demand[frag] - inventory.get_count(frag)
        if gap > 0:
            short[frag] = gap
    return short


def any_open_orders():
    # In catalog mode there is no order list to consult, but there is still
    # cataloging work to do, so the loop keeps running.
    if CATALOG_MODE:
        return True

    for order in exchange.orders():
        if order.status != "complete":
            return True
    return False


# ------------------------------------------------------------- inventory ----

def make_room():
    # Guarantee at least one free slot. Sells reagent surplus above the
    # buffer. Returns True if a slot is free.
    if inventory.get_used() < inventory.get_size():
        return True

    for reagent in known_reagents:
        while inventory.get_used() >= inventory.get_size():
            if inventory.get_count(reagent) <= REAGENT_BUFFER:
                break
            earned = shop.sell(reagent)
            if earned <= 0:
                break
            print("[lab] sold 1 surplus", reagent, "for", earned, "cr to free a slot")
        if inventory.get_used() < inventory.get_size():
            return True

    return inventory.get_used() < inventory.get_size()


# -------------------------------------------------------------- procedure ---

def build_procedure(recipe):
    # Turn an analyzed recipe into an ordered list of steps, given what
    # inventory holds right now.
    #
    # Each step is a dict:
    #     {"op": "buy",  "reagent": id, "qty": n, "required": n}
    #     {"op": "load", "reagent": id, "qty": n}
    #     {"op": "extract"}
    #
    # `qty` on a buy includes the buffer; `required` is the part that is not
    # optional. If a buy cannot reach `required`, the procedure is abandoned.
    steps = []
    for reagent in recipe.keys():
        remember_reagent(reagent)

        need = recipe[reagent]
        on_bench = self.loaded_reagents.get(reagent, 0)
        to_load = need - on_bench
        if to_load <= 0:
            continue

        in_stock = inventory.get_count(reagent)
        wanted = to_load + REAGENT_BUFFER
        if in_stock < wanted:
            step = {}
            step["op"] = "buy"
            step["reagent"] = reagent
            step["qty"] = wanted - in_stock
            step["required"] = to_load - in_stock   # <= 0 means pure buffer
            steps.append(step)

        step = {}
        step["op"] = "load"
        step["reagent"] = reagent
        step["qty"] = to_load
        steps.append(step)

    steps.append({"op": "extract"})
    return steps


def describe(steps):
    # One-line rendering of a procedure, printed before it runs.
    parts = []
    for step in steps:
        op = step["op"]
        if op == "extract":
            parts.append("extract")
        else:
            qty = step["qty"]
            reagent = step["reagent"]
            parts.append(f"{op} {qty}x {reagent}")
    return " -> ".join(parts)


def run_buy(step):
    # Buy up to step["qty"]. Succeeds as long as the non-optional part is
    # covered — the buffer is a nice-to-have, the bench need is not.
    reagent = step["reagent"]
    target = step["qty"]
    required = step["required"]

    bought = 0
    while bought < target:
        # Buffer purchases stop at the credit floor; required ones do not.
        if bought >= required and commander.get_credits() < CREDIT_FLOOR:
            break
        if not make_room():
            break

        result = shop.buy(reagent)
        if result == "ok":
            bought = bought + 1
            continue

        # not_enough / inventory_full / not_found / locked
        print("[lab] cannot buy", reagent, "-", result)
        break

    if bought > 0:
        print("[lab] bought", bought, "x", reagent)
    return bought >= required


def loaded_matches(recipe):
    # The bench must equal the recipe exactly — no missing units, no extras.
    # extract() destroys the loaded reagents otherwise.
    bench = self.loaded_reagents
    for reagent in recipe.keys():
        if bench.get(reagent, 0) != recipe[reagent]:
            return False
    for reagent in bench.keys():
        if recipe.get(reagent, 0) != bench[reagent]:
            return False
    return True


def run_procedure(steps, recipe):
    # Execute a built procedure. Returns a status string.
    for step in steps:
        op = step["op"]

        if op == "buy":
            if not run_buy(step):
                return "short_reagents"

        elif op == "load":
            result = self.load(step["reagent"], step["qty"])
            if result != True:
                print("[lab] load", step["reagent"], "failed:", result)
                return "short_reagents"

        elif op == "extract":
            if not loaded_matches(recipe):
                # Stale or wrong bench. discard() is the only way to clear
                # loaded reagents without destroying them — it refunds them.
                print("[lab] bench does not match recipe — refunding and resetting")
                self.discard()
                return "bench_reset"
            if not make_room():
                return "inventory_full"
            return self.extract()

    return "incomplete"


# ------------------------------------------------------------------ loop ----

while True:
    if not any_open_orders():
        print("[lab] every bio order is complete — stopping")
        break

    spec = self.input

    # --- no specimen: pull one out of the collector's cargo -----------------
    if not spec:
        if collector == None:
            sleep(DEMAND_SLEEP)
            continue
        result = self.take_from(collector)
        if result != True:
            # source_empty is the normal case — the collector is still out.
            sleep(IDLE_SLEEP)
        continue

    # --- specimen present but unidentified: analyze it ----------------------
    if spec.stage == "collected":
        result = self.analyze()
        # Read state back rather than inspecting the return type: analyze()
        # gives an AnalyzeInfo on success and a status string otherwise.
        if self.input and self.input.stage == "analyzed":
            print("[lab] analyzed", self.input.fragment_id, "-", self.input.rarity)
        else:
            print("[lab] analyze deferred:", result)
            sleep(IDLE_SLEEP)
        continue

    # --- analyzed: is this species still worth reagents? --------------------
    short = outstanding_demand()
    if not short.has(spec.fragment_id):
        result = self.discard()
        if CATALOG_MODE:
            # The analyze() above already wrote the catalog entry and the
            # journal coords — that was the whole point of the trip.
            print("[lab] cataloged", spec.fragment_id, "- discard", result)
        else:
            print("[lab] no open order needs", spec.fragment_id, "- discard", result)
        if result == "inventory_full":
            make_room()
        continue

    # --- build the procedure from the recipe + current inventory ------------
    fragment = spec.fragment_id
    still_short = short[fragment]
    recipe = spec.recipe
    steps = build_procedure(recipe)
    print("[lab] procedure for", fragment, ":", describe(steps))

    status = run_procedure(steps, recipe)

    if status == "ok":
        remaining = still_short - 1
        print("[lab] extracted 1x", fragment, "-", remaining, "still short")
    elif status == "inventory_full":
        print("[lab] inventory full — specimen and reagents held, retrying")
        sleep(1)
    elif status == "short_reagents":
        print("[lab] procedure stalled on reagents — waiting")
        sleep(1)
    elif status == "recipe_mismatch":
        # Should be unreachable: loaded_matches() gates extract().
        print("[lab] RECIPE MISMATCH — reagents lost, specimen preserved")
    elif status == "bench_reset":
        sleep(IDLE_SLEEP)
    else:
        # busy / input_empty / not_analyzed — transient, re-read state.
        print("[lab] extract returned", status)
        sleep(IDLE_SLEEP)
