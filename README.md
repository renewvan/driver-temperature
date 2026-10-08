# node-temperature

1-Wire (DS18B20) temperature sensing node for the renewvan bus

Scaffolded from `renewvan/node-tank`'s reference shape via `renewvan/skills`'
`scaffold-node` skill (per the **Node** term in `hub/docs/architecture.md`'s
Terminology section: "anything that publishes one specific device or feed
onto the renewvan bus, normalized into the device model"). Layout: pure,
unit-testable conversion math with no I/O, a layered
`config.default.ini`/`config.ini` loader (`config.py`), a persistent MQTT
publisher with LWT (`publisher.py`), a thin publish loop (`driver.py`), a
systemd unit, and its own Dockerfile + CI publishing a versioned image.

**This repo is a scaffold, not a working node yet** — `driver.py`'s
`read_and_publish()` raises `NotImplementedError` until the design round
below is resolved and implemented.

## Design checklist (resolve before first real commit)

- [ ] **Sensing or remapping?** Does this node own the sensing (reads
      hardware directly, like node-tank's ADS1115) or remap an existing feed
      (like node-battery's Victron remap)?
- [ ] **Topics published** — replace the section below with the real
      `renewvan/temperature/<id>/<property>` fields, split into identity
      (published once) vs live (republished every poll). See node-tank's
      README "Topics published" section for the shape to match.
- [ ] **Hub schema** — does Temperature extend an existing
      `hub/schema/*.schema.json` entity, or need a new
      `hub/schema/temperature.schema.json` + example fixtures
      (`hub/schema/validate-examples.sh` must pass)?
- [ ] **Wiring** — replace the section below with real hardware
      wiring/config, or delete it if this node remaps an existing feed
      instead of reading hardware directly.
- [ ] **`NodeConfig`** (`node_temperature/config.py`) — add the hardware/feed
      -specific fields this node needs, mirrored into `config.default.ini`.
- [ ] **Hub integration** — once a version is tagged, add a
      `node-temperature` service block to `hub/docker-compose.yml` (pattern:
      node-tank's block) and any new keys to `hub/.env.example`.

## Topics published

TODO — see the design checklist above.

## Wiring

TODO — see the design checklist above.

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
differs.

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
