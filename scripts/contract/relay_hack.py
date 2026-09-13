# CONTRACT: relay_hack
# intercept(code) reports one True/False per tumbler, so each tumbler is
# independent: hold the rest at 0 and sweep 0-99 until its flag flips.
# Worst case 600 probes.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[relay] transmitter:", link.message)

lock = self.contract.lock
code = [0, 0, 0, 0, 0, 0]

for pos in range(lock.tumblers):
    for value in range(lock.range):
        code[pos] = value
        if lock.intercept(code)[pos]:
            break
    print("[relay] tumbler", pos + 1, "=", code[pos])

print("[relay] code:", code)
sent = transmitter.transmit(self.contract.id, code)
print("[relay]", sent.status, "-", sent.message)
