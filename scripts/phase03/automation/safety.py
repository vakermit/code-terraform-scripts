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
# `publish` and `ENV` rather than `publish_envelope`: the envelope's shape is
# this loop's own output, so it is built here. That also removes a real
# hazard — the save keeps its own copy of each registered library, and a
# stale copy with an older signature would raise on every pass. Two
# positional arguments have been `publish`'s contract from the start.
from bus import ENV, publish, shed_order
from trace import note

LOOP = "safety"
# Rehearsal switch. False makes every breaker command a print instead: the
# loop measures, publishes its envelope and says exactly what it WOULD shed
# or restore, and touches nothing. A script that can switch a base off
# should be watchable for a while before it is believed, so this ships off
# and you turn it on once the trace reads the way you expect.
ENFORCE = False
PASS_S = 5.0                 # real seconds between passes
RESERVE_W = 150              # watts never offered to the planner
SETTLE_PASSES = 3            # passes to wait after a shed before shedding again
# Hours of battery autonomy to hold at the current deficit. The game restores
# a browned-out subnet once storage covers one hour of the remaining deficit,
# so two hours is one hour of margin over the floor the game itself uses.
MIN_AUTONOMY_H = 2.0

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
        if m.consumed > table.get(m.type_id, 0):
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
        total = total + max(table.get(m.type_id, 0), m.consumed)
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


def shed_to_fit(deficit_w, table, seen, ours, hour):
    """Switch machines off until the projected deficit is covered.

    Every machine switched off is written into `ours` so it can be switched
    back on later, and so that a machine the operator turned off by hand is
    never mistaken for one of ours.
    """
    grid = power()
    if grid == None:
        return 0
    ranked, how = shed_candidates(seen)
    freed = 0
    cut = 0
    skipped = 0
    for machine_id in ranked:
        if freed >= deficit_w:
            break
        rated = 0
        for m in seen:
            if m.id == machine_id:
                rated = max(m.consumed, table.get(m.type_id, 0))
        if rated <= 0:
            # Draws nothing measurable, so switching it off frees nothing and
            # buys only a dark machine the operator has to notice. An idle
            # machine reports 0 W and a type we have never seen busy is absent
            # from the table, so this is the common case early on, not an edge.
            skipped = skipped + 1
            continue
        if not ENFORCE:
            note(LOOP, hour, machine_id, "would shed, rehearsing",
                 {"w": rated, "need": deficit_w, "by": how})
            freed = freed + rated
            cut = cut + 1
            continue
        result = grid.set_powered(machine_id, False)
        if result.status != "ok":
            note(LOOP, hour, machine_id, "shed refused", {"why": result.status})
            continue
        ours[machine_id] = hour
        freed = freed + rated
        cut = cut + 1
        note(LOOP, hour, machine_id, "shed for power",
             {"w": rated, "need": deficit_w, "by": how})
    if cut == 0 and deficit_w > 0:
        note(LOOP, hour, "grid", "deficit with nothing sheddable",
             {"w": round(deficit_w, 1), "zero_draw": skipped, "by": how})
    elif freed < deficit_w:
        note(LOOP, hour, "grid", "shed all it could, still short",
             {"freed": round(freed, 1), "need": round(deficit_w, 1)})
    return freed


def restore(seen, headroom_w, table, ours, hour):
    """Switch back on what WE switched off, while it fits in the headroom.

    `ours` is the ledger of machines this loop shed, which is the whole point:
    the game does not rejoin a manually powered machine when the grid
    recovers, so somebody has to, but "every machine that is currently off"
    is the wrong set. It includes the ones the operator switched off
    deliberately, and powering those back on would make this loop override
    the person it works for — the one thing it must never do.
    """
    grid = power()
    if grid == None:
        return
    for m in seen:
        if m.powered or m.type_id in PROTECTED:
            continue
        if not ours.has(m.id):
            continue                      # not ours to restore; see the banner
        rated = table.get(m.type_id, 0)
        if rated > headroom_w:
            continue
        if not ENFORCE:
            note(LOOP, hour, m.id, "would restore, rehearsing", {"w": rated})
            headroom_w = headroom_w - rated
            continue
        result = grid.set_powered(m.id, True)
        if result.status == "ok":
            headroom_w = headroom_w - rated
            ours.pop(m.id, None)
            note(LOOP, hour, m.id, "restored, headroom returned", {"w": rated})


def water_supply():
    """Tonnes per hour of water the base can draw, or {} when unmeasurable.

    The first version read each pump's `water_out.flow_rate()` and always got
    zero. That was not a bug in the base, it is the documented behaviour: a
    pass-through output such as a pump's reads 0, because nothing buffers
    there. Measuring supply at that port can never work.

    So ask the well instead. A pump sited on a well exposes it through
    `well()`, and the site carries its own rated `flow_rate` — 10, 20 or 30
    t/h by yield tier for water. That is a ceiling rather than a live reading,
    which is the right kind of error here: the planner allocates against it
    and the machines degrade gracefully if the real flow falls short.

    An empty result means "could not measure", NOT "there is none". The
    planner distinguishes the two, because starving every fluid machine on a
    failed measurement is the worse mistake.
    """
    found = {}
    total = 0.0
    for m in members():
        if m.type_id != "water_pump":
            continue
        pump = get_component(m.id)
        if pump == None:
            continue
        well = pump.well()
        if well == None:
            continue                      # pump built but not sited on a well
        total = total + well.flow_rate
    if total > 0:
        found["water"] = total
    return found


def main():
    report(LOOP)
    if not ENFORCE:
        print("safety: REHEARSING, no breaker will be touched")
    book = get_component("notebook")
    table = {}
    ours = {}
    if book != None:
        table = book.get("safety.watts", {})
        # The shed ledger has to survive a restart, or a reload would leave
        # every machine this loop switched off dark for good, with no record
        # saying they were ours to switch back on.
        ours = book.get("safety.shed", {})
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

        # Generation alone is the wrong measure. A brownout happens when
        # generation PLUS storage cannot fund the load for a tick, so a base
        # running on batteries overnight with solar at zero is not in trouble
        # — it has hours of autonomy. Measuring spare as generated minus load
        # declares every night an emergency and sheds the base at dusk.
        deficit = load - summary.generated
        if deficit <= 0:
            spare = 0 - deficit - RESERVE_W
            autonomy = -1.0                   # not drawing down; no horizon
        else:
            spare = 0.0
            autonomy = summary.stored / deficit    # Wh over W gives hours

        # A fluid absent from `tonnes` means unmeasured, not zero. The
        # planner relies on that distinction, so never fill in a 0 here.
        publish(ENV, {
            "watts_free": max(0, spare),
            "reserve_w": RESERVE_W,
            "tonnes": water_supply(),
            "autonomy_h": autonomy,
            "stored_wh": summary.stored,
            "hour": hour,
        })

        before = ours.length
        if cooldown > 0:
            cooldown = cooldown - 1
        elif deficit > 0 and autonomy < MIN_AUTONOMY_H:
            # Shed only enough to put the horizon back above the floor, not
            # enough to erase the deficit: running on batteries is normal.
            keep = summary.stored / MIN_AUTONOMY_H
            shed_to_fit(deficit - keep, table, seen, ours, hour)
            cooldown = SETTLE_PASSES
        elif spare > RESERVE_W:
            restore(seen, spare - RESERVE_W, table, ours, hour)
        if ours.length != before and book != None:
            book.set("safety.shed", ours)

        sleep(PASS_S)


main()
