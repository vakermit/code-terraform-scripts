# =============================================================================
#  BIO EXCHANGE  —  paste into the script slot of  bio_exchange_1
#  Step 4 of the biology loop: sample -> order -> credits.
# =============================================================================
#
#  This is script 3 of 3, and it is the one that reads inventory hardest.
#
#  deliver() hands over one sample toward the ACTIVE order and nothing else,
#  so the only decision that matters here is which order to make active. A
#  naive script takes orders[0] and then blocks on "no_inventory" forever
#  while the Lab is busy extracting something a different order wanted.
#
#  So each pass scores every unfinished order against inventory:
#
#      ready     = samples held that this order can accept right now
#      remaining = samples this order still needs in total
#
#  and activates the order with the most ready samples, breaking ties toward
#  the one nearest completion (fewest remaining), then toward the bigger
#  reward. Credits arrive sooner and inventory slots are freed sooner, which
#  is what keeps the Lab from stalling on a full inventory.
#
#  If nothing is deliverable yet the script still parks an unfinished order
#  as the active goal, so the operator can see the target and so the first
#  sample the Lab produces has somewhere to go immediately.
# =============================================================================

IDLE_SLEEP = 0.5   # waiting on the Lab to extract something deliverable
BUSY_SLEEP = 0.25  # a delivery is already mid-flight

inventory = get_component("inventory")


def score_order(order):
    # How this order stands against current inventory.
    #
    # Returns {"ready": n, "remaining": n} — `ready` is how many samples we
    # hold that it can accept right now, capped at what it still needs.
    ready = 0
    remaining = 0
    for frag in order.requires.keys():
        needed = order.requires[frag] - order.delivered.get(frag, 0)
        if needed <= 0:
            continue
        remaining = remaining + needed

        held = inventory.get_count(frag)
        if held < needed:
            ready = ready + held
        else:
            ready = ready + needed

    result = {}
    result["ready"] = ready
    result["remaining"] = remaining
    return result


def better(candidate, champion):
    # Ranking rule: most deliverable now, then nearest completion, then
    # biggest reward.
    if candidate["ready"] != champion["ready"]:
        return candidate["ready"] > champion["ready"]
    if candidate["remaining"] != champion["remaining"]:
        return candidate["remaining"] < champion["remaining"]
    return candidate["reward"] > champion["reward"]


def pick_order(orders):
    # Best unfinished order, or None if every order is complete.
    champion = None
    for order in orders:
        if order.status == "complete":
            continue

        candidate = score_order(order)
        candidate["order"] = order
        candidate["reward"] = order.reward

        if champion == None:
            champion = candidate
        elif better(candidate, champion):
            champion = candidate
    return champion


last_waiting_on = ""

while True:
    orders = self.orders()
    choice = pick_order(orders)

    if choice == None:
        print("[exchange] every bio order is complete — stopping")
        break

    order = choice["order"]
    ready = choice["ready"]
    remaining = choice["remaining"]

    # Activating an already-active order is a harmless no-op, so this can run
    # every pass and the target re-evaluates as the Lab produces samples.
    result = self.set_order(order.id)
    if result != "ok":
        print("[exchange] cannot activate", order.name, "-", result)
        sleep(IDLE_SLEEP)
        continue

    if ready == 0:
        # Nothing to hand over yet. The Lab is upstream — let it catch up.
        # Report once per target instead of once per pass.
        if last_waiting_on != order.id:
            print("[exchange] waiting on samples for", order.name, "-", remaining, "still needed")
            last_waiting_on = order.id
        sleep(IDLE_SLEEP)
        continue

    # Deliver everything inventory can cover for this order before
    # re-scoring — each deliver() is one sample.
    delivered = 0
    while delivered < ready:
        status = self.deliver()

        if status == "ok":
            delivered = delivered + 1
        elif status == "complete":
            delivered = delivered + 1
            print("[exchange] ORDER COMPLETE:", order.name, "- paid", order.reward, "cr")
            break
        elif status == "busy":
            sleep(BUSY_SLEEP)
        elif status == "no_inventory":
            # Another script consumed the sample, or the score is stale.
            break
        else:
            # no_active — the active order changed under us; re-score.
            print("[exchange] deliver returned", status)
            break

    if delivered > 0:
        last_waiting_on = ""
        print("[exchange]", order.name, "-", delivered, "delivered,", order.percent, "% before this pass")
