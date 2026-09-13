# CONTRACT: terminal_breach
# 15 digits, each 1-5. guess() reports how many are in the correct
# position, so positions are independent: for each one, try all five
# digits and keep whichever raises the exact-match count. 75 guesses.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[terminal] transmitter:", link.message)

terminal = self.contract.terminal
length = terminal.length

code = []
for i in range(length):
    code.append(1)

for pos in range(length):
    best_digit = 1
    best_correct = -1
    for digit in range(1, 6):
        code[pos] = digit
        correct = terminal.guess(code).correct
        if correct > best_correct:
            best_correct = correct
            best_digit = digit
    code[pos] = best_digit
    print("[terminal] position", pos + 1, "=", best_digit, "(", best_correct, "locked )")

print("[terminal] code:", code)
sent = transmitter.transmit(self.contract.id, code)
print("[terminal]", sent.status, "-", sent.message)
