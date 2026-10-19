# CONTROL ROOM CARD — Fleet
# Best at 2x1 (wide) or 2x2. One row per ground vehicle: status dot, name,
# what the vehicle is physically doing, what its script says it is doing,
# distance from home, cargo, battery. Charging station queue underneath.
#
# Physical activity comes from fleet.vehicles() and the live vehicle;
# script intent comes from the rover.status / pioneer.status broadcasts.

from signals import field

fleet = get_component("fleet")
comms = get_component("comms")
home = get_component("outpost_network").home()

ROW = 26

station = None
for ref in home.buildings("charging_station"):
    station = get_component(ref.id)
    break


def latest(channel):
    if comms == None:
        return None
    return comms.latest(channel)


def dot_for(v, script_state):
    if v.is_being_rescued:
        return "error"
    if v.battery_level < 0.15 and not v.is_docked:
        return "paused"
    if script_state == "idle" or script_state == "":
        return "idle"
    return "running"


def battery_color(level):
    if level < 0.2:
        return "error"
    if level < 0.4:
        return "warning"
    return "success"


def distance_home(v):
    dx = v.x - home.x
    dy = v.y - home.y
    return floor(sqrt(dx * dx + dy * dy))


while True:
    panel.clear()
    W = panel.width()
    H = panel.height()

    panel.label(12, 18, "FLEET", "caption")
    y = 30

    # column anchors, relative so the card reflows at any span
    c_name = 34
    c_phys = W * 0.22
    c_script = W * 0.40
    c_dist = W * 0.62
    c_cargo = W * 0.71
    c_batt = W * 0.82

    panel.draw_text(c_phys, y, "vehicle", 10, "text-muted")
    panel.draw_text(c_script, y, "script", 10, "text-muted")
    panel.draw_text(c_dist, y, "home", 10, "text-muted")
    panel.draw_text(c_cargo, y, "cargo", 10, "text-muted")
    panel.draw_text(c_batt, y, "battery", 10, "text-muted")
    y = y + 16

    for v in fleet.vehicles():
        if y > H - ROW * 2:
            break

        telemetry = latest(v.kind + ".status")
        script_state = str(field(telemetry, "state", ""))
        detail = str(field(telemetry, "detail", ""))
        if detail != "":
            script_state = script_state + " " + detail

        live = get_component(v.id)
        physical = v.status
        if v.is_being_rescued:
            physical = "rescue " + v.rescue_status
        elif v.is_docked:
            physical = "docked"

        cargo_text = "-"
        if live != None:
            cargo_text = str(live.cargo.count()) + "/" + str(live.cargo.capacity())

        panel.status_dot(20, y + 6, 5, dot_for(v, script_state))
        panel.draw_text(c_name, y + 6, v.name, 12, "text-bright")
        panel.draw_text(c_phys, y + 6, physical, 11, "text-secondary")
        panel.draw_text(c_script, y + 6, script_state[0:28], 11, "text-secondary")
        panel.draw_text(c_dist, y + 6, str(distance_home(v)) + " m", 11, "text-muted")
        panel.draw_text(c_cargo, y + 6, cargo_text, 11, "text-muted")
        panel.progress_bar(c_batt, y + 1, W - c_batt - 44, 9, v.battery_level, battery_color(v.battery_level))
        panel.draw_text(W - 40, y + 6, str(floor(v.battery_level * 100)) + "%", 10, "text-value")
        y = y + ROW

    # --- charging station ------------------------------------------------
    if station != None and y + ROW < H:
        panel.divider(12, y + 4, W - 12, y + 4)
        y = y + 12
        active = station.get_active()
        queue = station.get_queue()
        text = "station: " + str(len(active)) + "/" + str(station.get_bay_count()) + " bays"
        if len(active) > 0:
            text = text + "  charging " + ", ".join(active)
        if len(queue) > len(active):
            text = text + "  queued " + str(len(queue) - len(active))
        panel.draw_text(20, y + 6, text, 11, "text-secondary")
