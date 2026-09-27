# =============================================================================
#  PIONEER  —  paste into the script slot of  pioneer_1
#  Build what is planned, explore what is unknown, mine what the factory
#  wants. Same loop shape as rover_1.py, with construction in front.
# =============================================================================
#
#  The Pioneer is eight Universal slots. What the script can do is read
#  from what is mounted: no Constructor means the build phase is skipped,
#  no Sonar skips exploring, no Drill skips mining. Batteries and cargo
#  are pools across every holder and rack, so the loop reads self.battery
#  and self.cargo and never cares which bay a cell or bin sits in.
#
#  ONE PASS, in priority order:
#    1. rescue in progress              -> wait
#    2. cargo full, or home with cargo  -> go home, unload to storage
#    3. home and below CHARGE_TO        -> wait for the station
#    4. a planned construction job      -> load its kit, drive, execute
#    5. an unscanned "?" contact        -> drive, scan, survey
#    6. best surveyed mineral site      -> drive, drill
#
#  CARGO BINS latch to one item id each until emptied. A build kit and an
#  ore can ride together in separate bins; the pool reports full() when
#  every bin is latched and full, or no bin can take the item at hand.
#
#  Storage routing matches the factory scripts: pull Inventory first, then
#  bins; push to a bin latched to the item, then an empty bin, then
#  Inventory. Battery cost per meter is measured while driving.
# =============================================================================

from control import allows, mine_targets, role_of
from demand import has_demand, ore_demand, weight_of
from scout import best_hub, best_outposts
from store import aim, bins, sink_for, source_for, stock_of
from util import key_of

PLANET_ID = "nocturna"
STORE = "inventory"

CRUISE = 0.6
ARRIVE_M = 2
RESERVE_FRACTION = 0.12    # reserve scales with the pool: 12% of capacity, 10 Wh minimum
LEVEL_FLOOR = 0.15
CHARGE_TO = 0.95
WH_PER_M_GUESS = 0.05
SAFETY = 1.4

WANTED_ITEMS = []
PURITY_VALUE = {"standard": 1, "rich": 2, "pure": 3}
TICK = 1
STUCK_TICKS = 20

nocturna = get_component("nocturna")
journal = get_component("journal")
network = get_component("outpost_network")
blueprint = get_component("construction_blueprint")
research = get_component("research")
inventory = get_component("inventory")
comms = get_component("comms")


# ------------------------------------------------------------- startup ----

home = network.home()
home_x = home.x
home_y = home.y
station_pos = None
for building in home.buildings("charging_station"):
    station_pos = building.position
    break
if station_pos != None:
    home_x = station_pos[0]
    home_y = station_pos[1]
else:
    print("[pioneer] no charging station at home — the pool will not refill")

can_transfer = research.is_unlocked("research_auto_feeders")
if not can_transfer:
    print("[pioneer] Auto Feeders is not researched — cargo cannot be loaded or unloaded by script")

# What is mounted decides which phases run.
fitted = {}
for slot in self.modules():
    if slot.module_id != None:
        fitted[slot.module_id] = True

has_sonar = False
has_drill = False
has_constructor = False
for module_id in fitted.keys():
    if module_id.find("sonar") >= 0:
        has_sonar = True
    if module_id.find("drill") >= 0:
        has_drill = True
    if module_id.find("constructor") >= 0:
        has_constructor = True

if self.battery.capacity() == 0:
    print("[pioneer] NO BATTERIES INSTALLED — cannot move")
RESERVE_WH = max(10, self.battery.capacity() * RESERVE_FRACTION)
print("[pioneer] pool", self.battery.capacity(), "Wh; cargo", self.cargo.capacity(),
      "units; sonar", has_sonar, "drill", has_drill, "constructor", has_constructor)

hardness_limit = 0
if has_drill:
    hardness_limit = self.drill.hardness_limit()

# Roles are assigned by the controller; capability is our own business. A role
# this rover cannot serve falls back to auto rather than idling: being told to
# scout without sonar should not stop it mining.
SCOUT_RADIUS = 150         # m: sites this close would share one outpost's pipes
SCOUT_MAX_RANGE = 1200     # m from home: beyond this a trip is doubtful
SCOUT_BIOME = ""           # "" = any biome that is not home


def my_role():
    wanted = role_of(self.id)
    if wanted == "scout" and not has_sonar:
        return "auto"
    if wanted == "mine" and not has_drill:
        return "auto"
    if wanted == "build" and not has_constructor:
        return "auto"
    return wanted


home_biome = nocturna.biome_at(home_x, home_y)

skipped = []


def publish(state, detail):
    if comms == None:
        return
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["battery"] = round(self.battery.level(), 2)
    status["cargo"] = self.cargo.count()
    comms.broadcast("pioneer.status", status)


# ---------------------------------------------------------------- stores ----

def load(item, count):
    # Pull `count` of item into cargo from home storage. Home only.
    moved = 0
    while moved < count:
        src = source_for(item)
        if src == "" or not aim(self.input, src, "pioneer"):
            break
        result = self.input.take(item, count - moved)
        if result.status != "ok" or result.moved == 0:
            if result.status != "ok":
                print("[pioneer] take", item, ":", result.message)
            break
        moved = moved + result.moved
    return moved


def unload():
    if not can_transfer:
        print("[pioneer] holding", self.cargo.count(), "units — unload by hand")
        return False
    for stack in self.cargo.stacks():
        left = stack.count
        while left > 0:
            if not aim(self.output, sink_for(stack.id), "pioneer"):
                return False
            result = self.output.send(stack.id, left, stack.properties, "exact")
            if result.status != "ok" or result.moved == 0:
                if result.status != "ok":
                    print("[pioneer] unload", stack.id, ":", result.message)
                return False
            left = left - result.moved
        print("[pioneer] unloaded", stack.count, "x", stack.id)
    return True


# -------------------------------------------------------------- battery ----

cost = {}
cost["wh_per_m"] = WH_PER_M_GUESS
cost["last_wh"] = self.battery.wh()
cost["last_pos"] = self.nav.get_position()


def learn_cost():
    pos = self.nav.get_position()
    last = cost["last_pos"]
    moved = self.nav.get_distance_to(last.x, last.y)
    spent = cost["last_wh"] - self.battery.wh()
    if moved > 1 and spent > 0:
        cost["wh_per_m"] = cost["wh_per_m"] * 0.8 + (spent / moved) * 0.2
    cost["last_wh"] = self.battery.wh()
    cost["last_pos"] = pos


def distance(x1, y1, x2, y2):
    dx = x1 - x2
    dy = y1 - y2
    return sqrt(dx * dx + dy * dy)


def wh_to_reach(x, y):
    return self.nav.get_distance_to(x, y) * cost["wh_per_m"] * SAFETY


def can_afford_to_be_here():
    if self.battery.level() < LEVEL_FLOOR:
        return False
    return self.battery.wh() > wh_to_reach(home_x, home_y) + RESERVE_WH


def can_afford_trip(x, y):
    there = wh_to_reach(x, y)
    back = distance(x, y, home_x, home_y) * cost["wh_per_m"] * SAFETY
    return self.battery.wh() > there + back + RESERVE_WH


def at_home():
    return self.nav.get_distance_to(home_x, home_y) <= ARRIVE_M


# ---------------------------------------------------------------- drive ----

def drive_to(x, y, heading_home):
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
        print("[pioneer] return home:", result)
    return result


# ---------------------------------------------------------- construction ----

def cargo_count(item):
    total = 0
    for stack in self.cargo.stacks():
        if stack.id == item:
            total = total + stack.count
    return total


def next_job():
    # Paused work first (progress is banked), then pending jobs whose kit is
    # either already aboard or available in storage. Nearest first.
    if not has_constructor:
        return None

    best = None
    best_d = 0
    for job in blueprint.paused_constructions():
        d = self.nav.get_distance_to(job.position.x, job.position.y)
        if best == None or d < best_d:
            best = job
            best_d = d
    if best != None:
        return best

    for job in blueprint.pending_constructions():
        if job.required_item != None and job.required_count > 0:
            have = stock_of(job.required_item) + cargo_count(job.required_item)
            if have < job.required_count:
                continue
        if not can_afford_trip(job.position.x, job.position.y):
            continue
        d = self.nav.get_distance_to(job.position.x, job.position.y)
        if best == None or d < best_d:
            best = job
            best_d = d
    return best


def build(job):
    # Make sure the kit is aboard (loading happens at home), drive, execute.
    if job.required_item != None and job.required_count > 0:
        short = job.required_count - cargo_count(job.required_item)
        if short > 0:
            if not at_home():
                return "need_kit"
            got = load(job.required_item, short)
            if got < short:
                print("[pioneer] could not load", short, "x", job.required_item, "for", job.kind)
                return "no_kit"
            print("[pioneer] loaded", got, "x", job.required_item, "for", job.kind)

    publish("building", job.kind)
    result = drive_to(job.position.x, job.position.y, False)
    if result != "ok":
        return result

    done = self.constructor.execute(job.id)
    if done.status != "ok":
        print("[pioneer] execute", job.kind, ":", done.message)
        return "execute_failed"
    print("[pioneer] built", job.kind, "at", job.position.x, ",", job.position.y)
    return "ok"


# -------------------------------------------------------------- explore ----

def open_contacts():
    out = []
    for p in nocturna.points_of_interest():
        if p.scanned or key_of(p.x, p.y) in skipped:
            continue
        out.append(p)
    return out


def next_contact():
    # Nearest-first surveys a ring around home and never leaves the home
    # biome. Scouting instead ranks whole sonar sweeps by what they contain,
    # so a cluster of new-biome contacts outranks one more nearby dot.
    if not has_sonar:
        return None
    contacts = open_contacts()
    if len(contacts) == 0:
        return None
    if my_role() == "scout":
        hub = best_hub(contacts, self.sonar.range() * 0.85, self.nav, nocturna,
                       home_biome, SCOUT_BIOME, can_afford_trip)
        if hub != None:
            return hub["members"][0]
    best = None
    best_d = 0
    for p in contacts:
        d = self.nav.get_distance_to(p.x, p.y)
        if best == None or d < best_d:
            best = p
            best_d = d
    return best


def report_outposts():
    # Cluster everything surveyed so far and pin the best candidates. Sites
    # within pipe range share one outpost, so the cluster is the unit of
    # value, not the site.
    surveyed = journal.surveyed_sites(PLANET_ID)
    if len(surveyed) == 0:
        return
    spots = best_outposts(surveyed, SCOUT_RADIUS, self.nav, nocturna,
                          home_biome, SCOUT_BIOME, SCOUT_MAX_RANGE, 3)
    if len(spots) == 0:
        return
    n = 1
    for spot in spots:
        print("[pioneer] outpost candidate", n, "score", round(spot["score"], 1),
              "at", int(spot["x"]), int(spot["y"]),
              "-", len(spot["members"]), "sites")
        n = n + 1
    publish("scouted", str(int(spots[0]["x"])) + "," + str(int(spots[0]["y"])))


def explore(p):
    publish("exploring", key_of(p.x, p.y))
    result = drive_to(p.x, p.y, False)
    if result != "ok":
        return result

    sweep = self.sonar.scan()
    if sweep.status != "ok":
        print("[pioneer] scan:", sweep.message)
        skipped.append(key_of(p.x, p.y))
        return "scan_failed"

    for site in sweep.sites:
        if site.surveyed:
            continue
        survey = self.sonar.survey(site)
        if survey.status == "ok":
            found = survey.site
            if found.kind() == "mineral":
                print("[pioneer] surveyed", found.name, "-", found.item_id,
                      "hardness", found.hardness, "purity", found.purity)
            else:
                print("[pioneer] surveyed", found.name, "-", found.kind())
        else:
            print("[pioneer] survey", site.name, "-", survey.message)

    for q in nocturna.points_of_interest():
        if q.x == p.x and q.y == p.y and not q.scanned:
            skipped.append(key_of(p.x, p.y))
            print("[pioneer] contact at", p.x, ",", p.y, "needs a different scanner — skipping")
    return "ok"


# ----------------------------------------------------------------- mine ----

def best_site(wanted):
    # Highest-value mineable site in reach, given what the base is short of.
    #
    # Score is purity over distance, tilted by demand. weight_of() grows with
    # the units outstanding and is capped, so a large shortfall outranks a
    # token one without letting demand override distance entirely. An ore
    # nobody asked for is deprioritised (0.35) but never excluded, so the
    # rover keeps working when the factory is quiet.
    if not has_drill:
        return None
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
        score = score * weight_of(wanted, site.item_id)
        if best == None or score > best_score:
            best = site
            best_score = score
    return best


def mine_at(site):
    publish("mining", site.item_id)
    result = drive_to(site.x, site.y, False)
    if result != "ok":
        return result
    mined = 0
    while not self.cargo.full():
        if not can_afford_to_be_here() or self.is_being_rescued():
            break
        dig = self.drill.mine()
        if dig.status != "ok":
            print("[pioneer] mine:", dig.message)
            break
        mined = mined + 1
        learn_cost()
    print("[pioneer] mined", mined, "x", site.item_id, "at", site.name)
    return "ok"


# ------------------------------------------------------------------ loop ----

idle_note = ""

while True:
    learn_cost()

    if self.is_being_rescued():
        publish("rescued", self.rescue_status())
        sleep(5)
        continue

    # Bring cargo home. Build kits ride along; unload() returns them to
    # storage, and build() reloads only what its job needs.
    if self.cargo.full() or (self.cargo.count() > 0 and at_home()):
        if not at_home():
            go_home()
            continue
        unload()
        if self.cargo.count() > 0:
            sleep(30)
            continue

    if at_home() and self.battery.level() < CHARGE_TO:
        publish("charging", str(round(self.battery.level(), 2)))
        sleep(5)
        continue

    if not at_home() and not can_afford_to_be_here():
        go_home()
        continue

    job = next_job()
    if job != None:
        idle_note = ""
        result = build(job)
        if result == "need_kit":
            go_home()
        elif result == "low_battery" or result == "stuck":
            go_home()
        elif result == "no_kit" or result == "execute_failed":
            sleep(10)
        continue

    # Demand decides the order of the next two blocks. With an order
    # outstanding, mining it is the job and scouting is what we do when
    # nothing is minable. With nothing asked for, the reverse: go and find
    # sites now, so the next order starts with somewhere to dig.
    # The controller sees the whole base, so its ore priority wins when it
    # is running. Falling back to the factory channels keeps the rover
    # working exactly as before when no controller is publishing.
    wanted = mine_targets()
    if not has_demand(wanted):
        wanted = ore_demand(WANTED_ITEMS)

    # A scout never mines, however loud the demand: that is the point of
    # assigning the role. Otherwise demand decides, as before.
    role = my_role()
    may_explore = allows("exploration") or role == "scout"
    if role == "scout":
        mine_first = False
    else:
        mine_first = has_demand(wanted) and allows("mining")

    if mine_first:
        site = best_site(wanted)
        if site != None:
            idle_note = ""
            result = mine_at(site)
            if result == "low_battery" or result == "stuck":
                go_home()
            continue

    contact = next_contact() if may_explore else None
    if contact != None and can_afford_trip(contact.x, contact.y):
        idle_note = ""
        result = explore(contact)
        if result == "low_battery" or result == "stuck":
            go_home()
        continue

    if not mine_first:
        site = best_site(wanted)
        if site != None:
            idle_note = ""
            result = mine_at(site)
            if result == "low_battery" or result == "stuck":
                go_home()
            continue

    if not at_home():
        go_home()
        continue

    if role == "scout":
        report_outposts()
    if idle_note != "idle":
        print("[pioneer] no jobs, contacts, or mineable sites in reach — idle at home")
        idle_note = "idle"
    publish("idle", "")
    sleep(60)
