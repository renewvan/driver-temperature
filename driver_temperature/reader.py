"""Filesystem I/O for sensors: 1-Wire probe discovery/reads and the Pi CPU zone.

Thin on purpose -- every parse/validation decision lives in sensors.py.
Paths are injected so tests point them at a tmp_path tree.
"""

from __future__ import annotations

import logging
from pathlib import Path

from driver_temperature.sensors import (
    W1_SERIAL_RE,
    Reading,
    SensorReadError,
    parse_thermal_zone,
    parse_w1_slave,
    to_reading,
)

logger = logging.getLogger(__name__)


def discover_w1_serials(base_path: Path) -> list[str]:
    """Serials of every DS18B20 currently on the bus, sorted for stable ordering.

    Returns [] when base_path does not exist (1-Wire overlay not enabled),
    so the device still serves the CPU sensor on a Pi without w1-gpio.
    """
    if not base_path.is_dir():
        return []
    return sorted(p.name for p in base_path.iterdir() if W1_SERIAL_RE.match(p.name))


def read_w1(base_path: Path, serial: str) -> Reading | None:
    """Read one probe. None means the probe is not on the bus (disconnected)."""
    device = base_path / serial / "w1_slave"
    try:
        text = device.read_text()
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("1-Wire read failed for %s: %s", serial, e)
        return to_reading(None, SensorReadError(str(e)))

    try:
        return to_reading(parse_w1_slave(text), None)
    except SensorReadError as e:
        logger.warning("Probe %s: %s", serial, e)
        return to_reading(None, e)


def read_cpu(thermal_zone_path: Path) -> Reading:
    try:
        return to_reading(parse_thermal_zone(thermal_zone_path.read_text()), None)
    except (OSError, SensorReadError) as e:
        logger.warning("CPU thermal zone %s: %s", thermal_zone_path, e)
        return to_reading(None, SensorReadError(str(e)))
