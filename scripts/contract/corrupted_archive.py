

archive = self.contract.archive
found = {}
for row in range(archive.rows):
    for col in range(archive.cols):
        word = archive.flip(row, col)
        if word not in found:
            found[word] = []
        found[word] += [row,col]

for word,coords in found.items():
    print(f"{word} - {coords}")

pairs = found.values()
transmitter = get_component("transmitter")
transmitter.connect("earth")
transmitter.transmit(self.contract.id, pairs)