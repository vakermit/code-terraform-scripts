# CONTRACT: crosstalk
# Two signals of letters with bits scattered through. A bit is real only
# if the letters around it mirror to min_length (a palindrome centred on
# the bit). Take the real bits from both signals, XOR them pairwise, and
# read the result five bits at a time as letters (00001 = A).

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[crosstalk] transmitter:", link.message)

half = self.contract.min_length // 2


def real_bits(signal):
    bits = []
    n = len(signal)
    for i in range(n):
        ch = signal[i]
        if ch != "0" and ch != "1":
            continue
        mirrored = True
        for d in range(1, half + 1):
            if i - d < 0 or i + d >= n or signal[i - d] != signal[i + d]:
                mirrored = False
                break
        if mirrored:
            bits.append(ch)
    return bits


x = real_bits(self.contract.input_x)
y = real_bits(self.contract.input_y)
print("[crosstalk] real bits: x", len(x), "y", len(y))

n = min(len(x), len(y))
mixed = ""
for i in range(n):
    if x[i] != y[i]:
        mixed = mixed + "1"
    else:
        mixed = mixed + "0"

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
message = ""
i = 0
while i + 5 <= len(mixed):
    value = 0
    for b in mixed[i:i + 5]:
        value = value * 2 + int(b)
    if value >= 1 and value <= 26:
        message = message + ALPHABET[value - 1]
    else:
        message = message + "?"
    i = i + 5

print("[crosstalk] message:", message)
sent = transmitter.transmit(self.contract.id, message)
print("[crosstalk]", sent.status, "-", sent.message)
