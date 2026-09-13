# CONTRACT: three_echoes
# The signal was split round-robin across three frequencies: a has chars
# 1, 4, 7, ...; b has 2, 5, 8, ...; c has 3, 6, 9, .... Interleave them
# back and the original text appears.
#
# The text is a riddle, not the answer. The answer is the word the riddle
# describes, so it cannot be computed — read it and set ANSWER. The known
# riddle (Greek word for steam / conflated with roundness / around you but
# untouchable) resolves to "atmosphere"; that is filled in automatically
# when the decoded text matches it.

ANSWER = ""   # set this if the decoded riddle is not the known one

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[echoes] transmitter:", link.message)

b = self.contract.broadcast
signal = ""
i = 0
longest = max(len(b.freq_a), len(b.freq_b), len(b.freq_c))
while i < longest:
    if i < len(b.freq_a):
        signal = signal + b.freq_a[i]
    if i < len(b.freq_b):
        signal = signal + b.freq_b[i]
    if i < len(b.freq_c):
        signal = signal + b.freq_c[i]
    i = i + 1

print("[echoes] decoded:", signal)

answer = ANSWER
lowered = signal.lower()
if answer == "" and lowered.find("steam") >= 0 and lowered.find("round") >= 0:
    answer = "atmosphere"

if answer == "":
    print("[echoes] this riddle is not the known one — read it above,")
    print("[echoes] set ANSWER at the top of the script and run again")
else:
    print("[echoes] submitting:", answer)
    sent = transmitter.transmit(self.contract.id, answer)
    print("[echoes]", sent.status, "-", sent.message)
