# =============================================================================
#  BIO COLLECTOR  —  paste into the script slot of  bio_collector_1
#  Step 1 of the biology loop: field -> cargo.
# =============================================================================
#
#  This is script 1 of 3. The set shares no code and no globals — the three
#  machines coordinate purely through game state:
#
#      collector  ->  cargo slot     ->  lab
#      lab        ->  inventory      ->  exchange
#      exchange   ->  order progress ->  collector (via demand, below)
#
#  DEMAND is the shared idea. Every script recomputes the same number:
#
#      demand[frag] = sum over unfinished orders of (requires - delivered)
#      short[frag]  = demand[frag] - inventory.get_count(frag)
#
#  That single inventory read is what stops all three machines from
#  over-producing: samples already sitting in inventory count as work done.
#
#  This script collects toward `short`. It prefers fragments the journal
#  already knows the coordinates of, and periodically takes a blind scan pick
#  instead so new species keep getting cataloged for future orders.
# =============================================================================

COLLECTOR_BIOME = "frozen"   # this outpost's biome; journal entries are filtered to it
PLANET_ID = "nocturna"

EXPLORE_EVERY = 4      # every Nth trip is a blind scan pick, to catalog new species
IDLE_SLEEP = 0.5       # cargo full / collector busy — short wait
DEMAND_SLEEP = 5       # nothing outstanding — long wait

# Leave as "" to auto-detect, or paste the exact id from the machine card.
EXCHANGE_ID = ""


def find_machine(kind, configured):
    # Instance ids are numbered per save — bio_exchange_1, bio_exchange_2,
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


exchange = find_machine("bio_exchange", EXCHANGE_ID)
inventory = get_component("inventory")
journal = get_component("journal")

# No Bio Exchange means no order list, so there is no demand to collect
# toward. Rather than stop, fall back to catalog mode: keep collecting
# unidentified fragments so the Lab can analyze and catalog them, which is
# what makes them targetable once an Exchange exists.
CATALOG_MODE = exchange == None
if CATALOG_MODE:
    print("[collector] no Bio Exchange found — running in catalog mode")
    print("[collector] set EXCHANGE_ID to the id on its machine card to target orders")


def outstanding_demand():
    # Fragments still owed to unfinished orders, minus what inventory holds.
    #
    # Returns dict {fragment_id: units_short}. Empty dict means every open
    # order is already covered by samples we hold — nothing to collect for.
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


def known_coords_for(short):
    # Cataloged fragments in this biome that are still short, worst gap first.
    #
    # The journal only lists fragments a Bio Lab has already analyzed, so this
    # is the 'we have been here before' path — no guessing, no wasted trips.
    hits = []
    for frag in journal.cataloged_fragments(PLANET_ID):
        if frag.biome != COLLECTOR_BIOME:
            continue
        if short.has(frag.fragment_id):
            hits.append(frag)

    # Selection sort by gap size — biggest shortfall gets collected first.
    ordered = []
    while len(hits) > 0:
        best = 0
        i = 1
        while i < len(hits):
            if short[hits[i].fragment_id] > short[hits[best].fragment_id]:
                best = i
            i = i + 1
        ordered.append(hits.pop(best))
    return ordered


def blind_pick(rotation):
    # A scan coordinate we have not identified yet — this is how new species
    # enter the catalog. Rotating by index instead of always taking the
    # nearest dot fans the collector out across sites, which fans it out
    # across species (sites do not deplete).
    sites = self.scan()
    if len(sites) == 0:
        return None
    return sites[rotation % len(sites)].coords


trips = 0
rotation = 0

while True:
    short = outstanding_demand()
    if len(short) == 0 and not CATALOG_MODE:
        print("[collector] every open order is covered by inventory — holding")
        sleep(DEMAND_SLEEP)
        continue

    # One cargo slot. If it is full the next move belongs to the Lab.
    if self.cargo:
        sleep(IDLE_SLEEP)
        continue

    coords = None
    label = "unknown"

    # In catalog mode every trip is a blind pick — there is no demand to aim at.
    explore = CATALOG_MODE or trips % EXPLORE_EVERY == (EXPLORE_EVERY - 1)
    if not explore:
        targets = known_coords_for(short)
        if len(targets) > 0:
            pick = targets[0]
            gap = short[pick.fragment_id]
            coords = pick.coords
            label = pick.fragment_id + " (short " + str(gap) + ")"

    if coords == None:
        coords = blind_pick(rotation)
        rotation = rotation + 1
        label = "unidentified — collecting to catalog it"

    if coords == None:
        print("[collector] scan returned no fragments — retrying")
        sleep(1)
        continue

    status = self.collect(coords)

    if status == "ok":
        trips = trips + 1
        print("[collector] retrieved", label)
    elif status == "cargo_occupied":
        # Normal: the Lab has not taken the last specimen yet.
        sleep(IDLE_SLEEP)
    elif status == "busy":
        sleep(IDLE_SLEEP)
    else:
        # invalid_coords / no_fragment — stale journal entry or bad index.
        # Rotate so the next pass tries somewhere else instead of relooping.
        print("[collector]", status, "at", coords, "- rotating")
        rotation = rotation + 1
        trips = trips + 1
        sleep(IDLE_SLEEP)
