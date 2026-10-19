# =============================================================================
#  scout  —  where to look next, and where a base should go
# =============================================================================
#
#  Two clustering problems that look different and are the same shape.
#
#  HUBS. A sonar sweep covers a radius, so contacts that fit inside one sweep
#  should cost one drive and one scan, not one each. Taking the nearest
#  contact every time surveys a ring around home and never leaves the home
#  biome; ranking whole hubs by what they contain pushes outward instead.
#
#  OUTPOST CLUSTERS. Sites within pipe range of each other share one outpost.
#  Same algorithm, different radius and scoring: a one-cluster k-means from
#  every seed, refined until the membership stops moving, then duplicates
#  collapsed by membership signature.
#
#  `self` does not exist in a library, so callers pass their `nav` component
#  for distances and the planet for biome lookups.
# =============================================================================

from util import key_of

MAX_REFINE = 6

# What a site contributes to an outpost's worth. Water and thermal unlock the
# most downstream machinery; inert rock unlocks nothing.
KIND_VALUE = {"water": 4, "thermal": 4, "exotic": 3, "oil": 2, "mineral": 1, "inert": 0}
PURITY_BONUS = {"standard": 0, "rich": 1, "pure": 2}
BIOME_BONUS = 6
HOME_PENALTY = 4


def distance(x1, y1, x2, y2):
    dx = x1 - x2
    dy = y1 - y2
    return (dx * dx + dy * dy) ** 0.5


def within(cx, cy, points, radius):
    """Every point inside `radius` of (cx, cy)."""
    out = []
    for p in points:
        if distance(p.x, p.y, cx, cy) <= radius:
            out.append(p)
    return out


def centroid(points):
    sx = 0
    sy = 0
    for p in points:
        sx = sx + p.x
        sy = sy + p.y
    return [sx / len(points), sy / len(points)]


def signature(points):
    """Membership identity, so two seeds that converge collapse to one cluster."""
    keys = []
    for p in points:
        keys.append(key_of(p.x, p.y))
    keys.sort()
    return ",".join(keys)


def cluster(points, radius, planet=None):
    """Group `points` into clusters of `radius`, as [{x, y, members}].

    Every point seeds a cluster whose centre is refined until its membership
    stops changing. Identical memberships collapse. When `planet` is given, a
    centre that drifts off the map snaps back to a member, because an
    unreachable centroid is worse than an off-centre real one.
    """
    seen = {}
    out = []
    for seed in points:
        group = within(seed.x, seed.y, points, radius)
        c = [seed.x, seed.y]
        for step in range(MAX_REFINE):
            c = centroid(group)
            regrouped = within(c[0], c[1], points, radius)
            if signature(regrouped) == signature(group):
                break
            group = regrouped
        if planet != None and not planet.contains(c[0], c[1]):
            c = [group[0].x, group[0].y]
        key = signature(group)
        if seen.has(key):
            continue
        seen[key] = True
        item = {}
        item["x"] = c[0]
        item["y"] = c[1]
        item["members"] = group
        out.append(item)
    return out


# ------------------------------------------------------------------- surveying
def best_hub(points, radius, nav, planet, home_biome, target_biome="",
             affordable=None):
    """The sweep worth driving to next, or None.

    A contact in a new biome is worth far more than one more contact in the
    biome we are standing in, which is what stops the rover circling home.
    Distance is a mild penalty, not a veto: `affordable` already removed
    anything the battery cannot reach.
    """
    best = None
    best_score = 0
    for hub in cluster(points, radius, planet):
        if affordable != None and not affordable(hub["x"], hub["y"]):
            continue
        score = 0 - nav.get_distance_to(hub["x"], hub["y"]) / 100
        for p in hub["members"]:
            if wants_biome(planet.biome_at(p.x, p.y), home_biome, target_biome):
                score = score + 20
            else:
                score = score + 1
        if best == None or score > best_score:
            best = hub
            best_score = score
    return best


def wants_biome(biome, home_biome, target_biome=""):
    """True for a biome worth travelling to: the target, or anything not home."""
    if target_biome != "":
        return biome == target_biome
    return biome != home_biome


# --------------------------------------------------------------- base siting
def site_value(site):
    """What one surveyed site contributes to an outpost's worth."""
    value = KIND_VALUE.get(site.kind(), 0)
    if site.kind() == "mineral":
        value = value + PURITY_BONUS.get(site.purity, 0)
    return value


def score_outpost(spot, nav, planet, home_biome, target_biome="", max_range=1200):
    """Rank a candidate outpost location. Higher is better; 0 means unusable.

    Worth is what the cluster contains, plus a bonus for opening a new biome
    and a penalty for sitting in the one already served, minus the drive. A
    cluster past `max_range` scores 0: a base the Pioneer cannot reasonably
    reach is not a candidate however rich it is.
    """
    d = nav.get_distance_to(spot["x"], spot["y"])
    if d > max_range:
        return 0
    score = 0
    for site in spot["members"]:
        score = score + site_value(site)
    biome = planet.biome_at(spot["x"], spot["y"])
    if wants_biome(biome, home_biome, target_biome):
        score = score + BIOME_BONUS
    else:
        score = score - HOME_PENALTY
    score = score - d / 200
    if score < 0:
        return 0
    return score


def best_outposts(sites, radius, nav, planet, home_biome, target_biome="",
                  max_range=1200, top=5):
    """Candidate base locations, best first, as [{x, y, members, score}]."""
    scored = []
    for spot in cluster(sites, radius, planet):
        spot["score"] = score_outpost(spot, nav, planet, home_biome,
                                      target_biome, max_range)
        if spot["score"] > 0:
            scored.append(spot)
    scored = sorted(scored, key=lambda s: 0 - s["score"])
    return scored[:top]
