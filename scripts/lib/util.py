# =============================================================================
#  util  —  small pure helpers with no game dependencies
# =============================================================================
#
#  Nothing here touches get_component() or any machine, so these are safe to
#  call from anywhere, including other libraries.
# =============================================================================


def key_of(x, y):
    """Stable dict key for a grid coordinate.

    Coordinates are used as dict keys all over the rover scripts; a tuple key
    would work but reads worse in debug output than "12:47".
    """
    return str(x) + ":" + str(y)


def clamp(value, low, high):
    """`value` limited to the inclusive range [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value
