# =============================================================================
#  FABRICATOR  —  paste into the script slot of  fabricator_1
#  Resolve a bill of materials from stock targets, craft it in tier order.
# =============================================================================
#
#  The Fabricator crafts automatically whenever its stockpile holds a full
#  recipe and its output has room. This script only moves material — and
#  decides what to make.
#
#  CHANNEL CONTRACT — shared by the factory scripts
#  ---------------------------------------------------------------------------
#    factory.targets   broadcast   operator -> Fabricator
#                      {item_id: wanted_in_stock}
#                      Set from Ship Computer > Signal Bus (Broadcast, JSON),
#                      e.g. {"gas_pipe_segment": 20}. TARGETS below is the
#                      fallback when nothing has been broadcast.
#
#    factory.needs     broadcast   Fabricator -> Smelter   (this script writes)
#                      {ingot_id: shortfall}  raw materials the plan is short
#                      of that a Smelter recipe produces
#
#    factory.ore       broadcast   Smelter -> Rover
#    factory.status.fabricator / .smelter   broadcast   telemetry
#  ---------------------------------------------------------------------------
#
#  THE PLAN. For every target the shortfall is wanted minus what the store
#  holds. Each shortfall is resolved recursively: a missing ingredient that
#  is itself a Fabricator recipe becomes a sub-step; one that a Smelter can
#  produce is published on factory.needs; anything else is reported as
#  unobtainable. Steps come out in dependency order, and the first one
#  whose ingredients are actually in stock is the one that runs.
#
#  STOCKPILE DISCIPLINE. The input stockpile is shared across every
#  material with one combined cap, and set_recipe() does NOT clear it. So
#  the script pulls exactly what one craft is missing — never a top-up —
#  and ejects materials the current recipe cannot use when the cap gets in
#  the way. A recipe cannot change while a craft runs or while output or
#  byproduct sit undrained, so those are drained on every pass.
#
#  FLUIDS. Recipes with fluid_inputs need a connected, fed FluidPort. They
#  are skipped with a message until FLUIDS_OK is set and the ports are
#  connected — a stocked fluid recipe with an empty port waits forever.
# =============================================================================

STORE = "inventory"
TARGETS = {}               # fallback stock targets, e.g. {"iron_plate": 10}
FLUIDS_OK = False          # allow steam / water / oil recipes
MAX_DEPTH = 6              # bill-of-materials recursion limit
IDLE_SLEEP = 2
CRAFT_POLL = 1

inventory = get_component("inventory")
research = get_component("research")
comms = get_component("comms")

# Leave as "" to auto-detect, or paste the exact id from the machine card.
SMELTER_ID = ""


def find_machine(kind, configured):
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


smelter = find_machine("smelter", SMELTER_ID)

if comms == None:
    print("[fab] DEGRADED: no Signal Bus — using TARGETS from the script; nothing published")
else:
    print("[fab] Signal Bus online — reading factory.targets, publishing factory.needs")
if smelter == None:
    print("[fab] no Smelter found — ingot shortfalls will be reported as unobtainable")
if not research.is_unlocked("research_auto_feeders"):
    print("[fab] Auto Feeders is not researched — port transfers will not move anything")


# --------------------------------------------------------------- recipes ----

# item_id -> Recipe, for everything this Fabricator can make
makes = {}
for recipe in self.list_recipes():
    makes[recipe.output_item] = recipe

# item_id -> True, for everything the Smelter can make
smeltable = {}
if smelter != None:
    for recipe in smelter.list_recipes():
        smeltable[recipe.output_item] = True

print("[fab]", len(makes), "recipes;", len(smeltable), "smeltable inputs")

warned_fluid = []


def usable(recipe):
    if len(recipe.fluid_inputs) > 0 and not FLUIDS_OK:
        if recipe.id not in warned_fluid:
            print("[fab] skipping", recipe.id, "- needs fluids", recipe.fluid_inputs,
                  "(set FLUIDS_OK once its ports are connected)")
            warned_fluid.append(recipe.id)
        return False
    return True


# ------------------------------------------------------------------ plan ----

def targets():
    if comms != None:
        published = comms.latest("factory.targets")
        if published != None:
            return published
    return TARGETS


def resolve(item, qty, depth, steps, needs, missing):
    # Turn "qty more of item" into ordered steps, recursively.
    if depth > MAX_DEPTH:
        missing[item] = missing.get(item, 0) + qty
        return

    if not makes.has(item):
        if smeltable.has(item):
            needs[item] = needs.get(item, 0) + qty
        else:
            missing[item] = missing.get(item, 0) + qty
        return

    recipe = makes[item]
    if not usable(recipe):
        missing[item] = missing.get(item, 0) + qty
        return

    crafts = ceil(qty / recipe.output_count)
    for ingredient in recipe.inputs.keys():
        need = crafts * recipe.inputs[ingredient]
        have = inventory.count(ingredient) + self.get_stockpile().get(ingredient, 0)
        short = need - have
        if short > 0:
            resolve(ingredient, short, depth + 1, steps, needs, missing)

    step = {}
    step["recipe"] = recipe
    step["crafts"] = crafts
    steps.append(step)


def plan():
    # Steps in dependency order plus the raw-material shortfalls.
    steps = []
    needs = {}
    missing = {}
    wanted = targets()
    for item in wanted.keys():
        short = wanted[item] - inventory.count(item)
        if short > 0:
            resolve(item, short, 0, steps, needs, missing)

    result = {}
    result["steps"] = steps
    result["needs"] = needs
    result["missing"] = missing
    return result


def craftable_now(recipe):
    # Every ingredient for ONE craft is in the store or already staged.
    for ingredient in recipe.inputs.keys():
        need = recipe.inputs[ingredient]
        have = inventory.count(ingredient) + self.get_stockpile().get(ingredient, 0)
        if have < need:
            return False
    return True


# ----------------------------------------------------------------- ports ----

def connect_ports():
    for port in [self.input, self.output, self.byproduct]:
        if port.connected_id() != STORE:
            result = port.connect(STORE)
            if result.status != "ok":
                print("[fab] connect:", result.message)
                return False
    return True


def drain():
    # Output and byproduct both block recipe changes and, when full, block
    # the craft itself. Byproduct is the one people forget.
    ok = True
    for port in [self.output, self.byproduct]:
        for stack in port.stacks():
            result = port.send(stack.id, stack.count, stack.properties, "exact")
            if result.status != "ok":
                print("[fab] drain", stack.id, ":", result.message)
                ok = False
    return ok


def make_room(recipe, units_needed):
    # Eject staged materials the current recipe does not use, until the
    # stockpile can accept what this craft needs.
    free = self.get_stockpile_capacity() - self.get_stockpile_used()
    if free >= units_needed:
        return True
    pile = self.get_stockpile()
    for item in pile.keys():
        if recipe.inputs.has(item):
            continue
        result = self.input.eject(STORE, item, pile[item])
        if result.status == "ok":
            print("[fab] returned", pile[item], "x", item, "to the store (not in recipe)")
        free = self.get_stockpile_capacity() - self.get_stockpile_used()
        if free >= units_needed:
            return True
    return free >= units_needed


def stage(recipe):
    # Pull exactly what one craft is missing from the stockpile.
    pile = self.get_stockpile()
    total_missing = 0
    for ingredient in recipe.inputs.keys():
        short = recipe.inputs[ingredient] - pile.get(ingredient, 0)
        if short > 0:
            total_missing = total_missing + short
    if total_missing == 0:
        return True
    if not make_room(recipe, total_missing):
        print("[fab] stockpile full and nothing to eject — cannot stage", recipe.id)
        return False

    for ingredient in recipe.inputs.keys():
        short = recipe.inputs[ingredient] - pile.get(ingredient, 0)
        if short <= 0:
            continue
        result = self.input.take(ingredient, short)
        if result.status != "ok" or result.moved < short:
            print("[fab] take", short, "x", ingredient, ":", result.message)
            return False
    return True


def select(recipe):
    if self.get_recipe() == recipe.id:
        return True
    if self.is_running():
        return False
    if not drain():
        return False
    result = self.set_recipe(recipe.id)
    if result.status != "ok":
        print("[fab] set_recipe", recipe.id, ":", result.message)
        return False
    print("[fab] recipe ->", recipe.name)
    return True


# ------------------------------------------------------------ publishing ----

def publish(needs, state, detail):
    if comms == None:
        return
    comms.broadcast("factory.needs", needs)
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["recipe"] = self.get_recipe()
    status["stockpile"] = self.get_stockpile_used()
    comms.broadcast("factory.status.fabricator", status)


# ------------------------------------------------------------------ loop ----

last_report = ""

while True:
    if not connect_ports():
        sleep(IDLE_SLEEP)
        continue

    drain()

    if self.is_running():
        sleep(CRAFT_POLL)
        continue

    p = plan()
    steps = p["steps"]
    needs = p["needs"]
    missing = p["missing"]

    if len(steps) == 0:
        publish(needs, "idle", "targets met")
        if last_report != "met":
            print("[fab] every target is in stock — idle")
            last_report = "met"
        sleep(IDLE_SLEEP)
        continue

    # First step whose ingredients are actually here, in dependency order.
    chosen = None
    for step in steps:
        if craftable_now(step["recipe"]):
            chosen = step["recipe"]
            break

    if chosen == None:
        publish(needs, "waiting", "materials")
        report = str(needs) + str(missing)
        if last_report != report:
            if len(needs) > 0:
                print("[fab] waiting on the smelter for", needs)
            if len(missing) > 0:
                print("[fab] cannot obtain", missing)
            last_report = report
        sleep(IDLE_SLEEP)
        continue

    last_report = ""
    if not select(chosen):
        sleep(IDLE_SLEEP)
        continue
    if not stage(chosen):
        sleep(IDLE_SLEEP)
        continue

    # Crafting starts on its own once the stockpile is complete.
    publish(needs, "crafting", chosen.id)
    waited = 0
    while not self.is_running() and waited < 5:
        sleep(CRAFT_POLL)
        waited = waited + 1
    while self.is_running():
        sleep(CRAFT_POLL)

    drain()
    print("[fab] crafted", chosen.output_count, "x", chosen.output_item)
