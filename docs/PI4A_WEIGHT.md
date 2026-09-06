# PI-4A weight measurement

Set `NUTRIBOX_WEIGHT_ADAPTER=simulated` explicitly for PC/CI or development.
For the hardware adapter, set `NUTRIBOX_WEIGHT_ADAPTER=hx711` together with
`NUTRIBOX_HX711_DATA_BCM` and `NUTRIBOX_HX711_CLOCK_BCM`; these are BCM pin
numbers selected for the installed load-cell wiring, not application defaults.

Before using HX711 measurements for meals, complete physical wiring validation,
run `nutribox-pi weight-tare` with the scale empty, then run
`nutribox-pi weight-calibrate --known-grams <known-weight>` using a verified
reference mass. Confirm stable readings with `nutribox-pi weight-check` across
the expected 0–5000 g range. Calibration persists only its schema version,
offset, and factor in the private device configuration directory.

Physical wiring, tare, calibration, and stable-read validation have passed for
the mounted JC5 load cell. Reconfirm a stable `weight-check` result after any
future wiring, mounting, or calibration change before using measurements in a
meal analysis.

## Product boundary

Reheating is excluded from NutriBox product scope. The Pi does not implement
heating controls, temperature-driven reheating, relays, or heater GPIO.
