# CONTRACT: lattice
# Minesweeper, 32 x 32. probe(x, y) on a clear cell returns how many of
# its 8 neighbours are volatile nodes. Probing a node trips the lattice
# and nothing more can be probed until reset() — so probe only cells that
# deduction has PROVEN clear. Answer: a row-major list of 1024 flags,
# 1 for node, 0 for clear.
#
# Deduction, in order of cost:
#   1. probe every proven-clear cell that has no reading yet
#   2. single-cell rule: a reading equal to its known nodes clears the rest;
#      a reading equal to its unknowns marks them all as nodes
#   3. subset rule: if one cell's unknowns are a subset of a neighbour's,
#      the difference in readings resolves the cells outside the subset
#   4. when all of that stalls, probe the unknown cell with the lowest
#      estimated node chance; a trip is recorded as a node and reset()
#      lets the search continue — the flag list still comes out right
#      because a tripped cell IS a node.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[lattice] transmitter:", link.message)

grid = self.contract.grid
W = grid.width()
H = grid.height()
N = W * H

UNKNOWN = 0
CLEAR = 1
NODE = 2

# neighbours[i] = list of the up to 8 cells around cell i
neighbours = []
for i in range(N):
    x = i % W
    y = i // W
    around = []
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            if dx == 0 and dy == 0:
                continue
            nx = x + dx
            ny = y + dy
            if nx >= 0 and nx < W and ny >= 0 and ny < H:
                around.append(ny * W + nx)
    neighbours.append(around)

state = []
reading = []      # -1 until probed
for i in range(N):
    state.append(UNKNOWN)
    reading.append(-1)

start = grid.start()
state[start[1] * W + start[0]] = CLEAR

trips = 0
guesses = 0


def split(i):
    # Known-node count and unknown-cell list around cell i.
    nodes = 0
    unknown = []
    for j in neighbours[i]:
        if state[j] == NODE:
            nodes = nodes + 1
        elif state[j] == UNKNOWN:
            unknown.append(j)
    result = {}
    result["nodes"] = nodes
    result["unknown"] = unknown
    return result


def probe(i):
    # Probe one cell. Returns True if the lattice state changed.
    hit = grid.probe(i % W, i // W)
    if hit.status == "ok":
        reading[i] = hit.reading
        state[i] = CLEAR
        return True
    # node_tripped / lattice_tripped: the cell was a node after all.
    state[i] = NODE
    reset = grid.reset()
    if reset.status != "ok":
        print("[lattice] reset:", reset.message)
    return True


def probe_clear_cells():
    did = False
    for i in range(N):
        if state[i] == CLEAR and reading[i] < 0:
            probe(i)
            did = True
    return did


def single_cell_rule():
    did = False
    for i in range(N):
        if reading[i] < 0:
            continue
        s = split(i)
        unknown = s["unknown"]
        if len(unknown) == 0:
            continue
        need = reading[i] - s["nodes"]
        if need == 0:
            for j in unknown:
                state[j] = CLEAR
            did = True
        elif need == len(unknown):
            for j in unknown:
                state[j] = NODE
            did = True
    return did


def subset_rule():
    did = False
    for a in range(N):
        if reading[a] < 0:
            continue
        sa = split(a)
        ua = sa["unknown"]
        if len(ua) == 0:
            continue
        need_a = reading[a] - sa["nodes"]

        # Any read cell within 2 steps can share unknowns with a.
        ax = a % W
        ay = a // W
        for dy in [-2, -1, 0, 1, 2]:
            for dx in [-2, -1, 0, 1, 2]:
                if dx == 0 and dy == 0:
                    continue
                bx = ax + dx
                by = ay + dy
                if bx < 0 or bx >= W or by < 0 or by >= H:
                    continue
                b = by * W + bx
                if reading[b] < 0:
                    continue
                sb = split(b)
                ub = sb["unknown"]
                if len(ub) <= len(ua):
                    continue
                is_subset = True
                for c in ua:
                    if c not in ub:
                        is_subset = False
                        break
                if not is_subset:
                    continue

                need_b = reading[b] - sb["nodes"]
                outside = []
                for c in ub:
                    if c not in ua:
                        outside.append(c)
                diff = need_b - need_a
                if diff == 0:
                    for c in outside:
                        state[c] = CLEAR
                    did = True
                elif diff == len(outside):
                    for c in outside:
                        state[c] = NODE
                    did = True
    return did


def safest_guess():
    # Unknown cell with the lowest node probability, estimated from the
    # constraints touching it. Cells touching no constraint get the global
    # density estimate.
    best = -1
    best_risk = 2
    for i in range(N):
        if state[i] != UNKNOWN:
            continue
        risk = -1
        for j in neighbours[i]:
            if reading[j] < 0:
                continue
            s = split(j)
            unknown = s["unknown"]
            if len(unknown) == 0:
                continue
            local = (reading[j] - s["nodes"]) / len(unknown)
            if local > risk:
                risk = local
        if risk < 0:
            risk = 0.2
        if risk < best_risk:
            best_risk = risk
            best = i
    return best


# ------------------------------------------------------------------ solve --

while True:
    if probe_clear_cells():
        continue
    if single_cell_rule():
        continue
    if subset_rule():
        continue

    remaining = 0
    for i in range(N):
        if state[i] == UNKNOWN:
            remaining = remaining + 1
    if remaining == 0:
        break

    pick = safest_guess()
    if pick < 0:
        break
    guesses = guesses + 1
    probe(pick)
    if state[pick] == NODE:
        trips = trips + 1

nodes = 0
flags = []
for i in range(N):
    if state[i] == NODE:
        flags.append(1)
        nodes = nodes + 1
    else:
        flags.append(0)

print("[lattice]", nodes, "nodes mapped;", guesses, "guesses,", trips, "trips")
sent = transmitter.transmit(self.contract.id, flags)
print("[lattice]", sent.status, "-", sent.message)
