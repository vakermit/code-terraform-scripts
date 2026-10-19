# =============================================================================
#  signals  —  reading the Signal Bus without repeating the None dance
# =============================================================================
#
#  comms may be absent (no Ship Computer yet, or powered down) and a channel
#  may never have been broadcast. Every caller was writing the same two guards;
#  these collapse them into a default.
#
#  Publishing is deliberately NOT here: the six publish() helpers across the
#  scripts had five different bodies, so there is no single correct version to
#  share. Each script keeps its own until they are reconciled by hand.
# =============================================================================


def comms():
    """The comms component, or None when there is no Signal Bus available."""
    return get_component("comms")


def latest(channel, default=None):
    """Most recent value broadcast on `channel`, or `default`.

    Covers both "no comms" and "nothing broadcast yet".
    """
    bus = get_component("comms")
    if bus == None:
        return default
    value = bus.latest(channel)
    if value == None:
        return default
    return value


def latest_map(channel, fallback_keys=None):
    """A broadcast mapping, falling back to `fallback_keys` set to 1 each.

    The factory channels carry {item_id: count} maps. When nothing has been
    broadcast, scripts fall back to a hard-coded want-list; this expresses
    that pattern once.
    """
    published = latest(channel)
    if published != None and len(published) > 0:
        return published
    wanted = {}
    if fallback_keys != None:
        for item in fallback_keys:
            wanted[item] = 1
    return wanted


def field(d, key, default):
    """Read `key` from a broadcast record, tolerating a missing record.

    Broadcast payloads arrive as dicts that may be None or may predate a field.
    """
    if d == None or not d.has(key):
        return default
    return d[key]


def wanted_ores(fallback_items=None, channel="factory.ore"):
    """What the factory is short of, as {ore_id: units}.

    Reads the Smelter's broadcast and falls back to a hard-coded want-list.
    An empty result means "mine anything".
    """
    return latest_map(channel, fallback_items)
