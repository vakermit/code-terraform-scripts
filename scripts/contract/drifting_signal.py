# CONTRACT: drifting_signal
# The slabs are a Caesar shift of an English sentence. Try all 26 shifts
# and score each for English-likeness — letter frequency plus a few very
# common words — rather than assuming a particular shift. Every candidate
# is printed so a wrong pick is obvious; SHIFT overrides the scorer.

SHIFT = -1   # -1 = pick by score; otherwise force this shift (0-25)

COMMON_LETTERS = "ETAOINSHRDLU"
COMMON_WORDS = ["THE", "AND", "OF", "TO", "IS", "IN", "IT", "YOU", "THAT", "FOR"]

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[slabs] transmitter:", link.message)

cipher = self.contract.device.slabs
print("[slabs] slabs:", cipher)


def unshift(text, shift):
    out = ""
    for ch in text:
        if ch == " ":
            out = out + " "
        else:
            out = out + chr((ord(ch) - 65 - shift) % 26 + 65)
    return out


def english_score(text):
    score = 0
    for ch in text:
        weight = COMMON_LETTERS.find(ch)
        if weight >= 0:
            score = score + (12 - weight)
    for word in text.split(" "):
        if word in COMMON_WORDS:
            score = score + 40
    return score


best_shift = 0
best_score = -1
for shift in range(26):
    candidate = unshift(cipher, shift)
    score = english_score(candidate)
    print("  shift", shift, "score", score, "->", candidate)
    if score > best_score:
        best_score = score
        best_shift = shift

if SHIFT >= 0:
    best_shift = SHIFT

answer = unshift(cipher, best_shift)
print("[slabs] shift", best_shift, "->", answer)
sent = transmitter.transmit(self.contract.id, answer)
print("[slabs]", sent.status, "-", sent.message)
