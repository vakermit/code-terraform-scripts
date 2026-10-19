# =============================================================================
#  bio  —  reading Bio Order progress
# =============================================================================
#
#  The Exchange holds the active order; the Collector and the Lab both need to
#  know what it still wants. `self` does not exist in a library, so the Exchange
#  component is passed in.
# =============================================================================


def active_remaining(exchange):
    """What the ACTIVE Bio Order still needs, as {fragment_id: count}.

    Subtracts both delivered and in-transit units, so two scripts working the
    same order do not both chase the same fragment.

    An empty dict means there is nothing to focus on: no Exchange, no active
    order, or every requirement already covered.
    """
    if exchange == None:
        return {}
    order = exchange.active_order()
    if order == None:
        return {}
    remaining = {}
    for frag in order.requires.keys():
        short = order.requires[frag]
        short = short - order.delivered.get(frag, 0)
        short = short - order.in_transit.get(frag, 0)
        if short > 0:
            remaining[frag] = short
    return remaining
