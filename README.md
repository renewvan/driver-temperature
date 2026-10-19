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

**Node info:** `renewvan/temperature/info` — one retained JSON message
describing this Node (see [Node info](#node-info)). Published on **every
connect, immediately before `online`**, so a consumer that sees `online`
always finds info already retained. It is **never cleared**: it stays retained
when the Node goes offline or its last will fires, which is what lets a
consumer say "offline, last seen vX".

Payload shapes match `hub`'s `schema/node-info.schema.json` for info and `hub`'s `schema/temperature.schema.json` for entities.

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

The release workflow passes the tag as the `NODE_VERSION` build argument, which
the Dockerfile promotes to an environment variable the Node reads (see
[Node info](#node-info)). Nothing else carries a version.

## Node info

The Node describes itself to the dashboard with a manifest plus two runtime
values. Contract: `hub`'s `schema/node-info.schema.json` (decision record:
`hub/docs/adr/0011-node-manifest-and-retained-info-topic.md`).

**`manifest.json`** (repo root) is the single source of the static fields:
`node` (`temperature`, the topic key), `product`, `source`, `publishes`, and
optional `manufacturer` / `homepage`. `version` and `host_serial` are
**forbidden** in it. The image build copies it beside the module
(`node_temperature/manifest.json`); the Node reads that copy first and falls
back to the repo-root file for a checkout run.

**`version`** comes from the git release tag and nowhere else. The release
workflow passes it as the `NODE_VERSION` build argument, which becomes an
environment variable the Node reads. When `NODE_VERSION` is unset or empty (a
checkout run, a local `docker build`) the Node reports the literal **`dev`**.
There is no `version` file or `__version__`, and the `pyproject.toml` version
is a fixed placeholder nothing reads.

**`host_serial`** is the `Serial` line of the host's `/proc/cpuinfo`, read once
at start. A default container can read it, so no compose or Dockerfile change
is needed. It is **omitted** (never faked, never `unknown`) when the file is
unreadable, the line is missing or empty, or the value is all zeros.

`node_temperature/node_info.py` is a small helper deliberately **copied** into
each Python node repo rather than shared as a package, so each Node releases
independently.

**CI gate:** `.github/workflows/manifest.yml` validates `manifest.json`
against `node-manifest.schema.json`, fetched from `hub` at a **pinned commit**
(`HUB_REF`) with `ajv-cli`, and fails if a manifest containing `version` is
accepted. Bump `HUB_REF` deliberately to adopt a newer contract. To check
locally:

```bash
npx --yes ajv-cli@5 validate -s path/to/hub/schema/node-manifest.schema.json -d manifest.json
```

