clock = get_component("clock")


while True:
    elev = clock.get_elevation()
    tilt = 90 - elev
    print(f"evel = {elev} tilt = {tilt}")
    self.set_tilt(tilt)
    sleep(1) 