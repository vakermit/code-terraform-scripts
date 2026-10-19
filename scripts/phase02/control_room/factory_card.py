# CONTROL ROOM CARD — Manufacturing loop
# Best at 2x2 (big). Draws relative to width()/height() so 2x1 also works.
#
# Reads the factory scripts' telemetry off the Signal Bus:
#   factory.status.dock / .fabricator / .smelter, factory.targets,
#   dock.needs, factory.needs, factory.ore
# plus live bin levels from the home outpost. Nothing here commands a
# machine; it only reads.

from signals import field

comms = get_component("comms")
orders = get_component("orders")
commander = get_component("commander")
home = get_component("outpost_network").home()

ROW = 22


def latest(channel):
    if comms == None:
        return None
    return comms.latest(channel)


def dot_for(state):
    if state == "" or state == "idle" or state == "no-coverage":
        return "idle"
    if state == "waiting" or state == "blocked":
        return "paused"
    return "running"


def dict_line(d, limit):
    # {"a": 3, "b": 1} -> "a 3  b 1", trimmed to `limit` entries
    if d == None or len(d) == 0:
        return "-"
    parts = []
    for key in d.keys():
        if len(parts) >= limit:
            parts.append("...")
            break
        parts.append(key + " " + str(floor(d[key])))
    return "  ".join(parts)


def machine_block(x, y, w, title, status, extra_label, extra):
    # One machine: title, status dot + state, current recipe, an extra line.
    state = field(status, "state", "")
    panel.card(x, y, w, ROW * 4 + 8, title)
    panel.status_dot(x + 14, y + ROW + 6, 5, dot_for(state))
    panel.draw_text(x + 26, y + ROW + 6, state + "  " + str(field(status, "detail", "")), 12, "text-bright")
    panel.draw_text(x + 12, y + ROW * 2 + 6, "recipe: " + str(field(status, "recipe", "-")), 11, "text-secondary")
    panel.draw_text(x + 12, y + ROW * 3 + 6, extra_label + " " + extra, 11, "text-muted")


while True:
    panel.clear()
    W = panel.width()
    H = panel.height()
    col = (W - 24) / 2

    panel.label(12, 18, "MANUFACTURING LOOP", "caption")
    panel.draw_text(W - 150, 18, str(floor(commander.get_credits())) + " cr", 12, "text-value")

    # --- row 1: dock + fabricator ------------------------------------------
    dock = latest("factory.status.dock")
    order_line = str(field(dock, "order", "no order"))
    owed = field(dock, "owed", 0)
    loaded = field(dock, "loaded", 0)
    y = 30
    panel.card(12, y, col, ROW * 4 + 8, "SUPPLY DOCK")
    panel.status_dot(26, y + ROW + 6, 5, dot_for(field(dock, "state", "")))
    panel.draw_text(38, y + ROW + 6, order_line, 12, "text-bright")
    panel.draw_text(24, y + ROW * 2 + 6, "dispatching: " + str(field(dock, "dispatching", "-")), 11, "text-secondary")
    panel.draw_text(24, y + ROW * 3 + 6, "loaded " + str(loaded) + " / owed " + str(owed), 11, "text-muted")
    if owed > 0:
        panel.progress_bar(col - 110, y + ROW + 1, 110, 8, loaded / owed, "accent")

    fab = latest("factory.status.fabricator")
    machine_block(24 + col, y, col, "FABRICATOR", fab,
                  "needs:", dict_line(latest("factory.needs"), 3))

    # --- row 2: smelter + targets ------------------------------------------
    y = y + ROW * 4 + 16
    smelt = latest("factory.status.smelter")
    machine_block(12, y, col, "SMELTER", smelt,
                  "ore short:", dict_line(latest("factory.ore"), 3))
    prog = field(smelt, "progress", 0)
    panel.progress_bar(12 + col - 110, y + ROW + 1, 110, 8, prog, "success")

    panel.card(24 + col, y, col, ROW * 4 + 8, "TARGETS")
    panel.draw_text(36 + col, y + ROW + 6, "operator: " + dict_line(latest("factory.targets"), 3), 11, "text-bright")
    panel.draw_text(36 + col, y + ROW * 2 + 6, "dock:     " + dict_line(latest("dock.needs"), 3), 11, "text-secondary")
    open_orders = len(orders.list_orders())
    weekly = 0
    for o in orders.list_weekly_orders():
        if o.status == "active":
            weekly = weekly + 1
    panel.draw_text(36 + col, y + ROW * 3 + 6, "earth orders open: " + str(open_orders) + " campaign, " + str(weekly) + " weekly", 11, "text-muted")

    # --- row 3: storage bins (fills whatever height is left) ---------------
    y = y + ROW * 4 + 16
    if y + ROW * 2 < H:
        panel.card(12, y, W - 24, H - y - 8, "STORAGE BINS")
        by = y + ROW + 2
        bx = 24
        for ref in home.buildings("storage_bin"):
            if by > H - 16:
                break
            b = get_component(ref.id)
            material = b.get_material()
            if material == "":
                material = "(empty)"
            fill = b.fill_percent()
            color = "accent"
            if fill > 0.9:
                color = "warning"
            panel.draw_text(bx, by + 4, material, 11, "text-secondary")
            panel.progress_bar(bx + 150, by, 120, 8, fill, color)
            panel.draw_text(bx + 280, by + 4, str(floor(b.count(b.get_material()))), 11, "text-muted")
            by = by + ROW
            if by > H - 16 and bx == 24 and W > 700:
                # second column on wide cards
                bx = 24 + (W - 24) / 2
                by = y + ROW + 2
