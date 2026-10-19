# =============================================================================
#  trace  —  why the machine did that
# =============================================================================
#
#  Four loops allocating from a learned model is opaque in a way a single
#  advisory controller never was. "Why is the smelter off" has at least four
#  answers — no lease, a lease of zero, shed for power, preempted for a
#  deadline — and the game's debugger pauses one script at a time, which
#  cannot follow a decision spread across four of them.
#
#  So every loop writes one line per decision here, and a card renders them.
#  This is a feature, not instrumentation: it is the only way the allocation
#  model can be improved, because it is the only way to see what it decided.
#
#  ONE KEY PER LOOP, not one shared key. The Archive has no locking worth
#  using and the platform's rule is that each prefix has exactly one writer;
#  a shared trace would break that on the very first concurrent append. Each
#  loop owns `<loop>.trace`, the card reads all four and merges on the hour
#  field. The cost is four reads instead of one; the gain is that no loop can
#  lose another's rows.
#
#  BOUNDED, because nothing sweeps the Archive. Forty rows per loop against a
#  16,384-node value ceiling is far inside budget and still more history than
#  anyone reads at once.
# =============================================================================

KEEP = 40                    # rows retained per loop


def _key(loop):
    return loop + ".trace"


def note(loop, hour, subject, reason, detail=None):
    """Append one decision row for `loop`. Silent when there is no Archive.

    `subject` is what the decision was about — a machine id, a pillar, a
    channel. `reason` is why, in a handful of words that read as a reason a
    day later rather than as a log level. `detail` carries the figures.
    """
    book = get_component("notebook")
    if book == None:
        return False
    row = {"h": hour, "s": subject, "why": reason}
    if detail != None:
        row["d"] = detail

    def append(rows):
        rows.append(row)
        if len(rows) > KEEP:
            return rows[len(rows) - KEEP:]
        return rows

    result = book.transaction(_key(loop), [], append)
    if result.status == "busy":
        # Our own loop is the only writer, so busy means a previous pass of
        # this same loop is still inside its transaction. Dropping the row is
        # right: the trace is an explanation, never a ledger, and blocking a
        # control loop to record why it blocked is a bad trade.
        return False
    if result.status != "ok":
        print(f"trace: {loop} row rejected, {result.message}")
        return False
    return True


def rows(loop):
    """One loop's rows, oldest first. Empty without an Archive."""
    book = get_component("notebook")
    if book == None:
        return []
    return book.get(_key(loop), [])


def merged(loops):
    """Every named loop's rows in one list, oldest first, each tagged.

    For the card. Sorted on the world hour the row was written, which is the
    only clock all four loops share.
    """
    out = []
    for loop in loops:
        for row in rows(loop):
            row["loop"] = loop
            out.append(row)
    return sorted(out, key=lambda r: r["h"])


def render(row):
    """One row as a line a human reads: `smelter_1  shed  rank 7  w=0`."""
    line = f"{row['s']}  {row['why']}"
    if row.has("d"):
        parts = []
        for field in row["d"]:
            parts.append(f"{field}={row['d'][field]}")
        line = line + "  " + " ".join(parts)
    return line
