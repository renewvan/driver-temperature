"""Layered INI config: config.default.ini (shipped) + config.ini (local
override).

Same two-file pattern as every renewvan/node-* repo (see
node-tank/node_tank/config.py): config.default.ini ships every key with a
safe default and is never edited at an install; config.ini is a gitignored,
install-local file that overrides only what differs.
"""

from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass
from pathlib import Path

from node_temperature.sensors import W1_SERIAL_RE, normalize_name, normalize_unit

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.default.ini"
DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    client_id: str
    reconnect_min_delay: float
    reconnect_max_delay: float


@dataclass(frozen=True)
class SensorConfig:
    """One configured DS18B20 probe (a [sensor.<id>] section)."""

    id: str  # topic path segment, e.g. renewvan/temperature/<id>/...
    serial: str
    name: str  # default label; a dashboard edit persisted in state/ wins
    unit: str  # default display unit, "C" or "F"; same override rule


@dataclass(frozen=True)
class CpuConfig:
    id: str
    name: str
    unit: str
    thermal_zone: Path


@dataclass(frozen=True)
class NodeConfig:
    update_interval_ms: int
    w1_base_path: Path
    default_unit: str
    state_dir: Path  # where name/unit edits from the dashboard persist
    cpu: CpuConfig | None  # None when cpu_enabled = false
    sensors: tuple[SensorConfig, ...]


@dataclass(frozen=True)
class AppConfig:
    mqtt: MqttConfig
    node: NodeConfig


def load_config(
    default_path: Path = DEFAULT_CONFIG_PATH, local_path: Path | None = None
) -> AppConfig:
    """Load config.default.ini, then layer config.ini (if present) on top."""
    parser = configparser.ConfigParser()
    parser.read(default_path)
    if local_path is not None and local_path.exists():
        parser.read(local_path)
    else:
        logger.info("No local config override at %s; using defaults only", local_path)

    mqtt = parser["mqtt"]
    node = parser["node"]

    default_unit = _unit(node.get("default_unit", "C"), "node.default_unit")
    sensors = _load_sensors(parser, default_unit)
    cpu = None
    if node.getboolean("cpu_enabled", True):
        cpu_id = node.get("cpu_id", "cpu")
        if any(sensor.id == cpu_id for sensor in sensors):
            raise ValueError(f"[sensor.{cpu_id}] collides with the built-in cpu sensor id")
        cpu = CpuConfig(
            id=cpu_id,
            name=_name(node.get("cpu_name", "Pi CPU"), "node.cpu_name"),
            unit=_unit(node.get("cpu_unit", "C"), "node.cpu_unit"),
            thermal_zone=Path(
                node.get("cpu_thermal_zone", "/sys/class/thermal/thermal_zone0/temp")
            ),
        )

    return AppConfig(
        mqtt=MqttConfig(
            host=mqtt.get("host", "localhost"),
            port=mqtt.getint("port", 1883),
            username=mqtt.get("username") or None,
            password=mqtt.get("password") or None,
            client_id=mqtt.get("client_id", "node-temperature"),
            reconnect_min_delay=mqtt.getfloat("reconnect_min_delay", 1.0),
            reconnect_max_delay=mqtt.getfloat("reconnect_max_delay", 30.0),
        ),
        node=NodeConfig(
            update_interval_ms=node.getint("update_interval_ms", 3000),
            w1_base_path=Path(node.get("w1_base_path", "/sys/bus/w1/devices")),
            default_unit=default_unit,
            state_dir=Path(node.get("state_dir", str(DEFAULT_STATE_DIR))),
            cpu=cpu,
            sensors=sensors,
        ),
    )


_SECTION_PREFIX = "sensor."


def _unit(value: str, where: str) -> str:
    unit = normalize_unit(value)
    if unit is None:
        raise ValueError(f"{where}: unit must be C or F, got {value!r}")
    return unit


def _name(value: str, where: str) -> str:
    name = normalize_name(value)
    if name is None:
        raise ValueError(f"{where}: name must not be empty")
    return name


def _load_sensors(parser: configparser.ConfigParser, default_unit: str) -> tuple[SensorConfig, ...]:
    sensors: list[SensorConfig] = []
    seen_serials: dict[str, str] = {}
    for section_name in parser.sections():
        if not section_name.startswith(_SECTION_PREFIX):
            continue
        sensor_id = section_name[len(_SECTION_PREFIX) :]
        if not sensor_id or "/" in sensor_id or "+" in sensor_id or "#" in sensor_id:
            raise ValueError(f"[{section_name}]: sensor id must be a plain topic segment")
        section = parser[section_name]

        serial = section.get("serial", "").strip().lower()
        if not W1_SERIAL_RE.match(serial):
            raise ValueError(
                f"[{section_name}]: serial must look like 28-0000075a1b2c, got {serial!r}"
            )
        if serial in seen_serials:
            raise ValueError(
                f"[{section_name}]: serial {serial} already used by [sensor.{seen_serials[serial]}]"
            )
        seen_serials[serial] = sensor_id

        sensors.append(
            SensorConfig(
                id=sensor_id,
                serial=serial,
                name=_name(section.get("name", sensor_id), f"[{section_name}] name"),
                unit=_unit(section.get("unit", default_unit), f"[{section_name}] unit"),
            )
        )
    return tuple(sensors)
