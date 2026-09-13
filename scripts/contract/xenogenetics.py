# CONTRACT: xenogenetics
# 1000 samples against 50 Earth references. Anything not on the Earth list
# is alien; the answer is the list of alien sequences.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[xeno] transmitter:", link.message)

earth = {}
for ref in self.contract.earth_ref:
    earth[ref] = True

alien = []
for sample in self.contract.samples:
    if not earth.has(sample):
        alien.append(sample)

print("[xeno]", len(alien), "alien of", len(self.contract.samples), "samples")
sent = transmitter.transmit(self.contract.id, alien)
print("[xeno]", sent.status, "-", sent.message)
