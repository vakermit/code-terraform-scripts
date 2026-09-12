# ============================================================
#  SCANNER - map the whole local grid once, cheaply
# ============================================================
#  Grid is rows A-H x columns 1-24 (192 sectors), base at E13.
#
#  Two things from the docs (reference/components/exploration.md)
#  shape this:
#  - scan() returns a ScanResult with .status ("ok" / "empty")
#    and .message. The demo's .ok / .reason fields are gone;
#    reading them now fails.
#  - Scan history persists across runs, and get_scanned() is a
#    LIVE view of every scanned sector, items collected or
#    dropped since show up without rescanning. So a sector only
#    ever needs one physical scan: re-running this script skips
#    everything it already knows and finishes instantly.
# ============================================================

ROWS      = "ABCDEFGH"
COLS      = 24
RESCAN    = False    # True forces a fresh physical scan of every sector
SHOW_EMPTY = False   # print a line for empty sectors too (192 lines)

known = {}
if not RESCAN:
    known = self.get_scanned()

scanned = 0
items = 0
worth = 0
for row in ROWS:
    for col in range(1, COLS + 1):
        sector = row + str(col)
        if sector in known:
            res = known[sector]
        else:
            res = self.scan(sector)
            scanned = scanned + 1
        if res.status == "ok":
            items = items + 1
            worth = worth + res.value
            print(sector + ": " + res.name + " (" + str(res.value) + ")")
        elif SHOW_EMPTY:
            print(sector + ": " + res.message)

print(str(scanned) + " sectors newly scanned, " + str(len(known)) +
      " already known - " + str(items) + " items on the grid worth " +
      str(worth))
