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

if comms == None:
    print("[collector] Signal Bus not researched — this is the mid-tier script;")
    print("[collector] use scripts/bio/early until comms unlock.")


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
        claimed = claim_job(known)
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
        # Nothing unknown left and no job this biome can serve.
        if quiet != "idle":
            print("[collector] biome fully cataloged and no serviceable jobs — idle")
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
