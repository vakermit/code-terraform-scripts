# CONTRACT: core_sample
# Ten cores, each a byte list with some bytes destroyed (None). A core's
# layout is:
#
#   [0]  magic       always 42
#   [1]  n           record count
#   [2]  length      4 + 4n  (the total byte count)
#   then n records of 4 bytes  [kind, load, partner, sum]
#   [3 + 4n]  lock   XOR of every record's sum byte
#
# Record rules:  partner links are mutual (a.partner = b  ->  b.partner = a)
#                kind + partner.kind = 5
#                sum = (kind + load + partner) mod 256
#
# Every rule is an equation with one unknown once the other terms are
# known, so propagate them until nothing changes. Then submit each core;
# the device's token appears once all ten lock in.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[core] transmitter:", link.message)

device = self.contract.device
cores = self.contract.cores


def mod256(value):
    # Guarded so a negative intermediate cannot leave a negative byte,
    # whichever sign convention the interpreter's % follows.
    return ((value % 256) + 256) % 256


def rec(core, i, field):
    return core[3 + 4 * i + field]


def set_rec(core, i, field, value):
    core[3 + 4 * i + field] = value


def rebuild(damaged):
    c = list(damaged)
    n = (len(c) - 4) // 4
    lock = 3 + 4 * n

    changed = True
    while changed:
        changed = False

        # header
        if c[0] == None:
            c[0] = 42
            changed = True
        if c[1] == None:
            c[1] = n
            changed = True
        if c[2] == None:
            c[2] = 4 + 4 * n
            changed = True

        for i in range(n):
            kind = rec(c, i, 0)
            load = rec(c, i, 1)
            partner = rec(c, i, 2)
            total = rec(c, i, 3)

            # partner links are mutual
            if partner != None and rec(c, partner, 2) == None:
                set_rec(c, partner, 2, i)
                changed = True
            if partner == None:
                for j in range(n):
                    if j != i and rec(c, j, 2) == i:
                        set_rec(c, i, 2, j)
                        partner = j
                        changed = True
                        break

            # kinds of partners sum to 5
            if kind == None and partner != None and rec(c, partner, 0) != None:
                kind = 5 - rec(c, partner, 0)
                set_rec(c, i, 0, kind)
                changed = True

            # sum rule: any one unknown of the four is determined
            known = 0
            for v in [kind, load, partner, total]:
                if v != None:
                    known = known + 1
            if known == 3:
                if total == None:
                    set_rec(c, i, 3, mod256(kind + load + partner))
                elif kind == None:
                    set_rec(c, i, 0, mod256(total - load - partner))
                elif load == None:
                    set_rec(c, i, 1, mod256(total - kind - partner))
                else:
                    set_rec(c, i, 2, mod256(total - kind - load))
                changed = True

        # lock = XOR of all sums; one missing sum is recoverable from it
        missing = -1
        missing_count = 0
        acc = 0
        for i in range(n):
            s = rec(c, i, 3)
            if s == None:
                missing = i
                missing_count = missing_count + 1
            else:
                acc = acc ^ s
        if missing_count == 0 and c[lock] == None:
            c[lock] = acc
            changed = True
        if missing_count == 1 and c[lock] != None:
            set_rec(c, missing, 3, c[lock] ^ acc)
            changed = True

    return c


for index in range(len(cores)):
    fixed = rebuild(cores[index])
    holes = 0
    for v in fixed:
        if v == None:
            holes = holes + 1
    if holes > 0:
        print("[core]", index, "still has", holes, "unknown bytes — submitting anyway")
    result = device.submit(index, fixed)
    print("[core]", index, "-", result.status, "-", result.message)

print("[core] recovered", device.recovered(), "/", device.target())
token = device.token()
if token == "":
    print("[core] no token — not every core locked in")
else:
    sent = transmitter.transmit(self.contract.id, token)
    print("[core]", sent.status, "-", sent.message)
