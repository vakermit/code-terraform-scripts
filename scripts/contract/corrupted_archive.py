# CONTRACT: corrupted_archive
# Every word appears on two cards. Flip the whole grid once, then pair each
# word's first sighting with its second. Answer: list of [r1, c1, r2, c2].

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[archive] transmitter:", link.message)

archive = self.contract.archive
print("[archive] flipping", archive.rows, "x", archive.cols)

first = {}
pairs = []
for row in range(archive.rows):
    for col in range(archive.cols):
        word = archive.flip(row, col)
        if first.has(word):
            prev = first[word]
            pairs.append([prev[0], prev[1], row, col])
        else:
            first[word] = [row, col]

print("[archive]", len(pairs), "pairs")
sent = transmitter.transmit(self.contract.id, pairs)
print("[archive]", sent.status, "-", sent.message)
