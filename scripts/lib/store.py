# =============================================================================
#  store  —  where material is, and where it should go
# =============================================================================
#
#  Every factory and rover script asks the same three questions: how much of
#  an item do we hold, which container should I pull it from, and which should
#  I push it into. The answers span the base inventory and every storage bin at
#  the home outpost.
#
#  These resolve `inventory` and the home outpost themselves via
#  get_component(), so callers pass only what is genuinely script-specific.
# =============================================================================

STORE = "inventory"


def bins():
    """Storage bins at the home outpost as [{"id": str, "bin": Component}].

    Empty when there is no outpost network or no bins are built.
    """
    out = []
    network = get_component("outpost_network")
    if network == None:
        return out
    home = network.home()
    if home == None:
        return out
    for ref in home.buildings("storage_bin"):
        entry = {}
        entry["id"] = ref.id
        entry["bin"] = get_component(ref.id)
        out.append(entry)
    return out


def stock_of(item):
    """Total units of `item` held across the inventory and every storage bin."""
    inventory = get_component(STORE)
    total = 0
    if inventory != None:
        total = inventory.count(item)
    for b in bins():
        total = total + b["bin"].count(item)
    return total


def source_for(item):
    """Id of a container currently holding `item`, preferring the inventory.

    Returns "" when nothing holds it — callers treat that as "cannot pull".
    """
    inventory = get_component(STORE)
    if inventory != None and inventory.count(item) > 0:
        return STORE
    for b in bins():
        if b["bin"].count(item) > 0:
            return b["id"]
    return ""


def sink_for(item):
    """Id of the best container to push `item` into.

    A bin already dedicated to that material with room wins; otherwise any
    empty bin; otherwise the inventory. Never returns "", so a caller always
    has somewhere to send output.
    """
    for b in bins():
        if b["bin"].get_material() == item and b["bin"].space() > 0:
            return b["id"]
    for b in bins():
        if b["bin"].is_empty():
            return b["id"]
    return STORE
