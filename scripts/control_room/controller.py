# =============================================================================
#  CONTROL ROOM CARD — Central controller
#  Best at 2x2. Draws relative to width()/height() so 2x1 degrades cleanly.
# =============================================================================
#
#  The one script that decides. Hardware actions are self-only, so this never
#  drives a machine directly: it reads the grid, picks an operating mode, and
#  broadcasts control.policy. Machine scripts read that policy and hold their
#  own discretionary work back.
#
#  WHAT IT OWNS
#    power       grid charge decides the mode, and the mode sheds subsystems
#                in increasing order of how much the base needs them
#    production  smelter / fabricator / supply dock, gated via policy
#    bio         collector / lab / exchange, the first discretionary thing cut
#    mining      pioneer, plus the ore priority it should favour
#
#  WHAT IT DOES NOT OWN
#    Atmosphere and sensors are life support and are never gated. Vehicle
#    rescue is never gated either: a stranded rover outranks any policy.
#
#  MANUAL OVERRIDE. The mode switch forces a mode and stops the automatic
#  decision. AUTO hands control back to the grid. An override is the operator
#  disagreeing with the policy, which should always win.
#
#  Publishing is deliberately rate-limited. Policy is a decision, not
#  telemetry, and rewriting it every tick would churn the bus for nothing.
# =============================================================================

from control import SUBSYSTEMS, decide, publish
from demand import ore_demand
from power import report, state
from signals import field

comms = get_component("comms")
power_control = get_component("power_control")
network = get_component("outpost_network")
home = network.home() if network != None else None

PUBLISH_EVERY = 0.25         # world-clock hours between policy writes
ROW = 20             # a 500x200 card fits ten rows; four go to subsystems
MODES = ["AUTO", "normal", "conserve", "emergency"]

# Role assignments, machine id -> role. Capability is the machine's own
# business: a rover told to scout without sonar falls back to auto rather
# than idling, so an over-broad assignment here is harmless.
#
# To make a second pioneer the scout, fit it with sonar and add:
#     "pioneer_2": "scout"
# A miner and a scout want different targets, which is why this split needs
# no claim protocol: they never contend for the same site.
ROLES = {
    "pioneer_1": "auto",
}

last_hour = -99
last_mode = ""


def grid_anchor():
    # Policy is written for the home grid. Field outposts run their own.
    if home == None:
        return ""
    return home.id


def dot_for(mode_name):
    if mode_name == "emergency":
        return "bad"
    if mode_name == "conserve":
        return "warn"
    return "good"


def subsystem_rows(allow, y, w):
    # One row each, right-aligned pill. Stays inside a 500px column.
    for name in SUBSYSTEMS:
        on = allow.get(name, True)
        panel.status_dot(14, y, 4, "good" if on else "idle")
        panel.draw_text(28, y - 4, name, 12)
        panel.pill(w - 66, y - 6, "RUN" if on else "HOLD",
                   "success" if on else "text-muted", 11)
        y = y + ROW
    return y


while True:
    panel.clear()
    w = panel.width()

    choice = panel.combo("mode", 12, 8, 132, MODES, "AUTO", "mode")
    manual = choice != None and choice != "AUTO"

    s = state(grid_anchor())
    pct = s["pct"]

    if manual:
        # The operator disagreeing with the policy always wins.
        plan = decide(pct)
        plan["mode"] = choice
        if choice == "normal":
            plan["allow"] = decide(100)["allow"]
        elif choice == "conserve":
            plan["allow"] = decide(50)["allow"]
        else:
            plan["allow"] = decide(0)["allow"]
    else:
        plan = decide(pct)

    mine = ore_demand()

    # Publish on a change or on a slow heartbeat, never every tick.
    hour = 0
    clock = get_component("clock")
    if clock != None:
        hour = clock.get_day() * 24 + clock.get_time()[0]
    if plan["mode"] != last_mode or hour - last_hour >= PUBLISH_EVERY:
        if publish(comms, plan["mode"], pct, plan["allow"], mine, ROLES):
            last_mode = plan["mode"]
            last_hour = hour

    # ---- draw ---------------------------------------------------------------
    # Laid out for the 500x200 single card; a 2x2 just gets more slack. The
    # combo costs one row where a radio_group cost four, which is what made
    # the first version overlap itself.
    h = panel.height()

    panel.status_dot(w - 22, 18, 5, dot_for(plan["mode"]))
    label = plan["mode"].upper()
    if manual:
        label = label + " (manual)"
    panel.draw_text(156, 14, label, 13, "text-bright")

    panel.progress_bar(12, 44, w - 24, 10, pct / 100.0)
    panel.draw_text(12, 60, report(grid_anchor()), 11, "text-secondary")

    panel.divider(12, 78, w - 12, 78)
    y = subsystem_rows(plan["allow"], 94, w)

    # Only a taller card has room for the ore list; the small one gets a count.
    if h >= 400:
        panel.divider(12, y + 2, w - 12, y + 2)
        if len(mine) > 0:
            panel.draw_text(12, y + 16, "mining priority", 12, "text-secondary")
            row = y + 16 + ROW
            for ore in mine.keys():
                panel.draw_text(28, row, ore + "  x" + str(int(mine[ore])), 12)
                row = row + ROW
        else:
            panel.draw_text(12, y + 16, "no ore demand - rover scouts", 12,
                            "text-muted")
    else:
        note = "scouting"
        if len(mine) > 0:
            note = str(len(mine)) + " ore wanted"
        roles = []
        for rid in ROLES.keys():
            if ROLES[rid] != "auto":
                roles.append(rid + ":" + ROLES[rid])
        if len(roles) > 0:
            note = note + "  |  " + ", ".join(roles)
        panel.draw_text(12, y + 2, note, 11, "text-muted")

    sleep(1)
