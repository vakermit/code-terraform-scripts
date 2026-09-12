# ============================================================
#  HARVESTER - heat-aware greedy collector
# ============================================================
#  Heat is charged by WHAT IS IN the destination sector:
#      move onto an item sector   -> +1 heat
#      move onto an empty sector  -> +7 heat
#      collect on an empty sector -> +9 heat  (never do this)
#  Max heat 100, draining 3 per world-hour - and the drain runs
#  DURING actions. A 0.5h move sheds 1.5, so an item-cell hop is
#  net negative heat and only empty-cell hops build any. Rest is
#  the whole time budget: on a scattered map the hours spent
#  cooling outnumber the hours spent moving about 3 to 1. So the
#  router prices an empty hop at 7x an item hop and prefers to
#  thread through item cells even when that is a little longer.
#
#  Rules that do the work:
#   1. Pick targets by value per step, walk toward them along
#      whichever axis lands on an item sector.
#   2. Rest only when the NEXT hop would cross the cap, and rest
#      exactly the hours that hop needs - not a fixed nap.
#
#  Not a rule, though it sounds like one: leaving "bridge" cells
#  standing as cheap road for later. Measured on this 8x24 grid
#  it costs 9-19% MORE time at every density above 15 items -
#  the trip back to sweep them up costs more empty hops than the
#  corridors ever saved. It is left in as DEFER_BRIDGES for
#  experiment, and off by default.
#
#  Runtime notes (docs/manual/37-loops, 04-long-running-scripts,
#  machine-guides harvester_script.info):
#  - move() and collect() BLOCK for 0.5h / 0.25h and return
#    result objects; branch on .status, never compare the result.
#  - get_scanned() is live: it already reflects what we picked
#    up. It is re-read every pass, so the map is never stale and
#    a game load costs nothing - the machine is the memory.
#  - Each pass of the outer loop does one physical action at
#    most, so the planning work between yields stays far under
#    the per-tick step limit even on a full 192-sector map.
#  - sleep() is in real seconds; world-hours are converted with
#    clock.real_seconds_per_hour().
# ============================================================

SCANNER_ID    = "scanner_1"
ROWS          = 8      # A-H
COLS          = 24     # 1-24
HEAT_MAX      = 100
HEAT_SAFETY   = 3      # never plan a hop that would land within this of the cap
COOL_PER_HOUR = 3.0    # heat drained per world-hour, per the machine guide
COST_ITEM     = 1      # routing weight for a hop onto an item sector
COST_EMPTY    = 7      # routing weight for a hop onto an empty sector
MIN_VALUE     = 0      # ignore items worth less than this (0 = take all)
DEFER_BRIDGES = False  # leave bridge cells standing as cheap road. Measured:
                       # 40 items +9%, 80 items +9%, 140 items +19% total
                       # hours vs off. Keep it off unless your map is one
                       # dense connected blob.
FLOOD_CAP     = 60     # give up the bridge test on blobs bigger than this
IDLE_HOURS    = 1.0    # world-hours to wait when the scan shows nothing
VERBOSE       = True

scanner = get_component(SCANNER_ID)
clock = get_component("clock")
RSPH = clock.real_seconds_per_hour()


def say(msg):
    if VERBOSE:
        print(msg)


# ---------- sector ids: "E13" -> (row 5, col 13) ------------------------

def parse(sid):
    return (ord(sid[0]) - 64, int(sid[1:]))


def fmt(p):
    return chr(64 + p[0]) + str(p[1])


def neighbors(p):
    r = p[0]
    c = p[1]
    return ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1))


# ---------- the live map -------------------------------------------------

# {(row, col): value} for every scanned sector that currently holds an item.
# Read fresh every pass: get_scanned() tracks pickups and drops on its own.
def read_map():
    pts = {}
    data = scanner.get_scanned()
    for sid in data:
        res = data[sid]
        if res.status == "ok" and res.value >= MIN_VALUE:
            pts[parse(sid)] = res.value
    return pts


# ---------- heat ---------------------------------------------------------

# Sleep exactly long enough to drain heat down to `target`. Cooling is
# 3/world-hour, so the nap is (excess / 3) hours, converted to the real
# seconds sleep() wants. Re-checked afterwards in case pacing differs.
def cool_to(target):
    n = 0
    while self.get_heat() > target and n < 6:
        n = n + 1
        excess = self.get_heat() - target
        hours = excess / COOL_PER_HOUR
        say("heat " + str(self.get_heat()) + " - resting " + str(hours) +
            "h to reach " + str(target))
        sleep(hours * RSPH + 0.5)


# ---------- bridges ------------------------------------------------------

# True if p is a cut vertex of the item network: collecting it now would
# turn a 1-heat corridor into a 7-heat one for trips we still have to make.
# Collecting is free once we are standing here, so when p still holds two
# groups of uncollected items together, leave it for a later pass. Bounded
# by FLOOD_CAP so a huge blob cannot eat the tick's step budget.
def is_bridge(p, pts):
    nb = []
    for q in neighbors(p):
        if q in pts:
            nb.append(q)
    if len(nb) < 2:
        return False
    seen = {nb[0]: 1}
    stack = [nb[0]]
    while len(stack) > 0:
        cur = stack.pop()
        for q in neighbors(cur):
            if q != p and q in pts and q not in seen:
                seen[q] = 1
                stack.append(q)
                if len(seen) > FLOOD_CAP:
                    return False
    for q in nb:
        if q not in seen:
            return True
    return False


# ---------- routing ------------------------------------------------------

# Best value per step away. The hot loop: `pts[p] <= bs*d` is the same test
# as `pts[p]/d <= bs` with the divide removed, so we only divide on a new
# leader. Measured earlier, a bonus for clustered items made things worse
# at every map size - it strands outliers - so there isn't one.
def choose(pos, pts, skip):
    best = None
    bs = -1.0
    pr = pos[0]
    pc = pos[1]
    for p in pts:
        d = abs(p[0] - pr) + abs(p[1] - pc)
        if d == 0 or p in skip:
            continue
        if pts[p] <= bs * d:
            continue
        bs = pts[p] / (d * 1.0)
        best = p
    return best


# Every cell is passable, so a greedy descent always reaches the target in
# exactly Manhattan distance hops. The only choice is which axis to move on,
# so prefer the one that lands on an item: 1 heat instead of 7.
def next_hop(pos, tgt, pts):
    dr = tgt[0] - pos[0]
    dc = tgt[1] - pos[1]
    cands = []
    if dr > 0:
        cands.append((pos[0] + 1, pos[1]))
    elif dr < 0:
        cands.append((pos[0] - 1, pos[1]))
    if dc > 0:
        cands.append((pos[0], pos[1] + 1))
    elif dc < 0:
        cands.append((pos[0], pos[1] - 1))
    for q in cands:
        if q in pts:
            return q
    if len(cands) == 0:
        return None
    if len(cands) == 2 and abs(dc) > abs(dr):
        return cands[1]       # stay near the diagonal; more items in reach
    return cands[0]


# ---------- physical actions ---------------------------------------------

# Store whatever is held. A full inventory is not an error to give up on:
# hold the item and keep trying every hour until the player sells.
def put_away():
    waited = 0
    while True:
        r = self.store()
        if r.status == "ok" or r.status == "empty":
            return True
        if r.status == "inventory_full":
            if waited % 6 == 0:
                say("INVENTORY FULL - holding " + self.get_held() +
                    "; sell something and I will carry on")
            waited = waited + 1
            sleep(IDLE_HOURS * RSPH)
            continue
        say("store failed: " + r.message)
        return False


# One cardinal hop. Rests first if the hop would cross the heat cap.
def go(q, pts):
    if q in pts:
        cost = COST_ITEM
    else:
        cost = COST_EMPTY
    if self.get_heat() + cost > HEAT_MAX - HEAT_SAFETY:
        cool_to(HEAT_MAX - HEAT_SAFETY - cost)
    sid = fmt(q)
    n = 0
    while n < 8:
        n = n + 1
        r = self.move(sid)
        if r.status == "ok" or r.status == "already_here":
            return True
        if r.status == "overheated":
            cool_to(HEAT_MAX - HEAT_SAFETY - cost)
        elif r.status == "moving" or r.status == "busy":
            sleep(0.25 * RSPH)
        else:
            say("move " + sid + " -> " + r.status + ": " + r.message)
            return False
    return False


# Collect the item under us and store it. Only called on a sector the live
# map says holds an item, so the +9 empty-collect penalty never happens.
def take(p, pts):
    if self.get_held() != "":
        if not put_away():
            return False
    n = 0
    while n < 8:
        n = n + 1
        res = self.collect()
        s = res.status
        if s == "ok":
            pts.pop(p, None)
            say("+ " + res.name + " (" + str(res.value) + ") at " + fmt(p) +
                ", heat " + str(self.get_heat()))
            return put_away()
        if s == "holding":
            put_away()
        elif s == "overheated":
            cool_to(HEAT_MAX - HEAT_SAFETY - 9)
        elif s == "moving" or s == "busy" or s == "collecting":
            sleep(0.25 * RSPH)
        else:
            pts.pop(p, None)          # "empty": the map was stale
            say("collect at " + fmt(p) + " -> " + s + ": " + res.message)
            return False
    return False


# ---------- main ---------------------------------------------------------

skip = {}            # bridge cells left standing; still 1-heat road
force = False        # sweep mode: only bridges remain, take them
idle_said = False
got = 0
worth = 0

say("harvester online at " + self.get_position() + ", heat " +
    str(self.get_heat()) + ", " + str(len(read_map())) + " items scanned")

while True:
    pts = read_map()
    if len(pts) == 0:
        if not idle_said:
            say("nothing left on the scanned grid (" + str(got) +
                " collected, worth " + str(worth) + ") - waiting")
            idle_said = True
        sleep(IDLE_HOURS * RSPH)
        continue
    idle_said = False

    pos = parse(self.get_position())
    if self.get_held() != "":
        put_away()

    # Standing on an item: take it, unless it is a bridge worth keeping.
    if pos in pts:
        if force or not (DEFER_BRIDGES and is_bridge(pos, pts)):
            v = pts[pos]
            if take(pos, pts):
                got = got + 1
                worth = worth + v
            continue
        if pos not in skip:
            skip[pos] = 1
            say("leaving " + fmt(pos) + " standing as 1-heat road")

    tgt = choose(pos, pts, skip)
    if tgt is None:
        if len(skip) > 0:
            # Only bridges left - nothing remains for them to hold together.
            say("sweeping " + str(len(skip)) + " held bridge(s)")
            skip = {}
            force = True
            continue
        sleep(IDLE_HOURS * RSPH)
        continue

    if DEFER_BRIDGES and not force and is_bridge(tgt, pts):
        skip[tgt] = 1
        continue

    q = next_hop(pos, tgt, pts)
    if q is None:
        continue
    if not go(q, pts):
        pts.pop(q, None)
        skip[tgt] = 1
