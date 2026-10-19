# CONTRACT: data_tablet
# probe() returns each cell's character and its distance to the nearest
# message cell. Distance 0 IS a message cell; read those in row-major
# order and the characters spell the message.
#
# The distance field lets us skip: a cell reading d has no message cell
# within d-1 steps, so the next d-1 cells on this row can be skipped.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[tablet] transmitter:", link.message)

tablet = self.contract.tablet
print("[tablet] probing", tablet.rows, "x", tablet.cols)

message = ""
probes = 0
for row in range(tablet.rows):
    col = 0
    while col < tablet.cols:
        hit = tablet.probe(row, col)
        probes = probes + 1
        if hit.distance == 0:
            message = message + hit.char
            col = col + 1
        else:
            col = col + hit.distance

print("[tablet]", probes, "probes; message:", message)
sent = transmitter.transmit(self.contract.id, message)
print("[tablet]", sent.status, "-", sent.message)
