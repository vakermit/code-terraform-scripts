# =============================================================================
#  SAFETY  —  automation, fast loop
#  What is available to spend, and the breaker when something overruns.
# =============================================================================
#
#  The first layer of the pipeline. It measures capacity and publishes an
#  envelope; it never decides who deserves what. That division is the whole
#  reason the loops cannot contradict each other: a safety loop empowered to
#  overrule an allocation would have to work out which machine matters least,
#  which is the planner's job done badly under the worst conditions.
#
#  WHY THIS IS AN AUTOMATION.  It has no power supply of its own and a
#  brownout never pauses it. A Control Room card does pause, which disqualifies
#  a card from being the thing that manages brownouts.
#
#  THE CLIFF.  A brownout is all-or-nothing: if generation plus storage cannot
#  fund the full live load for one tick, every consumer on that subnet stops.
#  There is no consumer priority and no partial shedding, and a machine
#  switched off by hand does not rejoin automatically. So the only winning move
#  is to never arrive at the cliff, which means modelling load and shedding
#  while there is still headroom to shed within.
#
#  WHY A HIGH-WATER MARK.  PowerGridMember.consumed is live draw, and the docs
#  are explicit that a powered-off or idle machine reports 0 W. So the live
#  reading cannot tell us what a machine WOULD draw once it starts, which is
#  exactly the figure headroom needs. The table therefore remembers the largest
#  draw ever seen for each machine type and projects with that.
#
#  WHO IT OBEYS.  When it must shed, it walks the planner's published ranking
#  and does not re-rank. Slow loop ranks, fast loop obeys. With no fresh
#  ranking it falls back to CONSERVATIVE below, which puts life support last
#  because that is the one ordering that is right regardless of marginal value.
# =============================================================================

from capability import clock, missing, now_hour, power, report
from bus import publish_envelope, shed_order
from trace import note

LOOP = "safety"
PASS_S = 5.0                 # real seconds between passes
RESERVE_W = 150              # watts never offered to the planner
SETTLE_PASSES = 3            # passes to wait after a shed before shedding again

# Type ids that are life support or rescue. Shed last, whatever the ranking
# says, and never shed on the conservative fallback at all.
PROTECTED = [
    "oxygen_generator",
    "pressure_generator",
    "heater",
    "oxygen_sensor",
    "pressure_sensor",
    "vehicle_charging_station",
]

# Fallback ordering by type when the planner has published no ranking. Cut
# first at the front. Deliberately crude: it exists so a dead planner cannot
# take the base down, not to be good at allocation.
CONSERVATIVE = [
    "smelter", "fabricator", "fuel_assembler", "refiner",
    "bio_collector", "bio_lab", "bio_exchange",
    "plant_terraformer", "crop_automator",
    "mining_drill", "water_pump", "oil_pump",
]


def members():
    """Every machine on every grid, as PowerGridMember snapshots."""
    grid = power()
    if grid == None:
        return []
    found = []
    for g in grid.grids():
        for m in g.members:
            found.append(m)
    return found


def learn_draw(table, seen):
    """Raise the high-water mark for each type drawing power right now.

    Returns True when anything changed, so the Archive is only written when
    there is something new to remember.
    """
    changed = False
    for m in seen:
        if m.consumed <= 0:
            continue                      # off or idle: tells us nothing
        known = 0
        if table.has(m.type_id):
            known = table[m.type_id]
        if m.consumed > known:
            table[m.type_id] = m.consumed
            changed = True
    return changed


def projected_load(table, seen):
    """What the base would draw with every installed consumer active.

    A machine that is powered on counts at its live draw when that is higher
    than the remembered figure, because the remembered figure may simply never
    have seen this machine busy yet.
    """
    total = 0
    for m in seen:
        if "consumer" not in m.roles:
            continue
        rated = 0
        if table.has(m.type_id):
            rated = table[m.type_id]
        if m.consumed > rated:
            rated = m.consumed
        total = total + rated
    return total


def shed_candidates(seen):
    """Machine ids safety may switch off, ranked worst-value first.

    The planner's ranking wins, filtered to machines that actually exist and
    actually have a breaker. Anything it ranked that is protected is dropped
    rather than obeyed: a ranking that says to cut life support first is a
    planner bug, and this loop is the wrong place to find out.
    """
    grid = power()
    by_id = {}
    for m in seen:
        by_id[m.id] = m

    ranked = []
    for machine_id in shed_order():
        if not by_id.has(machine_id):
            continue
        if by_id[machine_id].type_id in PROTECTED:
            continue
        if grid != None and not grid.can_power_off(machine_id):
            continue
        ranked.append(machine_id)

    if len(ranked) > 0:
        return ranked, "planner ranking"

    # No fresh ranking. Fall back to the crude type order, protected types
    # excluded entirely rather than merely last.
    for type_id in CONSERVATIVE:
        for m in seen:
            if m.type_id != type_id or m.type_id in PROTECTED:
                continue
            if grid != None and not grid.can_power_off(m.id):
                continue
            if m.powered:
                ranked.append(m.id)
    return ranked, "conservative fallback"


def shed_to_fit(deficit_w, table, seen, hour):
    """Switch machines off until the projected deficit is covered."""
    grid = power()
    if grid == None:
        return 0
    ranked, how = shed_candidates(seen)
    freed = 0
    cut = 0
    for machine_id in ranked:
        if freed >= deficit_w:
            break
        rated = 0
        for m in seen:
            if m.id == machine_id:
                rated = m.consumed
                if table.has(m.type_id) and table[m.type_id] > rated:
                    rated = table[m.type_id]
        result = grid.set_powered(machine_id, False)
        if result.status != "ok":
            note(LOOP, hour, machine_id, "shed refused", {"why": result.status})
            continue
        freed = freed + rated
        cut = cut + 1
        note(LOOP, hour, machine_id, "shed for power",
             {"w": rated, "need": deficit_w, "by": how})
    if cut == 0 and deficit_w > 0:
        note(LOOP, hour, "grid", "deficit with nothing sheddable", {"w": deficit_w})
    return freed


def restore(seen, headroom_w, table, hour):
    """Switch back on what we switched off, newest-shed last, while it fits.

    A machine safety turned off stays off until safety turns it back on — the
    game does not rejoin a manually powered machine when the grid recovers.
    Leaving that to the operator would be a slow leak of dark machines.
    """
    grid = power()
    if grid == None:
        return
    for m in seen:
        if m.powered or m.type_id in PROTECTED:
            continue
        rated = 0
        if table.has(m.type_id):
            rated = table[m.type_id]
        if rated > headroom_w:
            continue
        result = grid.set_powered(m.id, True)
        if result.status == "ok":
            headroom_w = headroom_w - rated
            note(LOOP, hour, m.id, "restored, headroom returned", {"w": rated})


def water_supply():
    """Tonnes per hour of water the base can currently draw.

    Measured from the pumps that report a live flow. A pump whose output is a
    pass-through reads zero, so this is a floor rather than a true total — the
    planner treats it as such, and the real figure is one of the ISA's open
    questions rather than something guessed at here.
    """
    found = {}
    grid = power()
    if grid == None:
        return found
    total = 0
    for m in members():
        if m.type_id != "water_pump":
            continue
        pump = get_component(m.id)
        if pump == None:
            continue
        port = pump.water_out
        if port == None:
            continue
        total = total + port.flow_rate()
    if total > 0:
        found["water"] = total
    return found


def main():
    report(LOOP)
    book = get_component("notebook")
    table = {}
    if book != None:
        table = book.get("safety.watts", {})
    cooldown = 0

    while True:
        grid = power()
        if grid == None:
            # Without power_control there is no envelope to publish and no
            # breaker to pull. Say so once per pass and stay alive, because
            # the component can appear when its research lands.
            print("safety: no power_control; publishing nothing")
            sleep(PASS_S)
            continue

        hour = now_hour()
        seen = members()
        if learn_draw(table, seen) and book != None:
            book.set("safety.watts", table)

        summary = grid.total()
        load = projected_load(table, seen)
        spare = summary.generated - load - RESERVE_W

        publish_envelope(max(0, spare), RESERVE_W, water_supply(), hour)

        if cooldown > 0:
            cooldown = cooldown - 1
        elif spare < 0:
            shed_to_fit(0 - spare, table, seen, hour)
            cooldown = SETTLE_PASSES
        elif spare > RESERVE_W:
            restore(seen, spare - RESERVE_W, table, hour)

        sleep(PASS_S)


main()
