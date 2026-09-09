

alien_list = []
for sample in self.contract.samples:
    if sample not in self.contract.earth_ref:
        alien_list.append(sample)


transmitter = get_component("transmitter")
transmitter.connect("earth")
transmitter.transmit(self.contract.id, alien_list)