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
ROW = 22
MODES = ["AUTO", "normal", "conserve", "emergency"]

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


def subsystem_rows(allow, y):
    for name in SUBSYSTEMS:
        on = allow.get(name, True)
        panel.status_dot(12, y, 5, "good" if on else "idle")
        panel.draw_text(28, y, name)
        panel.pill(panel.width() - 70, y, "RUN" if on else "HOLD")
        y = y + ROW
    return y


while True:
    panel.clear()
    w = panel.width()

    choice = panel.radio_group("mode", 12, 8, MODES, "AUTO")
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
        if publish(comms, plan["mode"], pct, plan["allow"], mine):
            last_mode = plan["mode"]
            last_hour = hour

    # ---- draw ---------------------------------------------------------------
    panel.card(8, 34, w - 16, 52, "GRID")
    panel.status_dot(20, 52, 5, dot_for(plan["mode"]))
    panel.draw_text(36, 52, plan["mode"].upper() + ("  (manual)" if manual else ""))
    panel.progress_bar(20, 70, w - 40, 12, pct / 100.0)
    panel.draw_text(20, 96, report(grid_anchor()))

    y = subsystem_rows(plan["allow"], 122)

    if len(mine) > 0:
        panel.divider(12, y + 4, w - 12, y + 4)
        panel.draw_text(12, y + 16, "mining priority")
        row = y + 16 + ROW
        for ore in mine.keys():
            panel.draw_text(28, row, ore + "  x" + str(int(mine[ore])))
            row = row + ROW
    else:
        panel.draw_text(12, y + 16, "no ore demand - rover scouts")

    sleep(1)
