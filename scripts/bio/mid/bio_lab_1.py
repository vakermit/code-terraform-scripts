# =============================================================================
#  BIO LAB  (mid tier)  —  paste into the script slot of  bio_lab_1
#  Steps 2 and 3 of the biology loop: specimen -> analyzed -> sample.
# =============================================================================
#
#  This is the machine that LEARNS, and in the mid tier it finally gets to
#  tell someone. Every analyze() reveals a recipe; priced against the shop
#  catalogue that is the true cost of one sample. The early script kept
#  that to itself and lost it on restart. This one:
#
#    * publishes it on the Signal Bus   ->  comms.broadcast("bio.prices")
#      so the Exchange can rank orders by real margin, and
#    * writes it to the Data Archive     ->  notebook.set("bio.prices")
#      so it survives script restarts and save/load.
#
#  The Data Archive is a separate research from the Signal Bus. If it is
#  not unlocked yet the book still works for this run and is re-learned
#  after a restart, one free analysis at a time.
#
#  CHANNEL CONTRACT — see bio_exchange_1.py for the full table.
#    reads   bio.plan     {"remaining": {fragment_id: n}, ...}
#    writes  bio.prices   {fragment_id: {"cost": n, "rarity": s, "name": s}}
#    writes  bio.status.lab
#
#  EXTRACT OR DISCARD. The plan's `remaining` is what the active order is
#  still owed. Subtract what the store already holds; if that is positive
#  the sample is wanted and reagents are spent, otherwise the specimen is
#  discarded — analyze() already banked its catalog entry and its price,
#  which was the value of the trip.
#
#  PORTS. self.input holds ONE reagent type at a time, so each reagent is
#  taken and loaded in turn. extract() stages into self.output and does not
#  forward; the output is drained to the store on every pass.
# =============================================================================

STORE = "inventory"    # freight endpoint; at a remote outpost use a local bin
REAGENT_BUFFER = 5     # spare units to keep beyond the recipe's need
CREDIT_FLOOR = 200     # never spend below this on optional buffer stock
IDLE_SLEEP = 0.5
DEMAND_SLEEP = 5

BOOK_KEY = "bio.prices"   # Data Archive key and Signal Bus channel

# Leave as "" to auto-detect, or paste the exact id from the machine card.
COLLECTOR_ID = ""


def find_machine(kind, configured):
    # Instance ids are numbered per save and a powered-down machine reads
    # the same as a missing one; get_component() returns None either way.
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
inventory = get_component("inventory")
shop = get_component("shop")
commander = get_component("commander")
research = get_component("research")
comms = get_component("comms")
notebook = get_component("notebook")

if collector == None:
    print("[lab] no Bio Collector found — is it powered on?")
if comms == None:
    print("[lab] Signal Bus not researched — this is the mid-tier script;")
    print("[lab] use scripts/bio/early until comms unlock.")
if notebook == None:
    print("[lab] Data Archive not researched — prices will not survive a restart")
if not research.is_unlocked("research_auto_feeders"):
    print("[lab] Auto Feeders is not researched — self.input.take() and")
    print("[lab] self.output.send() will not move anything yet.")


# ------------------------------------------------------------ price book ----

# Reagent prices are static, so read the catalogue once.
prices = {}
for entry in shop.get_catalogue():
    prices[entry.id] = entry.cost

# fragment_id -> {"cost": n, "rarity": s, "name": s}
book = {}
if notebook != None:
    book = notebook.get(BOOK_KEY, {})
    if len(book) > 0:
        print("[lab] loaded", len(book), "priced fragments from the Data Archive")

# The Exchange reads bio.prices from the bus, so republish what was loaded.
if comms != None:
    comms.broadcast(BOOK_KEY, book)


def recipe_cost(recipe):
    total = 0
    for reagent in recipe.keys():
        total = total + recipe[reagent] * prices.get(reagent, 0)
    return total


def learn(info):
    # Record one analysis in the book, then persist and publish it.
    entry = {}
    entry["cost"] = recipe_cost(info.required_recipe)
    entry["rarity"] = info.rarity
    entry["name"] = info.name

    fresh = not book.has(info.fragment_id)
    book[info.fragment_id] = entry

    if notebook != None:
        written = notebook.set(BOOK_KEY, book)
        if written.status != "ok":
            print("[lab] archive write failed:", written.message)
    if comms != None:
        comms.broadcast(BOOK_KEY, book)

    return fresh


# ------------------------------------------------------------------ plan ----

def wanted_count(fragment_id):
    # How many more samples of this fragment the plan wants MADE:
    # the active order's remaining need minus what the store already holds.
    if comms == None:
        return 0
    plan = comms.latest("bio.plan")
    if plan == None:
        return 0
    remaining = plan["remaining"]
    if not remaining.has(fragment_id):
        return 0
    return remaining[fragment_id] - inventory.count(fragment_id)


def publish_status(state, detail):
    if comms == None:
        return
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["priced"] = len(book)
    status["credits"] = commander.get_credits()
    comms.broadcast("bio.status.lab", status)


# ----------------------------------------------------------------- ports ----

def ensure_ports():
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
    # extract(), discard() and unload_reagents() all stage into the output
    # port and none of them forward; a full port stalls all three.
    for stack in self.output.stacks():
        result = self.output.send(stack.id, stack.count, stack.properties, "exact")
        if result.status != "ok":
            print("[lab] could not drain", stack.id, "-", result.message)
            return False
    return True


def clear_input_except(reagent):
    # self.input latches to one reagent id; a leftover of another type
    # blocks the next take(). Return it to the store first.
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
    # Ensure the store holds `units` of `reagent`, buying the shortfall plus
    # a buffer when credits allow. True when the required amount is covered.
    held = inventory.count(reagent)
    if held >= units:
        return True

    shortfall = units - held
    wanted = shortfall + REAGENT_BUFFER
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


def stage_recipe(recipe):
    # take -> load per reagent. Subtract what is already loaded on every
    # pass, or a retry leaves a surplus latched in the input port.
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
    # Exact match only — extract() destroys a mismatched bench.
    bench = self.loaded_reagents
    for reagent in recipe.keys():
        if bench.get(reagent, 0) != recipe[reagent]:
            return False
    for reagent in bench.keys():
        if recipe.get(reagent, 0) != bench[reagent]:
            return False
    return True


# ------------------------------------------------------------------ loop ----

blocked_on = ""

while True:
    if not ensure_ports():
        sleep(DEMAND_SLEEP)
        continue

    drain_output()
    specimen = self.specimen

    # --- empty chamber: pull from the collector -----------------------------
    if not specimen:
        if collector == None:
            sleep(DEMAND_SLEEP)
            continue
        result = self.take_from(collector)
        if result.status != "ok":
            publish_status("idle", "")
            sleep(IDLE_SLEEP)
        continue

    # --- unidentified: analyze and learn -----------------------------------
    if specimen.stage == "collected":
        publish_status("analyzing", "")
        result = self.analyze()
        if result.status != "ok":
            print("[lab] analyze:", result.message)
            sleep(IDLE_SLEEP)
            continue

        info = result.info
        fresh = learn(info)
        cost = book[info.fragment_id]["cost"]
        if fresh:
            print("[lab] NEW PRICE:", info.name, "-", info.rarity, "-", cost, "cr per sample")
        else:
            print("[lab] analyzed", info.name, "-", cost, "cr per sample")
        continue

    # --- analyzed: does the plan want it made? ------------------------------
    fragment = specimen.fragment_id
    want = wanted_count(fragment)

    if want <= 0:
        result = self.discard()
        print("[lab] plan does not need", fragment, "- discarded")
        if result.status != "ok":
            print("[lab] discard:", result.message)
            sleep(IDLE_SLEEP)
        continue

    # --- affordability gate --------------------------------------------------
    recipe = specimen.recipe
    cost = recipe_cost(recipe)
    if cost > commander.get_credits():
        if blocked_on != fragment:
            print("[lab] cannot afford", fragment, "-", cost, "cr needed,",
                  commander.get_credits(), "on hand")
            blocked_on = fragment
        publish_status("blocked", fragment)
        sleep(DEMAND_SLEEP)
        continue
    blocked_on = ""

    # --- stage and extract ---------------------------------------------------
    publish_status("extracting", fragment)
    if not stage_recipe(recipe):
        sleep(DEMAND_SLEEP)
        continue

    if not bench_matches(recipe):
        print("[lab] chamber does not match recipe — recovering reagents")
        self.unload_reagents()
        drain_output()
        continue

    result = self.extract()
    if result.status == "ok":
        print("[lab] extracted", fragment, "for", cost, "cr -", want - 1, "more wanted")
        drain_output()
    else:
        print("[lab] extract:", result.message)
        sleep(IDLE_SLEEP)
