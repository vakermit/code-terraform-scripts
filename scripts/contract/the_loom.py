# CONTRACT: the_loom
# The record is two 21-character threads braided by a fixed rule. Instead
# of assuming the rule, LEARN it: weave two probe threads whose characters
# are all distinct, then read off where every output position came from.
# That gives an exact position map for any deterministic weave, which is
# then run backwards over the record.
#
# One of the two recovered threads is the message. Both are printed; the
# one that reads more like English is transmitted. Set PICK to force it.

PICK = ""   # "" = auto, or "a" / "b"

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[loom] transmitter:", link.message)

loom = self.contract.loom
record = self.contract.record
half = len(record) // 2
print("[loom] record:", record, "(", len(record), "chars )")

# Probe threads: A uses one alphabet, B another, so every woven character
# identifies its source thread and index unambiguously.
ALPHA_A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ALPHA_B = "abcdefghijklmnopqrstuvwxyz"
probe_a = ALPHA_A[0:half]
probe_b = ALPHA_B[0:half]
woven = loom.weave(probe_a, probe_b)
print("[loom] probe weave:", woven)

# source[i] = ["a" or "b", index] for output position i
source = []
for ch in woven:
    ia = ALPHA_A.find(ch)
    ib = ALPHA_B.find(ch)
    if ia >= 0:
        source.append(["a", ia])
    else:
        source.append(["b", ib])

# Un-weave the record with that map.
chars_a = []
chars_b = []
for i in range(half):
    chars_a.append("")
    chars_b.append("")
for i in range(len(record)):
    which = source[i][0]
    index = source[i][1]
    if which == "a":
        chars_a[index] = record[i]
    else:
        chars_b[index] = record[i]

thread_a = "".join(chars_a)
thread_b = "".join(chars_b)
print("[loom] thread a:", thread_a)
print("[loom] thread b:", thread_b)


def english_score(text):
    score = 0
    for ch in text.upper():
        if "ETAOINSHR".find(ch) >= 0:
            score = score + 2
        elif ch == " ":
            score = score + 3
    return score


answer = thread_a
if PICK == "b":
    answer = thread_b
elif PICK == "" and english_score(thread_b) > english_score(thread_a):
    answer = thread_b

print("[loom] submitting:", answer)
sent = transmitter.transmit(self.contract.id, answer)
print("[loom]", sent.status, "-", sent.message)
