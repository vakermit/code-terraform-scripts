# =============================================================================
#  BIO COLLECTOR  —  paste into the script slot of  bio_collector_1
#  Step 1 of the biology loop: field -> cargo.
# =============================================================================
#
#  This is script 1 of 3. The three machines share no code and no variables.
#  They coordinate through game state only:
#
#      collector  ->  cargo slot        ->  lab
#      lab        ->  output -> store   ->  exchange
#      exchange   ->  active order      ->  collector  (this file)
#
#  TARGETING. The Exchange's ACTIVE order is the focus. Not the whole order
#  list — the one order actually selected. What it still needs is:
#
#      remaining[frag] = requires - delivered - in_transit
#
#  in_transit matters: samples already staged in an Exchange input or mid
#  delivery are committed. Counting them stops the collector from fetching
#  specimens for a requirement that is already covered but not yet paid.
#
#  scan() does the rest of the work. A location that has been analyzed once
#  comes back with .cataloged True and its .fragment_id filled in, so the
#  collector can walk straight to a known dot. Unknown dots keep those
#  fields None — those are the ones worth sampling to learn something.
#
#  BOOTSTRAP. On a cold save nothing is cataloged, so there is nothing to
#  target and no recipe prices are known. The first BOOTSTRAP_UNKNOWNS trips
#  therefore go to unknown dots on purpose. That is what fills the journal
#  and, through the Lab, the recipe book the cost model needs.
#
#  After the bootstrap, one trip in EXPLORE_EVERY still goes to an unknown
#  dot so the catalog keeps growing for orders you have not activated yet.
# =============================================================================

BOOTSTRAP_UNKNOWNS = 10   # unknown dots to sample before targeting begins
EXPLORE_EVERY = 5         # after that, every Nth trip is still an unknown dot

IDLE_SLEEP = 0.5          # cargo full / collector busy
DEMAND_SLEEP = 5          # no active order to work toward

# Leave as "" to auto-detect, or paste the exact id from the machine card.
EXCHANGE_ID = ""


def find_machine(kind, configured):
    # Instance ids are numbered per save — bio_exchange_1, bio_exchange_2,
    # ... — and a powered-down machine reads the same as a missing one.
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

if exchange == None:
    print("[collector] no Bio Exchange found — is it powered on?")
    print("[collector] running unfocused: every trip samples an unknown dot")


def active_remaining():
    # What the ACTIVE order still needs, as {fragment_id: count}.
    #
    # Empty dict means there is nothing to focus on: no Exchange, no active
    # order, or every requirement already delivered or committed.
    if exchange == None:
        return {}

    order = exchange.active_order()
    if order == None:
        return {}

    remaining = {}
    for frag in order.requires.keys():
        short = order.requires[frag]
        short = short - order.delivered.get(frag, 0)
        short = short - order.in_transit.get(frag, 0)
        if short > 0:
            remaining[frag] = short
    return remaining


def split_scan():
    # One scan, split into the two lists the policy chooses between.
    #
    # Returns {"known": [...], "unknown": [...]}. Both keep scan()'s
    # nearest-first order, so index 0 of either is the closest of its kind.
    known = []
    unknown = []
    for spot in self.scan():
        if spot.cataloged:
            known.append(spot)
        else:
            unknown.append(spot)

    split = {}
    split["known"] = known
    split["unknown"] = unknown
    return split


def pick_wanted(known, remaining):
    # Nearest cataloged dot whose fragment the active order still needs.
    # `known` is already nearest-first, so the first match is the closest.
    for spot in known:
        if remaining.has(spot.fragment_id):
            return spot
    return None


unknowns_sampled = 0
trips = 0
rotation = 0
last_state = ""

while True:
    # One cargo slot. If it is full the next move belongs to the Lab.
    if self.cargo:
        sleep(IDLE_SLEEP)
        continue

    remaining = active_remaining()
    scanned = split_scan()
    known = scanned["known"]
    unknown = scanned["unknown"]

    # --- decide what kind of trip this is -----------------------------------
    bootstrapping = unknowns_sampled < BOOTSTRAP_UNKNOWNS
    explore_turn = trips % EXPLORE_EVERY == (EXPLORE_EVERY - 1)
    want_unknown = bootstrapping or explore_turn or len(remaining) == 0

    target = None
    kind = ""

    if not want_unknown:
        target = pick_wanted(known, remaining)
        kind = "order"

    if target == None and len(unknown) > 0:
        # Rotate through unknown dots rather than always taking the nearest —
        # sites do not deplete, so the nearest one would repeat forever.
        target = unknown[rotation % len(unknown)]
        rotation = rotation + 1
        kind = "unknown"

    if target == None and not want_unknown:
        # Nothing unknown left in this biome and no cataloged dot matches the
        # order. Fall back to the nearest cataloged dot to keep the Lab fed.
        if len(known) > 0:
            target = known[0]
            kind = "spare"

    if target == None:
        if last_state != "empty":
            print("[collector] scan found nothing to collect — waiting")
            last_state = "empty"
        sleep(DEMAND_SLEEP)
        continue

    # --- go ------------------------------------------------------------------
    result = self.collect(target.coords)

    if result.status == "ok":
        trips = trips + 1
        last_state = ""

        if kind == "unknown":
            unknowns_sampled = unknowns_sampled + 1
            if bootstrapping:
                left = BOOTSTRAP_UNKNOWNS - unknowns_sampled
                print("[collector] bootstrap sample", unknowns_sampled, "- ", left, "to go")
            else:
                print("[collector] exploring — unknown dot sampled")
        elif kind == "order":
            need = remaining[target.fragment_id]
            print("[collector] for order:", target.name, "- still needs", need)
        else:
            print("[collector] no order match — collected", target.name)

    elif result.status == "cargo_occupied":
        # Normal: the Lab has not taken the last specimen yet.
        sleep(IDLE_SLEEP)
    elif result.status == "busy":
        sleep(IDLE_SLEEP)
    else:
        # no_fragment / bad coords — rotate so the next pass tries elsewhere.
        print("[collector]", result.status, "-", result.message)
        rotation = rotation + 1
        trips = trips + 1
        sleep(IDLE_SLEEP)
