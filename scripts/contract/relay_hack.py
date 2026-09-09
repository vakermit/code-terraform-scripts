

code = [0, 0, 0, 0, 0, 0]
lock = self.contract.lock

for pos in range(6):
    for num in range(100):
        code[pos] = num
        result = lock.intercept(code)
        if result[pos]:
            print(f"found - {pos} {code}")
            break

print(code)

transmitter = get_component("transmitter")
transmitter.connect("earth")
transmitter.transmit(self.contract.id, code)

