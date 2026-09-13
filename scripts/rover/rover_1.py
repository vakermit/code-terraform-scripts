# =============================================================================
#  ROVER  —  paste into the script slot of  rover_1
#  Explore every "?" contact with sonar, then mine the best surveyed site.
# =============================================================================
#
#  The Rover is a chassis with three modules: Nav drives, Sonar finds and
#  surveys sites, Drill mines them. Everything runs off one 100 Wh battery
#  that only a Vehicle Charging Station refills — so the whole script is
#  really a loop of "go out, do the most useful thing the battery allows,
#  come home". Needs scripts/power/charging_station_1.py running on the
#  station: charging jobs belong to the station, not the vehicle.
#
#  ONE PASS OF THE LOOP, in priority order:
#    1. rescue in progress            -> wait
#    2. cargo full, or home with ore  -> go home, unload to Inventory
#    3. home with a low battery       -> wait for the station to charge it
#    4. an unscanned "?" contact      -> drive there, scan, survey  (EXPLORE)
#    5. otherwise                     -> best surveyed mineral site, mine  (MINE)
#
#  Every decision is recomputed from live state each pass, so the script
#  can be stopped and restarted anywhere in its cycle.
#
#  DON'T ROAM. Every "?" is on the map from the start. The planet hands the
#  list over with nocturna.points_of_interest(); `not p.scanned` is the
#  work list. Sonar discoveries persist in the Journal, so the mining phase
#  reads journal.surveyed_sites() rather than remembering anything itself.
#
#  BATTERY. Movement cost per meter is measured as the rover drives (an
#  exponential average of Wh spent over meters moved) and used to estimate
#  the cost of getting home. The rover turns back while it can still afford
#  the trip plus a reserve. A hard floor on battery level backs that up.
# =============================================================================

PLANET_ID = "nocturna"
STORE = "inventory"        # unload target at home

CRUISE = 0.6               # throttle; lower = more meters per Wh
ARRIVE_M = 2               # "close enough" — brake happens after this
RESERVE_WH = 12            # keep this much after the estimated trip home
LEVEL_FLOOR = 0.2          # never let the battery go below this away from home
CHARGE_TO = 0.95           # leave home once charged to this
WH_PER_M_GUESS = 0.05      # movement cost before any is measured
SAFETY = 1.4               # multiplier on the estimated trip-home cost

WANTED_ITEMS = []          # e.g. ["iron_ore", "copper_ore"]; empty = any
PURITY_VALUE = {"standard": 1, "rich": 2, "pure": 3}

TICK = 1                   # seconds between drive-loop checks
STUCK_TICKS = 20           # zero speed for this long mid-drive = stuck

nocturna = get_component("nocturna")
journal = get_component("journal")
network = get_component("outpost_network")
research = get_component("research")
comms = get_component("comms")


# ------------------------------------------------------------- startup ----

home = network.home()
home_x = home.x
home_y = home.y

# Dock at the charging station's own position if it has one, so the
# station's service area — not just the outpost footprint — sees us.
station_pos = None
for building in home.buildings("charging_station"):
    station_pos = building.position
    break
if station_pos != None:
    home_x = station_pos[0]
    home_y = station_pos[1]
    print("[rover] home = charging station at", home_x, ",", home_y)
else:
    print("[rover] no charging station at home — parking at the outpost; battery will not refill")

can_unload = research.is_unlocked("research_auto_feeders")
if not can_unload:
    print("[rover] Auto Feeders is not researched — cargo must be unloaded by hand")

hardness_limit = self.drill.hardness_limit()
print("[rover] sonar", self.sonar.tier(), "-", self.sonar.range(), "m;",
      "drill hardness limit", hardness_limit)

# POI keys ("x:y") this run gave up on: scanned but never resolved (biomass
# needs a drone), or survey refused (too hard / tier too low).
skipped = []


def key_of(x, y):
    return str(x) + ":" + str(y)


def publish(state, detail):
    if comms == None:
        return
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["battery"] = round(self.battery.level(), 2)
    status["cargo"] = self.cargo.count()
    comms.broadcast("rover.status", status)


# -------------------------------------------------------------- battery ----

# Mutable state lives in a dict so functions can update it without the
# `global` statement, which the interpreter's language reference does not
# list.
cost = {}
cost["wh_per_m"] = WH_PER_M_GUESS
cost["last_wh"] = self.battery.wh()
cost["last_pos"] = self.nav.get_position()


def learn_cost():
    # Update the measured movement cost from what changed since last call.
    # Only counts ticks where the rover actually moved; drilling and sonar
    # also draw power and would otherwise pollute the per-meter figure.
    pos = self.nav.get_position()
    last = cost["last_pos"]
    moved = self.nav.get_distance_to(last.x, last.y)
    spent = cost["last_wh"] - self.battery.wh()
    if moved > 1 and spent > 0:
        sample = spent / moved
        cost["wh_per_m"] = cost["wh_per_m"] * 0.8 + sample * 0.2
    cost["last_wh"] = self.battery.wh()
    cost["last_pos"] = pos


def wh_to_reach(x, y):
    return self.nav.get_distance_to(x, y) * cost["wh_per_m"] * SAFETY


def can_afford_to_be_here():
    # True while the battery can still get us home with the reserve intact.
    if self.battery.level() < LEVEL_FLOOR:
        return False
    return self.battery.wh() > wh_to_reach(home_x, home_y) + RESERVE_WH


def can_afford_trip(x, y):
    # A trip to (x, y) and from there back home, with the reserve.
    there = wh_to_reach(x, y)
    back = nocturna_distance(x, y, home_x, home_y) * cost["wh_per_m"] * SAFETY
    return self.battery.wh() > there + back + RESERVE_WH


def nocturna_distance(x1, y1, x2, y2):
    dx = x1 - x2
    dy = y1 - y2
    return sqrt(dx * dx + dy * dy)


def at_home():
    return self.nav.get_distance_to(home_x, home_y) <= ARRIVE_M


# ---------------------------------------------------------------- drive ----

def drive_to(x, y, heading_home):
    # Drive and block until arrival, braking at the end. Returns "ok",
    # "low_battery" (turned around), "rescued", or "stuck".
    # set_target() returns immediately; the rover keeps driving only while
    # this script is running, so the wait loop is the drive.
    self.nav.set_target(x, y)
    self.nav.set_throttle(CRUISE)
    still = 0
    while self.nav.get_distance_to(x, y) > ARRIVE_M:
        sleep(TICK)
        learn_cost()

        if self.is_being_rescued():
            self.nav.brake()
            return "rescued"
        if not heading_home and not can_afford_to_be_here():
            self.nav.brake()
            return "low_battery"

        if self.nav.get_speed() == 0:
            still = still + 1
            if still >= STUCK_TICKS:
                self.nav.brake()
                return "stuck"
        else:
            still = 0

    self.nav.brake()
    return "ok"


def go_home():
    publish("returning", "")
    result = drive_to(home_x, home_y, True)
    if result != "ok":
        print("[rover] return home:", result)
    return result


# -------------------------------------------------------------- explore ----

def next_contact():
    # Nearest unscanned "?" we can afford to visit and get home from.
    best = None
    best_d = 0
    for p in nocturna.points_of_interest():
        if p.scanned:
            continue
        if key_of(p.x, p.y) in skipped:
            continue
        d = self.nav.get_distance_to(p.x, p.y)
        if best == None or d < best_d:
            best = p
            best_d = d
    return best


def explore(p):
    # Drive to a contact, sweep, and survey everything the sweep found.
    publish("exploring", key_of(p.x, p.y))
    result = drive_to(p.x, p.y, False)
    if result != "ok":
        return result

    sweep = self.sonar.scan()
    if sweep.status != "ok":
        print("[rover] scan:", sweep.message)
        skipped.append(key_of(p.x, p.y))
        return "scan_failed"

    resolved = 0
    for site in sweep.sites:
        if site.surveyed:
            resolved = resolved + 1
            continue
        survey = self.sonar.survey(site)
        if survey.status == "ok":
            resolved = resolved + 1
            found = survey.site
            if found.kind() == "mineral":
                print("[rover] surveyed", found.name, "-", found.item_id,
                      "hardness", found.hardness, "purity", found.purity)
            else:
                print("[rover] surveyed", found.name, "-", found.kind())
        else:
            # too_hard / tier_too_low / research_required: this sonar cannot
            # finish the job. Leave it for a better module.
            print("[rover] survey", site.name, "-", survey.message)

    # A contact that is still unscanned after a sweep is one sonar cannot
    # resolve here (biomass needs a drone). Do not come back.
    still_open = False
    for q in nocturna.points_of_interest():
        if q.x == p.x and q.y == p.y and not q.scanned:
            still_open = True
    if still_open:
        skipped.append(key_of(p.x, p.y))
        print("[rover] contact at", p.x, ",", p.y, "needs a different scanner — skipping")

    return "ok"


# ----------------------------------------------------------------- mine ----

def wanted_ores():
    # What the Smelter says it is short of (factory.ore), falling back to
    # WANTED_ITEMS. {ore_id: units}; empty means mine anything.
    if comms != None:
        published = comms.latest("factory.ore")
        if published != None and len(published) > 0:
            return published
    wanted = {}
    for item in WANTED_ITEMS:
        wanted[item] = 1
    return wanted


def best_site():
    # Highest-value mineable site the drill can handle: purity multiplier
    # divided by distance, so a rich site nearby beats a pure one far off.
    # Ore the factory is short of gets a strong preference; nothing is
    # excluded outright, so the rover keeps working when nothing is asked.
    wanted = wanted_ores()
    best = None
    best_score = 0
    for site in journal.surveyed_sites(PLANET_ID):
        if site.kind() != "mineral":
            continue
        if site.hardness == None or site.hardness > hardness_limit:
            continue
        if not can_afford_trip(site.x, site.y):
            continue
        d = self.nav.get_distance_to(site.x, site.y)
        score = PURITY_VALUE.get(site.purity, 1) / (1 + d / 100)
        if len(wanted) > 0:
            if wanted.has(site.item_id):
                score = score * 10
            else:
                score = score * 0.1
        if best == None or score > best_score:
            best = site
            best_score = score
    return best


def mine_at(site):
    # Drive to the site and drill until the hold is full or the battery
    # says it is time to leave. mine() pauses the script per unit.
    publish("mining", site.item_id)
    result = drive_to(site.x, site.y, False)
    if result != "ok":
        return result

    mined = 0
    while not self.cargo.full():
        if not can_afford_to_be_here():
            break
        if self.is_being_rescued():
            break
        dig = self.drill.mine()
        if dig.status != "ok":
            print("[rover] mine:", dig.message)
            break
        mined = mined + 1
        learn_cost()

    print("[rover] mined", mined, "x", site.item_id, "at", site.name)
    return "ok"


# --------------------------------------------------------------- unload ----

def unload():
    if not can_unload:
        print("[rover] holding", self.cargo.count(), "units — unload by hand")
        return False
    if self.output.connected_id() != STORE:
        result = self.output.connect(STORE)
        if result.status != "ok":
            print("[rover] output connect:", result.message)
            return False
    for stack in self.cargo.stacks():
        result = self.output.send(stack.id, stack.count, stack.properties, "exact")
        if result.status != "ok":
            print("[rover] unload", stack.id, ":", result.message)
            return False
        print("[rover] unloaded", stack.count, "x", stack.id)
    return True


# ------------------------------------------------------------------ loop ----

idle_note = ""

while True:
    learn_cost()

    # 1. hands off while the rescue drone works
    if self.is_being_rescued():
        publish("rescued", self.rescue_status())
        sleep(5)
        continue

    # 2. bring cargo home
    if self.cargo.full() or (self.cargo.count() > 0 and at_home()):
        if not at_home():
            go_home()
            continue
        unload()
        if self.cargo.count() > 0:
            sleep(30)   # manual unload, or the store is full — check back
            continue

    # 3. charge before leaving
    if at_home() and self.battery.level() < CHARGE_TO:
        publish("charging", str(round(self.battery.level(), 2)))
        if station_pos == None:
            sleep(60)
        else:
            sleep(5)
        continue

    # Not at home and cannot afford to stay out: head back now.
    if not at_home() and not can_afford_to_be_here():
        go_home()
        continue

    # 4. explore
    contact = next_contact()
    if contact != None and can_afford_trip(contact.x, contact.y):
        idle_note = ""
        result = explore(contact)
        if result == "low_battery" or result == "stuck":
            go_home()
        continue

    # 5. mine
    site = best_site()
    if site != None:
        idle_note = ""
        result = mine_at(site)
        if result == "low_battery" or result == "stuck":
            go_home()
        continue

    # Nothing reachable. Either everything is explored and mined out for
    # this drill, or the battery cannot cover any trip — in which case
    # go home and let the station fix that.
    if not at_home():
        go_home()
        continue

    if idle_note != "idle":
        if contact != None:
            print("[rover] contacts remain but none are within battery range — idle at home")
        else:
            print("[rover] every contact scanned and no mineable site within reach — idle at home")
        idle_note = "idle"
    publish("idle", "")
    sleep(60)
