# =============================================================================
#  PLANNER  —  automation, slow loop
#  Who gets the scarce thing, and what to cut first when there is less of it.
# =============================================================================
#
#  The second layer. It reads safety's envelope and allocates inside it; it
#  never measures capacity itself and never pulls a breaker. Writes flow one
#  way, so nothing here can contradict the loop above it.
#
#  WHY THIS EXISTS.  A Mk III generator runs 200x supplied and 5x starved, and
#  one Oxygen plus one Pressure Mk III want 13 t/h of water from a well that
#  gives 10. Which machine gets the water is therefore worth a fortyfold swing
#  in terraforming rate, and nothing in the game decides it for you.
#
#  SLOW ON PURPOSE.  The things it reasons about move in hours: a terraformer
#  batch is 3, a reactor's condition drifts every 12, breeding momentum takes
#  24. Re-deciding every tick would be churn, and the one decision that must
#  be fast — shedding — is precomputed as a ranking for safety to walk.
#
#  SEEDED, THEN MEASURED.  The exchange rate between a tonne of water and a
#  Terraform Point is not readable: pillars() gives value and target, but TP
#  does not map one-to-one onto raw units. So the table starts from the
#  documented figures, is marked "doc", and is corrected to "measured" once a
#  delta has been observed against real spend. A seeded belief that gets
#  corrected beats an unseeded one that never forms.
#
#  WHAT IT CANNOT DO.  It cannot set a throttle, a recipe or a target: those
#  are the machine's own. It publishes an allowance and the machine applies it.
# =============================================================================

from capability import clock, hours, missing, network, now_hour, report, terraforming
from bus import envelope, publish_allocation, publish_shed
from trace import note

LOOP = "plan"
PASS_H = 0.25                # world hours between allocations
RATES_KEY = "plan.rates"
# Passes this loop may miss before its allocation should be disbelieved. The
# horizon is published with every allocation, computed from this and the live
# clock, because a world hour is roughly 25 simulation seconds and a reader
# that guesses the conversion is wrong by a factor of a hundred.
MISSABLE_PASSES = 4
MIN_TTL_S = 10.0

# What each consumer type wants, how much of it satisfies the machine, and
# which pillar the output serves. Figures are the documented Mk III intakes;
# anything absent here is unranked and gets no allowance.
WANTS = {
    "oxygen_generator": {"fluid": "water", "full": 8.0, "pillar": "oxygen"},
    "pressure_generator": {"fluid": "water", "full": 5.0, "pillar": "pressure"},
    "heater": {"fluid": "steam", "full": 12.0, "pillar": "temperature"},
}

# Machines that want no fluid but are still discretionary: they need a lease
# to run at all, because their fail-safe is to idle. Without this list the
# planner would name only fluid consumers and every factory machine on the
# base would sit idle forever waiting for an allowance that never came.
DISCRETIONARY = [
    "smelter", "fabricator", "fuel_assembler", "refiner",
    "bio_collector", "bio_lab", "bio_exchange",
    "plant_terraformer", "crop_automator", "seed_maker",
]

# Starting beliefs, in Terraform Points per tonne. These are placeholders of
# the right shape rather than measured truth, which is why every one carries
# confidence "doc" until an observation replaces it. Equal values mean the
# first allocations rank purely on how far a pillar is from its next target,
# which is the right behaviour while nothing better is known.
SEED = {
    "oxygen": 1.0,
    "pressure": 1.0,
    "temperature": 1.0,
}


def load_rates(book):
    """The rate table, seeded on first run. Every entry carries a confidence."""
    if book == None:
        table = {}
        for pillar in SEED:
            table[pillar] = {"tp_per_tonne": SEED[pillar], "confidence": "doc"}
        return table
    table = book.get(RATES_KEY, {})
    changed = False
    for pillar in SEED:
        if not table.has(pillar):
            table[pillar] = {"tp_per_tonne": SEED[pillar], "confidence": "doc"}
            changed = True
    if changed:
        book.set(RATES_KEY, table)
    return table


def gaps():
    """How far each unlocked pillar is from its next target, as 0..1.

    A complete pillar answers 0, because a tonne spent there buys nothing —
    though its machines may still be feeding the carbon cycle, which is why
    the planner stops ALLOCATING to it rather than shedding it.
    """
    index = terraforming()
    found = {}
    if index == None:
        return found
    for pillar in index.pillars():
        if pillar.complete:
            found[pillar.id] = 0.0
            continue
        target = pillar.next_target
        if target == None or target <= 0:
            found[pillar.id] = 1.0
            continue
        remaining = target - pillar.value
        if remaining < 0:
            remaining = 0
        found[pillar.id] = remaining / target
    return found


def consumers():
    """Every machine the planner allocates to, fluid wanters first.

    A row carries its outpost so the allocation can be published per outpost
    rather than per machine: the save allows 512 channels in total, and one
    lease channel each would spend them all on a late base.
    """
    net = network()
    found = []
    if net == None:
        return found
    for outpost in net.outposts():
        for type_id in WANTS:
            for ref in outpost.buildings(type_id):
                found.append({"outpost": outpost.id, "id": ref.id,
                              "type": type_id, "fluid": True,
                              "powered": ref.powered})
        for type_id in DISCRETIONARY:
            for ref in outpost.buildings(type_id):
                found.append({"outpost": outpost.id, "id": ref.id,
                              "type": type_id, "fluid": False,
                              "powered": ref.powered})
    return found


def value_of(row, rates, gap):
    """Marginal value of fully supplying this machine, in TP per hour.

    For a fluid wanter, the product of how short its pillar is and what a
    tonne buys there. Equal rates make this pure gap-chasing, which is the
    honest behaviour before anything has been measured.

    A discretionary machine serves the Index only indirectly — a smelter's
    ingots become packs become generators — so it cannot be priced against a
    pillar at all yet. It is ranked below every fluid wanter and above
    nothing, which is a deliberate placeholder rather than a measurement.
    """
    if not row["fluid"]:
        return 0.0
    want = WANTS[row["type"]]
    pillar = want["pillar"]
    rate = 0.0
    if rates.has(pillar) and rates[pillar].has("tp_per_tonne"):
        rate = rates[pillar]["tp_per_tonne"]
    share = 0.0
    if gap.has(pillar):
        share = gap[pillar]
    return rate * share * want["full"]


def allocate(rows, free, rates, gap, hour):
    """Hand out each fluid best-value first. Returns per-outpost allocations.

    Greedy rather than optimal: four scarce goods against a learned value
    model is a small linear program and there is no solver here, so each
    fluid is spent down its own ranking. The ranking is the part that matters,
    and it is the same list safety walks when it has to shed.
    """
    ranked = sorted(rows, key=lambda r: 0 - value_of(r, rates, gap))
    remaining = {}
    for fluid in free:
        remaining[fluid] = free[fluid]

    by_outpost = {}
    order = []
    rank = 0
    for row in ranked:
        rank = rank + 1
        grant = {"rank": rank, "hour": hour}

        if row["fluid"]:
            want = WANTS[row["type"]]
            fluid = want["fluid"]
            if not remaining.has(fluid):
                # Safety could not measure this supply at all, which is a
                # different thing from there being none of it. Granting the
                # full want is the safer error: an unmeasured fluid that is
                # actually plentiful would otherwise starve every machine
                # that needs it, and a machine below the tier that consumes
                # it ignores the grant anyway.
                grant[fluid] = want["full"]
                grant["unmeasured"] = True
                note(LOOP, hour, row["id"], "supply unmeasured, granted in full",
                     {"fluid": fluid, "want": want["full"], "rank": rank})
            else:
                give = min(want["full"], remaining[fluid])
                remaining[fluid] = remaining[fluid] - give
                grant[fluid] = give
                if give < want["full"]:
                    note(LOOP, hour, row["id"], "starved by envelope",
                         {"got": round(give, 2), "want": want["full"], "rank": rank})
        else:
            # A discretionary machine needs only permission, not a quantity:
            # it has no fluid to meter and its draw is already inside the
            # envelope safety measured. The lease says run; safety's breaker
            # says stop, and the breaker outranks this.
            grant["run"] = True

        if not by_outpost.has(row["outpost"]):
            by_outpost[row["outpost"]] = {}
        by_outpost[row["outpost"]][row["id"]] = grant

        # The shed order is this ranking reversed: the machine that earns
        # least is the one to cut first.
        order.append(row["id"])
    order.reverse()
    return by_outpost, order


def lease_ttl():
    """How long an allocation should be believed, in simulation seconds.

    Derived from this loop's own cadence against the live clock, so it tracks
    whatever speed the game is running at rather than assuming one. Floored,
    because a horizon shorter than a pass would expire every lease before the
    next one arrived and leave every machine permanently on its fail-safe.
    """
    c = clock()
    if c == None:
        return 60.0
    per_pass = PASS_H * c.real_seconds_per_hour()
    return max(MIN_TTL_S, per_pass * MISSABLE_PASSES)


def main():
    report(LOOP)
    book = get_component("notebook")

    while True:
        env = envelope()
        if env == None:
            # No fresh envelope means safety is silent or stale. Publishing an
            # allocation anyway would be the planner inventing capacity it
            # cannot see, so it publishes nothing and every machine falls to
            # its own fail-safe. That is the pipeline working, not failing.
            print("plan: no fresh envelope; holding")
            hours(PASS_H)
            continue

        hour = now_hour()
        rates = load_rates(book)
        gap = gaps()
        rows = consumers()
        if len(rows) == 0:
            hours(PASS_H)
            continue

        free = {}
        if env.has("tonnes"):
            free = env["tonnes"]

        by_outpost, order = allocate(rows, free, rates, gap, hour)
        ttl = lease_ttl()
        for outpost_id in by_outpost:
            publish_allocation(outpost_id, by_outpost[outpost_id], ttl)
        publish_shed(order)

        hours(PASS_H)


main()
