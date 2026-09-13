# CONTRACT: buried_five
# The message was wrapped `layers` times, each layer expanding every token
# into five. analyzer.read() collapses one aligned group of five back to
# the token it came from. Peel one layer at a time, left to right.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[buried] transmitter:", link.message)

analyzer = self.contract.analyzer
tokens = list(self.contract.transmission)
layers = self.contract.layers
print("[buried]", len(tokens), "tokens,", layers, "layers")

for layer in range(layers):
    if len(tokens) % 5 != 0:
        print("[buried] length", len(tokens), "is not a multiple of 5 — stopping early")
        break
    collapsed = []
    i = 0
    while i < len(tokens):
        collapsed.append(analyzer.read(tokens[i:i + 5]))
        i = i + 5
    tokens = collapsed
    print("[buried] layer", layer + 1, "peeled ->", len(tokens), "tokens")

message = "".join(tokens)
print("[buried] message:", message)
sent = transmitter.transmit(self.contract.id, message)
print("[buried]", sent.status, "-", sent.message)
