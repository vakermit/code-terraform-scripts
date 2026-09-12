# =============================================================================
#  BIO COLLECTOR  (mid tier)  —  paste into the script slot of  bio_collector_1
#  Step 1 of the biology loop: field -> cargo.
# =============================================================================
#
#  The early collector worked out what to fetch by reading the Exchange's
#  active order directly. This one takes JOBS. The Exchange queues one
#  message on bio.jobs per sample that still has to be collected, and each
#  message can be received by exactly one script — so two Collectors at
#  two outposts share the queue without ever fetching the same sample
#  twice, and each skips jobs its own biome cannot serve.
#
#  CHANNEL CONTRACT — see bio_exchange_1.py for the full table.
#    reads    bio.jobs    queue   {"fragment_id": s, "name": s, "order": id}
#    reads    bio.plan    {"scout": bool, "remaining": {...}, ...}
#    writes   bio.status.collector
#
#  CHOOSING A JOB. pending() shows the queue without taking anything. A job
#  is serviceable here when scan() has a cataloged dot with that fragment
#  id. The nearest serviceable job is claimed with receive(id); if another
#  Collector got there first the result is "not_found" and the next one is
#  tried. A claimed job that then fails to collect is re-sent so it is not
#  lost.
#
#  SCOUTING. Unknown dots are the only way to catalog new fragments and the
#  only way the Lab can price them. Three things send this collector to an
#  unknown dot:
#    * bootstrap — fewer than BOOTSTRAP_KNOWN cataloged dots in this biome;
#      this is read from scan() so it survives a restart with no counter
#    * plan.scout — the Exchange's chosen order has unpriced fragments, so
#      exploring is worth more than usual (every 2nd trip instead of 5th)
#    * the steady 1-in-EXPLORE_EVERY trip that keeps the catalog growing
# =============================================================================

BOOTSTRAP_KNOWN = 10      # cataloged dots to reach before jobs take priority
EXPLORE_EVERY = 5         # steady-state: every Nth trip samples an unknown dot
SCOUT_EVERY = 2           # while plan.scout is set: every Nth trip instead

IDLE_SLEEP = 0.5
EMPTY_SLEEP = 5

comms = get_component("comms")
biome = self.outpost.biome


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


# --- capability check ---------------------------------------------------------
# Without the Signal Bus there is no job queue. Fall back to the early
# behaviour: read the Exchange's active order directly and target cataloged
# dots by fragment id.
exchange = None
if comms == None:
    exchange = find_machine("bio_exchange", "")
    if exchange == None:
        print("[collector] DEGRADED: no Signal Bus and no Exchange — scouting only")
    else:
        print("[collector] DEGRADED: no Signal Bus — reading the Exchange's active order directly")
else:
    print("[collector] Signal Bus online — taking jobs from bio.jobs")
print("[collector] this outpost's biome:", biome)


# ------------------------------------------------------------------ scan ----

def split_scan():
    # One scan, split by whether the dot has been cataloged. Both lists keep
    # scan()'s nearest-first order.
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


def nearest_dot_for(fragment_id, known):
    for spot in known:
        if spot.fragment_id == fragment_id:
            return spot
    return None


# ------------------------------------------------------------------ jobs ----

def claim_job(known):
    # Take the nearest serviceable job off the queue. Returns
    # {"job": value, "spot": FragmentLocation} or None.
    if comms == None:
        return None

    best = None
    best_spot = None
    for msg in comms.pending("bio.jobs"):
        spot = nearest_dot_for(msg.value["fragment_id"], known)
        if spot == None:
            continue   # not in this biome — another Collector's job
        if best == None or spot.distance < best_spot.distance:
            best = msg
            best_spot = spot

    if best == None:
        return None

    taken = comms.receive("bio.jobs", best.id)
    if taken.status != "ok":
        # "not_found": another Collector claimed it first. Try again later.
        return None

    claimed = {}
    claimed["job"] = taken.packet.value
    claimed["spot"] = best_spot
    return claimed


def requeue(job):
    # A claimed job that could not be collected goes back on the queue.
    if comms == None:
        return
    sent = comms.send("bio.jobs", job)
    if sent.status != "ok":
        print("[collector] could not requeue", job["name"], "-", sent.message)


def direct_target(known):
    # Degraded mode: nearest cataloged dot the Exchange's active order still
    # needs, net of delivered and in_transit. Returns {"job", "spot"} shaped
    # like claim_job() so the main loop does not care which path it came by.
    if exchange == None:
        return None
    order = exchange.active_order()
    if order == None:
        return None

    for spot in known:
        frag = spot.fragment_id
        need = order.requires.get(frag, 0)
        need = need - order.delivered.get(frag, 0)
        need = need - order.in_transit.get(frag, 0)
        if need > 0:
            job = {}
            job["fragment_id"] = frag
            job["name"] = spot.name
            job["order"] = order.id
            found = {}
            found["job"] = job
            found["spot"] = spot
            return found
    return None


def next_job(known):
    if comms != None:
        return claim_job(known)
    return direct_target(known)


def plan_wants_scouting():
    if comms == None:
        return False
    plan = comms.latest("bio.plan")
    if plan == None:
        return False
    return plan["scout"] == True


def publish_status(state, detail, known_count):
    if comms == None:
        return
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["biome"] = biome
    status["cataloged_here"] = known_count
    comms.broadcast("bio.status.collector", status)


# ------------------------------------------------------------------ loop ----

trips = 0
rotation = 0
quiet = ""

while True:
    # One cargo slot. If it is full the next move belongs to the Lab.
    if self.cargo:
        sleep(IDLE_SLEEP)
        continue

    scanned = split_scan()
    known = scanned["known"]
    unknown = scanned["unknown"]

    # --- what kind of trip is this? ------------------------------------------
    bootstrapping = len(known) < BOOTSTRAP_KNOWN
    every = EXPLORE_EVERY
    if plan_wants_scouting():
        every = SCOUT_EVERY
    explore_turn = trips % every == (every - 1)
    want_unknown = (bootstrapping or explore_turn) and len(unknown) > 0

    target = None
    kind = ""
    job = None

    if not want_unknown:
        claimed = next_job(known)
        if claimed != None:
            job = claimed["job"]
            target = claimed["spot"]
            kind = "job"

    if target == None and len(unknown) > 0:
        # Rotate rather than always taking the nearest — dots do not
        # deplete, so the nearest one would repeat forever.
        target = unknown[rotation % len(unknown)]
        rotation = rotation + 1
        kind = "unknown"

    if target == None:
        # Nothing unknown left and no job this biome can serve — usually the
        # active order is for a different biome than this outpost sits in.
        if quiet != "idle":
            print("[collector]", biome, "biome fully cataloged and no job needs it — idle")
            quiet = "idle"
        publish_status("idle", "", len(known))
        sleep(EMPTY_SLEEP)
        continue
    quiet = ""

    # --- go -------------------------------------------------------------------
    if kind == "job":
        publish_status("collecting", job["name"], len(known))
    else:
        publish_status("scouting", "", len(known))

    result = self.collect(target.coords)

    if result.status == "ok":
        trips = trips + 1
        if kind == "job":
            print("[collector] job:", job["name"], "collected")
        elif bootstrapping:
            print("[collector] bootstrap: unknown dot sampled -", len(known), "of",
                  BOOTSTRAP_KNOWN, "cataloged here")
        else:
            print("[collector] scouting: unknown dot sampled")

    elif result.status == "cargo_occupied" or result.status == "busy":
        if job != None:
            requeue(job)
        sleep(IDLE_SLEEP)

    else:
        # no_fragment / bad coords — put the job back, rotate the unknowns.
        print("[collector]", result.status, "-", result.message)
        if job != None:
            requeue(job)
        rotation = rotation + 1
        trips = trips + 1
        sleep(IDLE_SLEEP)
