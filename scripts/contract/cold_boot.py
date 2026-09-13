# CONTRACT: cold_boot
# The program is Intcode-style bytecode: each instruction is an opcode in
# the low two digits with parameter modes in the digits above (0 = the
# parameter is an address, 1 = the parameter is the value itself).
#
#   1 add   a b -> dest       5 jump-if-true   cond target
#   2 mul   a b -> dest       6 jump-if-false  cond target
#   4 out   a                 7 less-than      a b -> dest
#  99 halt                    8 equals         a b -> dest
#
# The outputs are letters, 1 = A. Run it, collect the outputs, decode.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[boot] transmitter:", link.message)

memory = list(self.contract.program)
outputs = []
ip = 0
steps = 0
STEP_LIMIT = 100000


def read(offset, mode):
    raw = memory[ip + offset]
    if mode == 1:
        return raw
    return memory[raw]


while ip < len(memory) and steps < STEP_LIMIT:
    steps = steps + 1
    instr = memory[ip]
    op = instr % 100
    m1 = (instr // 100) % 10
    m2 = (instr // 1000) % 10

    if op == 99:
        break
    elif op == 1:
        memory[memory[ip + 3]] = read(1, m1) + read(2, m2)
        ip = ip + 4
    elif op == 2:
        memory[memory[ip + 3]] = read(1, m1) * read(2, m2)
        ip = ip + 4
    elif op == 4:
        outputs.append(read(1, m1))
        ip = ip + 2
    elif op == 5:
        if read(1, m1) != 0:
            ip = read(2, m2)
        else:
            ip = ip + 3
    elif op == 6:
        if read(1, m1) == 0:
            ip = read(2, m2)
        else:
            ip = ip + 3
    elif op == 7:
        if read(1, m1) < read(2, m2):
            memory[memory[ip + 3]] = 1
        else:
            memory[memory[ip + 3]] = 0
        ip = ip + 4
    elif op == 8:
        if read(1, m1) == read(2, m2):
            memory[memory[ip + 3]] = 1
        else:
            memory[memory[ip + 3]] = 0
        ip = ip + 4
    else:
        print("[boot] unknown opcode", op, "at", ip, "- halting")
        break

if steps >= STEP_LIMIT:
    print("[boot] step limit hit — program did not halt")

message = ""
for value in outputs:
    message = message + chr(value + 64)

print("[boot] outputs:", outputs)
print("[boot] decoded:", message)
sent = transmitter.transmit(self.contract.id, message)
print("[boot]", sent.status, "-", sent.message)
