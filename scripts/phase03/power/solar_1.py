# =============================================================================
#  SOLAR PANEL  —  paste into the script slot of  solar_1
#  Tracks the sun. Says almost nothing.
# =============================================================================
#
#  FAIL_SAFE = "hold". A panel is a generator, not a consumer: it has no
#  discretionary draw to stand down and no allowance to honour, so it never
#  reads a lease and the kernel never ranks it. Tracking the sun is always
#  the right thing to be doing.
#
#  WHY THIS EXISTS AT ALL.  The phase 2 version printed one line per pass per
#  panel. Fourteen panels at a line each flushed the game's 500-entry console
#  in seconds, and it twice destroyed the evidence from a live test before it
#  could be read — the fail-safe test that followed proved nothing, and this
#  was half the reason. A script that logs every pass is a script that makes
#  every other script unobservable.
#
#  So: print on a real change in tilt, not on every pass. A degree of
#  hysteresis, because elevation is a float and will otherwise jitter across
#  a boundary forever and print just as much as before.
#
#  The setpoint still has to be written every pass. It resets to 0 when the
#  script stops, so a loop that only wrote on change would hold a stale tilt
#  after any restart.
# =============================================================================

FAIL_SAFE = "hold"           # a generator never stands down
PASS_S = 1.0
REPORT_DEGREES = 5.0         # tilt change worth a line
NIGHT_ELEVATION = 0.0        # at or below this the panel makes nothing

clock = get_component("clock")
last_said = -999.0
was_night = None


def tilt_for(elevation):
    """Face the sun: a panel flat at noon is a panel edge-on to the light."""
    return 90 - elevation


while True:
    if clock == None:
        # No clock means no elevation to track. Hold whatever tilt was last
        # set rather than slewing to a guess, and do not say so repeatedly.
        sleep(PASS_S)
        continue

    elev = clock.get_elevation()
    tilt = tilt_for(elev)
    self.set_tilt(tilt)

    night = elev <= NIGHT_ELEVATION
    if night != was_night:
        # The one transition worth a line: it explains a power envelope
        # collapsing or recovering, which is what the safety loop reacts to.
        print("solar: " + ("night, generating nothing" if night
                           else f"daylight, elevation {round(elev, 1)}"))
        was_night = night
        last_said = tilt
    elif not night and abs(tilt - last_said) >= REPORT_DEGREES:
        print(f"solar: tilt {round(tilt, 1)} at elevation {round(elev, 1)}")
        last_said = tilt

    sleep(PASS_S)
