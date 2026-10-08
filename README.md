# node-temperature

1-Wire (DS18B20) temperature sensing node for the renewvan bus

Sensing node: reads every standalone temperature sensor the Pi can see
directly and publishes it as the `temperature` entity (`hub`'s
`schema/temperature.schema.json`). It does **not** publish temperatures that
belong to another entity's hardware: tank water temperature stays on
`node-tank` (NTC on the ADS1115), battery temperature on `node-battery`
(Victron feed), ESP32 sensors on the ESPHome firmware. Layout follows
`renewvan/node-tank`: pure parsing (`sensors.py`), sysfs I/O (`reader.py`),
layered `config.default.ini`/`config.ini` (`config.py`), persistent MQTT
publisher with LWT (`publisher.py`), publish loop (`driver.py`).

## Topics published

Retained, under `renewvan/temperature/<id>/`. `<id>` is the `[sensor.<id>]`
section name from `config.ini`; an unconfigured 1-Wire probe is published
under its serial; the Pi CPU sensor is `cpu`.

**Identity fields** (published at startup, and again after a user edit):
- `name` — string, label shown on the dashboard (editable)
- `unit` — `"C"` / `"F"`, **display preference only** (editable)
- `source` — `"w1"` (DS18B20) / `"cpu"` (Pi SoC)
- `serial` — string, 1-Wire id, e.g. `28-0000075a1b2c` (`w1` only)

**Live fields** (republished every poll, ~3s default):
- `temperature_c` — number, **always degrees Celsius** regardless of `unit`.
  Skipped (not cleared) while `status` is not `ok`, so consumers must gate on
  `status == "ok"` before rendering it
- `status` — `ok` / `no_reading` (CRC failure, the DS18B20 85.0 °C power-on
  default, unparseable or out-of-range value) / `disconnected` (probe no
  longer on the bus; keeps being polled and recovers on replug)

**Command topics** (unretained, for the dashboard):
- `renewvan/temperature/<id>/name/set` — payload: JSON string, e.g. `"Galley fridge"`
- `renewvan/temperature/<id>/unit/set` — payload: `"C"` or `"F"` (any case)

A valid edit is persisted to `state/<id>.json` and republished retained; it
then **wins over `config.ini`** on every restart, which only supplies the
defaults. Invalid payloads are logged and dropped. If the state file cannot
be written the edit is rejected, so the retained topic never advertises a
value that would be lost on restart.

**Node liveness:** `renewvan/temperature/health` — `online`/`offline` via MQTT LWT.

Payload shapes match `hub`'s `schema/temperature.schema.json`.

## Wiring

### DS18B20 probes (1-Wire)

All probes share one data line; each has a unique 64-bit serial.

- VDD → 3.3V, GND → GND, DATA → the chosen GPIO (GPIO4 = pin 7 by default)
- **4.7 kΩ pull-up between DATA and 3.3V** (one resistor for the whole bus)
- Enable the kernel driver, then reboot:
  `dtoverlay=w1-gpio,gpiopin=4` in `/boot/firmware/config.txt`
- List serials: `ls /sys/bus/w1/devices` (entries named `28-...`)

Map a probe to an id and label in `config.ini`:

```ini
[sensor.fridge]
serial = 28-0000075a1b2c
name = Fridge
unit = C
```

No overlay, or no probes: the node still publishes the CPU sensor.

### Pi CPU

Built in (`/sys/class/thermal/thermal_zone0/temp`). Disable with
`cpu_enabled = false`.

## Development

```bash
git clone git@github.com:renewvan/node-temperature.git
cd node-temperature
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
```

Keep conversion/decision logic in pure functions tested against fixture
values — no MQTT broker or real hardware required for any of it. Before
opening a PR: `pytest tests/ -v` must pass (same command CI runs), and any
change to a published field needs a matching
`hub/schema/temperature.schema.json` update in a `hub` PR (per
`hub/docs/adr/0001-compose-services-via-pinned-images-not-git-submodules.md`,
the two repos are never coupled at build time, only at the schema-version
level).

## Configuration

`config.default.ini` ships every key with a default. Copy
`config.ini.example` to `config.ini` (gitignored) and override only what
differs. Malformed `[sensor.*]` sections (bad serial, unit, duplicate serial,
topic-unsafe id) fail at startup rather than being silently skipped.

`state_dir` (default `<install dir>/state`) must be writable by the service
user, and a mounted volume under Docker, or dashboard edits are lost when the
container is recreated.

## Running

```bash
pip install -r requirements.txt
python -m node_temperature.main --config config.ini
```

Install `node_temperature/systemd/node-temperature.service` to run at boot
(`Restart=on-failure`).

## Testing

```bash
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -v
```

## Releasing

Tagging a GitHub release builds and publishes
`ghcr.io/<owner>/node-temperature:<tag>`, which `hub`'s deployment compose file pins
by tag (never builds from source — see
`hub/docs/adr/0001-compose-services-via-pinned-images-not-git-submodules.md`).
