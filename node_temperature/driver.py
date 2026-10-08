"""Publish loop: read every temperature sensor -> renewvan/temperature/<id>/<property>.

Sensing node (it owns the reads, like node-tank), shaped per
hub/schema/temperature.schema.json.

Identity fields (retained, published at startup and after a user edit):
- name, unit, source, serial (serial: 1-Wire probes only)
Live fields (republished every poll):
- temperature_c (only when status == ok), status

User-editable identity: `name` and `unit` accept a JSON-string payload on
renewvan/temperature/<id>/<field>/set (unretained, node-tank's last_inspected_at
pattern). A valid edit is persisted to state/<id>.json -- install-local runtime
state, never written back into config.ini -- and republished retained. On the
next start the persisted value wins over the config.ini default.

Sensor set: every [sensor.<id>] section, plus every unconfigured 28-* probe on
the bus (id = serial), plus the built-in CPU sensor. A probe that vanishes
publishes status=disconnected and keeps being polled, so it recovers on replug.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from node_temperature.config import AppConfig
from node_temperature.publisher import Publisher
from node_temperature.reader import discover_w1_serials, read_cpu, read_w1
from node_temperature.sensors import (
    STATUS_DISCONNECTED,
    STATUS_OK,
    Reading,
    normalize_name,
    normalize_unit,
)

logger = logging.getLogger(__name__)


@dataclass
class Sensor:
    """Runtime view of one sensor: fixed identity + mutable user-editable fields."""

    id: str
    source: str  # "w1" | "cpu"
    name: str
    unit: str
    serial: str | None = None  # w1 only
    thermal_zone: Path | None = None  # cpu only
    published_identity: bool = False


def _topic(sensor_id: str, prop: str) -> str:
    return f"renewvan/temperature/{sensor_id}/{prop}"


# --- state persistence -----------------------------------------------------


def _state_file(sensor_id: str, state_dir: Path) -> Path:
    return state_dir / f"{sensor_id}.json"


def load_state(sensor_id: str, state_dir: Path) -> dict:
    """state/<id>.json as a dict, or {} if absent/unreadable."""
    state_file = _state_file(sensor_id, state_dir)
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text())
    except Exception as e:
        logger.warning("Sensor %s: failed to load state: %s", sensor_id, e)
        return {}
    return data if isinstance(data, dict) else {}


def save_state_field(sensor_id: str, field_name: str, value: str, state_dir: Path) -> bool:
    """Read-modify-write one field. False (and logged) if the write failed."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        data = load_state(sensor_id, state_dir)
        data[field_name] = value
        _state_file(sensor_id, state_dir).write_text(json.dumps(data))
        return True
    except Exception as e:
        logger.error("Sensor %s: failed to save state: %s", sensor_id, e)
        return False


def apply_persisted_state(sensor: Sensor, state_dir: Path) -> None:
    """Overlay persisted name/unit onto the config.ini defaults; invalid values are ignored."""
    state = load_state(sensor.id, state_dir)
    raw_name = state.get("name")
    name = normalize_name(raw_name) if isinstance(raw_name, str) else None
    if name is not None:
        sensor.name = name
    raw_unit = state.get("unit")
    unit = normalize_unit(raw_unit) if isinstance(raw_unit, str) else None
    if unit is not None:
        sensor.unit = unit


# --- sensor set ------------------------------------------------------------


def build_sensors(config: AppConfig) -> dict[str, Sensor]:
    """Configured probes + built-in CPU sensor, state overlay applied."""
    state_dir = config.node.state_dir
    sensors: dict[str, Sensor] = {}
    for cfg in config.node.sensors:
        sensors[cfg.id] = Sensor(
            id=cfg.id, source="w1", name=cfg.name, unit=cfg.unit, serial=cfg.serial
        )
    if config.node.cpu is not None:
        cpu = config.node.cpu
        sensors[cpu.id] = Sensor(
            id=cpu.id,
            source="cpu",
            name=cpu.name,
            unit=cpu.unit,
            thermal_zone=cpu.thermal_zone,
        )
    for sensor in sensors.values():
        apply_persisted_state(sensor, state_dir)
    return sensors


def adopt_unconfigured_probes(config: AppConfig, sensors: dict[str, Sensor]) -> list[Sensor]:
    """Add any bus probe not yet in `sensors` (id = serial). Returns the new ones."""
    known_serials = {s.serial for s in sensors.values() if s.serial}
    added: list[Sensor] = []
    for serial in discover_w1_serials(config.node.w1_base_path):
        if serial in known_serials or serial in sensors:
            continue
        sensor = Sensor(
            id=serial,
            source="w1",
            name=serial,
            unit=config.node.default_unit,
            serial=serial,
        )
        apply_persisted_state(sensor, config.node.state_dir)
        sensors[serial] = sensor
        added.append(sensor)
        logger.info("Discovered unconfigured probe %s; publishing as id=%s", serial, serial)
    return added


# --- publishing ------------------------------------------------------------


def publish_identity(publisher: Publisher, sensor: Sensor) -> None:
    publisher.publish(_topic(sensor.id, "name"), json.dumps(sensor.name))
    publisher.publish(_topic(sensor.id, "unit"), json.dumps(sensor.unit))
    publisher.publish(_topic(sensor.id, "source"), json.dumps(sensor.source))
    if sensor.serial is not None:
        publisher.publish(_topic(sensor.id, "serial"), json.dumps(sensor.serial))
    sensor.published_identity = True


def read_sensor(config: AppConfig, sensor: Sensor) -> Reading | None:
    """None only for a 1-Wire probe that is no longer on the bus."""
    if sensor.source == "cpu":
        assert sensor.thermal_zone is not None
        return read_cpu(sensor.thermal_zone)
    assert sensor.serial is not None
    return read_w1(config.node.w1_base_path, sensor.serial)


def publish_live(publisher: Publisher, sensor: Sensor, reading: Reading | None) -> None:
    """status always; temperature_c only when ok.

    A non-ok sensor skips the temperature_c publish (node-tank's NTC failure
    convention) rather than clearing it: an empty retained payload would reach
    live subscribers as an unparseable message. The last retained temperature_c
    therefore stays on the broker, so consumers MUST gate on `status == ok`
    before rendering it -- the schema documents this.
    """
    status = STATUS_DISCONNECTED if reading is None else reading.status
    publisher.publish(_topic(sensor.id, "status"), json.dumps(status))
    if reading is not None and reading.status == STATUS_OK:
        publisher.publish(_topic(sensor.id, "temperature_c"), json.dumps(reading.temperature_c))


def poll_once(publisher: Publisher, config: AppConfig, sensors: dict[str, Sensor]) -> None:
    adopt_unconfigured_probes(config, sensors)
    for sensor in list(sensors.values()):
        try:
            if not sensor.published_identity:
                publish_identity(publisher, sensor)
            publish_live(publisher, sensor, read_sensor(config, sensor))
        except Exception:
            logger.exception("Read failed for sensor=%s", sensor.id)


# --- /set commands ---------------------------------------------------------


def handle_set_command(
    publisher: Publisher, sensor: Sensor, field_name: str, payload: str, state_dir: Path
) -> None:
    """Apply a name/unit edit: validate, persist, republish retained.

    Payload is a JSON string, e.g. "F" or "Galley fridge". Invalid input is
    logged and dropped (no error topic), matching node-tank's /set handlers.
    A failed disk write rejects the edit so the retained topic never claims a
    value that would be lost at the next restart.
    """
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Sensor %s: invalid JSON in %s/set: %s", sensor.id, field_name, payload)
        return

    normalize = {"name": normalize_name, "unit": normalize_unit}[field_name]
    value = normalize(raw) if isinstance(raw, str) else None
    if value is None:
        logger.error("Sensor %s: invalid %s: %r", sensor.id, field_name, raw)
        return

    if not save_state_field(sensor.id, field_name, value, state_dir):
        return
    setattr(sensor, field_name, value)
    publisher.publish(_topic(sensor.id, field_name), json.dumps(value))
    logger.info("Sensor %s: %s set to %s", sensor.id, field_name, value)


def subscribe_set_commands(publisher: Publisher, sensor: Sensor, state_dir: Path) -> None:
    for field_name in ("name", "unit"):

        def make_callback(f: str) -> callable:
            def callback(payload: str) -> None:
                handle_set_command(publisher, sensor, f, payload, state_dir)

            return callback

        publisher.subscribe(_topic(sensor.id, f"{field_name}/set"), make_callback(field_name))


def run(config: AppConfig) -> None:
    publisher = Publisher(config.mqtt)
    publisher.connect()
    sensors = build_sensors(config)
    for sensor in sensors.values():
        subscribe_set_commands(publisher, sensor, config.node.state_dir)

    try:
        while True:
            before = set(sensors)
            poll_once(publisher, config, sensors)
            # Probes discovered mid-run need their /set topics too.
            for sensor_id in set(sensors) - before:
                subscribe_set_commands(publisher, sensors[sensor_id], config.node.state_dir)
            time.sleep(config.node.update_interval_ms / 1000)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        publisher.disconnect()
