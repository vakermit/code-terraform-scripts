# =============================================================================
#  SMELTER  —  paste into the script slot of  smelter_1
#  Smelt whatever the Fabricator is short of, in batches; keep stock floors.
# =============================================================================
#
#  The Smelter processes automatically once a recipe is set and ore is in
#  its input. This script chooses the recipe and moves ore in, ingots out.
#
#  CHANNEL CONTRACT — see fabricator_1.py for the full table.
#    reads    factory.needs   {ingot_id: shortfall}   from the Fabricator
#    writes   factory.ore     {ore_id: units_short}   for the Rover
#    writes   factory.status.smelter
#
#  CHOOSING. Demand for each ingot is the larger of what the Fabricator
#  asked for and what it takes to bring the store up to FLOORS. The recipe
#  with the biggest demand that has ore in the store wins — and then it
#  KEEPS winning until its batch is done. Switching recipes means draining
#  input and output completely first, so flapping between two ingots would
#  spend all its time flushing. BATCH sets how many units a commitment is.
#
#  Ore that is missing for a wanted ingot is published on factory.ore so
#  the Rover can go and mine it.
# =============================================================================

STORE = "inventory"
FLOORS = {}                # minimum stock per ingot, e.g. {"iron_ingot": 20}
BATCH = 10                 # units to commit to before re-choosing
IDLE_SLEEP = 2
POLL = 1

research = get_component("research")
inventory = get_component("inventory")
comms = get_component("comms")

if comms == None:
    print("[smelter] DEGRADED: no Signal Bus — keeping FLOORS only; nothing published")
else:
    print("[smelter] Signal Bus online — reading factory.needs, publishing factory.ore")
if not research.is_unlocked("research_auto_feeders"):
    print("[smelter] Auto Feeders is not researched — port transfers will not move anything")

# ingot -> Recipe
makes = {}
for recipe in self.list_recipes():
    makes[recipe.output_item] = recipe
print("[smelter]", len(makes), "recipes:", list(makes.keys()))


# ---------------------------------------------------------------- demand ----

def demand():
    # {ingot: units wanted}, combining the Fabricator's asks with FLOORS.
    wanted = {}
    if comms != None:
        needs = comms.latest("factory.needs")
        if needs != None:
            for item in needs.keys():
                wanted[item] = needs[item]
    for item in FLOORS.keys():
        short = FLOORS[item] - inventory.count(item)
        if short > wanted.get(item, 0):
            wanted[item] = short
    return wanted


def ore_for(recipe):
    # Smelter recipes take one ore; return its id and units per craft.
    for item in recipe.inputs.keys():
        pair = {}
        pair["item"] = item
        pair["per_craft"] = recipe.inputs[item]
        return pair
    return None


def choose(wanted):
    # Biggest demand we can actually start on. Also collects the ore
    # shortfalls for demands we cannot start, for the Rover.
    best = None
    best_units = 0
    ore_short = {}
    for ingot in wanted.keys():
        units = wanted[ingot]
        if units <= 0 or not makes.has(ingot):
            continue
        recipe = makes[ingot]
        ore = ore_for(recipe)
        if ore == None:
            continue
        crafts = ceil(units / recipe.output_count)
        ore_needed = crafts * ore["per_craft"]
        ore_have = inventory.count(ore["item"]) + self.get_input_count()
        if ore_have < ore["per_craft"]:
            ore_short[ore["item"]] = ore_short.get(ore["item"], 0) + ore_needed - ore_have
            continue
        if ore_have < ore_needed:
            ore_short[ore["item"]] = ore_short.get(ore["item"], 0) + ore_needed - ore_have
        if best == None or units > best_units:
            best = recipe
            best_units = units

    result = {}
    result["recipe"] = best
    result["units"] = best_units
    result["ore_short"] = ore_short
    return result


# ----------------------------------------------------------------- ports ----

def connect_ports():
    for port in [self.input, self.output]:
        if port.connected_id() != STORE:
            result = port.connect(STORE)
            if result.status != "ok":
                print("[smelter] connect:", result.message)
                return False
    return True


def drain():
    # Send finished ingots to the store. Returns units moved, so the batch
    # loop counts what actually left rather than what was sitting there.
    moved = 0
    for stack in self.output.stacks():
        result = self.output.send(stack.id, stack.count, stack.properties, "exact")
        if result.status != "ok":
            print("[smelter] drain", stack.id, ":", result.message)
        else:
            moved = moved + result.moved
    return moved


def flush_input_to_store():
    # Return leftover ore to the store so the recipe can change.
    ok = True
    for stack in self.input.stacks():
        result = self.input.eject(STORE, stack.id, stack.count)
        if result.status != "ok":
            print("[smelter] eject", stack.id, ":", result.message)
            ok = False
    return ok


def select(recipe):
    if self.get_recipe() == recipe.id:
        return True
    if self.is_running():
        return False
    drain()
    if self.get_output_count() > 0:
        return False
    if not flush_input_to_store():
        return False
    result = self.set_recipe(recipe.id)
    if result.status != "ok":
        print("[smelter] set_recipe", recipe.id, ":", result.message)
        return False
    print("[smelter] recipe ->", recipe.name)
    return True


def feed(recipe, units_left):
    # Keep the input topped up toward the batch without overfilling.
    ore = ore_for(recipe)
    crafts_left = ceil(units_left / recipe.output_count)
    want_in = crafts_left * ore["per_craft"]
    room = self.input.capacity() - self.input.count()
    pull = min(want_in - self.input.count(), room, inventory.count(ore["item"]))
    if pull <= 0:
        return
    result = self.input.take(ore["item"], pull)
    if result.status != "ok":
        print("[smelter] take", ore["item"], ":", result.message)


# ------------------------------------------------------------ publishing ----

def publish(ore_short, state, detail):
    if comms == None:
        return
    comms.broadcast("factory.ore", ore_short)
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["recipe"] = self.get_recipe()
    status["progress"] = round(self.get_progress(), 2)
    comms.broadcast("factory.status.smelter", status)


# ------------------------------------------------------------------ loop ----

last_note = ""

while True:
    if not connect_ports():
        sleep(IDLE_SLEEP)
        continue

    drain()

    pick = choose(demand())
    recipe = pick["recipe"]

    if recipe == None:
        publish(pick["ore_short"], "idle", "")
        note = str(pick["ore_short"])
        if note != last_note:
            if len(pick["ore_short"]) > 0:
                print("[smelter] nothing startable — short of ore:", pick["ore_short"])
            else:
                print("[smelter] no demand — idle")
            last_note = note
        sleep(IDLE_SLEEP)
        continue
    last_note = ""

    if not select(recipe):
        sleep(IDLE_SLEEP)
        continue

    # Commit to a batch: the smaller of BATCH and what is wanted.
    goal = min(BATCH, pick["units"])
    made = 0
    print("[smelter] batch:", goal, "x", recipe.output_item)
    publish(pick["ore_short"], "smelting", recipe.output_item)

    while made < goal:
        feed(recipe, goal - made)
        sleep(POLL)
        made = made + drain()
        if self.get_input_count() == 0 and not self.is_running():
            if inventory.count(ore_for(recipe)["item"]) == 0:
                print("[smelter] out of", ore_for(recipe)["item"], "after", made, "units")
                break

    made = made + drain()
    print("[smelter] batch done:", made, "x", recipe.output_item)
