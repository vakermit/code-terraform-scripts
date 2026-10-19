# =============================================================================
#  VEHICLE CHARGING STATION  —  paste into the script slot of  charging_station_1
#  Charge whatever docks; rescue anything stranded.
# =============================================================================
#
#  Charging jobs belong to the station, not the vehicle: a rover can drive
#  into the pad and park, but nothing flows until this script queues it with
#  self.charge(). The rover script (scripts/rover/rover_1.py) relies on
#  that — it comes home, parks, and waits for its level to rise.
#
#  Jobs survive this script stopping, so it is safe to leave alone.
#
#  RESCUE. A vehicle whose battery hits the floor away from the pad can only
#  be recovered by the station's field-service drone. One drone, one
#  mission at a time; the lowest vehicle goes first.
# =============================================================================

TARGET_LEVEL = 1.0         # charge docked vehicles to full
RESCUE_BELOW = 0.05        # dispatch the drone for any vehicle under this
POLL = 5

fleet = get_component("fleet")

rescuing = ""

while True:
    # --- charge everything on the pad -----------------------------------------
    for vehicle_id in self.get_docked():
        state = self.status(vehicle_id)["state"]
        if state == "charging" or state == "queued" or state == "target_reached":
            continue
        result = self.charge(vehicle_id, TARGET_LEVEL)
        if result.status == "ok":
            print("[station] charging", vehicle_id)
        elif result.status != "target_reached":
            print("[station] charge", vehicle_id, ":", result.message)

    # --- rescue the most stranded vehicle, one at a time -----------------------
    lowest = None
    for v in fleet.vehicles():
        if v.is_docked or v.is_being_rescued:
            continue
        if v.battery_level >= RESCUE_BELOW:
            continue
        if lowest == None or v.battery_level < lowest.battery_level:
            lowest = v

    if lowest != None and rescuing == "":
        result = self.dispatch_rescue(lowest.id, TARGET_LEVEL)
        if result.status == "ok":
            print("[station] rescue drone sent to", lowest.name)
            rescuing = lowest.id
        else:
            print("[station] rescue", lowest.name, ":", result.message)

    # Clear the flag once that vehicle is no longer flagged as being rescued.
    if rescuing != "":
        still = False
        for v in fleet.vehicles():
            if v.id == rescuing and v.is_being_rescued:
                still = True
        if not still:
            rescuing = ""

    sleep(POLL)
