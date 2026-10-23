# driver-temperature

Domain glossary for driver-temperature: what each published field *means*,
independent of the Python that computes it. Entity contract:
`hub/schema/temperature.schema.json`.

## Language

**Temperature sensor**:
A standalone thermometer this driver reads directly: a 1-Wire DS18B20 probe or the Pi's SoC thermal zone. Published as its own `temperature` entity keyed by sensor id.
_Avoid_: Thermistor/NTC sensor (that is driver-tank's water-temperature input, published on the tank entity); heater/battery temperature (owned by their own drivers).

**Sensor id**:
The `<id>` topic segment. The `[sensor.<id>]` section name for a configured probe, the serial for an unconfigured probe, `cpu` for the built-in. Stable across renames: `name` is the label, the id is the key.
_Avoid_: Name (the editable display label), serial (the hardware identity, which can be re-mapped to a new id).

**Driver**:
This software, the publisher of the `temperature` entity. Its key is `temperature` (repo name minus `driver-`), equal to the `renewvan/temperature/info` segment and to the retained `driver` field it publishes on every sensor instance so consumers know which Driver owns the instance.
_Avoid_: Device (the 1-Wire probe is hardware; the software is the Driver).

**Serial**:
The probe's 1-Wire id (`28-` + 12 hex), the hardware identity. Published for `w1` sensors only.

**Unit**:
A *display preference* (`C`/`F`). Never changes the wire: `temperature_c` is always Celsius and the dashboard converts. Editable at runtime.
_Avoid_: Treating it as the unit of `temperature_c`.

**Status**:
Sensor health. `ok`, `no_reading` (present but unusable: CRC failure, the 85.0 °C power-on default, out of range), `disconnected` (a known probe is gone from the bus). `temperature_c` is only republished while `ok`.

**User edit**:
A `name`/`unit` change from the dashboard via `<field>/set`, persisted to `state/<id>.json`. Overrides `config.ini`, which only supplies defaults.
