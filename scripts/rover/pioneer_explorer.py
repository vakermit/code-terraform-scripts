# =============================================================================
#  PIONEER EXPLORER  —  paste into the script slot of  pioneer_1
#  Survey-only mode that pushes OUTWARD into new biomes. No mining, no
#  building. Swap back to pioneer_1.py when the map is known.
# =============================================================================
#
#  Why a separate script: the rover's loop takes the NEAREST unscanned
#  contact every time, so it surveys a ring around home and never leaves
#  the home biome before the battery says turn back. This one ranks
#  contacts by biome first — anything outside the home biome, or in
#  EXPLORE_BIOME if set — and chains contact to contact from wherever it
#  is, only heading home when the battery model says the next hop plus
#  the return would not fit.
#
#  It also tells you WHY the map is empty. At startup and whenever it idles
#  it prints a census: unscanned contacts per biome, the nearest one, and
#  whether it is inside one-way range. Contacts whose survey fails for
#  sonar tier are counted separately, so "need Wide Sonar" and "need more
#  battery" are distinguishable in the log.
# =============================================================================

from util import key_of

EXPLORE_BIOME = ""         # "" = any biome that is not home; or e.g. "coastal"
CRUISE = 0.6
ARRIVE_M = 2
RESERVE_FRACTION = 0.12
LEVEL_FLOOR = 0.15
CHARGE_TO = 0.95
WH_PER_M_GUESS = 0.05
SAFETY = 1.4
TICK = 1
STUCK_TICKS = 20

nocturna = get_component("nocturna")
network = get_component("outpost_network")
comms = get_component("comms")

home = network.home()
home_biome = home.biome
home_x = home.x
home_y = home.y
for building in home.buildings("charging_station"):
    home_x = building.position[0]
    home_y = building.position[1]
    break

RESERVE_WH = max(10, self.battery.capacity() * RESERVE_FRACTION)
print("[explorer] pool", self.battery.capacity(), "Wh; sonar", self.sonar.tier(),
      self.sonar.range(), "m, hardness <=", self.sonar.hardness_limit())

skipped = []           # contacts sonar cannot resolve here (biomass etc.)
too_hard = []          # contacts whose survey failed on tier/hardness


def publish(state, detail):
    if comms == None:
        return
    status = {}
    status["state"] = state
    status["detail"] = detail
    status["battery"] = round(self.battery.level(), 2)
    status["cargo"] = self.cargo.count()
    comms.broadcast("pioneer.status", status)


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


def dist(x1, y1, x2, y2):
    dx = x1 - x2
    dy = y1 - y2
    return sqrt(dx * dx + dy * dy)


def wh_for(meters):
    return meters * cost["wh_per_m"] * SAFETY


def can_afford_to_be_here():
    if self.battery.level() < LEVEL_FLOOR:
        return False
    return self.battery.wh() > wh_for(self.nav.get_distance_to(home_x, home_y)) + RESERVE_WH


def can_afford_hop(x, y):
    there = wh_for(self.nav.get_distance_to(x, y))
    back = wh_for(dist(x, y, home_x, home_y))
    return self.battery.wh() > there + back + RESERVE_WH


def one_way_range():
    # Metres reachable from home on a full pool with the return kept.
    usable = self.battery.capacity() - RESERVE_WH
    return floor(usable / (cost["wh_per_m"] * SAFETY) / 2)


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


# --------------------------------------------------------------- census ----

def open_contacts():
    out = []
    for p in nocturna.points_of_interest():
        if p.scanned:
            continue
        k = key_of(p.x, p.y)
        if k in skipped or k in too_hard:
            continue
        out.append(p)
    return out


def census():
    reach = one_way_range()
    print("[explorer] census — one-way range ~", reach, "m at",
          round(cost["wh_per_m"], 3), "Wh/m")
    per_biome = {}
    for p in nocturna.points_of_interest():
        b = nocturna.biome_at(p.x, p.y)
        if not per_biome.has(b):
            row = {}
            row["scanned"] = 0
            row["open"] = 0
            row["nearest"] = -1
            per_biome[b] = row
        row = per_biome[b]
        if p.scanned:
            row["scanned"] = row["scanned"] + 1
        else:
            row["open"] = row["open"] + 1
            d = dist(p.x, p.y, home_x, home_y)
            if row["nearest"] < 0 or d < row["nearest"]:
                row["nearest"] = d
    for b in per_biome.keys():
        row = per_biome[b]
        note = ""
        if row["open"] > 0:
            if row["nearest"] > reach:
                note = "OUT OF RANGE — more battery or an outpost closer"
            else:
                note = "in range"
        print("[explorer]  ", b, "- scanned", row["scanned"], "open", row["open"],
              "nearest open", floor(row["nearest"]), "m", note)
    if len(too_hard) > 0:
        print("[explorer]  ", len(too_hard), "contacts refused survey — need a higher sonar tier")


# ----------------------------------------------------------------- pick ----

def wanted_biome(b):
    if EXPLORE_BIOME != "":
        return b == EXPLORE_BIOME
    return b != home_biome


# A sweep covers sonar.range() around the vehicle. Contacts that fit inside
# one sweep share a HUB: drive to their centroid once, scan once, survey
# them all. The margin keeps every member comfortably inside the circle.
SWEEP = self.sonar.range() * 0.85


def within(cx, cy, contacts, r):
    out = []
    for p in contacts:
        if dist(p.x, p.y, cx, cy) <= r:
            out.append(p)
    return out


def centroid(contacts):
    sx = 0
    sy = 0
    for p in contacts:
        sx = sx + p.x
        sy = sy + p.y
    return [sx / len(contacts), sy / len(contacts)]


def signature(contacts):
    keys = []
    for p in contacts:
        keys.append(key_of(p.x, p.y))
    keys.sort()
    return ",".join(keys)


def hubs(contacts):
    # Every open contact seeds a hub; the centroid is refined until its
    # membership stops changing, then duplicates collapse.
    seen = {}
    out = []
    for seed in contacts:
        group = within(seed.x, seed.y, contacts, SWEEP)
        c = [seed.x, seed.y]
        for step in range(6):
            c = centroid(group)
            regrouped = within(c[0], c[1], contacts, SWEEP)
            if signature(regrouped) == signature(group):
                break
            group = regrouped
        # Snap to a member if the centroid drifted outside the planet.
        if not nocturna.contains(c[0], c[1]):
            c = [group[0].x, group[0].y]
        key = signature(group)
        if seen.has(key):
            continue
        seen[key] = True
        hub = {}
        hub["x"] = c[0]
        hub["y"] = c[1]
        hub["members"] = group
        out.append(hub)
    return out


def next_hub():
    # Best hub from where the Pioneer is NOW. Each new-biome contact is
    # worth 20, each other contact 1, minus distance; must fit hop+return.
    best = None
    best_score = 0
    for hub in hubs(open_contacts()):
        if not can_afford_hop(hub["x"], hub["y"]):
            continue
        score = -self.nav.get_distance_to(hub["x"], hub["y"]) / 100
        for p in hub["members"]:
            if wanted_biome(nocturna.biome_at(p.x, p.y)):
                score = score + 20
            else:
                score = score + 1
        if best == None or score > best_score:
            best = hub
            best_score = score
    return best


def survey_hub(hub):
    # One scan covers every member; survey whatever it found.
    sweep = self.sonar.scan()
    if sweep.status != "ok":
        print("[explorer] scan:", sweep.message)
        for p in hub["members"]:
            skipped.append(key_of(p.x, p.y))
        return
    refused = False
    for site in sweep.sites:
        if site.surveyed:
            continue
        result = self.sonar.survey(site)
        if result.status == "ok":
            s = result.site
            print("[explorer] surveyed", s.name, "-", s.kind(), "-",
                  nocturna.biome_at(s.x, s.y))
        else:
            if result.status == "tier_too_low" or result.status == "too_hard":
                refused = True
            print("[explorer] survey", site.name, "-", result.message)

    # Members still unscanned after the sweep will not resolve from here.
    still_open = 0
    for p in hub["members"]:
        for q in nocturna.points_of_interest():
            if q.x == p.x and q.y == p.y and not q.scanned:
                still_open = still_open + 1
                if refused:
                    too_hard.append(key_of(p.x, p.y))
                else:
                    skipped.append(key_of(p.x, p.y))
    print("[explorer] hub done:", len(hub["members"]) - still_open, "of",
          len(hub["members"]), "contacts resolved")


# ------------------------------------------------------------------ loop ----

census()
reported = False

while True:
    learn_cost()

    if self.is_being_rescued():
        publish("rescued", self.rescue_status())
        sleep(5)
        continue

    if at_home() and self.battery.level() < CHARGE_TO:
        publish("charging", str(round(self.battery.level(), 2)))
        sleep(5)
        continue

    if not at_home() and not can_afford_to_be_here():
        publish("returning", "")
        drive_to(home_x, home_y, True)
        continue

    hub = next_hub()
    if hub == None:
        if not at_home():
            publish("returning", "")
            drive_to(home_x, home_y, True)
            continue
        if not reported:
            print("[explorer] nothing reachable from home — idle")
            census()
            reported = True
        publish("idle", "")
        sleep(60)
        continue

    reported = False
    publish("exploring", str(len(hub["members"])) + " contacts")
    print("[explorer] hub at", round(hub["x"]), ",", round(hub["y"]), "-",
          len(hub["members"]), "contacts in one sweep,",
          round(self.nav.get_distance_to(hub["x"], hub["y"])), "m away")
    result = drive_to(hub["x"], hub["y"], False)
    if result == "ok":
        survey_hub(hub)
    elif result == "low_battery" or result == "stuck":
        drive_to(home_x, home_y, True)
