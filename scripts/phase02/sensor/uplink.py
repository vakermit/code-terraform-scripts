
sensor = get_component("thermometer")
xmit = get_component("transmitter")

temp = sensor.get_value()

xmit.connect("earth")
xmit.transmit("current_temperature",temp)
