# =============================================================================
#  machines  —  finding machines by type when instance ids vary
# =============================================================================
#
#  Instance ids are numbered per save — bio_exchange_1, bio_exchange_2, ... —
#  so a script that hard-codes one breaks on the next save. These helpers
#  probe instead.
#
#  Library scope: `self` and `panel` do not exist here, but get_component()
#  and the other top-level game functions do. Pass a machine in when a helper
#  needs to act for the calling script.
# =============================================================================

MAX_INSTANCE = 8


def find_machine(kind, configured=""):
    """Resolve a machine by type when its instance number is unknown.

    Tries the configured id first, then the bare type, then `<kind>_1` up to
    `<kind>_8`. get_component() returns None for an unknown id rather than
    raising, so probing is safe. A powered-down machine reads the same as a
    missing one, so None means "not usable right now", not "does not exist".

    Returns the Component, or None if nothing answered.
    """
    if configured != "":
        found = get_component(configured)
        if found != None:
            return found

    found = get_component(kind)
    if found != None:
        return found

    n = 1
    while n <= MAX_INSTANCE:
        found = get_component(kind + "_" + str(n))
        if found != None:
            return found
        n = n + 1
    return None


def find_all(kind):
    """Every instance of a machine type that answers, as a list of Components.

    Use when a script should drive all of them rather than the first one.
    """
    out = []
    bare = get_component(kind)
    if bare != None:
        out.append(bare)
    n = 1
    while n <= MAX_INSTANCE:
        found = get_component(kind + "_" + str(n))
        if found != None:
            out.append(found)
        n = n + 1
    return out
