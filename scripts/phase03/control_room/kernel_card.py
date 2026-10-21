# =============================================================================
#  CONTROL ROOM CARD — Kernel
#  What is available, who got it, and why. Best at 2x2.
# =============================================================================
#
#  A VIEW, AND NOTHING ELSE. This card issues no command: no breaker, no
#  lease, no recipe, not even a shop purchase. Every number on it is read
#  from the bus or the Archive, and the only thing it writes is pixels. A
#  card is allowed to command shared authorities, which is exactly why the
#  restraint has to be deliberate — two things deciding who gets the water
#  is one thing too many, and the one that decides should be the one that
#  can still think when this page is closed.
#
#  WHAT IT IS FOR. Four loops allocating from a learned model cannot be
#  debugged by a breakpoint, because no single script holds the decision. So
#  this card answers one question — why is that machine doing that — out of
#  the envelope, the allocation and the merged decision trace. It is the only
#  reason the model can be improved rather than merely trusted.
#
#  READS DEGRADE. Any of comms, notebook or the clock can be absent, and the
#  card says so in place of the panel it cannot fill rather than going blank
#  or raising. A card that dies takes the view away exactly when something
#  has gone wrong enough to need looking at.
#
#  Drawn relative to width() and height(), so 2x1 degrades to the envelope
#  and the trace without the allocation table.
# =============================================================================

from bus import ALLOC, ENV, SHED, envelope
from capability import network
from trace import merged, render

LOOPS = ["safety", "plan", "logi", "opp"]
ROW = 16
MUTED = "text-muted"
DIM = "text-secondary"


def bus_latest(channel):
    """A broadcast value with no freshness opinion. The card shows what IS."""
    comms = get_component("comms")
    if comms == None:
        return None
    return comms.latest(channel)


def home_id():
    net = network()
    if net == None:
        return ""
    home = net.home()
    if home == None:
        return ""
    return home.id


def draw_envelope(y, w):
    """Capacity: what safety says is spendable right now."""
    env = envelope()
    if env == None:
        stale = bus_latest(ENV)
        if stale == None:
            panel.draw_text(12, y, "no envelope: safety has never published", 12, MUTED)
        else:
            panel.draw_text(12, y, "envelope stale — safety is not running", 12, "warning")
        return y + ROW

    watts = env["watts_free"] if env.has("watts_free") else 0
    autonomy = env["autonomy_h"] if env.has("autonomy_h") else -1
    panel.draw_text(12, y, "free " + str(round(watts)) + " W", 12, "text-bright")
    if autonomy < 0:
        panel.draw_text(110, y, "generating surplus", 12, DIM)
    else:
        colour = "error" if autonomy < 2 else "success"
        panel.draw_text(110, y, str(round(autonomy, 1)) + " h autonomy", 12, colour)
    y = y + ROW

    # Supply, with unmeasured shown as unmeasured rather than as zero: the
    # difference drives the planner's fail-open and belongs on the card.
    for field in ("tonnes", "stock"):
        if not env.has(field):
            continue
        supply = env[field]
        if len(supply) == 0:
            panel.draw_text(12, y, field + ": unmeasured", 11, MUTED)
            y = y + ROW
            continue
        parts = []
        for key in supply:
            parts.append(key + " " + str(round(supply[key], 1)))
        panel.draw_text(12, y, field + ": " + ", ".join(parts), 11, DIM)
        y = y + ROW
    return y


def draw_allocation(y, w):
    """Distribution: who the planner gave what, worst-ranked first to cut."""
    payload = bus_latest(ALLOC + home_id())
    if payload == None or not payload.has("machines"):
        panel.draw_text(12, y, "no allocation published", 12, MUTED)
        return y + ROW

    machines = payload["machines"]
    shed = bus_latest(SHED)
    order = shed if shed != None else []

    rows = []
    for machine_id in machines:
        grant = machines[machine_id]
        rank = grant["rank"] if grant.has("rank") else 999
        amount = "run" if grant.has("run") else ""
        for key in grant:
            if key in ("rank", "hour", "unmeasured", "run"):
                continue
            amount = key + " " + str(round(grant[key], 1))
        if grant.has("unmeasured"):
            amount = amount + " ?"
        rows.append({"id": machine_id, "rank": rank, "amount": amount})

    for row in sorted(rows, key=lambda r: r["rank"]):
        cut_first = len(order) > 0 and order[0] == row["id"]
        panel.status_dot(14, y + 4, 4, "bad" if cut_first else "good")
        panel.draw_text(26, y, str(row["rank"]) + ". " + row["id"], 12)
        panel.draw_text(w - 120, y, row["amount"], 12, DIM)
        y = y + ROW
        if y > panel.height() - 60:
            break
    return y


def draw_trace(y, w):
    """Why: the merged decision trail, newest last, from every loop."""
    rows = merged(LOOPS)
    if len(rows) == 0:
        panel.draw_text(12, y, "no decisions recorded yet", 12, MUTED)
        return
    room = int((panel.height() - y - 8) / ROW)
    if room < 1:
        return
    for row in rows[0 - room:]:
        held = ""
        if row.has("last_h"):
            held = "  (since h" + str(row["h"]) + ")"
        panel.draw_text(12, y, row["loop"] + "  " + render(row) + held, 11, DIM)
        y = y + ROW


while True:
    panel.clear()
    w = panel.width()
    panel.label(12, 20, "KERNEL", "caption")

    y = 40
    y = draw_envelope(y, w) + 4
    panel.divider(12, y, w - 12, y)
    y = y + 10

    if w > 320:
        y = draw_allocation(y, w) + 4
        panel.divider(12, y, w - 12, y)
        y = y + 10

    draw_trace(y, w)
    sleep(0.5)
