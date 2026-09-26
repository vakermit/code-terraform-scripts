# =============================================================================
#  demand  —  what the base actually wants, as ore
# =============================================================================
#
#  Earth's orders name finished goods. The chain that turns those into ore is
#  dock -> fabricator -> smelter -> factory.ore, and every hop is a broadcast
#  that only happens while that machine is running. Pause the Smelter and the
#  rover stops hearing about iron, even though the order still needs it.
#
#  So this reads the precise signal when it exists and rebuilds it from the
#  upstream asks when it does not, resolving ingot -> ore through the Smelter's
#  own recipes rather than a hardcoded table that would rot as blueprints
#  unlock.
#
#  Everything returns {item_id: units_wanted}. Units matter: callers weight by
#  them, so "needs 40 iron" outranks "needs 2 silicon".
# =============================================================================

from machines import find_machine
from signals import latest


def ore_demand(fallback_items=None):
    """What to mine, as {ore_id: units}. Empty means nothing is asked for.

    Prefers the Smelter's own `factory.ore` broadcast. When that is silent —
    Smelter paused, no recipe set, or simply not built yet — falls back to
    translating the ingots the Fabricator asked for, then to `fallback_items`.
    """
    direct = latest("factory.ore")
    if direct != None and len(direct) > 0:
        return direct

    wanted = {}
    needs = latest("factory.needs")
    if needs != None and len(needs) > 0:
        for ore, units in ores_for_items(needs).items():
            wanted[ore] = units
    if len(wanted) > 0:
        return wanted

    if fallback_items != None:
        for item in fallback_items:
            wanted[item] = 1
    return wanted


def ores_for_items(items):
    """Translate {ingot_id: units} into {ore_id: units} via Smelter recipes.

    Returns {} when no Smelter is reachable, because guessing the mapping is
    worse than admitting we do not know it. Unknown ingots are skipped rather
    than passed through: an ore id and an ingot id are not interchangeable.
    """
    smelter = find_machine("smelter")
    if smelter == None:
        return {}
    out = {}
    for recipe in smelter.list_recipes():
        made = recipe.output_item
        if not items.has(made):
            continue
        batches = items[made] / max(1, recipe.output_count)
        for ore in recipe.inputs.keys():
            units = recipe.inputs[ore] * batches
            out[ore] = out.get(ore, 0) + units
    return out


def weight_of(wanted, item_id, cap=8):
    """How much to favour `item_id`, given `wanted` from ore_demand().

    1.0 means "not asked for". Anything wanted scores above 1 and grows with
    the units outstanding, so a big shortfall outranks a token one, but the
    result is capped: demand should tilt the choice, not let a distant rich
    site lose to a depleted near one forever.
    """
    if wanted == None or len(wanted) == 0:
        return 1.0
    if not wanted.has(item_id):
        return 0.35                      # actively deprioritised, never excluded
    units = wanted[item_id]
    bonus = 1.0 + units / 10.0
    if bonus > cap:
        return cap
    return bonus


def has_demand(wanted):
    """True when anything is actually being asked for."""
    return wanted != None and len(wanted) > 0
