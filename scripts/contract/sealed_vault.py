# CONTRACT: sealed_vault
# A square maze from (0, 0) to (size-1, size-1). Depth-first search with a
# backtrack stack. Whether a move succeeded is read from the position
# before and after the call — the only signal that cannot lie, whatever
# the result's status string says.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[vault] transmitter:", link.message)

vault = self.contract.vault
size = vault.size
print("[vault]", size, "x", size, "maze")

DIRS = ["east", "south", "west", "north"]
BACK = {"east": "west", "west": "east", "south": "north", "north": "south"}


def here():
    p = vault.position
    return str(p.row) + "," + str(p.col)


def at_exit():
    p = vault.position
    return p.row == size - 1 and p.col == size - 1


def step(direction):
    # True if the vault actually moved.
    before = here()
    vault.move(direction)
    return here() != before


visited = {}
visited[here()] = True
trail = []       # direction to step to return to the previous cell
moves = 0

while not at_exit():
    advanced = False
    for d in DIRS:
        if step(d):
            moves = moves + 1
            if visited.has(here()):
                # Already explored — step straight back and try the next.
                step(BACK[d])
                moves = moves + 1
            else:
                visited[here()] = True
                trail.append(BACK[d])
                advanced = True
                break

    if advanced:
        continue

    if len(trail) == 0:
        print("[vault] no unexplored path and nothing to backtrack — stuck")
        break
    step(trail.pop())
    moves = moves + 1

print("[vault] at", here(), "after", moves, "moves,", len(visited), "cells seen")

result = vault.escape()
if result.status == "ok":
    print("[vault] key:", result.key)
    sent = transmitter.transmit(self.contract.id, result.key)
    print("[vault]", sent.status, "-", sent.message)
else:
    print("[vault] escape:", result.message)
