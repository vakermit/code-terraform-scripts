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

# What each machine type competes for, how much satisfies it, and what the
# output buys. `needs_tier` is the installed tier at which the machine starts
# consuming that resource at all — below it the want is dormant and the
# machine is left unranked, which is why a tier-1 oxygen generator gets no
# water lease and simply runs on its own fail-safe.
#
# WHY TIER-DETECTED RATHER THAN A FLAG.  The water contention this planner was
# first written for — one Oxygen and one Pressure Mk III wanting 13 t/h from a
# 10 t/h well — needs Mk III, which gates at 625,000 Terraform Index. This
# base is at oxygen 41 and every generator is tier 1. Hard-coding those wants
# as active produced four machines traced as starved every pass over a
# resource none of them consumes. Reading the tier instead means the water
# allocation switches itself on the day a pack is installed, and says nothing
# until then.
#
# `rate` wants are measured in units per hour and come from the envelope's
# `tonnes`; `stock` wants are a count and come from its `stock`. They are not
# interchangeable and do not share a field.
WANTS = {
    # Contended today: ingots can become an upgrade pack or an Earth order,
    # and that is a real choice between a tier rise later and credits now.
    "fabricator": {"resource": "iron_ingot", "kind": "stock", "full": 20,
                   "serves": "tier", "needs_tier": 1},
    "supply_dock": {"resource": "iron_ingot", "kind": "stock", "full": 20,
                    "serves": "credits", "needs_tier": 1},

    # Defined and dormant. These are the late-game wants the architecture was
    # built for; they rank themselves the moment the hardware exists.
    "oxygen_generator": {"resource": "water", "kind": "rate", "full": 8.0,
                         "serves": "oxygen", "needs_tier": 3},
    "pressure_generator": {"resource": "water", "kind": "rate", "full": 5.0,
                           "serves": "pressure", "needs_tier": 3},
    "heater": {"resource": "steam", "kind": "rate", "full": 12.0,
               "serves": "temperature", "needs_tier": 3},
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

# Starting beliefs: what a unit spent on each outcome is worth. Placeholders
# of the right shape rather than measured truth, which is why every one
# carries confidence "doc" until an observation replaces it. Equal values
# make the first allocations rank purely on how short each outcome is, which
# is the honest behaviour while nothing better is known.
#
# `credits` is the one that can be measured properly and soon: an order's
# reward divided by what it requires gives credits per ingot directly. That
# is recorded as work still owed rather than guessed at here.
SEED = {
    "tier": 1.0,
    "credits": 1.0,
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


def installed_tier(machine_id):
    """The permanently installed Mk tier of a machine, or 1 when unreadable.

    `tier()` is a read, so it works through a remote handle. A machine that
    does not expose one is treated as tier 1, which keeps every fluid want
    dormant rather than switching one on by accident.
    """
    m = get_component(machine_id)
    if m == None:
        return 1
    try:
        return m.tier()
    except (AttributeError, TypeError):
        return 1


def consumers():
    """Every machine the planner allocates to this pass.

    A row carries its outpost so the allocation publishes per outpost rather
    than per machine: a save allows 512 channels in total, and one lease
    channel each would spend them all on a late base.

    A machine with a want whose `needs_tier` it has not reached is skipped
    entirely rather than ranked and starved. That is the difference between
    "you may have none of this" and "this does not apply to you", and tracing
    the first when the second is true is how four generators came to be
    reported starved of water that none of them consumes.
    """
    net = network()
    found = []
    if net == None:
        return found
    for outpost in net.outposts():
        for type_id in WANTS:
            want = WANTS[type_id]
            for ref in outpost.buildings(type_id):
                if installed_tier(ref.id) < want["needs_tier"]:
                    continue                  # want dormant at this tier
                found.append({"outpost": outpost.id, "id": ref.id,
                              "type": type_id, "wants": True,
                              "powered": ref.powered})
        for type_id in DISCRETIONARY:
            if WANTS.has(type_id):
                continue                      # already ranked by its want
            for ref in outpost.buildings(type_id):
                found.append({"outpost": outpost.id, "id": ref.id,
                              "type": type_id, "wants": False,
                              "powered": ref.powered})
    return found


def value_of(row, rates, gap):
    """Marginal value of fully supplying this machine.

    The product of what a unit buys for the outcome this machine serves and
    how short that outcome currently is. Equal seeded rates make this pure
    shortfall-chasing, which is the honest behaviour before anything has been
    measured.

    An outcome with no pillar behind it — `tier`, `credits` — has no readable
    shortfall, so it scores on its rate alone at a neutral share. That ranks
    ingot consumers against each other, which is the live contention, without
    pretending the Index can price them yet.

    A machine with no want at all is permission-only and scores zero: ranked
    below every wanter and above nothing.
    """
    if not row["wants"]:
        return 0.0
    want = WANTS[row["type"]]
    serves = want["serves"]
    rate = 0.0
    if rates.has(serves) and rates[serves].has("tp_per_tonne"):
        rate = rates[serves]["tp_per_tonne"]
    share = 0.5                               # neutral when nothing measures it
    if gap.has(serves):
        share = gap[serves]
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

        if row["wants"]:
            want = WANTS[row["type"]]
            fluid = want["resource"]
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

        # Rates and counts both land here keyed by resource id. A resource
        # absent from either map means safety could not measure it, which the
        # allocator treats as unmeasured rather than as zero.
        free = {}
        if env.has("tonnes"):
            for k in env["tonnes"]:
                free[k] = env["tonnes"][k]
        if env.has("stock"):
            for k in env["stock"]:
                free[k] = env["stock"][k]

        by_outpost, order = allocate(rows, free, rates, gap, hour)
        ttl = lease_ttl()
        for outpost_id in by_outpost:
            publish_allocation(outpost_id, by_outpost[outpost_id], ttl)
        publish_shed(order)

        hours(PASS_H)


main()
